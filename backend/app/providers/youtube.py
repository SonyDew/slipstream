"""YouTube (and YouTube Music / Shorts / youtu.be)."""

from __future__ import annotations

import re
from typing import Any, ClassVar

from app.providers.base import YtDlpProvider


class YouTubeProvider(YtDlpProvider):
    platform: ClassVar[str] = "youtube"
    label: ClassVar[str] = "YouTube"
    domains: ClassVar[tuple[str, ...]] = (
        "youtube.com",
        "youtu.be",
        "music.youtube.com",
        "m.youtube.com",
        "youtube-nocookie.com",
    )
    url_patterns: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"^(?:[\w-]+\.)*youtube\.com/(?:watch|shorts|live|embed|v)/?", re.I),
    )
    priority: ClassVar[int] = 10

    def extra_ydl_opts(self) -> dict[str, Any]:
        """Options for YouTube.

        Deliberately does **not** pin ``extractor_args.player_client``. Which
        innertube clients work changes on YouTube's schedule, and yt-dlp tracks
        that upstream — hard-coding a client list here means extraction breaks the
        moment one of those names is retired, even though yt-dlp itself would
        have kept working. Let the extractor choose.
        """
        return {
            # A watch URL that also belongs to a playlist should resolve to the
            # single video the user actually pasted.
            "noplaylist": True,
        }
