"""Normalized media models.

Every provider returns one of these regardless of which extractor produced it.
The API layer and frontend only ever see these shapes, so replacing or fixing a
single provider never changes the contract.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

MediaTypeLiteral = Literal["video", "audio", "image", "image_set", "unknown"]

# Ladder the UI offers. A rung is only shown when the source actually has it.
VIDEO_QUALITY_LADDER: tuple[int, ...] = (2160, 1440, 1080, 720, 540, 480, 360, 240, 144)
AUDIO_BITRATE_LADDER: tuple[int, ...] = (320, 256, 192, 128, 96, 64)


class MediaFormat(BaseModel):
    """One concrete stream offered by the source."""

    model_config = ConfigDict(extra="ignore")

    format_id: str
    ext: str = "mp4"
    label: str = ""
    height: int | None = None
    width: int | None = None
    fps: float | None = None
    vcodec: str | None = None
    acodec: str | None = None
    filesize: int | None = None
    filesize_is_estimate: bool = False
    tbr: float | None = None  # total bitrate, kbps
    abr: float | None = None  # audio bitrate, kbps
    has_video: bool = False
    has_audio: bool = False
    # True when video and audio arrive as separate streams and must be muxed.
    needs_merge: bool = False
    protocol: str | None = None
    note: str | None = None

    @property
    def is_progressive(self) -> bool:
        """Single file already containing both tracks."""
        return self.has_video and self.has_audio


class MediaImage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    index: int
    url: str
    width: int | None = None
    height: int | None = None
    ext: str = "jpg"


class VideoOption(BaseModel):
    """A user-selectable video quality, derived from available formats."""

    quality: str  # "best" | "2160" | "1080" | ...
    label: str  # "1080p", "Best available"
    height: int | None = None
    fps: float | None = None
    ext: str = "mp4"
    filesize: int | None = None
    filesize_is_estimate: bool = False
    needs_merge: bool = False
    note: str | None = None


class AudioOption(BaseModel):
    """A user-selectable MP3 bitrate.

    ``capped`` marks a rung the UI should annotate: the source audio is lower
    quality than the requested bitrate, so re-encoding upward would only inflate
    the file. The pipeline never claims a bitrate the source cannot support.
    """

    quality: str  # "best" | "320" | "256" | "192" | "128"
    label: str
    bitrate: int | None = None
    ext: str = "mp3"
    capped: bool = False


class NormalizedMedia(BaseModel):
    """Provider output contract."""

    model_config = ConfigDict(extra="ignore")

    platform: str
    platform_label: str = ""
    original_url: str
    media_id: str | None = None

    title: str | None = None
    description: str | None = None
    author: str | None = None
    author_url: str | None = None
    thumbnail: str | None = None
    duration: int | None = None
    upload_date: str | None = None
    view_count: int | None = None
    like_count: int | None = None

    media_type: MediaTypeLiteral = "video"
    formats: list[MediaFormat] = Field(default_factory=list)
    images: list[MediaImage] = Field(default_factory=list)
    audio_available: bool = False

    extractor: str = "yt-dlp"
    is_live: bool = False
    age_limit: int = 0
    # Non-fatal notes surfaced to the user (e.g. "audio track only").
    warnings: list[str] = Field(default_factory=list)
    # Small, non-sensitive extras. Never contains cookies, tokens or headers.
    metadata: dict[str, Any] = Field(default_factory=dict)

    # Ephemeral signed CDN URLs produced by specialised providers. They are
    # intentionally excluded from serialisation/cache payloads: the download
    # worker re-analyses the source and receives a fresh URL just before use.
    direct_sources: dict[str, str] = Field(default_factory=dict, exclude=True, repr=False)

    # -- derived ---------------------------------------------------------- #
    @property
    def is_slideshow(self) -> bool:
        return self.media_type == "image_set" or (len(self.images) > 1 and not self.has_video)

    @property
    def has_video(self) -> bool:
        return any(f.has_video for f in self.formats)

    @property
    def has_audio(self) -> bool:
        return self.audio_available or any(f.has_audio for f in self.formats)

    def available_heights(self) -> list[int]:
        return sorted({f.height for f in self.formats if f.has_video and f.height}, reverse=True)
