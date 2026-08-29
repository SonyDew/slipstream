"""Media analysis, download creation, job polling and file delivery."""

from __future__ import annotations

import os

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import (
    Auth,
    DbSession,
    RateLimitAnalyze,
    RateLimitDownload,
    RequireUser,
)
from app.core.errors import (
    DownloadExpiredError,
    JobNotReadyError,
    MediaUnavailableError,
)
from app.core.filenames import content_disposition
from app.core.logging import get_logger
from app.db.base import utcnow
from app.models.job import JobStatus
from app.models.records import DownloadHistory
from app.providers.registry import registry
from app.schemas.api import AnalyzeRequest, DownloadRequest, JobCreatedResponse
from app.services.analyze import analyze_url, build_analysis_payload
from app.services.jobs import (
    cancel_job,
    create_job,
    get_job_for_requester,
    job_to_payload,
    notify_queue,
)

router = APIRouter(tags=["media"])
log = get_logger("slipstream.api.media")


# --------------------------------------------------------------------------- #
# Analyse
# --------------------------------------------------------------------------- #
@router.post("/media/analyze")
async def analyze(
    payload: AnalyzeRequest,
    auth: Auth,
    db: DbSession,
    _rate: RateLimitAnalyze,
) -> dict:
    """Inspect a URL and return the available download options."""
    media = await analyze_url(payload.url, db)
    return build_analysis_payload(media, container=payload.container)


@router.get("/media/platforms")
def platforms(db: DbSession) -> dict:
    """Supported platforms, filtered by the admin allow-list."""
    from app.core.settings_store import store

    allowed = store.get_list(db, "allowed_platforms")
    described = registry.describe()
    if allowed:
        described = [p for p in described if p["platform"] in allowed]
    return {"platforms": described}


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
@router.post("/download", status_code=status.HTTP_202_ACCEPTED, response_model=JobCreatedResponse)
async def create_download(
    payload: DownloadRequest,
    auth: Auth,
    db: DbSession,
    _rate: RateLimitDownload,
) -> dict:
    """Queue a download job.

    The URL is analysed first (usually a cache hit from the preceding
    ``/media/analyze`` call) so the requested quality can be validated against
    what the source actually offers.
    """
    media = await analyze_url(payload.url, db)

    container = payload.container
    if payload.mode == "audio":
        container = "mp3"
    elif container == "mp3":
        container = "mp4"

    job = create_job(
        db,
        media=media,
        url=payload.url,
        mode=payload.mode,
        quality=payload.quality,
        container=container,
        user=auth.user,
        guest_key=auth.guest_key,
        image_indexes=payload.image_indexes,
    )
    job_id = job.id
    db.commit()

    # Only wake the workers once the row is durably committed.
    notify_queue(job_id)

    return {
        "job_id": job_id,
        "status": JobStatus.QUEUED.value,
        "poll_url": f"/api/jobs/{job_id}",
    }


# --------------------------------------------------------------------------- #
# Jobs
# --------------------------------------------------------------------------- #
@router.get("/jobs/{job_id}")
def get_job(job_id: str, auth: Auth, db: DbSession) -> dict:
    """Poll job status."""
    job = get_job_for_requester(db, job_id, user=auth.user, guest_key=auth.guest_key)

    # Lazily reflect expiry so a client polling an old job sees the truth.
    if job.status == JobStatus.READY.value and job.is_expired:
        job.status = JobStatus.EXPIRED.value
        job.file_path = None
        job.progress_label = "Expired"
        db.commit()

    return job_to_payload(job)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_200_OK)
def delete_job(job_id: str, auth: Auth, db: DbSession) -> dict:
    """Cancel a running job, or discard a finished one."""
    job = get_job_for_requester(db, job_id, user=auth.user, guest_key=auth.guest_key)
    cancelled = cancel_job(db, job)
    db.commit()

    if not cancelled:
        # Already terminal: drop the bytes now rather than waiting for cleanup.
        from app.services import storage

        storage.remove_job_dir(job.id)

    return {"cancelled": cancelled, "status": job.status}


@router.get("/jobs/{job_id}/file")
def download_file(job_id: str, auth: Auth, db: DbSession, request: Request) -> Response:
    """Stream the finished file.

    Uses :class:`FileResponse`, which sends the file in chunks via sendfile/anyio
    rather than reading it into memory, and supports HTTP range requests so a
    browser can resume a large download.
    """
    job = get_job_for_requester(db, job_id, user=auth.user, guest_key=auth.guest_key)

    if job.status == JobStatus.EXPIRED.value:
        raise DownloadExpiredError()
    if job.status in {JobStatus.FAILED.value, JobStatus.CANCELLED.value}:
        raise MediaUnavailableError("This download did not complete.")
    if job.status != JobStatus.READY.value or not job.file_path:
        raise JobNotReadyError()
    if job.is_expired:
        raise DownloadExpiredError()

    if not os.path.isfile(job.file_path):
        # Row says ready but the bytes are gone (cleanup race, manual delete).
        job.status = JobStatus.EXPIRED.value
        job.file_path = None
        db.commit()
        raise DownloadExpiredError()

    filename = job.file_name or "download"
    if job.delivered_at is None:
        job.delivered_at = utcnow()
        db.commit()

    headers = {
        "Content-Disposition": content_disposition(filename),
        # Nothing about a temporary download should be cached by a proxy.
        "Cache-Control": "no-store, must-revalidate",
        "X-Content-Type-Options": "nosniff",
    }
    return FileResponse(
        job.file_path,
        media_type=job.mime_type or "application/octet-stream",
        headers=headers,
        # FileResponse sets Content-Disposition itself unless we pass headers,
        # which we do, so the filename argument is intentionally omitted.
    )


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
@router.get("/history")
def list_history(
    auth: RequireUser,
    db: DbSession,
    page: int = 1,
    per_page: int = 20,
) -> dict:
    """Paginated download history for the signed-in user."""
    from sqlalchemy import func

    assert auth.user is not None
    page = max(1, min(page, 10_000))
    per_page = max(1, min(per_page, 100))

    total = int(
        db.execute(
            select(func.count())
            .select_from(DownloadHistory)
            .where(DownloadHistory.user_id == auth.user.id)
        ).scalar()
        or 0
    )
    rows = (
        db.execute(
            select(DownloadHistory)
            .where(DownloadHistory.user_id == auth.user.id)
            .order_by(DownloadHistory.created_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
        .scalars()
        .all()
    )

    return {
        "items": [_history_payload(row) for row in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


@router.delete("/history", status_code=status.HTTP_200_OK)
def clear_history(auth: RequireUser, db: DbSession) -> dict:
    """Delete every history row for the signed-in user."""
    from sqlalchemy import delete

    assert auth.user is not None
    result = db.execute(delete(DownloadHistory).where(DownloadHistory.user_id == auth.user.id))
    db.commit()
    log.info("history cleared", user_id=auth.user.id, removed=result.rowcount)
    return {"deleted": int(result.rowcount or 0)}


@router.delete("/history/{item_id}", status_code=status.HTTP_200_OK)
def delete_history_item(item_id: int, auth: RequireUser, db: DbSession) -> dict:
    from app.core.errors import JobNotFoundError

    assert auth.user is not None
    row = db.get(DownloadHistory, item_id)
    if row is None or row.user_id != auth.user.id:
        raise JobNotFoundError("That history entry does not exist.")
    db.delete(row)
    db.commit()
    return {"deleted": 1}


def _history_payload(row: DownloadHistory) -> dict:
    return {
        "id": row.id,
        "job_id": row.job_id,
        "platform": row.platform,
        "source_domain": row.source_domain,
        "title": row.title,
        "author": row.author,
        "thumbnail": row.thumbnail,
        "media_type": row.media_type,
        "quality": row.quality,
        "output_format": row.output_format,
        "file_size": row.file_size,
        "status": row.status,
        "error_code": row.error_code,
        "created_at": row.created_at,
    }
