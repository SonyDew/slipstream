"""SoundCloud — audio-first provider."""

from __future__ import annotations

from typing import Any, ClassVar

from app.providers.base import YtDlpProvider
from app.providers.models import NormalizedMedia


class SoundCloudProvider(YtDlpProvider):
    platform: ClassVar[str] = "soundcloud"
    label: ClassVar[str] = "SoundCloud"
    domains: ClassVar[tuple[str, ...]] = ("soundcloud.com", "snd.sc", "on.soundcloud.com")
    priority: ClassVar[int] = 10

    def extra_ydl_opts(self) -> dict[str, Any]:
        return {"noplaylist": True}

    def normalize(self, url: str, raw: dict[str, Any]) -> NormalizedMedia:
        media = super().normalize(url, raw)
        # SoundCloud never has a video track; force the audio presentation so
        # the UI opens on the MP3 tab.
        media.media_type = "audio"
        media.audio_available = True
        return media
