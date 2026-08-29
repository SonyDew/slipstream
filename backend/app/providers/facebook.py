"""Facebook — public videos, reels and watch pages."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from app.providers.base import YtDlpProvider


class FacebookProvider(YtDlpProvider):
    platform: ClassVar[str] = "facebook"
    label: ClassVar[str] = "Facebook"
    domains: ClassVar[tuple[str, ...]] = ("facebook.com", "fb.watch", "fb.com", "m.facebook.com")
    url_patterns: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"^(?:[\w-]+\.)*facebook\.com/(?:watch|reel|share|[^/]+/videos)/", re.I),
    )
    priority: ClassVar[int] = 10

    def extra_ydl_opts(self) -> dict[str, Any]:
        return {"noplaylist": True}
