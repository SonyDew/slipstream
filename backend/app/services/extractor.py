"""yt-dlp integration.

All extractor access funnels through here so that timeouts, option hardening,
SSRF validation and error classification are applied uniformly. yt-dlp is
synchronous, so every call is dispatched to a worker thread and wrapped in an
asyncio timeout.
"""

from __future__ import annotations

import asyncio
import functools
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.errors import (
    AppError,
    ExtractorFailureError,
    NetworkTimeoutError,
)
from app.core.logging import get_logger
from app.core.ssrf import assert_url_allowed
from app.providers.base import classify_extractor_error

log = get_logger("slipstream.extractor")

# Extractors that would let the service be pointed at arbitrary internal hosts
# or at protocols we do not want to speak. yt-dlp's `generic` extractor will
# happily fetch any URL, so it stays enabled but the URL is SSRF-checked first.
_BLOCKED_PROTOCOLS = ("file", "ftp", "ftps", "data", "gopher", "dict", "smb")


def base_ydl_opts(**overrides: Any) -> dict[str, Any]:
    """Hardened default yt-dlp options."""
    opts: dict[str, Any] = {
        # Silence: yt-dlp writes to stdout by default and can echo signed URLs.
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "logger": _NullLogger(),
        "verbose": False,
        # Never touch the user's home directory or leave state behind.
        "cachedir": False,
        "no_color": True,
        # Do not read a system/user config that could re-enable dangerous flags.
        "ignoreconfig": True,
        # Networking
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 3,
        "extractor_retries": 1,
        "nocheckcertificate": False,
        # Safety
        "noplaylist": True,
        "geo_bypass": False,  # we do not defeat geo restrictions
        "age_limit": None,
        "call_home": False,
        "check_formats": False,
        # Never write metadata/thumbnail sidecar files.
        "writethumbnail": False,
        "writeinfojson": False,
        "writesubtitles": False,
        "writeautomaticsub": False,
        "overwrites": True,
        "consoletitle": False,
        "progress_hooks": [],
        # Reject the protocols we never want yt-dlp to speak.
        "allowed_extractors": ["default"],
    }

    if settings.FFMPEG_PATH and settings.FFMPEG_PATH != "ffmpeg":
        opts["ffmpeg_location"] = settings.FFMPEG_PATH
    elif ffmpeg_dir := _ffmpeg_directory():
        opts["ffmpeg_location"] = ffmpeg_dir

    if settings.YTDLP_PROXY:
        opts["proxy"] = settings.YTDLP_PROXY
    if settings.YTDLP_USER_AGENT:
        opts.setdefault("http_headers", {})["User-Agent"] = settings.YTDLP_USER_AGENT

    # Deep-merge http_headers so a provider adding a Referer does not drop the UA.
    headers_override = overrides.pop("http_headers", None)
    if headers_override:
        merged = dict(opts.get("http_headers") or {})
        merged.update(headers_override)
        opts["http_headers"] = merged

    opts.update(overrides)
    return opts


class _NullLogger:
    """Swallow yt-dlp's own logging; we surface errors through exceptions."""

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        # Kept at debug: the exception carries the same text and is classified.
        log.debug("yt-dlp error: %s", str(msg)[:300])


def _run_sync_extract(url: str, opts: dict[str, Any]) -> dict[str, Any]:
    """Blocking yt-dlp metadata extraction. Runs on a worker thread."""
    import yt_dlp

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
        if info is None:
            raise ExtractorFailureError(detail="extractor returned no info")
        # sanitize_info strips the internal, non-serialisable and credential-ish
        # fields (cookies, http_headers on formats, etc.).
        return ydl.sanitize_info(info)  # type: ignore[no-any-return]


async def _to_thread_with_timeout(
    func: Callable[[], Any],
    *,
    timeout: int,
    what: str,
) -> Any:
    """Run a blocking callable in a thread, bounded by ``timeout`` seconds."""
    try:
        return await asyncio.wait_for(asyncio.to_thread(func), timeout=timeout)
    except TimeoutError as exc:
        log.warning("%s timed out after %ss", what, timeout)
        raise NetworkTimeoutError(detail=f"{what} exceeded {timeout}s") from exc


async def extract_info(
    url: str,
    *,
    extra_opts: dict[str, Any] | None = None,
    timeout: int | None = None,
) -> dict[str, Any]:
    """Extract metadata for ``url``.

    Raises an :class:`AppError` subclass on every failure path; callers never
    see a raw yt-dlp exception.
    """
    checked = assert_url_allowed(url)
    if checked.scheme in _BLOCKED_PROTOCOLS:  # pragma: no cover - ssrf covers this
        raise ExtractorFailureError(detail=f"blocked protocol {checked.scheme}")

    opts = base_ydl_opts(**(extra_opts or {}))
    deadline = timeout or settings.ANALYZE_TIMEOUT

    try:
        return await _to_thread_with_timeout(
            functools.partial(_run_sync_extract, checked.url, opts),
            timeout=deadline,
            what="metadata extraction",
        )
    except AppError:
        raise
    except Exception as exc:
        raise classify_extractor_error(exc) from exc


# --------------------------------------------------------------------------- #
# Toolchain probes (used by /api/health and startup logging)
# --------------------------------------------------------------------------- #
def _ffmpeg_directory() -> str | None:
    """Directory containing a discoverable ffmpeg, for yt-dlp's ffmpeg_location."""
    found = shutil.which("ffmpeg")
    return str(Path(found).parent) if found else None


def resolve_binary(configured: str, fallback_name: str) -> str | None:
    """Resolve a configured binary path or look it up on PATH."""
    if configured and configured != fallback_name:
        candidate = Path(configured)
        if candidate.is_file():
            return str(candidate)
        # A directory was given: look inside it.
        if candidate.is_dir():
            for suffix in ("", ".exe"):
                inner = candidate / f"{fallback_name}{suffix}"
                if inner.is_file():
                    return str(inner)
        found = shutil.which(configured)
        if found:
            return found
        return None
    return shutil.which(fallback_name)


@functools.lru_cache(maxsize=4)
def _probe_binary_cached(path: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(  # noqa: S603 - path resolved from config/PATH
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, type(exc).__name__
    if result.returncode != 0:
        return False, f"exit {result.returncode}"
    first_line = (result.stdout or result.stderr or "").splitlines()
    version = first_line[0].strip() if first_line else "unknown"
    return True, version[:120]


def ffmpeg_status() -> dict[str, Any]:
    """Report whether FFmpeg/FFprobe are usable."""
    ffmpeg = resolve_binary(settings.FFMPEG_PATH, "ffmpeg")
    ffprobe = resolve_binary(settings.FFPROBE_PATH, "ffprobe")

    available = False
    version = "not found"
    if ffmpeg:
        available, version = _probe_binary_cached(ffmpeg)

    return {
        "available": available,
        "version": version,
        "path": ffmpeg,
        "ffprobe_available": bool(ffprobe),
    }


def ffmpeg_available() -> bool:
    return bool(ffmpeg_status()["available"])


def extractor_status() -> dict[str, Any]:
    try:
        import yt_dlp

        return {
            "available": True,
            "name": "yt-dlp",
            "version": yt_dlp.version.__version__,
        }
    except Exception as exc:
        return {"available": False, "name": "yt-dlp", "error": type(exc).__name__}


def reset_probe_cache() -> None:
    """Clear the memoised binary probes (used by tests and after an update)."""
    _probe_binary_cached.cache_clear()
