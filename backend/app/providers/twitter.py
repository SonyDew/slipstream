"""X / Twitter — public posts containing video or images."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from app.providers.base import YtDlpProvider
from app.services.slideshow import images_from_ytdlp_info


class TwitterProvider(YtDlpProvider):
    platform: ClassVar[str] = "twitter"
    label: ClassVar[str] = "X"
    domains: ClassVar[tuple[str, ...]] = (
        "twitter.com",
        "x.com",
        "mobile.twitter.com",
        "fxtwitter.com",
        "vxtwitter.com",
        "nitter.net",
    )
    url_patterns: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"^(?:[\w-]+\.)*(?:twitter|x)\.com/[^/]+/status/\d+", re.I),
    )
    priority: ClassVar[int] = 10

    def extra_ydl_opts(self) -> dict[str, Any]:
        return {"noplaylist": True}

    def _normalize_images(self, raw: dict[str, Any]):
        return images_from_ytdlp_info(raw)
