"""Instagram — public posts, reels and IGTV.

Instagram gates most content behind a session. Slipstream deliberately does not
carry user cookies or credentials, so only genuinely public posts can be read;
anything else surfaces a clear "sign-in required" message.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from app.providers.base import YtDlpProvider
from app.providers.models import NormalizedMedia
from app.services.slideshow import images_from_ytdlp_info


class InstagramProvider(YtDlpProvider):
    platform: ClassVar[str] = "instagram"
    label: ClassVar[str] = "Instagram"
    domains: ClassVar[tuple[str, ...]] = ("instagram.com", "instagr.am", "ddinstagram.com")
    url_patterns: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"^(?:[\w-]+\.)*instagram\.com/(?:p|reel|reels|tv|share)/", re.I),
    )
    priority: ClassVar[int] = 10

    def extra_ydl_opts(self) -> dict[str, Any]:
        return {"noplaylist": True}

    def _normalize_images(self, raw: dict[str, Any]):
        # Carousel posts mixing images and video come back as a playlist.
        return images_from_ytdlp_info(raw)

    def normalize(self, url: str, raw: dict[str, Any]) -> NormalizedMedia:
        media = super().normalize(url, raw)
        if media.media_type == "unknown" and not media.formats:
            media.warnings.append("Only public Instagram posts can be processed.")
        return media
