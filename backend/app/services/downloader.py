"""Job execution pipeline.

One job goes through: analyse → select format → fetch (yt-dlp) → post-process
(FFmpeg for merge/MP3, ZIP for slideshows) → publish → record history.

Design notes
------------
* yt-dlp is synchronous, so the fetch runs on a worker thread while progress is
  pushed back into the database through a throttled hook.
* Size and duration limits are enforced *before* the fetch when metadata allows
  it, and again *during* the fetch, so a source that lies about its size cannot
  fill the disk.
* Nothing here trusts the client: the quality token has already been validated
  against the real format list, and the output filename is sanitised.
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import shutil
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, update

from app.core.config import settings
from app.core.errors import (
    AppError,
    FFmpegError,
    FFmpegMissingError,
    FileTooLargeError,
    JobCancelledError,
    MediaUnavailableError,
    NoSuitableFormatError,
    VideoTooLongError,
)
from app.core.filenames import build_download_filename, sanitize_filename
from app.core.logging import get_logger
from app.core.settings_store import store
from app.core.ssrf import assert_url_allowed
from app.db.base import utcnow
from app.db.session import session_scope
from app.models.job import DownloadJob, JobStatus, MediaType
from app.models.records import DownloadHistory
from app.providers.base import classify_extractor_error
from app.providers.models import NormalizedMedia
from app.providers.registry import registry
from app.services import storage
from app.services.extractor import base_ydl_opts, ffmpeg_available, resolve_binary
from app.services.formats import (
    build_format_selector,
    target_audio_bitrate,
    validate_quality,
)

log = get_logger("slipstream.downloader")

# Progress writes are throttled: a 2 GB download would otherwise generate
# thousands of UPDATEs and dominate SQLite write traffic.
PROGRESS_MIN_INTERVAL = 0.7
PROGRESS_MIN_DELTA = 2  # percent

MIME_BY_EXT = {
    "mp4": "video/mp4",
    "webm": "video/webm",
    "mkv": "video/x-matroska",
    "mov": "video/quicktime",
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "opus": "audio/opus",
    "ogg": "audio/ogg",
    "wav": "audio/wav",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "webp": "image/webp",
    "zip": "application/zip",
}


# --------------------------------------------------------------------------- #
# Job state helpers
# --------------------------------------------------------------------------- #
def _set_status(job_id: str, status: str, **fields: Any) -> None:
    with session_scope() as db:
        db.execute(
            update(DownloadJob).where(DownloadJob.id == job_id).values(status=status, **fields)
        )


def _update_fields(job_id: str, **fields: Any) -> None:
    with session_scope() as db:
        db.execute(update(DownloadJob).where(DownloadJob.id == job_id).values(**fields))


def fail_job(job_id: str, *, code: str, message: str) -> None:
    """Terminal failure. Also records history and removes partial bytes."""
    started: float | None = None
    with session_scope() as db:
        job = db.get(DownloadJob, job_id)
        if job is None:
            return
        if job.status in JobStatus.terminal():
            return
        if job.started_at:
            started = job.started_at.timestamp()
        job.status = JobStatus.FAILED.value
        job.error_code = code
        job.error_message = message
        job.finished_at = utcnow()
        job.progress_label = "Failed"
        if started:
            job.duration_ms = int((time.time() - started) * 1000)
        _write_history(db, job)

    storage.remove_job_dir(job_id)
    log.info("job failed", job_id=job_id, error_code=code)


def _write_history(db: Any, job: DownloadJob) -> None:
    """Append a history row for signed-in users only.

    Guests leave nothing behind by design — see docs/SECURITY.md.
    """
    if job.user_id is None:
        return
    retention = store.get_int(db, "history_retention_days")
    if retention <= 0:
        return
    db.add(
        DownloadHistory(
            user_id=job.user_id,
            job_id=job.id,
            platform=job.platform,
            source_domain=job.source_domain,
            source_url=job.source_url,
            title=job.title,
            author=job.author,
            thumbnail=job.thumbnail,
            media_type=job.media_type,
            quality=job.requested_quality,
            output_format=job.output_format,
            file_size=job.file_size,
            status=job.status,
            error_code=job.error_code,
            duration_ms=job.duration_ms,
        )
    )


class _ProgressReporter:
    """Throttled progress writer shared by the fetch and post-process stages.

    Progress is clamped to be monotonically non-decreasing. An adaptive download
    fetches the video and audio streams sequentially, and yt-dlp reports 0-100%
    for *each* file, so the raw numbers would otherwise jump backwards halfway
    through — which reads as a bug to anyone watching the bar.
    """

    def __init__(self, job_id: str, queue: Any) -> None:
        self.job_id = job_id
        self.queue = queue
        self._last_write = 0.0
        self._last_percent = -1
        self._high_water = 0
        self.cancelled = False

    def check_cancel(self) -> None:
        if self.queue is not None and self.queue.is_cancelled(self.job_id):
            self.cancelled = True
            raise JobCancelledError()

    def push(
        self,
        percent: int,
        label: str,
        *,
        force: bool = False,
        eta: int | None = None,
        speed: int | None = None,
        monotonic: bool = True,
    ) -> None:
        percent = max(0, min(100, int(percent)))
        if monotonic:
            percent = max(percent, self._high_water)
        self._high_water = max(self._high_water, percent)

        now = time.monotonic()
        if not force:
            if now - self._last_write < PROGRESS_MIN_INTERVAL:
                return
            if abs(percent - self._last_percent) < PROGRESS_MIN_DELTA and percent != 100:
                return
        self._last_write = now
        self._last_percent = percent
        with contextlib.suppress(Exception):
            _update_fields(
                self.job_id,
                progress=percent,
                progress_label=label[:128],
                eta_seconds=eta,
                speed_bps=speed,
            )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
async def process_job(job_id: str, queue: Any = None) -> None:
    """Run one job end to end. Never raises for expected failures."""
    snapshot = await asyncio.to_thread(_load_job_snapshot, job_id)
    if snapshot is None:
        log.warning("job vanished before processing", job_id=job_id)
        return

    reporter = _ProgressReporter(job_id, queue)
    started = time.time()

    try:
        await _run_pipeline(snapshot, reporter)
    except JobCancelledError:
        await asyncio.to_thread(_finish_cancelled, job_id)
    except AppError as exc:
        if exc.detail:
            log.info("job failed", job_id=job_id, error_code=exc.code, detail=exc.detail[:200])
        await asyncio.to_thread(
            functools.partial(fail_job, job_id, code=exc.code, message=exc.message)
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.error("unhandled job error: %s", type(exc).__name__, job_id=job_id, exc_info=True)
        await asyncio.to_thread(
            functools.partial(
                fail_job,
                job_id,
                code="internal_error",
                message="An unexpected server error occurred while preparing this download.",
            )
        )
    finally:
        log.info("job finished", job_id=job_id, elapsed_ms=int((time.time() - started) * 1000))


def _load_job_snapshot(job_id: str) -> dict[str, Any] | None:
    """Read the job into a plain dict so no ORM object crosses threads."""
    with session_scope() as db:
        job = db.get(DownloadJob, job_id)
        if job is None:
            return None
        return {
            "id": job.id,
            "user_id": job.user_id,
            "platform": job.platform,
            "source_url": job.source_url,
            "media_type": job.media_type,
            "requested_quality": job.requested_quality,
            "output_format": job.output_format,
            "selected_images": job.selected_images,
        }


def _finish_cancelled(job_id: str) -> None:
    with session_scope() as db:
        job = db.get(DownloadJob, job_id)
        if job is None or job.status in JobStatus.terminal():
            return
        job.status = JobStatus.CANCELLED.value
        job.finished_at = utcnow()
        job.progress_label = "Cancelled"
        job.error_code = "cancelled"
        job.error_message = "Cancelled at your request."
    storage.remove_job_dir(job_id)
    log.info("job cancelled", job_id=job_id)


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
async def _run_pipeline(job: dict[str, Any], reporter: _ProgressReporter) -> None:
    job_id = job["id"]
    mode = _mode_for(job["media_type"], job["output_format"])

    reporter.check_cancel()
    reporter.push(2, "Reading media information", force=True)

    provider = registry.find(job["source_url"])
    media = await provider.analyze(job["source_url"])

    with session_scope() as db:
        limits = {
            "max_file_size": store.get_int(db, "max_file_size"),
            "max_video_duration": store.get_int(db, "max_video_duration"),
            "temp_file_ttl": store.get_int(db, "temp_file_ttl"),
        }

    _enforce_metadata_limits(media, mode, limits)

    # Persist resolved metadata so the UI can show a real title while working.
    await asyncio.to_thread(
        functools.partial(
            _update_fields,
            job_id,
            title=media.title,
            author=media.author,
            thumbnail=media.thumbnail,
            duration=media.duration,
            media_id=media.media_id,
            extractor=media.extractor,
            media_type=_media_type_for(mode, media),
        )
    )

    reporter.check_cancel()
    work_dir = storage.job_dir(job_id, create=True)

    if mode == "image":
        result = await _run_image_pipeline(job, media, work_dir, reporter)
    else:
        result = await _run_media_pipeline(job, media, mode, work_dir, reporter, limits)

    reporter.check_cancel()
    _publish(job_id, result, ttl_seconds=limits["temp_file_ttl"])


def _mode_for(media_type: str, output_format: str) -> str:
    if output_format == "mp3":
        return "audio"
    if media_type in {MediaType.IMAGE.value, MediaType.IMAGE_SET.value}:
        return "image"
    if media_type == MediaType.AUDIO.value:
        return "audio"
    return "video"


def _media_type_for(mode: str, media: NormalizedMedia) -> str:
    if mode == "audio":
        return MediaType.AUDIO.value
    if mode == "image":
        return MediaType.IMAGE_SET.value if len(media.images) > 1 else MediaType.IMAGE.value
    return MediaType.VIDEO.value


def _enforce_metadata_limits(media: NormalizedMedia, mode: str, limits: dict[str, int]) -> None:
    if media.duration and mode != "image" and media.duration > limits["max_video_duration"]:
        raise VideoTooLongError(
            f"This media is {media.duration // 60} minutes long; the limit is "
            f"{limits['max_video_duration'] // 60} minutes."
        )
    if media.is_live:
        raise MediaUnavailableError(
            "Live streams cannot be downloaded. Try again once the stream has ended."
        )


# --------------------------------------------------------------------------- #
# Video / audio
# --------------------------------------------------------------------------- #
async def _run_media_pipeline(
    job: dict[str, Any],
    media: NormalizedMedia,
    mode: str,
    work_dir: Path,
    reporter: _ProgressReporter,
    limits: dict[str, int],
) -> dict[str, Any]:
    job_id = job["id"]
    container = job["output_format"] if mode == "video" else "mp3"
    has_ffmpeg = ffmpeg_available()

    quality = validate_quality(
        media,
        mode=mode,  # type: ignore[arg-type]
        quality=job["requested_quality"],
        container=container,
        ffmpeg_available=has_ffmpeg,
    )

    if mode == "audio" and not has_ffmpeg:
        raise FFmpegMissingError(
            "MP3 conversion needs FFmpeg, which is not installed on this server."
        )

    selector = build_format_selector(
        mode=mode,  # type: ignore[arg-type]
        quality=quality,
        container=container,
        ffmpeg_available=has_ffmpeg,
    )

    _set_status(job_id, JobStatus.DOWNLOADING.value, progress=5, progress_label="Downloading")

    outtmpl = str(work_dir / "%(title).120B.%(ext)s")
    direct_url = _pick_direct_source(media, quality) if mode in {"video", "audio"} else None
    opts: dict[str, Any] = base_ydl_opts(
        format=selector,
        outtmpl={"default": outtmpl},
        paths={"home": str(work_dir), "temp": str(work_dir)},
        # Hard stop if the source turns out bigger than policy allows.
        max_filesize=limits["max_file_size"],
        # Keep the merge target aligned with what the user asked for.
        merge_output_format=container if mode == "video" else None,
        restrictfilenames=False,
        windowsfilenames=True,
        trim_file_name=120,
        concurrent_fragment_downloads=2,
        **(media.metadata.get("_ydl_extra") or {}),
    )
    opts.update(registry.find(job["source_url"]).extra_ydl_opts())
    # A specialised provider may already have selected a progressive source.
    # Let yt-dlp's generic downloader handle retries/progress/post-processing,
    # but do not apply the original site's adaptive format expression to it.
    opts["format"] = "best" if direct_url else selector

    if mode == "audio":
        bitrate = target_audio_bitrate(media, quality)
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                # None -> let FFmpeg choose based on the source (best VBR).
                "preferredquality": str(bitrate) if bitrate else "0",
            }
        ]
        opts["postprocessor_args"] = {
            # Cap threads so a 1 vCPU VPS stays responsive under load.
            "ffmpeg": ["-threads", "1"],
        }

    hook = _make_progress_hook(reporter, limits["max_file_size"])
    opts["progress_hooks"] = [hook]
    opts["postprocessor_hooks"] = [_make_postprocessor_hook(reporter)]

    await asyncio.to_thread(
        functools.partial(_run_ytdlp_download, direct_url or job["source_url"], opts)
    )

    reporter.check_cancel()
    output = storage.find_output_file(work_dir)
    if output is None:
        raise NoSuitableFormatError("The download produced no output file.")

    size = output.stat().st_size
    if size <= 0:
        raise NoSuitableFormatError("The download produced an empty file.")
    if size > limits["max_file_size"]:
        output.unlink(missing_ok=True)
        raise FileTooLargeError()

    ext = output.suffix.lstrip(".").lower() or container
    label = "" if quality == "best" else (f"{quality}p" if mode == "video" else f"{quality}kbps")
    filename = build_download_filename(
        media.title or job["platform"],
        extension=ext,
        quality=label,
        platform=job["platform"],
    )

    return {
        "path": output,
        "filename": filename,
        "size": size,
        "mime": MIME_BY_EXT.get(ext, "application/octet-stream"),
    }


def _pick_direct_source(media: NormalizedMedia, quality: str) -> str | None:
    """Choose the fresh provider URL matching a validated quality token."""
    if not media.direct_sources:
        return None
    candidates = [
        (fmt.height or 0, media.direct_sources[fmt.format_id])
        for fmt in media.formats
        if fmt.format_id in media.direct_sources and fmt.has_video
    ]
    if not candidates:
        return None
    if quality == "best" or not quality.isdigit():
        return max(candidates, key=lambda item: item[0])[1]
    target = int(quality)
    fitting = [item for item in candidates if item[0] <= target * 1.05]
    return max(fitting or candidates, key=lambda item: item[0])[1]


def _run_ytdlp_download(url: str, opts: dict[str, Any]) -> None:
    """Blocking yt-dlp download. Runs on a worker thread."""
    import yt_dlp

    checked = assert_url_allowed(url)
    # Strip None values: yt-dlp treats a present-but-None key as a real setting.
    clean = {k: v for k, v in opts.items() if v is not None}
    try:
        with yt_dlp.YoutubeDL(clean) as ydl:
            code = ydl.download([checked.url])
        if code != 0:
            raise FFmpegError(detail=f"yt-dlp exited with {code}")
    except AppError:
        raise
    except Exception as exc:
        raise classify_extractor_error(exc) from exc


def _make_progress_hook(reporter: _ProgressReporter, max_size: int):
    """yt-dlp progress hook: reports progress and enforces the size ceiling."""

    def hook(status: dict[str, Any]) -> None:
        # Raising inside the hook aborts the download, which is exactly how
        # cancellation and the size guard are enforced mid-transfer.
        reporter.check_cancel()

        state = status.get("status")
        downloaded = int(status.get("downloaded_bytes") or 0)
        if downloaded > max_size:
            raise FileTooLargeError()

        if state == "downloading":
            total = status.get("total_bytes") or status.get("total_bytes_estimate")
            if total:
                if int(total) > max_size:
                    raise FileTooLargeError()
                # The fetch stage owns 5-85% of the overall bar.
                fraction = downloaded / float(total)
                percent = 5 + int(fraction * 80)
            else:
                percent = 40
            speed = status.get("speed")
            eta = status.get("eta")
            reporter.push(
                percent,
                "Downloading",
                eta=int(eta) if eta else None,
                speed=int(speed) if speed else None,
            )
        elif state == "finished":
            reporter.push(85, "Download complete", force=True)

    return hook


def _make_postprocessor_hook(reporter: _ProgressReporter):
    def hook(status: dict[str, Any]) -> None:
        reporter.check_cancel()
        if status.get("status") == "started":
            name = str(status.get("postprocessor") or "")
            label = "Converting audio" if "ExtractAudio" in name else "Processing media"
            _set_status(reporter.job_id, JobStatus.PROCESSING.value)
            reporter.push(88, label, force=True)
        elif status.get("status") == "finished":
            reporter.push(95, "Finalising", force=True)

    return hook


# --------------------------------------------------------------------------- #
# Images / slideshows
# --------------------------------------------------------------------------- #
async def _run_image_pipeline(
    job: dict[str, Any],
    media: NormalizedMedia,
    work_dir: Path,
    reporter: _ProgressReporter,
) -> dict[str, Any]:
    job_id = job["id"]
    if not media.images:
        raise MediaUnavailableError("No images could be found in this post.")

    selection = job.get("selected_images") or {}
    wanted = selection.get("indexes") if isinstance(selection, dict) else None
    images = media.images
    if wanted:
        allowed = {int(i) for i in wanted if isinstance(i, (int, float, str)) and str(i).isdigit()}
        images = [img for img in media.images if img.index in allowed] or media.images

    _set_status(job_id, JobStatus.DOWNLOADING.value, progress=10, progress_label="Fetching images")

    saved: list[Path] = []
    total = len(images)
    max_size = 0
    with session_scope() as db:
        max_size = store.get_int(db, "max_file_size")

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        follow_redirects=False,
        headers={"User-Agent": settings.YTDLP_USER_AGENT or "Mozilla/5.0"},
        limits=httpx.Limits(max_connections=4),
    ) as client:
        running_total = 0
        for position, image in enumerate(images):
            reporter.check_cancel()
            target = work_dir / sanitize_filename(
                f"{position + 1:02d}", extension=image.ext or "jpg", fallback=f"image-{position}"
            )
            written = await _download_image(client, image.url, target, max_size - running_total)
            if written > 0:
                saved.append(target)
                running_total += written
            reporter.push(
                10 + int((position + 1) / total * 70),
                f"Fetched {position + 1} of {total} images",
            )

    if not saved:
        raise MediaUnavailableError("None of the images in this post could be fetched.")

    base_name = sanitize_filename(
        media.title or f"{job['platform']}-images", fallback=f"{job['platform']}-images"
    )

    # A single image is served directly; multiple images are zipped.
    if len(saved) == 1:
        only = saved[0]
        ext = only.suffix.lstrip(".").lower() or "jpg"
        final = work_dir / sanitize_filename(base_name, extension=ext)
        if final != only:
            storage.atomic_replace(only, final)
        return {
            "path": final,
            "filename": final.name,
            "size": final.stat().st_size,
            "mime": MIME_BY_EXT.get(ext, "image/jpeg"),
        }

    _set_status(job_id, JobStatus.PROCESSING.value, progress=85, progress_label="Building ZIP")
    archive = work_dir / sanitize_filename(base_name, extension="zip")
    await asyncio.to_thread(functools.partial(_build_zip, saved, archive))

    size = archive.stat().st_size
    if size > max_size:
        archive.unlink(missing_ok=True)
        raise FileTooLargeError()

    return {
        "path": archive,
        "filename": archive.name,
        "size": size,
        "mime": "application/zip",
    }


async def _download_image(
    client: httpx.AsyncClient,
    url: str,
    target: Path,
    remaining_budget: int,
) -> int:
    """Stream one image to disk with SSRF and size checks. Returns bytes written."""
    try:
        checked = assert_url_allowed(url)
    except AppError:
        log.info("skipped image with disallowed URL")
        return 0

    budget = max(0, remaining_budget)
    if budget == 0:
        raise FileTooLargeError()

    current = checked.url
    for _ in range(4):
        try:
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return 0
                    from app.core.ssrf import safe_redirect_target

                    current = safe_redirect_target(location, base_url=current)
                    continue
                if response.status_code >= 400:
                    return 0

                written = 0
                with target.open("wb") as handle:
                    async for chunk in response.aiter_bytes(64 * 1024):
                        written += len(chunk)
                        if written > budget:
                            handle.close()
                            target.unlink(missing_ok=True)
                            raise FileTooLargeError()
                        handle.write(chunk)
                return written
        except FileTooLargeError:
            raise
        except (httpx.HTTPError, OSError) as exc:
            log.info("image fetch failed: %s", type(exc).__name__)
            target.unlink(missing_ok=True)
            return 0
    return 0


def _build_zip(files: list[Path], archive: Path) -> None:
    # Images are already compressed; ZIP_STORED avoids burning CPU for nothing.
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
        for path in files:
            zf.write(path, arcname=path.name)
    for path in files:
        path.unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# Publish
# --------------------------------------------------------------------------- #
def _publish(job_id: str, result: dict[str, Any], *, ttl_seconds: int) -> None:
    from datetime import timedelta

    path: Path = result["path"]
    with session_scope() as db:
        job = db.get(DownloadJob, job_id)
        if job is None:
            return
        job.status = JobStatus.READY.value
        job.file_path = str(path)
        job.file_name = result["filename"]
        job.file_size = int(result["size"])
        job.mime_type = result["mime"]
        job.progress = 100
        job.progress_label = "Ready"
        job.eta_seconds = None
        job.speed_bps = None
        job.finished_at = utcnow()
        job.expires_at = utcnow() + timedelta(seconds=ttl_seconds)
        if job.started_at:
            job.duration_ms = int((utcnow() - job.started_at).total_seconds() * 1000)
        _write_history(db, job)

    log.info(
        "job ready",
        job_id=job_id,
        size=result["size"],
        filename_len=len(result["filename"]),
    )


# --------------------------------------------------------------------------- #
# FFmpeg direct invocation (used by the audio-from-slideshow path and tests)
# --------------------------------------------------------------------------- #
def transcode_to_mp3(source: Path, destination: Path, bitrate: int | None) -> None:
    """Convert an arbitrary audio/video file to MP3 with FFmpeg."""
    binary = resolve_binary(settings.FFMPEG_PATH, "ffmpeg")
    if not binary:
        raise FFmpegMissingError()

    args = [
        binary,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-threads",
        "1",
    ]
    if bitrate:
        args += ["-b:a", f"{int(bitrate)}k"]
    else:
        args += ["-q:a", "2"]  # ~190 kbps VBR
    args.append(str(destination))

    try:
        result = subprocess.run(  # noqa: S603 - argv list, binary resolved from config
            args,
            capture_output=True,
            text=True,
            timeout=settings.JOB_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(detail="ffmpeg timed out") from exc
    except OSError as exc:
        raise FFmpegMissingError(detail=str(exc)[:200]) from exc

    if result.returncode != 0 or not destination.exists():
        raise FFmpegError(detail=(result.stderr or "")[-400:])


def ffmpeg_binary_present() -> bool:
    return bool(
        shutil.which(settings.FFMPEG_PATH) or resolve_binary(settings.FFMPEG_PATH, "ffmpeg")
    )


def pending_job_ids() -> list[str]:
    with session_scope() as db:
        return list(
            db.execute(
                select(DownloadJob.id).where(DownloadJob.status == JobStatus.QUEUED.value)
            ).scalars()
        )
