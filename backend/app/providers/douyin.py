"""Douyin (抖音) — videos and photo posts.

The normal path stays on yt-dlp. If Douyin returns its JavaScript challenge,
the provider can observe the public page's own metadata request in Chromium.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from app.providers.base import YtDlpProvider
from app.providers.models import NormalizedMedia
from app.services.slideshow import fetch_slideshow, images_from_ytdlp_info


class DouyinProvider(YtDlpProvider):
    platform: ClassVar[str] = "douyin"
    label: ClassVar[str] = "Douyin"
    domains: ClassVar[tuple[str, ...]] = (
        "douyin.com",
        "iesdouyin.com",
        "v.douyin.com",
    )
    url_patterns: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"^(?:[\w-]+\.)*douyin\.com/(?:video|note|slides)/\d+", re.I),
    )
    priority: ClassVar[int] = 10

    _NOTE_URL_RE = re.compile(r"/(note|slides)/\d+", re.I)

    def extra_ydl_opts(self) -> dict[str, Any]:
        return {
            "noplaylist": True,
            # Douyin serves the standard page only to browser-like clients.
            "http_headers": {"Referer": "https://www.douyin.com/"},
        }

    def _normalize_images(self, raw: dict[str, Any]):
        return images_from_ytdlp_info(raw)

    async def analyze(self, url: str) -> NormalizedMedia:
        from app.core.errors import AppError
        from app.services.extractor import extract_info

        looks_like_photo = bool(self._NOTE_URL_RE.search(url))

        original_error: AppError | None = None
        try:
            raw = await extract_info(url, extra_opts=self.extra_ydl_opts())
        except AppError as exc:
            original_error = exc
            images, meta = await fetch_slideshow(url, platform=self.platform)
            if images:
                return NormalizedMedia(
                    platform=self.platform,
                    platform_label=self.label,
                    original_url=url,
                    media_id=self._media_id_from_url(url),
                    title=meta.get("title"),
                    author=meta.get("author"),
                    thumbnail=images[0].url,
                    media_type="image_set" if len(images) > 1 else "image",
                    images=images,
                    extractor="slipstream-slideshow",
                )

            from app.services.douyin_browser import extract_public_douyin

            browser_media = await extract_public_douyin(url)
            if browser_media is not None:
                return browser_media
            raise original_error from None

        media = self.normalize(url, raw)
        if looks_like_photo and not media.images:
            images, meta = await fetch_slideshow(url, platform=self.platform)
            if images:
                media.images = images
                media.media_type = "image_set" if len(images) > 1 else "image"
                media.title = media.title or meta.get("title")
                media.author = media.author or meta.get("author")
        return media

    @staticmethod
    def _media_id_from_url(url: str) -> str | None:
        match = re.search(r"/(?:video|note|slides)/(\d+)", url)
        return match.group(1) if match else None
