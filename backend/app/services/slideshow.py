"""Slideshow (photo post) extraction for TikTok and Douyin.

yt-dlp's coverage of image posts varies between releases and regions, so this
module adds a best-effort second path: read the *public* page HTML and pull the
image list out of the JSON blob the site itself embeds for hydration.

This only ever reads publicly served markup. There is no login, no cookie
injection, no signature forging and no attempt to reach private posts — if the
page is not public the request simply fails and the caller degrades to whatever
yt-dlp returned.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.core.ssrf import assert_url_allowed
from app.providers.models import MediaImage

log = get_logger("slipstream.slideshow")

# A plain desktop UA. Not evasion — many CDNs serve a JS-only shell to unknown
# clients, and this is the documented way to receive the standard public page.
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

_IMAGE_EXTS = ("jpg", "jpeg", "png", "webp", "heic", "avif")

# Markers that identify a deliberately downscaled CDN variant rather than the
# full-size asset: a width query parameter, a WxH suffix, or a ByteDance
# "tplv-" template segment carrying small dimensions.
_DOWNSCALE_HINT = re.compile(
    r"[?&](?:w|width|size)=\d{1,3}" r"|[_~-]\d{2,3}x\d{2,3}" r"|/\d{2,3}x\d{2,3}/",
    re.I,
)

# TikTok embeds hydration state in a script tag with this id.
_TIKTOK_UNIVERSAL_RE = re.compile(
    r'<script[^>]+id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
    re.DOTALL,
)
_TIKTOK_SIGI_RE = re.compile(
    r'<script[^>]+id="SIGI_STATE"[^>]*>(.*?)</script>',
    re.DOTALL,
)
# Douyin server-renders into one of these.
_DOUYIN_RENDER_RE = re.compile(
    r'<script[^>]+id="RENDER_DATA"[^>]*>(.*?)</script>',
    re.DOTALL,
)
_DOUYIN_ROUTER_RE = re.compile(r"_ROUTER_DATA\s*=\s*(\{.*?\});?\s*</script>", re.DOTALL)


def _user_agent() -> str:
    return settings.YTDLP_USER_AGENT or _DEFAULT_UA


def _client_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "timeout": httpx.Timeout(15.0, connect=8.0),
        "follow_redirects": False,  # we validate every hop ourselves
        "headers": {
            "User-Agent": _user_agent(),
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
        # Cap the body we will read: a page is markup, not media.
        "limits": httpx.Limits(max_connections=4),
    }
    if settings.YTDLP_PROXY:
        kwargs["proxy"] = settings.YTDLP_PROXY
    return kwargs


async def _fetch_html(url: str, *, max_hops: int = 4, max_bytes: int = 4_000_000) -> str | None:
    """Fetch page HTML, re-validating the target on every redirect hop."""
    current = assert_url_allowed(url).url
    try:
        async with httpx.AsyncClient(**_client_kwargs()) as client:
            for _ in range(max_hops):
                response = await client.get(current)
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return None
                    # Re-run the full SSRF check on the redirect target.
                    from app.core.ssrf import safe_redirect_target

                    current = safe_redirect_target(location, base_url=current)
                    continue

                if response.status_code >= 400:
                    log.info("slideshow fetch returned %s", response.status_code)
                    return None

                content_type = response.headers.get("content-type", "")
                if "html" not in content_type and "json" not in content_type:
                    return None

                body = response.content[:max_bytes]
                return body.decode(response.encoding or "utf-8", errors="replace")
    except httpx.HTTPError as exc:
        log.info("slideshow fetch failed: %s", type(exc).__name__)
        return None
    except Exception as exc:
        log.info("slideshow fetch error: %s", type(exc).__name__)
        return None
    return None


def _walk(node: Any, depth: int = 0):
    """Yield every dict in a nested JSON structure."""
    if depth > 14:
        return
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value, depth + 1)
    elif isinstance(node, list):
        for value in node[:400]:
            yield from _walk(value, depth + 1)


def _best_url_from_list(url_list: Any) -> str | None:
    """Pick the highest-quality URL from a TikTok/Douyin urlList.

    The entries are normally CDN mirrors of the *same* asset, so any of them
    will do — except that these lists sometimes also include a downscaled
    preview. Mirrors carrying an explicit small-size hint are therefore
    deprioritised rather than excluded, so a list made up entirely of hinted
    URLs still yields something.
    """
    if isinstance(url_list, str):
        return url_list
    if not isinstance(url_list, list):
        return None
    candidates = [u for u in url_list if isinstance(u, str) and u.startswith("http")]
    if not candidates:
        return None
    full_size = [u for u in candidates if not _DOWNSCALE_HINT.search(u)]
    return (full_size or candidates)[0]


def _images_from_image_post(container: dict[str, Any]) -> list[MediaImage]:
    """Parse a TikTok/Douyin ``imagePost``-shaped structure."""
    images: list[MediaImage] = []
    raw_images = container.get("images")
    if not isinstance(raw_images, list):
        return images

    for index, item in enumerate(raw_images):
        if not isinstance(item, dict):
            continue
        # TikTok: {"imageURL": {"urlList": [...]}, "imageWidth": .., "imageHeight": ..}
        # Douyin: {"url_list": [...], "width": .., "height": ..}
        holder = item.get("imageURL") or item.get("image_url") or item
        url = _best_url_from_list(
            holder.get("urlList") if isinstance(holder, dict) else None
        ) or _best_url_from_list(holder.get("url_list") if isinstance(holder, dict) else None)
        if not url:
            url = _best_url_from_list(item.get("url_list"))
        if not url:
            continue

        width = item.get("imageWidth") or item.get("width")
        height = item.get("imageHeight") or item.get("height")
        ext = "jpeg"
        for candidate in _IMAGE_EXTS:
            if f".{candidate}" in url.lower():
                ext = candidate
                break

        images.append(
            MediaImage(
                index=index,
                url=url,
                width=int(width) if isinstance(width, (int, float)) and width else None,
                height=int(height) if isinstance(height, (int, float)) and height else None,
                ext="jpg" if ext == "jpeg" else ext,
            )
        )
    return images


def _extract_json_blocks(html: str, patterns: tuple[re.Pattern[str], ...]) -> list[Any]:
    """Pull and parse every JSON blob matching the given script patterns."""
    blocks: list[Any] = []
    for pattern in patterns:
        for match in pattern.finditer(html):
            payload = match.group(1).strip()
            if not payload:
                continue
            # Douyin percent-encodes RENDER_DATA.
            if payload.startswith("%7B") or payload.startswith("%7b"):
                from urllib.parse import unquote

                payload = unquote(payload)
            try:
                blocks.append(json.loads(payload))
            except (ValueError, TypeError):
                continue
    return blocks


def _find_images(blocks: list[Any]) -> list[MediaImage]:
    for block in blocks:
        for node in _walk(block):
            for key in ("imagePost", "image_post_info", "imagePostInfo"):
                container = node.get(key)
                if isinstance(container, dict):
                    images = _images_from_image_post(container)
                    if images:
                        return images
    return []


def _find_slideshow_meta(blocks: list[Any]) -> dict[str, Any]:
    """Best-effort title/author for a slideshow post."""
    meta: dict[str, Any] = {}
    for block in blocks:
        for node in _walk(block):
            if "desc" in node and isinstance(node.get("desc"), str) and not meta.get("title"):
                text = node["desc"].strip()
                if text:
                    meta["title"] = text[:300]
            author = node.get("author")
            if isinstance(author, dict) and not meta.get("author"):
                name = author.get("nickname") or author.get("uniqueId") or author.get("unique_id")
                if isinstance(name, str) and name.strip():
                    meta["author"] = name.strip()[:255]
            if meta.get("title") and meta.get("author"):
                return meta
    return meta


async def fetch_slideshow(url: str, *, platform: str) -> tuple[list[MediaImage], dict[str, Any]]:
    """Return ``(images, meta)`` for a photo post, or ``([], {})``.

    Never raises: slideshow support is an enhancement layered on top of the
    normal extraction path.
    """
    try:
        html = await _fetch_html(url)
    except Exception as exc:
        log.info("slideshow prefetch rejected: %s", type(exc).__name__)
        return [], {}

    if not html:
        return [], {}

    patterns: tuple[re.Pattern[str], ...]
    if platform == "douyin":
        patterns = (_DOUYIN_RENDER_RE, _DOUYIN_ROUTER_RE, _TIKTOK_UNIVERSAL_RE)
    else:
        patterns = (_TIKTOK_UNIVERSAL_RE, _TIKTOK_SIGI_RE)

    blocks = _extract_json_blocks(html, patterns)
    if not blocks:
        return [], {}

    images = _find_images(blocks)
    if not images:
        return [], {}

    meta = _find_slideshow_meta(blocks)
    log.info("slideshow extracted", extra_images=len(images), platform=platform)
    return images, meta


def images_from_ytdlp_info(raw: dict[str, Any]) -> list[MediaImage]:
    """Recover slideshow images from a yt-dlp info dict.

    Different yt-dlp releases surface TikTok photo posts differently, so this
    checks each shape that has been observed rather than assuming one.
    """
    images: list[MediaImage] = []

    # Shape 1: a playlist whose entries are images.
    if raw.get("_type") == "playlist":
        for index, entry in enumerate(raw.get("entries") or []):
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            ext = (entry.get("ext") or "").lower()
            looks_like_image = ext in _IMAGE_EXTS or (
                entry.get("vcodec") == "none" and not entry.get("acodec")
            )
            if url and looks_like_image:
                images.append(
                    MediaImage(
                        index=index,
                        url=str(url),
                        width=entry.get("width"),
                        height=entry.get("height"),
                        ext=ext or "jpg",
                    )
                )
        if images:
            return images

    # Shape 2: image-only formats on a single info dict.
    for index, fmt in enumerate(raw.get("formats") or []):
        if not isinstance(fmt, dict):
            continue
        ext = (fmt.get("ext") or "").lower()
        vcodec = (fmt.get("vcodec") or "").lower()
        if ext in _IMAGE_EXTS and vcodec in {"none", ""} and fmt.get("url"):
            images.append(
                MediaImage(
                    index=index,
                    url=str(fmt["url"]),
                    width=fmt.get("width"),
                    height=fmt.get("height"),
                    ext=ext,
                )
            )
    if images:
        return images

    # Shape 3: an explicit list some extractors attach.
    explicit = raw.get("images")
    if isinstance(explicit, list):
        for index, item in enumerate(explicit):
            if isinstance(item, dict) and item.get("url"):
                images.append(
                    MediaImage(
                        index=index,
                        url=str(item["url"]),
                        width=item.get("width"),
                        height=item.get("height"),
                    )
                )
            elif isinstance(item, str) and item.startswith("http"):
                images.append(MediaImage(index=index, url=item))
    return images
