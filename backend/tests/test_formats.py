"""Quality derivation and format-selector construction."""

from __future__ import annotations

import pytest

from app.core.errors import NoSuitableFormatError
from app.providers.models import AudioOption, MediaFormat, NormalizedMedia
from app.services.formats import (
    build_audio_options,
    build_format_selector,
    build_video_options,
    humanize_size,
    source_audio_bitrate,
    target_audio_bitrate,
    validate_quality,
)


def test_direct_provider_source_matches_requested_quality() -> None:
    from app.providers.models import MediaFormat, NormalizedMedia
    from app.services.downloader import _pick_direct_source

    media = NormalizedMedia(
        platform="douyin",
        original_url="https://www.douyin.com/video/1",
        formats=[
            MediaFormat(format_id="720", height=720, has_video=True, has_audio=True),
            MediaFormat(format_id="1080", height=1080, has_video=True, has_audio=True),
        ],
        direct_sources={"720": "https://cdn.example/720.mp4", "1080": "https://cdn.example/1080.mp4"},
    )

    assert _pick_direct_source(media, "best").endswith("1080.mp4")
    assert _pick_direct_source(media, "720").endswith("720.mp4")


def make_media(formats: list[MediaFormat], **kwargs) -> NormalizedMedia:
    return NormalizedMedia(
        platform="generic",
        original_url="https://example.com/video",
        formats=formats,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Video ladders
# --------------------------------------------------------------------------- #
def test_only_available_rungs_are_offered(sample_media: NormalizedMedia) -> None:
    qualities = [option.quality for option in build_video_options(sample_media)]
    assert qualities == ["best", "2160", "1080", "720", "360"]


def test_non_standard_heights_snap_to_the_expected_rung() -> None:
    media = make_media(
        [
            MediaFormat(format_id="a", height=1078, has_video=True, has_audio=True, ext="mp4"),
            MediaFormat(format_id="b", height=718, has_video=True, has_audio=True, ext="mp4"),
        ]
    )
    qualities = [option.quality for option in build_video_options(media)]
    assert "1080" in qualities
    assert "720" in qualities


def test_best_option_reports_the_real_top_height(sample_media: NormalizedMedia) -> None:
    best = build_video_options(sample_media)[0]
    assert best.quality == "best"
    assert best.height == 2160
    assert "2160p" in best.label


def test_no_video_formats_yields_no_video_options() -> None:
    media = make_media(
        [MediaFormat(format_id="140", has_audio=True, abr=192, ext="m4a")],
        media_type="audio",
        audio_available=True,
    )
    assert build_video_options(media) == []


def test_progressive_streams_are_preferred_for_a_rung() -> None:
    """When both a progressive and an adaptive stream exist, avoid the merge."""
    media = make_media(
        [
            MediaFormat(
                format_id="video-only",
                height=720,
                has_video=True,
                needs_merge=True,
                ext="mp4",
                tbr=2000,
            ),
            MediaFormat(
                format_id="progressive",
                height=720,
                has_video=True,
                has_audio=True,
                ext="mp4",
                tbr=1500,
            ),
            MediaFormat(format_id="audio", has_audio=True, abr=128, ext="m4a"),
        ]
    )
    option = next(o for o in build_video_options(media) if o.quality == "720")
    assert option.needs_merge is False


def test_missing_ffmpeg_hides_adaptive_only_rungs() -> None:
    """Without FFmpeg an adaptive-only rung would produce a silent file."""
    media = make_media(
        [
            MediaFormat(format_id="137", height=1080, has_video=True, needs_merge=True, ext="mp4"),
            MediaFormat(format_id="140", has_audio=True, abr=128, ext="m4a"),
        ]
    )
    assert build_video_options(media, ffmpeg_available=False) == []
    # With FFmpeg the same source offers the rung normally.
    with_ffmpeg = build_video_options(media, ffmpeg_available=True)
    assert [o.quality for o in with_ffmpeg] == ["best", "1080"]
    assert with_ffmpeg[1].needs_merge is True


def test_missing_ffmpeg_keeps_progressive_rungs() -> None:
    """A progressive stream needs no muxing, so it stays available."""
    media = make_media(
        [
            MediaFormat(format_id="137", height=1080, has_video=True, needs_merge=True, ext="mp4"),
            MediaFormat(format_id="18", height=360, has_video=True, has_audio=True, ext="mp4"),
            MediaFormat(format_id="140", has_audio=True, abr=128, ext="m4a"),
        ]
    )
    options = build_video_options(media, ffmpeg_available=False)
    qualities = [o.quality for o in options]
    assert qualities == ["best", "360"]
    # "Best available" must describe the best *servable* rung, not 1080p.
    assert options[0].height == 360
    assert all(o.needs_merge is False for o in options)


# --------------------------------------------------------------------------- #
# Audio honesty
# --------------------------------------------------------------------------- #
def test_audio_rungs_never_exceed_the_source_bitrate() -> None:
    """A 96 kbps source must not advertise 320 kbps."""
    media = make_media(
        [MediaFormat(format_id="low", has_audio=True, abr=96, ext="m4a")],
        audio_available=True,
    )
    assert source_audio_bitrate(media) == 96

    qualities = [option.quality for option in build_audio_options(media)]
    # Nothing above the source is offered at all. With a 96 kbps source none of
    # the standard rungs (320/256/192/128) are honest, so only "Best" remains —
    # labelled with the real bitrate so the user knows what they are getting.
    assert qualities == ["best"]
    assert "96" in build_audio_options(media)[0].label


def test_high_bitrate_source_offers_the_full_ladder() -> None:
    media = make_media(
        [MediaFormat(format_id="hi", has_audio=True, abr=320, ext="m4a")],
        audio_available=True,
    )
    qualities = [option.quality for option in build_audio_options(media)]
    assert qualities == ["best", "320", "256", "192", "128"]


def test_unknown_source_bitrate_offers_the_ladder_and_caps_at_encode_time() -> None:
    media = make_media(
        [MediaFormat(format_id="unknown", has_audio=True, ext="m4a")],
        audio_available=True,
    )
    assert source_audio_bitrate(media) is None
    qualities = [option.quality for option in build_audio_options(media)]
    assert qualities == ["best", "320", "256", "192", "128"]
    # With no known source bitrate the requested value is used as-is.
    assert target_audio_bitrate(media, "192") == 192
    assert target_audio_bitrate(media, "best") is None


def test_target_bitrate_is_capped_to_the_source() -> None:
    media = make_media(
        [MediaFormat(format_id="low", has_audio=True, abr=64, ext="m4a")],
        audio_available=True,
    )
    # Even if a crafted request asks for 320, the encoder is told 64.
    assert target_audio_bitrate(media, "320") == 64
    assert target_audio_bitrate(media, "best") == 64


def test_best_audio_label_mentions_the_source_bitrate() -> None:
    media = make_media(
        [MediaFormat(format_id="x", has_audio=True, abr=128, ext="m4a")],
        audio_available=True,
    )
    best: AudioOption = build_audio_options(media)[0]
    assert "128" in best.label


def test_no_audio_track_yields_no_audio_options() -> None:
    media = make_media(
        [MediaFormat(format_id="v", height=720, has_video=True, needs_merge=True, ext="mp4")]
    )
    assert build_audio_options(media) == []


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def test_validate_quality_accepts_available_and_rejects_missing(
    sample_media: NormalizedMedia,
) -> None:
    assert validate_quality(sample_media, mode="video", quality="1080", container="mp4") == "1080"
    assert validate_quality(sample_media, mode="video", quality="best", container="mp4") == "best"

    with pytest.raises(NoSuitableFormatError):
        validate_quality(sample_media, mode="video", quality="1440", container="mp4")
    with pytest.raises(NoSuitableFormatError):
        validate_quality(sample_media, mode="audio", quality="320", container="mp3")


def test_validate_quality_rejects_injection_attempts(sample_media: NormalizedMedia) -> None:
    for payload in ("bestvideo+bestaudio", "best[height<=9999]", "1080;rm -rf /", "../best"):
        with pytest.raises(NoSuitableFormatError):
            validate_quality(sample_media, mode="video", quality=payload, container="mp4")


# --------------------------------------------------------------------------- #
# Selector construction
# --------------------------------------------------------------------------- #
def test_selector_for_specific_height() -> None:
    selector = build_format_selector(mode="video", quality="1080", container="mp4")
    assert "[height<=1080]" in selector
    assert "bestvideo[ext=mp4]" in selector
    assert "+bestaudio[ext=m4a]" in selector
    # A fallback chain must always be present.
    assert selector.endswith("/best")


def test_selector_for_best_has_no_height_filter() -> None:
    selector = build_format_selector(mode="video", quality="best", container="mp4")
    assert "height<=" not in selector
    assert selector.startswith("bestvideo")


def test_selector_for_webm_prefers_webm_streams() -> None:
    selector = build_format_selector(mode="video", quality="720", container="webm")
    assert "bestvideo[ext=webm]" in selector
    assert "bestaudio[ext=webm]" in selector


def test_selector_without_ffmpeg_avoids_stream_merging() -> None:
    selector = build_format_selector(
        mode="video", quality="720", container="mp4", ffmpeg_available=False
    )
    assert "+" not in selector, "a merge selector would produce a silent video"
    assert "best[ext=mp4][height<=720]" in selector


def test_selector_for_audio() -> None:
    assert build_format_selector(mode="audio", quality="192") == "bestaudio/best"


def test_selector_rejects_non_numeric_quality() -> None:
    with pytest.raises(NoSuitableFormatError):
        build_format_selector(mode="video", quality="1080p", container="mp4")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def test_humanize_size() -> None:
    assert humanize_size(None) == "—"
    assert humanize_size(0) == "—"
    assert humanize_size(512) == "512 B"
    assert humanize_size(2048) == "2 KB"
    assert humanize_size(5 * 1024 * 1024) == "5.0 MB"
    assert humanize_size(3 * 1024**3) == "3.0 GB"
