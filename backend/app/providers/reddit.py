"""Reddit — v.redd.it hosted video and image posts."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from app.providers.base import YtDlpProvider
from app.services.slideshow import images_from_ytdlp_info


class RedditProvider(YtDlpProvider):
    platform: ClassVar[str] = "reddit"
    label: ClassVar[str] = "Reddit"
    domains: ClassVar[tuple[str, ...]] = (
        "reddit.com",
        "redd.it",
        "v.redd.it",
        "i.redd.it",
        "old.reddit.com",
    )
    url_patterns: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"^(?:[\w-]+\.)*reddit\.com/r/[^/]+/comments/", re.I),
    )
    priority: ClassVar[int] = 10

    def extra_ydl_opts(self) -> dict[str, Any]:
        return {"noplaylist": True}

    def _normalize_images(self, raw: dict[str, Any]):
        return images_from_ytdlp_info(raw)
