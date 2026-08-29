"""Storage for job working directories and finished files.

Every job gets its own directory under ``TEMP_DIR/jobs/<job_id>``. Isolation
means cleanup is a single recursive delete, a failed job cannot leave fragments
in another job's space, and no filename collision is possible between jobs.
"""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path

from app.core.config import settings
from app.core.filenames import resolve_within
from app.core.logging import get_logger

log = get_logger("slipstream.storage")

JOBS_DIRNAME = "jobs"


def jobs_root() -> Path:
    root = settings.temp_path / JOBS_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def job_dir(job_id: str, *, create: bool = False) -> Path:
    """Working directory for a job.

    ``job_id`` is a UUID hex string generated server-side, but this still goes
    through :func:`resolve_within` so a future change that lets a client
    influence the id cannot turn into a traversal.
    """
    path = resolve_within(jobs_root(), job_id)
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def remove_job_dir(job_id: str) -> bool:
    """Delete a job's directory. Returns True when something was removed."""
    try:
        path = job_dir(job_id)
    except ValueError:
        log.warning("refused to remove suspicious job id")
        return False
    if not path.exists():
        return False
    shutil.rmtree(path, ignore_errors=True)
    return True


def directory_size(path: Path) -> int:
    total = 0
    try:
        for entry in path.rglob("*"):
            if entry.is_file():
                with suppress_os_error():
                    total += entry.stat().st_size
    except OSError:
        pass
    return total


class suppress_os_error:
    """Tiny context manager: ignore per-file stat races during a walk."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, exc_type, exc, tb) -> bool:
        return exc_type is not None and issubclass(exc_type, OSError)


def temp_usage() -> dict[str, int]:
    """Bytes and file count currently held in the temp area."""
    root = jobs_root()
    files = 0
    total = 0
    try:
        for entry in root.rglob("*"):
            if entry.is_file():
                files += 1
                with suppress_os_error():
                    total += entry.stat().st_size
    except OSError:
        pass
    return {"bytes": total, "files": files}


def disk_free_bytes() -> int | None:
    try:
        usage = shutil.disk_usage(settings.temp_path)
        return int(usage.free)
    except OSError:  # pragma: no cover
        return None


def find_output_file(directory: Path) -> Path | None:
    """Pick the finished media file from a job directory.

    yt-dlp leaves ``.part``/``.ytdl`` fragments behind on failure and writes the
    merged output last, so the largest non-fragment file is the result.
    """
    if not directory.is_dir():
        return None
    candidates = [
        entry
        for entry in directory.iterdir()
        if entry.is_file()
        and entry.suffix.lower() not in {".part", ".ytdl", ".tmp"}
        and not entry.name.endswith(".part")
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


def prune_stale_directories(max_age_seconds: int) -> int:
    """Remove job directories older than ``max_age_seconds``.

    Belt-and-braces for directories whose job row vanished (manual DB edit,
    restored backup) so orphaned bytes cannot accumulate forever.
    """
    root = jobs_root()
    cutoff = time.time() - max_age_seconds
    removed = 0
    try:
        for entry in root.iterdir():
            if not entry.is_dir():
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    shutil.rmtree(entry, ignore_errors=True)
                    removed += 1
            except OSError:
                continue
    except OSError:
        pass
    return removed


def atomic_replace(source: Path, destination: Path) -> None:
    """Move ``source`` onto ``destination`` atomically where the OS allows."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, destination)
