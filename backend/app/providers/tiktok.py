"""TikTok — videos and photo (slideshow) posts."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from app.core.logging import get_logger
from app.providers.base import YtDlpProvider
from app.providers.models import NormalizedMedia
from app.services.slideshow import fetch_slideshow, images_from_ytdlp_info

log = get_logger("slipstream.providers.tiktok")


class TikTokProvider(YtDlpProvider):
    platform: ClassVar[str] = "tiktok"
    label: ClassVar[str] = "TikTok"
    domains: ClassVar[tuple[str, ...]] = (
        "tiktok.com",
        "vm.tiktok.com",
        "vt.tiktok.com",
        "m.tiktok.com",
        "tiktokv.com",
    )
    url_patterns: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"^(?:[\w-]+\.)*tiktok\.com/@[^/]+/(?:video|photo)/\d+", re.I),
    )
    priority: ClassVar[int] = 10

    # A photo post URL uses /photo/ instead of /video/.
    _PHOTO_URL_RE = re.compile(r"/photo/\d+", re.I)

    def extra_ydl_opts(self) -> dict[str, Any]:
        return {"noplaylist": True}

    def _normalize_images(self, raw: dict[str, Any]):
        return images_from_ytdlp_info(raw)

    async def analyze(self, url: str) -> NormalizedMedia:
        from app.core.errors import AppError
        from app.services.extractor import extract_info

        looks_like_photo = bool(self._PHOTO_URL_RE.search(url))

        raw: dict[str, Any] | None = None
        extractor_error: Exception | None = None
        try:
            raw = await extract_info(url, extra_opts=self.extra_ydl_opts())
        except AppError as exc:
            # A photo post can make the video extractor fail outright. Keep the
            # error and let the slideshow path decide whether to surface it.
            extractor_error = exc
            if not looks_like_photo:
                # Still try the slideshow path — some photo posts do not use
                # the /photo/ URL form.
                images, meta = await fetch_slideshow(url, platform=self.platform)
                if not images:
                    raise
                return self._slideshow_media(url, images, meta, {})

        if raw is not None:
            media = self.normalize(url, raw)
            if media.images and media.media_type in {"image", "image_set"}:
                media.audio_available = media.audio_available or any(
                    f.has_audio for f in media.formats
                )
                return media
            # yt-dlp returned a video result. If the URL says photo but no
            # images came back, try the HTML path before trusting it.
            if looks_like_photo and not media.images:
                images, meta = await fetch_slideshow(url, platform=self.platform)
                if images:
                    media.images = images
                    media.media_type = "image_set" if len(images) > 1 else "image"
                    media.title = media.title or meta.get("title")
                    media.author = media.author or meta.get("author")
                    media.audio_available = media.audio_available or any(
                        f.has_audio for f in media.formats
                    )
            return media

        # Extraction failed and the URL looks like a photo post.
        images, meta = await fetch_slideshow(url, platform=self.platform)
        if images:
            return self._slideshow_media(url, images, meta, {})
        raise extractor_error or RuntimeError("extraction failed")

    def _slideshow_media(
        self,
        url: str,
        images: list,
        meta: dict[str, Any],
        raw: dict[str, Any],
    ) -> NormalizedMedia:
        return NormalizedMedia(
            platform=self.platform,
            platform_label=self.label,
            original_url=url,
            media_id=self._media_id_from_url(url),
            title=meta.get("title"),
            author=meta.get("author"),
            thumbnail=images[0].url if images else None,
            media_type="image_set" if len(images) > 1 else "image",
            images=images,
            audio_available=False,
            extractor="slipstream-slideshow",
            warnings=["Audio for this photo post could not be detected."] if not raw else [],
        )

    @staticmethod
    def _media_id_from_url(url: str) -> str | None:
        match = re.search(r"/(?:video|photo)/(\d+)", url)
        return match.group(1) if match else None
