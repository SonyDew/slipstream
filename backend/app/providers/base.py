"""Provider base classes.

A provider owns two things for one family of sites: URL recognition, and turning
raw extractor output into a :class:`NormalizedMedia`. Everything else — the
queue, the HTTP layer, file handling — is provider-agnostic.

``YtDlpProvider`` carries the shared yt-dlp implementation so a concrete
provider is usually only a URL pattern plus a few normalisation overrides.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any, ClassVar
from urllib.parse import urlparse

from app.core.errors import (
    AppError,
    AuthRequiredContentError,
    DRMProtectedError,
    ExtractorFailureError,
    GeoRestrictedError,
    MediaUnavailableError,
    NetworkTimeoutError,
    PrivateContentError,
)
from app.core.logging import get_logger
from app.providers.models import (
    MediaFormat,
    MediaImage,
    NormalizedMedia,
)

log = get_logger("slipstream.providers")


class MediaProvider(ABC):
    """Contract every provider implements."""

    # Machine name, used in the DB and the admin allow-list.
    platform: ClassVar[str] = "generic"
    # Human label for the UI badge.
    label: ClassVar[str] = "Generic"
    # Host suffixes this provider claims.
    domains: ClassVar[tuple[str, ...]] = ()
    # Optional extra patterns, for a provider that must disambiguate by path.
    # Matched against "<host><path>" and therefore MUST be anchored with ^, so a
    # lookalike host such as notyoutube.com/watch cannot satisfy them.
    url_patterns: ClassVar[tuple[re.Pattern[str], ...]] = ()
    # Higher wins when several providers match. `generic` sits at -100.
    priority: ClassVar[int] = 0
    # Whether the provider is currently healthy enough to advertise publicly.
    # Recognition remains active when false so users receive a precise error.
    operational: ClassVar[bool] = True

    def matches(self, url: str) -> bool:
        """True when this provider claims the URL."""
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().lstrip(".")
        if host:
            for domain in self.domains:
                # Exact host, or a genuine subdomain. Never a suffix match on the
                # raw string, which would accept "notyoutube.com".
                if host == domain or host.endswith(f".{domain}"):
                    return True

        if not self.url_patterns:
            return False
        target = f"{host}{parsed.path}"
        return any(pattern.search(target) for pattern in self.url_patterns)

    @abstractmethod
    async def analyze(self, url: str) -> NormalizedMedia:
        """Extract metadata without downloading media bytes."""

    def extra_ydl_opts(self) -> dict[str, Any]:
        """Extractor options this provider needs. Part of the provider contract
        so callers can consult it without knowing the concrete class."""
        return {}

    def build_format_selector(
        self,
        *,
        mode: str,
        quality: str,
        container: str,
    ) -> str:
        """Translate a validated quality token into an extractor format spec."""
        raise NotImplementedError

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} platform={self.platform}>"


# --------------------------------------------------------------------------- #
# yt-dlp backed implementation
# --------------------------------------------------------------------------- #
# Message fragments yt-dlp emits, mapped to our error taxonomy. Matched
# case-insensitively against the exception text.
_ERROR_SIGNATURES: tuple[tuple[tuple[str, ...], type[AppError]], ...] = (
    (("drm", "protected by drm"), DRMProtectedError),
    (
        (
            "private video",
            "this video is private",
            "private account",
            "login required to view",
            "this post is not available",
            "requested content is not available",
        ),
        PrivateContentError,
    ),
    (
        (
            "sign in to confirm",
            "sign in to view",
            "cookies",
            "authentication",
            "log in",
            "confirm your age",
            "age-restricted",
            "account authentication",
        ),
        AuthRequiredContentError,
    ),
    (
        (
            "available in your country",
            "not available in your country",
            "geo restricted",
            "geo-restricted",
            "blocked it in your country",
            "unavailable in your location",
        ),
        GeoRestrictedError,
    ),
    (
        (
            "video unavailable",
            "removed by the uploader",
            "has been removed",
            "no longer available",
            "does not exist",
            "not found",
            "404",
            "deleted",
            "terminated",
            "unable to find",
        ),
        MediaUnavailableError,
    ),
    (
        ("timed out", "timeout", "read operation", "connection reset", "temporary failure"),
        NetworkTimeoutError,
    ),
)


def classify_extractor_error(exc: Exception) -> AppError:
    """Map a raw extractor exception onto a user-safe :class:`AppError`.

    The original text is attached as ``detail`` for the logs only.
    """
    text = str(exc).lower()
    for needles, error_cls in _ERROR_SIGNATURES:
        if any(needle in text for needle in needles):
            return error_cls(detail=str(exc)[:500])
    return ExtractorFailureError(detail=str(exc)[:500])


class YtDlpProvider(MediaProvider):
    """Shared yt-dlp implementation.

    Subclasses normally only declare ``platform``/``domains`` and optionally
    override :meth:`normalize` or :meth:`extra_ydl_opts`.
    """

    # Passed to yt-dlp so it uses the right extractor even for odd short links.
    force_generic: ClassVar[bool] = False

    def extra_ydl_opts(self) -> dict[str, Any]:
        """Provider-specific yt-dlp options."""
        return {}

    async def analyze(self, url: str) -> NormalizedMedia:
        from app.services.extractor import extract_info

        raw = await extract_info(url, extra_opts=self.extra_ydl_opts())
        return self.normalize(url, raw)

    # -- normalisation ---------------------------------------------------- #
    def normalize(self, url: str, raw: dict[str, Any]) -> NormalizedMedia:
        """Turn a yt-dlp info dict into a :class:`NormalizedMedia`."""
        # A playlist/multi-entry result: use the first playable entry but keep a
        # warning so the user understands only one item was taken.
        warnings: list[str] = []
        if raw.get("_type") == "playlist":
            entries = [e for e in (raw.get("entries") or []) if e]
            if not entries:
                raise MediaUnavailableError()
            if len(entries) > 1:
                warnings.append(
                    f"This link contains {len(entries)} items; the first one was analysed."
                )
            playlist_title = raw.get("title")
            raw = entries[0]
            if playlist_title and not raw.get("title"):
                raw["title"] = playlist_title

        formats = self._normalize_formats(raw)
        images = self._normalize_images(raw)

        has_video_stream = any(f.has_video for f in formats)
        has_audio_stream = any(f.has_audio for f in formats)

        if images and not has_video_stream:
            media_type = "image_set" if len(images) > 1 else "image"
        elif has_video_stream:
            media_type = "video"
        elif has_audio_stream:
            media_type = "audio"
        else:
            media_type = "unknown"

        if media_type == "audio":
            warnings.append("This source only provides an audio track.")
        if raw.get("is_live"):
            warnings.append("This is a live stream; only the current buffer can be captured.")

        media = NormalizedMedia(
            platform=self.platform,
            platform_label=self.label,
            original_url=url,
            media_id=str(raw.get("id")) if raw.get("id") is not None else None,
            title=self._clean_text(raw.get("title")) or None,
            description=self._clean_text(raw.get("description"), limit=2000) or None,
            author=self._pick_author(raw),
            author_url=raw.get("uploader_url") or raw.get("channel_url"),
            thumbnail=self._pick_thumbnail(raw),
            duration=self._coerce_int(raw.get("duration")),
            upload_date=raw.get("upload_date"),
            view_count=self._coerce_int(raw.get("view_count")),
            like_count=self._coerce_int(raw.get("like_count")),
            media_type=media_type,  # type: ignore[arg-type]
            formats=formats,
            images=images,
            audio_available=has_audio_stream or bool(raw.get("_slideshow_audio")),
            extractor=str(raw.get("extractor") or "yt-dlp"),
            is_live=bool(raw.get("is_live")),
            age_limit=self._coerce_int(raw.get("age_limit")) or 0,
            warnings=warnings,
            metadata=self._safe_metadata(raw),
        )
        return media

    # -- helpers ---------------------------------------------------------- #
    def _normalize_formats(self, raw: dict[str, Any]) -> list[MediaFormat]:
        out: list[MediaFormat] = []
        for entry in raw.get("formats") or []:
            if not isinstance(entry, dict):
                continue
            vcodec = (entry.get("vcodec") or "none").lower()
            acodec = (entry.get("acodec") or "none").lower()
            has_video = vcodec not in {"none", ""} or entry.get("height") is not None
            has_audio = acodec not in {"none", ""}
            if not has_video and not has_audio:
                continue

            protocol = (entry.get("protocol") or "").lower()
            # Storyboard/thumbnail pseudo-formats and manifest-only entries are
            # not downloadable media.
            if entry.get("format_note") == "storyboard" or vcodec == "mjpeg":
                continue
            if protocol in {"mhtml"}:
                continue

            filesize = self._coerce_int(entry.get("filesize"))
            approx = filesize is None
            if approx:
                filesize = self._coerce_int(entry.get("filesize_approx"))

            height = self._coerce_int(entry.get("height"))
            fmt = MediaFormat(
                format_id=str(entry.get("format_id") or ""),
                ext=(entry.get("ext") or "mp4").lower(),
                label=self._format_label(entry, height, has_video, has_audio),
                height=height,
                width=self._coerce_int(entry.get("width")),
                fps=self._coerce_float(entry.get("fps")),
                vcodec=None if vcodec == "none" else vcodec,
                acodec=None if acodec == "none" else acodec,
                filesize=filesize,
                filesize_is_estimate=approx and filesize is not None,
                tbr=self._coerce_float(entry.get("tbr")),
                abr=self._coerce_float(entry.get("abr")),
                has_video=has_video,
                has_audio=has_audio,
                needs_merge=has_video and not has_audio,
                protocol=protocol or None,
                note=entry.get("format_note") or None,
            )
            out.append(fmt)

        # Some extractors (older TikTok, direct files) expose a bare `url` with
        # no `formats` list at all.
        if not out and raw.get("url"):
            height = self._coerce_int(raw.get("height"))
            out.append(
                MediaFormat(
                    format_id=str(raw.get("format_id") or "0"),
                    ext=(raw.get("ext") or "mp4").lower(),
                    label=f"{height}p" if height else "Source",
                    height=height,
                    width=self._coerce_int(raw.get("width")),
                    has_video=True,
                    has_audio=True,
                    filesize=self._coerce_int(raw.get("filesize"))
                    or self._coerce_int(raw.get("filesize_approx")),
                )
            )
        return out

    def _normalize_images(self, raw: dict[str, Any]) -> list[MediaImage]:
        """Override point for slideshow platforms."""
        return []

    @staticmethod
    def _format_label(
        entry: dict[str, Any], height: int | None, has_video: bool, has_audio: bool
    ) -> str:
        if has_video and height:
            fps = entry.get("fps")
            suffix = f"{int(fps)}" if fps and float(fps) >= 50 else ""
            return f"{height}p{suffix}"
        if has_audio and not has_video:
            abr = entry.get("abr") or entry.get("tbr")
            return f"{int(abr)} kbps audio" if abr else "Audio"
        return str(entry.get("format_note") or entry.get("format_id") or "Source")

    @staticmethod
    def _pick_author(raw: dict[str, Any]) -> str | None:
        for key in (
            "uploader",
            "channel",
            "creator",
            "artist",
            "uploader_id",
            "webpage_url_domain",
        ):
            value = raw.get(key)
            if value:
                return str(value)[:255]
        return None

    @staticmethod
    def _pick_thumbnail(raw: dict[str, Any]) -> str | None:
        if raw.get("thumbnail"):
            return str(raw["thumbnail"])
        thumbs = raw.get("thumbnails") or []
        best: str | None = None
        best_area = -1
        for thumb in thumbs:
            if not isinstance(thumb, dict) or not thumb.get("url"):
                continue
            area = (thumb.get("width") or 0) * (thumb.get("height") or 0)
            if area >= best_area:
                best_area = area
                best = str(thumb["url"])
        return best

    @staticmethod
    def _clean_text(value: Any, limit: int = 500) -> str:
        if not value:
            return ""
        text = str(value).replace("\x00", "").strip()
        return text[:limit]

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        try:
            if value is None or isinstance(value, bool):
                return None
            return int(float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        try:
            if value is None or isinstance(value, bool):
                return None
            return round(float(value), 3)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _safe_metadata(raw: dict[str, Any]) -> dict[str, Any]:
        """Whitelist of extra fields safe to persist and return.

        A yt-dlp info dict contains request headers, cookies and signed URLs, so
        this is an allow-list rather than a deny-list.
        """
        allowed = (
            "webpage_url_domain",
            "extractor_key",
            "categories",
            "tags",
            "comment_count",
            "repost_count",
            "channel_follower_count",
            "availability",
            "live_status",
            "resolution",
            "aspect_ratio",
            "track",
            "album",
        )
        out: dict[str, Any] = {}
        for key in allowed:
            value = raw.get(key)
            if value in (None, "", [], {}):
                continue
            if isinstance(value, (list, tuple)):
                out[key] = [str(v)[:80] for v in value[:12]]
            elif isinstance(value, (int, float, bool)):
                out[key] = value
            else:
                out[key] = str(value)[:200]
        return out
