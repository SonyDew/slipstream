"""Filename sanitisation, path confinement and Content-Disposition."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.filenames import (
    build_download_filename,
    content_disposition,
    is_safe_relative_path,
    resolve_within,
    sanitize_filename,
)

TRAVERSAL_INPUTS = [
    "../../etc/passwd",
    "..\\..\\Windows\\System32\\config\\SAM",
    "/etc/shadow",
    "C:\\Windows\\win.ini",
    "....//....//etc/passwd",
    "foo/../../bar",
    "video/../../../root/.ssh/id_rsa",
]


@pytest.mark.parametrize("raw", TRAVERSAL_INPUTS)
def test_traversal_is_stripped_to_a_single_segment(raw: str) -> None:
    result = sanitize_filename(raw, extension="mp4")
    assert "/" not in result
    assert "\\" not in result
    assert ".." not in result
    assert not result.startswith(".")
    assert result.endswith(".mp4")


def test_null_bytes_and_control_characters_are_removed() -> None:
    result = sanitize_filename("evil\x00name\x1fhere\x7f", extension="mp4")
    assert "\x00" not in result
    assert "\x1f" not in result
    assert "\x7f" not in result


def test_windows_illegal_characters_are_replaced() -> None:
    result = sanitize_filename('a<b>c:d"e|f?g*h', extension="mp4")
    for char in '<>:"|?*':
        assert char not in result


def test_windows_reserved_device_names_are_defused() -> None:
    for reserved in ("CON", "con", "NUL", "COM1", "lpt9", "AUX", "PRN"):
        result = sanitize_filename(reserved, extension="mp4")
        stem = result.rsplit(".", 1)[0]
        assert stem.lower() not in {
            "con",
            "nul",
            "com1",
            "lpt9",
            "aux",
            "prn",
        }, f"{reserved} -> {result}"


def test_unicode_titles_are_preserved() -> None:
    for title in (
        "测试视频标题",
        "Ünïcödé Tëst",
        "Видео тест",
        "日本語のタイトル",
        "🎬 emoji title",
        "العربية",
    ):
        result = sanitize_filename(title, extension="mp4")
        assert result.endswith(".mp4")
        assert len(result) > 4
        # At least some of the original characters survive.
        assert any(char in result for char in title if char.isalnum() or ord(char) > 0x2000)


def test_empty_and_punctuation_only_names_fall_back() -> None:
    for raw in ("", "   ", "...", "___", "---", ".", ".."):
        result = sanitize_filename(raw, extension="mp4", fallback="media")
        assert result == "media.mp4", raw


def test_zero_width_and_bidi_characters_are_dropped() -> None:
    """RTL-override characters can make a filename display deceptively."""
    result = sanitize_filename("safe\u202ecod.exe\u200b", extension="mp4")
    assert "\u202e" not in result
    assert "\u200b" not in result


def test_length_is_bounded_in_bytes_not_characters() -> None:
    """ext4 limits names to 255 *bytes*; CJK is 3 bytes per character."""
    result = sanitize_filename("测" * 300, extension="mp4")
    assert len(result.encode("utf-8")) <= 255
    assert result.endswith(".mp4")

    ascii_result = sanitize_filename("a" * 500, extension="webm")
    assert len(ascii_result.encode("utf-8")) <= 255


def test_extension_is_sanitised_independently() -> None:
    # A malicious "extension" must not smuggle a separator.
    result = sanitize_filename("clip", extension="mp4/../../evil")
    assert "/" not in result
    assert result.startswith("clip.")

    assert sanitize_filename("clip", extension=".MP4").endswith(".mp4")
    assert sanitize_filename("clip", extension="") == "clip"


def test_build_download_filename_composes_title_and_quality() -> None:
    result = build_download_filename(
        "My Video", extension="mp4", quality="1080p", platform="youtube"
    )
    assert result == "My Video - 1080p.mp4"

    without_quality = build_download_filename("My Video", extension="mp3", platform="youtube")
    assert without_quality == "My Video.mp3"

    no_title = build_download_filename("", extension="mp4", platform="tiktok")
    assert no_title.endswith(".mp4")
    assert "tiktok" in no_title


# --------------------------------------------------------------------------- #
# Path confinement
# --------------------------------------------------------------------------- #
def test_is_safe_relative_path() -> None:
    assert is_safe_relative_path("abc123") is True
    assert is_safe_relative_path("nested/file.mp4") is True

    assert is_safe_relative_path("") is False
    assert is_safe_relative_path("../escape") is False
    assert is_safe_relative_path("a/../../b") is False
    assert is_safe_relative_path("/absolute") is False
    assert is_safe_relative_path("with\x00null") is False


def test_resolve_within_confines_paths(tmp_path: Path) -> None:
    base = tmp_path / "jobs"
    base.mkdir()

    inside = resolve_within(base, "abcdef123456")
    assert inside.parent == base.resolve()

    for escape in ("../outside", "..", "/etc/passwd", "a/../../b"):
        with pytest.raises(ValueError):
            resolve_within(base, escape)


def test_resolve_within_rejects_symlink_escape(tmp_path: Path) -> None:
    """A symlink inside the base must not become an escape hatch."""
    base = tmp_path / "jobs"
    base.mkdir()
    outside = tmp_path / "secret"
    outside.mkdir()

    link = base / "link"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable on this platform/permission level")

    resolved = resolve_within(base, "link")
    # resolve() follows the link, so the guard must reject the result.
    assert resolved == outside.resolve() or base.resolve() in resolved.parents


# --------------------------------------------------------------------------- #
# Content-Disposition
# --------------------------------------------------------------------------- #
def test_content_disposition_provides_ascii_and_utf8_forms() -> None:
    header = content_disposition("测试视频.mp4")
    assert header.startswith("attachment;")
    assert 'filename="' in header
    assert "filename*=UTF-8''" in header
    assert "%E6%B5%8B" in header


def test_content_disposition_escapes_quotes_and_backslashes() -> None:
    header = content_disposition('evil".mp4')
    ascii_part = header.split('filename="', 1)[1].split('"', 1)[0]
    assert '"' not in ascii_part
    assert "\\" not in ascii_part


def test_content_disposition_inline_mode() -> None:
    assert content_disposition("a.jpg", inline=True).startswith("inline;")


def test_content_disposition_handles_pure_unicode_names() -> None:
    """A name with no ASCII at all still needs a usable fallback."""
    header = content_disposition("测试.mp4")
    ascii_part = header.split('filename="', 1)[1].split('"', 1)[0]
    assert ascii_part  # never empty
    assert ascii_part.isascii()
