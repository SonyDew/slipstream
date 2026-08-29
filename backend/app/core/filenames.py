"""Safe filename generation.

User-controlled media titles become filenames, so this module is the boundary
between arbitrary Unicode text and the filesystem. It must guarantee:

* no directory traversal (``..``, ``/``, ``\\``, absolute paths, NUL)
* no Windows reserved device names (``CON``, ``NUL``, ``COM1`` ...)
* no filesystem-hostile characters on any supported platform
* Unicode is preserved (a Douyin title in Chinese stays readable)
* bounded length in *bytes*, because ext4 limits names to 255 bytes
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path, PurePosixPath, PureWindowsPath

# Reserved on Windows regardless of extension.
_WINDOWS_RESERVED = frozenset(
    {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
)

# Characters that are illegal on Windows or meaningful to a shell/path parser.
_ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
# Collapse runs of whitespace/underscores that survive sanitisation.
_WHITESPACE = re.compile(r"\s+")
_MULTI_UNDERSCORE = re.compile(r"_{3,}")

MAX_NAME_BYTES = 200  # leaves headroom for suffixes like ".part" and "-1080p"
FALLBACK_STEM = "media"


def _truncate_bytes(text: str, limit: int) -> str:
    """Truncate to at most ``limit`` UTF-8 bytes without splitting a codepoint."""
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    # Cut then drop the trailing partial sequence.
    return encoded[:limit].decode("utf-8", errors="ignore").rstrip()


def sanitize_filename(
    name: str,
    *,
    extension: str = "",
    fallback: str = FALLBACK_STEM,
    max_bytes: int = MAX_NAME_BYTES,
) -> str:
    """Return a single safe path segment. Never returns an empty string.

    ``extension`` may be given with or without a leading dot and is sanitised
    independently so a malicious "title.mp4/../../etc/passwd" cannot smuggle
    separators through.
    """
    stem = name or ""

    # Normalise so visually identical strings collapse, and strip marks that
    # some filesystems reject.
    stem = unicodedata.normalize("NFC", stem)

    # Remove zero-width and bidi control characters: they can make a filename
    # display differently from its bytes (RTL override spoofing).
    stem = "".join(ch for ch in stem if unicodedata.category(ch) not in {"Cf", "Cs", "Co", "Cn"})

    # Take only the final path component of whatever the user supplied.
    stem = stem.replace("\\", "/").split("/")[-1]

    stem = _ILLEGAL_CHARS.sub("_", stem)
    stem = _WHITESPACE.sub(" ", stem).strip()
    # Leading dots create hidden files; trailing dots/spaces break on Windows.
    stem = stem.strip(". ").strip()
    stem = _MULTI_UNDERSCORE.sub("__", stem)

    if not stem or set(stem) <= {"_", "-", "."}:
        stem = fallback

    if stem.lower() in _WINDOWS_RESERVED:
        stem = f"{stem}_file"

    ext = _sanitize_extension(extension)
    stem = _truncate_bytes(stem, max_bytes - len(ext.encode("utf-8")))
    if not stem:
        stem = fallback

    return f"{stem}{ext}"


def _sanitize_extension(extension: str) -> str:
    if not extension:
        return ""
    ext = extension.strip().lstrip(".")
    ext = re.sub(r"[^A-Za-z0-9]", "", ext)[:12]
    return f".{ext.lower()}" if ext else ""


def build_download_filename(
    title: str,
    *,
    extension: str,
    quality: str = "",
    platform: str = "",
) -> str:
    """Compose the user-facing filename for a finished download."""
    pieces = [p for p in (title.strip(), quality.strip()) if p]
    stem = " - ".join(pieces) if pieces else (platform or FALLBACK_STEM)
    return sanitize_filename(stem, extension=extension, fallback=platform or FALLBACK_STEM)


def is_safe_relative_path(candidate: str) -> bool:
    """True when ``candidate`` is a relative path with no traversal component.

    Checked against *both* path flavours rather than the native one: on Windows
    ``PurePath("/etc/passwd").is_absolute()`` is False, because there is no drive
    letter. Relying on the native flavour would therefore let a POSIX-absolute
    path through this gate on a Windows host.
    """
    if not candidate or "\x00" in candidate:
        return False

    normalized = candidate.replace("\\", "/")

    if normalized.startswith("/"):
        return False
    if PurePosixPath(normalized).is_absolute():
        return False
    if PureWindowsPath(candidate).is_absolute():
        return False
    # Drive-relative forms such as "C:file" are absolute in spirit.
    if re.match(r"^[A-Za-z]:", candidate):
        return False

    return not any(part == ".." for part in PurePosixPath(normalized).parts)


def resolve_within(base: Path, *parts: str) -> Path:
    """Join ``parts`` onto ``base`` and assert the result stays inside it.

    This is the last line of defence for any path built from request data.
    """
    base_resolved = base.resolve()
    for part in parts:
        if not is_safe_relative_path(part):
            raise ValueError(f"unsafe path component: {part!r}")
    candidate = base_resolved.joinpath(*parts)
    # Resolve without requiring existence (strict=False is the default).
    resolved = candidate.resolve()
    if resolved != base_resolved and base_resolved not in resolved.parents:
        raise ValueError("resolved path escapes its base directory")
    return resolved


def content_disposition(filename: str, *, inline: bool = False) -> str:
    """Build an RFC 6266 / RFC 5987 Content-Disposition header value.

    Emits both a plain ASCII ``filename`` for legacy clients and a UTF-8
    ``filename*`` so non-Latin titles survive intact.
    """
    from urllib.parse import quote

    disposition = "inline" if inline else "attachment"
    ascii_fallback = (
        unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode("ascii")
    )
    ascii_fallback = _ILLEGAL_CHARS.sub("_", ascii_fallback).strip() or FALLBACK_STEM
    # A quote or backslash inside the quoted-string form would break parsing.
    ascii_fallback = ascii_fallback.replace('"', "_").replace("\\", "_")
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"
