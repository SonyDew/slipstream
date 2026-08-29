"""Health, version and public configuration endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import DbSession
from app.core.config import settings
from app.core.settings_store import public_settings
from app.core.version import build_info
from app.db.session import check_database
from app.providers.registry import registry
from app.services.extractor import extractor_status, ffmpeg_status
from app.services.queue import get_queue
from app.services.storage import disk_free_bytes, temp_usage

router = APIRouter(tags=["system"])


@router.get("/health")
def health(response: Response) -> dict:
    """Service health.

    Deliberately free of environment detail: no paths, no database URL, no
    secrets — only whether each dependency works. FFmpeg being absent is
    reported as ``degraded`` rather than unhealthy, because video downloads that
    need no muxing still work without it.
    """
    db_ok, db_detail = check_database()
    extractor = extractor_status()
    ffmpeg = ffmpeg_status()
    queue_stats = get_queue().stats()

    components = {
        "database": {"status": "ok" if db_ok else "error", "detail": db_detail},
        "extractor": {
            "status": "ok" if extractor["available"] else "error",
            "name": extractor.get("name"),
            "version": extractor.get("version"),
        },
        "ffmpeg": {
            "status": "ok" if ffmpeg["available"] else "unavailable",
            "version": ffmpeg["version"] if ffmpeg["available"] else None,
        },
        "queue": {
            "status": "ok" if queue_stats.running else "stopped",
            "workers": queue_stats.workers,
            "active": queue_stats.active,
            "queued": queue_stats.queued,
        },
    }

    if not db_ok or not extractor["available"]:
        overall = "unhealthy"
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    elif not ffmpeg["available"] or not queue_stats.running:
        overall = "degraded"
    else:
        overall = "healthy"

    return {
        "status": overall,
        "version": build_info()["version"],
        "environment": settings.ENVIRONMENT,
        "components": components,
    }


@router.get("/health/ready")
def readiness(response: Response) -> dict:
    """Minimal readiness probe for container orchestration."""
    db_ok, _ = check_database()
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"ready": False}
    return {"ready": True}


@router.get("/version")
def version() -> dict:
    """Safe build metadata for the About page."""
    info = build_info()
    return {
        **info,
        "extractor": extractor_status(),
        "ffmpeg_available": ffmpeg_status()["available"],
    }


@router.get("/config")
def public_config(db: DbSession) -> dict:
    """Everything the frontend needs before a user signs in."""
    return {
        "app_name": settings.APP_NAME,
        "version": build_info()["version"],
        "environment": settings.ENVIRONMENT,
        **public_settings(db),
        "platforms": registry.describe(),
        "ffmpeg_available": ffmpeg_status()["available"],
        "limits": {
            "max_file_size": settings.MAX_FILE_SIZE,
            "max_video_duration": settings.MAX_VIDEO_DURATION,
        },
    }


@router.get("/health/storage")
def storage_health() -> dict:
    """Temp-area usage. Used by the admin dashboard and monitoring."""
    usage = temp_usage()
    return {
        "temp_bytes": usage["bytes"],
        "temp_files": usage["files"],
        "disk_free_bytes": disk_free_bytes(),
    }
