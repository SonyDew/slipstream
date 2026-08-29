"""Media analysis.

Wraps provider extraction with the checks that must happen before any network
call (SSRF, platform allow-list, maintenance mode) and turns the normalized
result into the payload the frontend renders.

A small TTL cache sits in front of extraction. It exists for two reasons: the
"analyse then download" flow would otherwise extract twice, and a user retrying
a link should not generate repeated requests to the source platform.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.core.errors import UnsupportedURLError
from app.core.logging import get_logger
from app.core.settings_store import store
from app.core.ssrf import assert_url_allowed
from app.providers.models import NormalizedMedia
from app.providers.registry import registry
from app.services.extractor import ffmpeg_available
from app.services.formats import build_audio_options, build_video_options

log = get_logger("slipstream.analyze")

CACHE_TTL_SECONDS = 300.0
CACHE_MAX_ENTRIES = 256


@dataclass
class _Entry:
    media: NormalizedMedia
    stored_at: float


class AnalysisCache:
    """Tiny TTL cache with a per-URL lock so concurrent requests coalesce."""

    def __init__(self, ttl: float = CACHE_TTL_SECONDS, max_entries: int = CACHE_MAX_ENTRIES):
        self._entries: dict[str, _Entry] = {}
        self._lock = threading.Lock()
        self._locks: dict[str, asyncio.Lock] = {}
        self._ttl = ttl
        self._max = max_entries

    def get(self, key: str) -> NormalizedMedia | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            if now - entry.stored_at > self._ttl:
                self._entries.pop(key, None)
                return None
            return entry.media

    def put(self, key: str, media: NormalizedMedia) -> None:
        with self._lock:
            if len(self._entries) >= self._max:
                # Evict the oldest; this cache is a latency optimisation, so a
                # crude policy is fine.
                oldest = min(self._entries.items(), key=lambda kv: kv[1].stored_at)[0]
                self._entries.pop(oldest, None)
            self._entries[key] = _Entry(media, time.monotonic())

    def lock_for(self, key: str) -> asyncio.Lock:
        with self._lock:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
                # Bound the lock dictionary.
                if len(self._locks) > self._max * 2:
                    for stale in list(self._locks)[: self._max]:
                        if stale != key and not self._locks[stale].locked():
                            self._locks.pop(stale, None)
            return lock

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


cache = AnalysisCache()


async def analyze_url(
    raw_url: str,
    db: Session,
    *,
    use_cache: bool = True,
) -> NormalizedMedia:
    """Validate, route and extract. Returns normalized media."""
    checked = assert_url_allowed(raw_url)
    allowed = store.get_list(db, "allowed_platforms")

    provider = registry.find_enabled(checked.url, allowed or None)

    key = checked.url
    if use_cache:
        cached = cache.get(key)
        if cached is not None:
            log.debug("analysis cache hit")
            return cached

    lock = cache.lock_for(key)
    async with lock:
        # Another coroutine may have populated the cache while we waited.
        if use_cache:
            cached = cache.get(key)
            if cached is not None:
                return cached

        log.info(
            "analysing url",
            platform=provider.platform,
            host=urlparse(checked.url).hostname,
        )
        media = await provider.analyze(checked.url)

        if media.media_type == "unknown" and not media.formats and not media.images:
            raise UnsupportedURLError("No downloadable media was found at that link.")

        cache.put(key, media)
        return media


def build_analysis_payload(media: NormalizedMedia, *, container: str = "mp4") -> dict[str, Any]:
    """Shape a :class:`NormalizedMedia` for the API/frontend."""
    has_ffmpeg = ffmpeg_available()

    video_options = build_video_options(media, container=container, ffmpeg_available=has_ffmpeg)
    audio_options = build_audio_options(media)

    warnings = list(media.warnings)
    if not has_ffmpeg:
        if media.has_audio:
            warnings.append(
                "FFmpeg is not installed on this server, so MP3 conversion is unavailable."
            )
        # build_video_options already dropped adaptive-only rungs, so compare
        # against what the source really has to explain the shortfall.
        adaptive_only = [f for f in media.formats if f.has_video and not f.is_progressive]
        if adaptive_only and not video_options:
            warnings.append(
                "This video is only published as separate video and audio streams, "
                "which need FFmpeg to combine. Install FFmpeg on the server to "
                "enable video downloads for this source."
            )
        elif adaptive_only:
            warnings.append(
                "Higher qualities need FFmpeg to combine separate streams and are "
                "hidden until it is installed."
            )

    return {
        "platform": media.platform,
        "platform_label": media.platform_label or media.platform.title(),
        "original_url": media.original_url,
        "media_id": media.media_id,
        "title": media.title or "Untitled",
        "description": media.description,
        "author": media.author,
        "author_url": media.author_url,
        "thumbnail": media.thumbnail,
        "duration": media.duration,
        "duration_label": format_duration(media.duration),
        "upload_date": media.upload_date,
        "view_count": media.view_count,
        "like_count": media.like_count,
        "media_type": media.media_type,
        "is_slideshow": media.is_slideshow,
        "extractor": media.extractor,
        "is_live": media.is_live,
        "video_options": [o.model_dump() for o in video_options],
        # MP3 output is impossible without FFmpeg, so offer nothing rather than
        # options that would fail at download time.
        "audio_options": [o.model_dump() for o in audio_options] if has_ffmpeg else [],
        "images": [i.model_dump() for i in media.images],
        "audio_available": media.has_audio,
        "ffmpeg_available": has_ffmpeg,
        "warnings": _dedupe(warnings),
        "metadata": media.metadata,
    }


def _dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


def format_duration(seconds: int | None) -> str | None:
    if not seconds or seconds <= 0:
        return None
    hours, remainder = divmod(int(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
