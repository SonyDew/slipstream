"""Vimeo — public and unlisted-with-link videos."""

from __future__ import annotations

import re
from typing import ClassVar

from app.core.errors import (
    AuthRequiredContentError,
    ExtractorFailureError,
    PlatformTemporarilyUnsupportedError,
)
from app.providers.base import YtDlpProvider
from app.providers.models import NormalizedMedia


class VimeoProvider(YtDlpProvider):
    platform: ClassVar[str] = "vimeo"
    label: ClassVar[str] = "Vimeo"
    domains: ClassVar[tuple[str, ...]] = ("vimeo.com", "player.vimeo.com")
    url_patterns: ClassVar[tuple[re.Pattern[str], ...]] = (
        re.compile(r"^(?:[\w-]+\.)*vimeo\.com/(?:\d+|channels/|groups/)", re.I),
    )
    priority: ClassVar[int] = 10
    # Vimeo disabled anonymous API access in July 2026. Keep recognition and
    # extraction in place, but do not market it as an enabled source until the
    # upstream anonymous client works again.
    operational: ClassVar[bool] = False

    async def analyze(self, url: str) -> NormalizedMedia:
        """Give an honest error for Vimeo's current anonymous-client outage.

        Since July 2026 Vimeo's anonymous API client can no longer obtain an
        OAuth token.  The web client then asks for a login, even for otherwise
        public videos, while some player pages are rejected with a 403.  Those
        are platform-wide extractor failures, not evidence that the user's
        particular video is private.

        Keep using yt-dlp first so working embeds and a future upstream repair
        start working automatically.  Only remap the two known outage
        signatures; genuine private/login-only Vimeo content keeps the normal
        authentication error.
        """
        try:
            return await super().analyze(url)
        except (AuthRequiredContentError, ExtractorFailureError) as exc:
            detail = (exc.detail or "").lower()
            anonymous_client_outage = (
                "web client only works when logged-in" in detail
                or "failed to fetch macos oauth token" in detail
                or ("http error 403" in detail and "vimeo" in detail)
            )
            if anonymous_client_outage:
                raise PlatformTemporarilyUnsupportedError(
                    "Vimeo public downloads are temporarily unavailable because "
                    "Vimeo currently blocks anonymous extractor access.",
                    detail=exc.detail,
                ) from exc
            raise
