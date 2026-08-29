"""Quality option derivation and extractor format-selector construction.

Two responsibilities:

1. Turn the raw format list into the option lists the UI renders — only rungs
   that genuinely exist, with honest size estimates.
2. Translate a *validated* quality token back into a yt-dlp format selector.

The client never sends a raw yt-dlp format string. It sends a token from a small
closed set (``best``, ``1080``, ``320`` ...) which is validated against what the
source actually offers, so a crafted request cannot inject selector syntax.
"""

from __future__ import annotations

import math
from typing import Literal

from app.core.errors import NoSuitableFormatError
from app.providers.models import (
    AUDIO_BITRATE_LADDER,
    VIDEO_QUALITY_LADDER,
    AudioOption,
    MediaFormat,
    NormalizedMedia,
    VideoOption,
)

DownloadMode = Literal["video", "audio", "image"]

VALID_VIDEO_CONTAINERS = ("mp4", "webm")
VALID_AUDIO_CONTAINERS = ("mp3",)

BEST = "best"


# --------------------------------------------------------------------------- #
# Video
# --------------------------------------------------------------------------- #
def _bucket_height(height: int) -> int | None:
    """Map a real pixel height onto the nearest standard rung at or below it.

    Sources are not always exactly 1080/720 tall (a 1078px re-encode is common),
    so a 5% tolerance keeps such streams on the rung users expect.
    """
    for rung in VIDEO_QUALITY_LADDER:
        if rung <= height * 1.05:
            return rung
    return None


def _best_audio_format(media: NormalizedMedia) -> MediaFormat | None:
    audio_only = [f for f in media.formats if f.has_audio and not f.has_video]
    pool = audio_only or [f for f in media.formats if f.has_audio]
    if not pool:
        return None
    return max(pool, key=lambda f: (f.abr or f.tbr or 0, f.filesize or 0))


def _score_video_format(fmt: MediaFormat, container: str) -> tuple:
    """Rank candidate formats for one rung: right container, then bitrate."""
    container_match = 1 if fmt.ext == container else 0
    # A progressive stream avoids a merge step entirely — cheaper and safer when
    # FFmpeg is unavailable.
    return (container_match, 1 if fmt.is_progressive else 0, fmt.tbr or 0, fmt.height or 0)


def build_video_options(
    media: NormalizedMedia,
    *,
    container: str = "mp4",
    ffmpeg_available: bool = True,
) -> list[VideoOption]:
    """Derive the selectable video qualities for this media.

    When FFmpeg is unavailable only *progressive* streams (video and audio in one
    file) can be served, so adaptive-only rungs are omitted entirely rather than
    offered with a caveat — serving a silent video would be worse than not
    offering the rung. :func:`app.services.analyze.build_analysis_payload` turns
    the empty result into a single clear message.
    """
    video_formats = [f for f in media.formats if f.has_video]
    if not ffmpeg_available:
        video_formats = [f for f in video_formats if f.is_progressive]
    if not video_formats:
        return []

    audio = _best_audio_format(media)
    audio_size = audio.filesize if audio else None

    # Group formats by the rung they satisfy.
    by_rung: dict[int, list[MediaFormat]] = {}
    for fmt in video_formats:
        if not fmt.height:
            continue
        rung = _bucket_height(fmt.height)
        if rung is not None:
            by_rung.setdefault(rung, []).append(fmt)

    options: list[VideoOption] = []

    # "Best available" — always first when there is any usable video at all.
    best_fmt = max(video_formats, key=lambda f: (f.height or 0, f.tbr or 0))
    best_rung = _bucket_height(best_fmt.height) if best_fmt.height else None
    options.append(
        VideoOption(
            quality=BEST,
            label="Best available" + (f" ({best_rung}p)" if best_rung else ""),
            height=best_fmt.height,
            fps=best_fmt.fps,
            ext=container,
            filesize=_combined_size(best_fmt, audio_size),
            filesize_is_estimate=best_fmt.filesize_is_estimate or best_fmt.filesize is None,
            needs_merge=best_fmt.needs_merge,
        )
    )

    for rung in VIDEO_QUALITY_LADDER:
        candidates = by_rung.get(rung)
        if not candidates:
            continue
        chosen = max(candidates, key=lambda f: _score_video_format(f, container))
        needs_merge = chosen.needs_merge
        fps_suffix = ""
        if chosen.fps and chosen.fps >= 50:
            fps_suffix = f"{int(chosen.fps)}"
        options.append(
            VideoOption(
                quality=str(rung),
                label=f"{rung}p{fps_suffix}",
                height=chosen.height,
                fps=chosen.fps,
                ext=container if chosen.ext not in VALID_VIDEO_CONTAINERS else chosen.ext,
                filesize=_combined_size(chosen, audio_size if needs_merge else None),
                filesize_is_estimate=chosen.filesize_is_estimate or chosen.filesize is None,
                needs_merge=needs_merge,
            )
        )

    return options


def _combined_size(video: MediaFormat, audio_size: int | None) -> int | None:
    if video.filesize is None:
        return None
    if video.needs_merge and audio_size:
        return video.filesize + audio_size
    return video.filesize


# --------------------------------------------------------------------------- #
# Audio
# --------------------------------------------------------------------------- #
def source_audio_bitrate(media: NormalizedMedia) -> int | None:
    """Best known source audio bitrate in kbps, or None when unknown."""
    best = _best_audio_format(media)
    if best is None:
        return None
    value = best.abr or (best.tbr if not best.has_video else None)
    return int(value) if value else None


def build_audio_options(media: NormalizedMedia) -> list[AudioOption]:
    """Derive selectable MP3 bitrates.

    Rungs above the source bitrate are omitted: re-encoding 96 kbps audio to
    320 kbps produces a bigger file with no extra information, and advertising
    it would be dishonest. When the source bitrate is unknown the full ladder is
    offered and the pipeline caps to the real value at encode time.
    """
    if not media.has_audio:
        return []

    source_kbps = source_audio_bitrate(media)
    options: list[AudioOption] = [
        AudioOption(
            quality=BEST,
            label="Best available" + (f" (~{source_kbps} kbps)" if source_kbps else ""),
            bitrate=source_kbps,
        )
    ]

    for rung in (320, 256, 192, 128):
        if source_kbps is not None:
            # Allow the rung immediately above the source so a 128 kbps source
            # still offers a clean 128 option, but nothing beyond it.
            ceiling = _ceil_to_rung(source_kbps)
            if rung > ceiling:
                continue
        options.append(
            AudioOption(
                quality=str(rung),
                label=f"{rung} kbps",
                bitrate=rung,
                capped=source_kbps is not None and rung > source_kbps,
            )
        )
    return options


def _ceil_to_rung(kbps: int) -> int:
    for rung in sorted(AUDIO_BITRATE_LADDER):
        if kbps <= rung * 1.02:
            return rung
    return max(AUDIO_BITRATE_LADDER)


# --------------------------------------------------------------------------- #
# Validation + selector construction
# --------------------------------------------------------------------------- #
def validate_quality(
    media: NormalizedMedia,
    *,
    mode: DownloadMode,
    quality: str,
    container: str,
    ffmpeg_available: bool = True,
) -> str:
    """Assert the requested token is available; return the normalised token."""
    token = (quality or BEST).strip().lower()

    if mode == "video":
        available = {
            o.quality
            for o in build_video_options(
                media, container=container, ffmpeg_available=ffmpeg_available
            )
        }
        if not available:
            raise NoSuitableFormatError("This media has no downloadable video stream.")
        if token not in available:
            raise NoSuitableFormatError(
                f"{quality} is not available for this media."
                if token != BEST
                else "No video stream is available."
            )
        return token

    if mode == "audio":
        available = {o.quality for o in build_audio_options(media)}
        if not available:
            raise NoSuitableFormatError("This media has no audio track to convert.")
        if token not in available:
            raise NoSuitableFormatError(f"{quality} kbps is not available for this media.")
        return token

    return BEST


def build_format_selector(
    *,
    mode: DownloadMode,
    quality: str,
    container: str = "mp4",
    ffmpeg_available: bool = True,
) -> str:
    """Build a yt-dlp format selector from a validated token.

    ``quality`` must already have passed :func:`validate_quality`; it is only
    ever ``best`` or a numeric string, so no user text reaches the selector.
    """
    if mode == "audio":
        return "bestaudio/best"

    token = (quality or BEST).lower()
    if token != BEST and not token.isdigit():  # defence in depth
        raise NoSuitableFormatError()

    height_filter = "" if token == BEST else f"[height<={int(token)}]"
    ext = container if container in VALID_VIDEO_CONTAINERS else "mp4"

    if not ffmpeg_available:
        # Without FFmpeg only a progressive stream is usable; asking for a
        # separate video track would yield a silent file.
        return f"best[ext={ext}]{height_filter}/best{height_filter}/best"

    # Preference order: container-matched merge, any merge, progressive, anything.
    audio_pref = "bestaudio[ext=m4a]" if ext == "mp4" else "bestaudio[ext=webm]"
    return (
        f"bestvideo[ext={ext}]{height_filter}+{audio_pref}/"
        f"bestvideo{height_filter}+bestaudio/"
        f"best[ext={ext}]{height_filter}/"
        f"best{height_filter}/best"
    )


def target_audio_bitrate(media: NormalizedMedia, quality: str) -> int | None:
    """Resolve the MP3 bitrate to encode at, never above the source.

    Returning None means "let the encoder pick a VBR-quality default", used when
    the source bitrate is unknown and the user asked for best.
    """
    source = source_audio_bitrate(media)
    if quality == BEST or not quality.isdigit():
        if source is None:
            return None
        return min(_ceil_to_rung(source), 320)

    requested = int(quality)
    if source is None:
        return requested
    # Honest cap: never claim more than the source carries.
    return min(requested, _ceil_to_rung(source))


def humanize_size(num_bytes: int | None) -> str:
    if not num_bytes or num_bytes <= 0:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB")
    index = min(int(math.log(num_bytes, 1024)), len(units) - 1)
    value = num_bytes / (1024**index)
    return f"{value:.0f} {units[index]}" if index < 2 else f"{value:.1f} {units[index]}"
