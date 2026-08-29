#!/usr/bin/env python
"""Manual live extractor smoke test.

This talks to real third-party websites, so it is deliberately EXCLUDED from CI:
platform changes and rate limits would make the build red for reasons unrelated
to this codebase. Run it by hand when you suspect an extractor has drifted, or
after bumping yt-dlp.

    # analyse a built-in set of stable public URLs
    python scripts/test_extractors.py

    # analyse specific links
    python scripts/test_extractors.py https://youtu.be/aqz-KE-bpKQ

    # also perform a real download of the smallest rung (writes to a temp dir)
    python scripts/test_extractors.py --download

    # exercise a running server over HTTP instead of the library directly
    python scripts/test_extractors.py --api http://localhost:8000

Exit code is non-zero if any URL failed, so it can be wired into a cron-style
health check if you want one.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

# Long-lived, license-friendly public URLs. Big Buck Bunny and Sintel are
# Blender Foundation releases; the rest are official platform accounts. Replace
# freely — nothing here is load-bearing.
DEFAULT_URLS: list[tuple[str, str]] = [
    ("youtube", "https://www.youtube.com/watch?v=aqz-KE-bpKQ"),
    ("youtube-short", "https://youtu.be/aqz-KE-bpKQ"),
    ("vimeo", "https://vimeo.com/1084537"),
    ("soundcloud", "https://soundcloud.com/octobersveryown/drake-hotline-bling"),
    ("tiktok", "https://www.tiktok.com/@tiktok/video/7106594312292453675"),
    ("reddit", "https://www.reddit.com/r/aww/comments/nsl82m/"),
    ("twitter", "https://x.com/X/status/1683501861178657280"),
    ("instagram", "https://www.instagram.com/p/C0kZLbaLQxV/"),
    ("facebook", "https://www.facebook.com/watch/?v=10153231379946729"),
    ("douyin", "https://www.douyin.com/video/7178970026383117577"),
]

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
DIM = "\033[2m"
RESET = "\033[0m"


def colour(text: str, code: str) -> str:
    return text if os.getenv("NO_COLOR") else f"{code}{text}{RESET}"


# --------------------------------------------------------------------------- #
# Library mode
# --------------------------------------------------------------------------- #
async def analyse_via_library(url: str) -> dict:
    """Run the real provider + format pipeline in-process."""
    from app.providers.registry import registry
    from app.services.analyze import build_analysis_payload

    provider = registry.find(url)
    started = time.perf_counter()
    media = await provider.analyze(url)
    elapsed = (time.perf_counter() - started) * 1000

    payload = build_analysis_payload(media)
    payload["_elapsed_ms"] = round(elapsed)
    payload["_provider"] = provider.platform
    return payload


async def download_via_library(url: str, payload: dict, out_dir: Path) -> dict:
    """Download the *smallest* available rung, to keep the test cheap."""
    import uuid

    from app.db.session import session_scope
    from app.models.job import DownloadJob, JobStatus
    from app.providers.registry import registry
    from app.services.downloader import process_job

    video_options = payload.get("video_options") or []
    audio_options = payload.get("audio_options") or []

    if video_options:
        mode, container = "video", "mp4"
        numeric = [o for o in video_options if o["quality"] != "best"]
        quality = numeric[-1]["quality"] if numeric else "best"
    elif audio_options:
        mode, container = "audio", "mp3"
        numeric = [o for o in audio_options if o["quality"] != "best"]
        quality = numeric[-1]["quality"] if numeric else "best"
    elif payload.get("images"):
        mode, container, quality = "image", "zip", "best"
    else:
        return {"ok": False, "reason": "nothing downloadable"}

    job_id = uuid.uuid4().hex
    with session_scope() as db:
        db.add(
            DownloadJob(
                id=job_id,
                status=JobStatus.QUEUED.value,
                platform=registry.detect_platform(url),
                source_url=url,
                source_domain="smoke-test",
                media_type="video" if mode == "video" else mode,
                requested_quality=quality,
                output_format=container,
            )
        )

    started = time.perf_counter()
    await process_job(job_id, None)
    elapsed = (time.perf_counter() - started) * 1000

    with session_scope() as db:
        job = db.get(DownloadJob, job_id)
        result = {
            "ok": job is not None and job.status == JobStatus.READY.value,
            "status": job.status if job else "missing",
            "mode": mode,
            "quality": quality,
            "file_name": job.file_name if job else None,
            "file_size": job.file_size if job else None,
            "error": f"{job.error_code}: {job.error_message}" if job and job.error_code else None,
            "elapsed_ms": round(elapsed),
        }
        if job is not None and job.file_path:
            source = Path(job.file_path)
            if source.is_file():
                out_dir.mkdir(parents=True, exist_ok=True)
                target = out_dir / source.name
                target.write_bytes(source.read_bytes())
                result["saved_to"] = str(target)
    return result


# --------------------------------------------------------------------------- #
# API mode
# --------------------------------------------------------------------------- #
def analyse_via_api(base_url: str, url: str) -> dict:
    import httpx

    started = time.perf_counter()
    response = httpx.post(
        f"{base_url.rstrip('/')}/api/media/analyze",
        json={"url": url},
        timeout=180.0,
    )
    elapsed = (time.perf_counter() - started) * 1000
    body = response.json()
    if "error" in body:
        raise RuntimeError(f"{body['error']['code']}: {body['error']['message']}")
    body["_elapsed_ms"] = round(elapsed)
    body["_provider"] = body.get("platform")
    return body


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def describe(payload: dict) -> None:
    video = [o["quality"] for o in payload.get("video_options", [])]
    audio = [o["quality"] for o in payload.get("audio_options", [])]
    images = payload.get("images") or []

    print(f"      title      : {(payload.get('title') or '?')[:64]}")
    print(f"      author     : {payload.get('author')}")
    print(f"      type       : {payload.get('media_type')}  duration={payload.get('duration_label')}")
    print(f"      video      : {', '.join(video) if video else '-'}")
    print(f"      audio      : {', '.join(audio) if audio else '-'}")
    if images:
        print(f"      images     : {len(images)}")
    for warning in payload.get("warnings", []):
        print(colour(f"      note       : {warning}", YELLOW))
    print(colour(f"      extracted in {payload['_elapsed_ms']} ms", DIM))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("urls", nargs="*", help="URLs to test (default: built-in set)")
    parser.add_argument("--api", help="test a running server instead of the library")
    parser.add_argument(
        "--download", action="store_true", help="also download the smallest rung"
    )
    parser.add_argument("--json", action="store_true", help="emit a machine-readable summary")
    parser.add_argument(
        "--out",
        default=str(REPO_ROOT / "data" / "smoke-test"),
        help="where --download writes files",
    )
    args = parser.parse_args()

    targets: list[tuple[str, str]] = (
        [("cli", u) for u in args.urls] if args.urls else DEFAULT_URLS
    )

    print()
    print(colour("Slipstream live extractor smoke test", "\033[1m"))
    print(colour("These calls hit real websites; failures are often upstream.", DIM))
    if args.api:
        print(colour(f"mode: HTTP against {args.api}", DIM))
    else:
        from app.services.extractor import extractor_status, ffmpeg_status

        print(
            colour(
                f"mode: in-process | {extractor_status().get('name')} "
                f"{extractor_status().get('version')} | ffmpeg="
                f"{'yes' if ffmpeg_status()['available'] else 'NO'}",
                DIM,
            )
        )
    print()

    results: list[dict] = []
    failures = 0

    for label, url in targets:
        print(f"  {label:16s} {url}")
        entry: dict = {"label": label, "url": url}
        try:
            payload = (
                analyse_via_api(args.api, url) if args.api else await analyse_via_library(url)
            )
            entry |= {
                "ok": True,
                "platform": payload.get("platform"),
                "title": payload.get("title"),
                "media_type": payload.get("media_type"),
                "video_options": [o["quality"] for o in payload.get("video_options", [])],
                "audio_options": [o["quality"] for o in payload.get("audio_options", [])],
                "images": len(payload.get("images") or []),
                "elapsed_ms": payload["_elapsed_ms"],
            }
            print(colour("      ANALYSE OK", GREEN))
            describe(payload)

            if args.download and not args.api:
                outcome = await download_via_library(url, payload, Path(args.out))
                entry["download"] = outcome
                if outcome["ok"]:
                    size = (outcome.get("file_size") or 0) / 1048576
                    print(
                        colour(
                            f"      DOWNLOAD OK  {outcome['mode']}/{outcome['quality']}  "
                            f"{size:.1f} MB in {outcome['elapsed_ms']} ms",
                            GREEN,
                        )
                    )
                    print(colour(f"      saved: {outcome.get('saved_to')}", DIM))
                else:
                    failures += 1
                    print(colour(f"      DOWNLOAD FAILED: {outcome.get('error')}", RED))
        except Exception as exc:  # noqa: BLE001 - a smoke test reports, never crashes
            failures += 1
            entry |= {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
            print(colour(f"      FAILED: {type(exc).__name__}: {str(exc)[:160]}", RED))
        results.append(entry)
        print()

    total = len(results)
    passed = sum(1 for r in results if r.get("ok"))
    print(colour(f"  {passed}/{total} analysed successfully", GREEN if passed == total else YELLOW))
    if failures:
        print(
            colour(
                "  Failures are frequently upstream (platform change, geo-block, "
                "rate limit). Check docs/TROUBLESHOOTING.md.",
                YELLOW,
            )
        )
    print()

    if args.json:
        print(json.dumps({"results": results, "passed": passed, "total": total}, indent=2))

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
