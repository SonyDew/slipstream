"""Provider detection, normalisation and error classification."""

from __future__ import annotations

import pytest

from app.core.errors import (
    AuthRequiredContentError,
    DRMProtectedError,
    ExtractorFailureError,
    GeoRestrictedError,
    MediaUnavailableError,
    NetworkTimeoutError,
    PlatformDisabledError,
    PlatformTemporarilyUnsupportedError,
    PrivateContentError,
)
from app.providers.base import classify_extractor_error
from app.providers.registry import ProviderRegistry, registry

DETECTION_CASES = [
    # YouTube
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "youtube"),
    ("https://youtu.be/dQw4w9WgXcQ", "youtube"),
    ("https://www.youtube.com/shorts/abc123", "youtube"),
    ("https://m.youtube.com/watch?v=abc", "youtube"),
    ("https://music.youtube.com/watch?v=abc", "youtube"),
    ("https://www.youtube-nocookie.com/embed/abc", "youtube"),
    # TikTok
    ("https://www.tiktok.com/@user/video/7300000000000000000", "tiktok"),
    ("https://www.tiktok.com/@user/photo/7300000000000000000", "tiktok"),
    ("https://vm.tiktok.com/ZMabcdef/", "tiktok"),
    ("https://vt.tiktok.com/ZSabcdef/", "tiktok"),
    ("https://m.tiktok.com/v/123.html", "tiktok"),
    # Douyin
    ("https://www.douyin.com/video/7200000000000000000", "douyin"),
    ("https://www.douyin.com/note/7200000000000000000", "douyin"),
    ("https://v.douyin.com/abcdef/", "douyin"),
    ("https://www.iesdouyin.com/share/video/123", "douyin"),
    # Instagram
    ("https://www.instagram.com/p/Cabcdefghij/", "instagram"),
    ("https://www.instagram.com/reel/Cabcdefghij/", "instagram"),
    ("https://www.instagram.com/tv/Cabcdefghij/", "instagram"),
    ("https://instagr.am/p/Cabc/", "instagram"),
    # X / Twitter
    ("https://x.com/user/status/1700000000000000000", "twitter"),
    ("https://twitter.com/user/status/1700000000000000000", "twitter"),
    ("https://mobile.twitter.com/user/status/123", "twitter"),
    # Facebook
    ("https://www.facebook.com/watch/?v=123456", "facebook"),
    ("https://fb.watch/abcdefg/", "facebook"),
    ("https://www.facebook.com/reel/123456", "facebook"),
    # Reddit
    ("https://www.reddit.com/r/videos/comments/abc123/title/", "reddit"),
    ("https://v.redd.it/abcdef", "reddit"),
    ("https://old.reddit.com/r/x/comments/abc/t/", "reddit"),
    # Vimeo
    ("https://vimeo.com/123456789", "vimeo"),
    ("https://player.vimeo.com/video/123456789", "vimeo"),
    # SoundCloud
    ("https://soundcloud.com/artist/track-name", "soundcloud"),
    ("https://on.soundcloud.com/abcdef", "soundcloud"),
    # Fallback
    ("https://example.com/media/video.mp4", "generic"),
    ("https://some-random-video-site.tv/watch/1", "generic"),
]


@pytest.mark.parametrize(("url", "expected"), DETECTION_CASES)
def test_platform_detection(url: str, expected: str) -> None:
    assert registry.detect_platform(url) == expected


def test_detection_is_case_insensitive_on_host() -> None:
    assert registry.detect_platform("https://WWW.YouTube.COM/watch?v=abc") == "youtube"


def test_lookalike_domains_do_not_match_a_real_provider() -> None:
    """`youtube.com.evil.test` must not be treated as YouTube."""
    for url in (
        "https://youtube.com.evil.test/watch?v=abc",
        "https://tiktok.com.attacker.test/@a/video/1",
        "https://notyoutube.com/watch?v=abc",
        "https://faketiktok.com/@a/video/1",
    ):
        assert registry.detect_platform(url) == "generic", url


def test_subdomains_of_a_provider_do_match() -> None:
    assert registry.detect_platform("https://www.m.youtube.com/watch?v=a") == "youtube"


def test_registry_describes_every_provider() -> None:
    described = registry.describe()
    assert len(described) >= 10
    for entry in described:
        assert entry["platform"]
        assert entry["label"]
        assert isinstance(entry["domains"], list)
        assert isinstance(entry["operational"], bool)
    fallback = [entry for entry in described if entry["is_fallback"]]
    assert len(fallback) == 1
    assert fallback[0]["platform"] == "generic"
    assert next(entry for entry in described if entry["platform"] == "vimeo")["operational"] is False


def test_registry_get_returns_providers_by_name() -> None:
    assert registry.get("youtube") is not None
    assert registry.get("generic") is not None
    assert registry.get("no-such-platform") is None


def test_allow_list_blocks_disabled_platforms() -> None:
    url = "https://www.youtube.com/watch?v=abc"
    assert registry.find_enabled(url, ["youtube", "tiktok"]).platform == "youtube"

    with pytest.raises(PlatformDisabledError):
        registry.find_enabled(url, ["tiktok"])

    # An empty/None allow-list means "everything permitted".
    assert registry.find_enabled(url, None).platform == "youtube"


def test_a_broken_provider_does_not_break_detection() -> None:
    """A provider raising in matches() must be skipped, not crash the request."""

    class BrokenProvider:
        platform = "broken"
        label = "Broken"
        domains = ()
        url_patterns = ()
        priority = 1000

        def matches(self, url: str) -> bool:
            raise RuntimeError("intentional failure")

    from app.providers.generic import GenericProvider
    from app.providers.youtube import YouTubeProvider

    isolated = ProviderRegistry([BrokenProvider(), YouTubeProvider(), GenericProvider()])
    assert isolated.detect_platform("https://youtu.be/abc") == "youtube"
    assert isolated.detect_platform("https://example.com/x") == "generic"


# --------------------------------------------------------------------------- #
# Error classification
# --------------------------------------------------------------------------- #
CLASSIFICATION_CASES = [
    ("Video unavailable", MediaUnavailableError),
    (
        "ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
        PrivateContentError,
    ),
    ("This video has been removed by the uploader", MediaUnavailableError),
    ("Sign in to confirm your age", AuthRequiredContentError),
    ("Sign in to confirm you're not a bot. Use --cookies", AuthRequiredContentError),
    ("The uploader has not made this video available in your country", GeoRestrictedError),
    ("This video is DRM protected", DRMProtectedError),
    ("Unable to download webpage: The read operation timed out", NetworkTimeoutError),
    ("HTTP Error 404: Not Found", MediaUnavailableError),
    ("Something completely unexpected happened", ExtractorFailureError),
]


@pytest.mark.parametrize(("message", "expected"), CLASSIFICATION_CASES)
def test_extractor_errors_map_to_user_safe_types(message: str, expected: type) -> None:
    classified = classify_extractor_error(RuntimeError(message))
    assert isinstance(classified, expected)
    # The user-facing message must never be the raw extractor text.
    assert classified.message != message
    assert "--cookies" not in classified.message
    # The original text is retained for logs only.
    assert classified.detail


def test_classification_truncates_long_details() -> None:
    classified = classify_extractor_error(RuntimeError("x" * 5000))
    assert classified.detail is not None
    assert len(classified.detail) <= 500


@pytest.mark.asyncio
async def test_vimeo_anonymous_client_outage_has_honest_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A platform outage must not be presented as a private user video."""
    from app.providers.vimeo import VimeoProvider

    async def broken_extract(*args: object, **kwargs: object) -> dict:
        raise AuthRequiredContentError(
            detail="[vimeo] The web client only works when logged-in. Use --cookies"
        )

    monkeypatch.setattr("app.services.extractor.extract_info", broken_extract)

    with pytest.raises(PlatformTemporarilyUnsupportedError) as caught:
        await VimeoProvider().analyze("https://vimeo.com/76979871")

    assert "temporarily unavailable" in caught.value.message
    assert "cookies" not in caught.value.message


@pytest.mark.asyncio
async def test_vimeo_keeps_genuine_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.providers.vimeo import VimeoProvider

    async def private_extract(*args: object, **kwargs: object) -> dict:
        raise AuthRequiredContentError(detail="This private video requires authentication")

    monkeypatch.setattr("app.services.extractor.extract_info", private_extract)

    with pytest.raises(AuthRequiredContentError):
        await VimeoProvider().analyze("https://vimeo.com/123")


# --------------------------------------------------------------------------- #
# Normalisation
# --------------------------------------------------------------------------- #
def test_normalize_builds_media_from_a_ytdlp_info_dict() -> None:
    from app.providers.youtube import YouTubeProvider

    raw = {
        "id": "abc123",
        "title": "Example Video",
        "description": "A description",
        "uploader": "Some Channel",
        "duration": 125.4,
        "view_count": 1000,
        "thumbnails": [
            {"url": "https://img/small.jpg", "width": 120, "height": 90},
            {"url": "https://img/large.jpg", "width": 1280, "height": 720},
        ],
        "extractor": "youtube",
        "formats": [
            {
                "format_id": "137",
                "ext": "mp4",
                "height": 1080,
                "width": 1920,
                "vcodec": "avc1.640028",
                "acodec": "none",
                "filesize": 100_000,
                "tbr": 4000,
            },
            {
                "format_id": "140",
                "ext": "m4a",
                "vcodec": "none",
                "acodec": "mp4a.40.2",
                "abr": 128,
                "filesize": 5_000,
            },
            # Storyboard pseudo-format must be discarded.
            {
                "format_id": "sb0",
                "ext": "mhtml",
                "vcodec": "none",
                "acodec": "none",
                "format_note": "storyboard",
                "protocol": "mhtml",
            },
        ],
        # Credential-ish fields that must not survive normalisation.
        "http_headers": {"Cookie": "SECRET=1", "Authorization": "Bearer x"},
        "cookies": "SESSION=abc",
    }

    media = YouTubeProvider().normalize("https://youtu.be/abc123", raw)

    assert media.platform == "youtube"
    assert media.media_id == "abc123"
    assert media.title == "Example Video"
    assert media.author == "Some Channel"
    assert media.duration == 125
    assert media.thumbnail == "https://img/large.jpg"  # largest wins
    assert media.media_type == "video"
    assert len(media.formats) == 2  # storyboard dropped
    assert media.has_audio is True

    video = next(f for f in media.formats if f.has_video)
    assert video.height == 1080
    assert video.needs_merge is True  # acodec none

    # Nothing sensitive leaks into the normalised model.
    blob = media.model_dump_json()
    assert "SECRET" not in blob
    assert "Bearer" not in blob
    assert "Cookie" not in blob
    assert "SESSION" not in blob


def test_normalize_handles_playlist_by_taking_first_entry() -> None:
    from app.providers.generic import GenericProvider

    raw = {
        "_type": "playlist",
        "title": "A Playlist",
        "entries": [
            {
                "id": "first",
                "title": "First Video",
                "formats": [
                    {
                        "format_id": "18",
                        "ext": "mp4",
                        "height": 360,
                        "vcodec": "avc1",
                        "acodec": "mp4a",
                    }
                ],
            },
            {"id": "second", "title": "Second Video", "formats": []},
        ],
    }
    media = GenericProvider().normalize("https://example.com/list", raw)
    assert media.media_id == "first"
    assert media.title == "First Video"
    assert any("2 items" in warning for warning in media.warnings)


def test_normalize_raises_for_an_empty_playlist() -> None:
    from app.providers.generic import GenericProvider

    with pytest.raises(MediaUnavailableError):
        GenericProvider().normalize("https://example.com/x", {"_type": "playlist", "entries": []})


def test_normalize_falls_back_to_a_bare_url_field() -> None:
    """Some extractors return a single URL with no formats list."""
    from app.providers.generic import GenericProvider

    media = GenericProvider().normalize(
        "https://example.com/a.mp4",
        {"id": "x", "title": "Direct", "url": "https://cdn/a.mp4", "ext": "mp4", "height": 720},
    )
    assert len(media.formats) == 1
    assert media.formats[0].has_video is True
    assert media.formats[0].has_audio is True
    assert media.media_type == "video"


def test_soundcloud_is_presented_as_audio() -> None:
    from app.providers.soundcloud import SoundCloudProvider

    media = SoundCloudProvider().normalize(
        "https://soundcloud.com/a/b",
        {
            "id": "1",
            "title": "Track",
            "formats": [
                {
                    "format_id": "http_mp3",
                    "ext": "mp3",
                    "vcodec": "none",
                    "acodec": "mp3",
                    "abr": 128,
                }
            ],
        },
    )
    assert media.media_type == "audio"
    assert media.audio_available is True


def test_live_stream_is_flagged_with_a_warning() -> None:
    from app.providers.youtube import YouTubeProvider

    media = YouTubeProvider().normalize(
        "https://youtu.be/live",
        {
            "id": "live",
            "title": "Live Now",
            "is_live": True,
            "formats": [
                {"format_id": "1", "ext": "mp4", "height": 720, "vcodec": "avc1", "acodec": "mp4a"}
            ],
        },
    )
    assert media.is_live is True
    assert any("live" in warning.lower() for warning in media.warnings)


def test_slideshow_images_are_recovered_from_multiple_shapes() -> None:
    from app.services.slideshow import images_from_ytdlp_info

    # Shape 1: playlist of image entries.
    playlist = {
        "_type": "playlist",
        "entries": [
            {"url": "https://cdn/1.jpg", "ext": "jpg", "width": 1080, "height": 1350},
            {"url": "https://cdn/2.jpg", "ext": "jpg"},
        ],
    }
    images = images_from_ytdlp_info(playlist)
    assert len(images) == 2
    assert images[0].url == "https://cdn/1.jpg"
    assert images[0].width == 1080

    # Shape 2: image-only formats.
    formats = {
        "formats": [
            {"url": "https://cdn/a.jpeg", "ext": "jpeg", "vcodec": "none"},
            {"url": "https://cdn/b.jpeg", "ext": "jpeg", "vcodec": "none"},
            {"url": "https://cdn/v.mp4", "ext": "mp4", "vcodec": "avc1"},
        ]
    }
    images = images_from_ytdlp_info(formats)
    assert len(images) == 2

    # Shape 3: explicit list.
    explicit = {"images": [{"url": "https://cdn/x.jpg", "width": 800}, "https://cdn/y.jpg"]}
    images = images_from_ytdlp_info(explicit)
    assert len(images) == 2

    assert images_from_ytdlp_info({}) == []


def test_slideshow_image_post_parsing() -> None:
    """TikTok and Douyin imagePost shapes both produce images."""
    from app.services.slideshow import _images_from_image_post

    tiktok = {
        "images": [
            {
                "imageURL": {
                    "urlList": [
                        # A thumbnail variant followed by the full-size asset.
                        "https://p16.tiktokcdn.com/img/a~tplv-photomode-image_100x100.jpeg",
                        "https://p16.tiktokcdn.com/img/a~tplv-photomode-image.jpeg",
                    ]
                },
                "imageWidth": 1080,
                "imageHeight": 1350,
            }
        ]
    }
    images = _images_from_image_post(tiktok)
    assert len(images) == 1
    # The downscaled mirror must not be selected.
    assert images[0].url.endswith("photomode-image.jpeg")
    assert images[0].width == 1080

    # A list containing only hinted URLs must still yield the image.
    only_hinted = {"images": [{"imageURL": {"urlList": ["https://cdn/x_200x200.jpeg"]}}]}
    assert len(_images_from_image_post(only_hinted)) == 1

    douyin = {"images": [{"url_list": ["https://cdn/d.jpeg"], "width": 720, "height": 960}]}
    images = _images_from_image_post(douyin)
    assert len(images) == 1
    assert images[0].url == "https://cdn/d.jpeg"

    assert _images_from_image_post({}) == []
    assert _images_from_image_post({"images": "not-a-list"}) == []


def test_douyin_browser_normalises_progressive_formats_without_leaking_urls() -> None:
    from app.services.douyin_browser import _normalise_aweme

    media = _normalise_aweme(
        "https://v.douyin.com/short/",
        "https://www.douyin.com/video/1234567890123456789",
        {
            "aweme_id": "1234567890123456789",
            "desc": "Public video",
            "duration": 12_500,
            "create_time": 1_700_000_000,
            "author": {"nickname": "Creator", "sec_uid": "safe-id"},
            "statistics": {"digg_count": 42, "play_count": 100},
            "video": {
                "cover": {"url_list": ["https://img.example/cover.jpg"]},
                "bit_rate": [
                    {
                        "FPS": 30,
                        "bit_rate": 5_000_000,
                        "is_h265": 0,
                        "is_bytevc1": 0,
                        "play_addr": {
                            "width": 1080,
                            "height": 1920,
                            "data_size": 8_000_000,
                            "url_list": ["https://cdn.example/video.mp4?token=secret"],
                        },
                    },
                    {
                        "bit_rate": 3_000_000,
                        "is_h265": 1,
                        "play_addr": {
                            "width": 1080,
                            "height": 1920,
                            "url_list": ["https://cdn.example/h265.mp4"],
                        },
                    },
                ],
            },
        },
    )

    assert media.extractor == "douyin-browser"
    assert media.title == "Public video"
    assert media.author == "Creator"
    assert media.duration == 12
    assert len(media.formats) == 1
    assert media.formats[0].height == 1080
    assert media.formats[0].is_progressive
    assert next(iter(media.direct_sources.values())).startswith("https://cdn.example/")
    assert "token=secret" not in media.model_dump_json()


def test_douyin_browser_normalises_image_posts() -> None:
    from app.services.douyin_browser import _normalise_aweme

    media = _normalise_aweme(
        "https://www.douyin.com/note/1234567890123456789",
        "https://www.douyin.com/note/1234567890123456789",
        {
            "aweme_id": "1234567890123456789",
            "desc": "Gallery",
            "images": [
                {"url_list": ["https://cdn.example/1.webp"], "width": 1080, "height": 1440},
                {"url_list": ["https://cdn.example/2.jpg"], "width": 1080, "height": 1440},
            ],
        },
    )

    assert media.media_type == "image_set"
    assert len(media.images) == 2
    assert media.images[0].ext == "webp"
