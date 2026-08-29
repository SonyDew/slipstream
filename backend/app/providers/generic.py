"""Fallback provider.

Claims any URL that no dedicated provider matched, so the roughly 1800 sites
yt-dlp supports keep working without a bespoke class each. Registered at the
lowest priority so a specific provider always wins.
"""

from __future__ import annotations

from typing import Any, ClassVar

from app.providers.base import YtDlpProvider
from app.services.slideshow import images_from_ytdlp_info


class GenericProvider(YtDlpProvider):
    platform: ClassVar[str] = "generic"
    label: ClassVar[str] = "Direct link"
    priority: ClassVar[int] = -100

    def matches(self, url: str) -> bool:
        # The registry only consults this provider after every other one has
        # declined, so it accepts everything that reached it.
        return True

    def extra_ydl_opts(self) -> dict[str, Any]:
        return {"noplaylist": True}

    def _normalize_images(self, raw: dict[str, Any]):
        return images_from_ytdlp_info(raw)
