"""Job creation, inspection and cancellation."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import (
    JobNotFoundError,
    NoSuitableFormatError,
    QueueFullError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.settings_store import store
from app.core.ssrf import assert_url_allowed
from app.db.base import utcnow
from app.models.job import DownloadJob, JobStatus, MediaType
from app.models.user import User
from app.providers.models import NormalizedMedia
from app.providers.registry import registry
from app.services.extractor import ffmpeg_available
from app.services.formats import validate_quality
from app.services.queue import get_queue

log = get_logger("slipstream.jobs")

VALID_MODES = ("video", "audio", "image")


def create_job(
    db: Session,
    *,
    media: NormalizedMedia,
    url: str,
    mode: str,
    quality: str,
    container: str,
    user: User | None,
    guest_key: str | None,
    image_indexes: list[int] | None = None,
) -> DownloadJob:
    """Validate a download request and persist a queued job."""
    if mode not in VALID_MODES:
        raise ValidationError("Unknown download type.")

    checked = assert_url_allowed(url)
    has_ffmpeg = ffmpeg_available()

    if mode == "image":
        if not media.images:
            raise NoSuitableFormatError("This post has no images to download.")
        normalized_quality = "best"
        output_format = "zip" if (image_indexes is None or len(image_indexes) != 1) else "jpg"
        if len(media.images) == 1:
            output_format = media.images[0].ext or "jpg"
        media_type = MediaType.IMAGE_SET.value if len(media.images) > 1 else MediaType.IMAGE.value
    elif mode == "audio":
        normalized_quality = validate_quality(
            media, mode="audio", quality=quality, container="mp3", ffmpeg_available=has_ffmpeg
        )
        output_format = "mp3"
        media_type = MediaType.AUDIO.value
    else:
        container = container if container in ("mp4", "webm") else "mp4"
        normalized_quality = validate_quality(
            media,
            mode="video",
            quality=quality,
            container=container,
            ffmpeg_available=has_ffmpeg,
        )
        output_format = container
        media_type = MediaType.VIDEO.value

    _enforce_queue_capacity(db)

    job = DownloadJob(
        id=uuid.uuid4().hex,
        user_id=user.id if user else None,
        guest_key=None if user else guest_key,
        status=JobStatus.QUEUED.value,
        platform=media.platform,
        source_url=checked.url,
        source_domain=(urlparse(checked.url).hostname or "unknown")[:255],
        media_id=media.media_id,
        media_type=media_type,
        requested_quality=normalized_quality,
        output_format=output_format,
        selected_images={"indexes": image_indexes} if image_indexes else None,
        title=media.title,
        author=media.author,
        thumbnail=media.thumbnail,
        duration=media.duration,
        extractor=media.extractor,
        progress=0,
        progress_label="Queued",
    )
    db.add(job)
    db.flush()

    log.info(
        "job created",
        job_id=job.id,
        platform=job.platform,
        user_id=job.user_id,
        mode=mode,
        quality=normalized_quality,
    )
    return job


def _enforce_queue_capacity(db: Session) -> None:
    """Refuse new work when the backlog is already at the configured ceiling."""
    pending = int(
        db.execute(
            select(func.count())
            .select_from(DownloadJob)
            .where(DownloadJob.status.in_(sorted(JobStatus.active())))
        ).scalar()
        or 0
    )
    if pending >= settings.JOB_QUEUE_SIZE:
        raise QueueFullError()


def notify_queue(job_id: str) -> None:
    """Wake the worker pool after the transaction has committed."""
    get_queue().submit(job_id)


def get_job_for_requester(
    db: Session,
    job_id: str,
    *,
    user: User | None,
    guest_key: str | None,
) -> DownloadJob:
    """Fetch a job the caller is allowed to see.

    Ownership rules: a signed-in user sees their own jobs; an admin sees all; a
    guest job is addressable by whoever holds the unguessable job id, optionally
    narrowed to the originating client key.
    """
    job = db.get(DownloadJob, job_id)
    if job is None:
        raise JobNotFoundError()

    if user is not None:
        if job.user_id == user.id or user.is_admin:
            return job
        # A signed-in user may still claim a guest job they started before
        # logging in, provided the client key matches.
        if job.user_id is None and guest_key and job.guest_key == guest_key:
            return job
        raise JobNotFoundError()

    if job.user_id is not None:
        # Do not confirm the existence of another account's job.
        raise JobNotFoundError()
    return job


def cancel_job(db: Session, job: DownloadJob) -> bool:
    """Request cancellation. Returns True when the job was still cancellable."""
    if job.status in JobStatus.terminal():
        return False

    job.cancel_requested = True
    if job.status == JobStatus.QUEUED.value:
        # Not started yet: finalise immediately so the user sees it stop.
        job.status = JobStatus.CANCELLED.value
        job.finished_at = utcnow()
        job.progress_label = "Cancelled"
        job.error_code = "cancelled"
        job.error_message = "Cancelled before it started."
    db.flush()
    get_queue().request_cancel(job.id)
    log.info("cancellation requested", job_id=job.id)
    return True


def job_to_payload(job: DownloadJob) -> dict[str, Any]:
    """Serialise a job for the polling endpoint."""
    return {
        "id": job.id,
        "status": job.status,
        "platform": job.platform,
        "media_type": job.media_type,
        "title": job.title,
        "author": job.author,
        "thumbnail": job.thumbnail,
        "duration": job.duration,
        "quality": job.requested_quality,
        "output_format": job.output_format,
        "progress": job.progress,
        "progress_label": job.progress_label,
        "eta_seconds": job.eta_seconds,
        "speed_bps": job.speed_bps,
        "file_name": job.file_name,
        "file_size": job.file_size,
        "mime_type": job.mime_type,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "created_at": job.created_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "expires_at": job.expires_at,
        "is_downloadable": job.is_downloadable,
        "download_url": f"/api/jobs/{job.id}/file" if job.is_downloadable else None,
    }


def expire_ready_jobs(db: Session) -> int:
    """Flip READY jobs whose TTL has passed to EXPIRED."""
    stale = (
        db.execute(
            select(DownloadJob).where(
                DownloadJob.status == JobStatus.READY.value,
                DownloadJob.expires_at.is_not(None),
                DownloadJob.expires_at <= utcnow(),
            )
        )
        .scalars()
        .all()
    )
    for job in stale:
        job.status = JobStatus.EXPIRED.value
        job.progress_label = "Expired"
        job.file_path = None
    return len(stale)


def default_expiry(db: Session) -> Any:
    return utcnow() + timedelta(seconds=store.get_int(db, "temp_file_ttl"))


def platform_label(platform: str) -> str:
    provider = registry.get(platform)
    return provider.label if provider else platform.title()
