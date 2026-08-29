"""Cleanup.

Runs on a schedule inside the app (and is invokable manually via the admin API
or ``python -m app.cli cleanup``) so a Docker deployment needs no host cron.

Sweeps, in order:

1. READY jobs past their TTL  → mark EXPIRED, delete bytes
2. terminal jobs older than the retention window → delete row + bytes
3. orphaned job directories (no matching row) → delete
4. expired/revoked sessions → delete
5. download history past the retention window → delete
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import asdict, dataclass
from datetime import timedelta

from sqlalchemy import delete, select

from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_store import store
from app.db.base import utcnow
from app.db.session import session_scope
from app.models.job import DownloadJob, JobStatus
from app.models.records import DownloadHistory
from app.models.user import UserSession
from app.services import storage

log = get_logger("slipstream.cleanup")

# Terminal job rows are kept briefly after their files go, so a user polling a
# finished job still gets a meaningful status instead of a 404.
JOB_ROW_GRACE = timedelta(hours=6)


@dataclass
class CleanupReport:
    expired_jobs: int = 0
    deleted_jobs: int = 0
    freed_bytes: int = 0
    orphan_dirs: int = 0
    expired_sessions: int = 0
    pruned_history: int = 0

    def as_dict(self) -> dict[str, int]:
        return asdict(self)

    @property
    def total_actions(self) -> int:
        return (
            self.expired_jobs
            + self.deleted_jobs
            + self.orphan_dirs
            + self.expired_sessions
            + self.pruned_history
        )


def run_cleanup() -> CleanupReport:
    """Perform one full sweep. Safe to call concurrently (idempotent)."""
    report = CleanupReport()

    with session_scope() as db:
        ttl = store.get_int(db, "temp_file_ttl")
        retention_days = store.get_int(db, "history_retention_days")

        # 1. Expire finished-but-stale downloads.
        stale = (
            db.execute(
                select(DownloadJob).where(
                    DownloadJob.status == JobStatus.READY.value,
                    DownloadJob.expires_at.is_not(None),
                    DownloadJob.expires_at <= utcnow(),
                )
            )
            .scalars()
            .all()
        )
        for job in stale:
            report.freed_bytes += job.file_size or 0
            storage.remove_job_dir(job.id)
            job.status = JobStatus.EXPIRED.value
            job.file_path = None
            job.progress_label = "Expired"
            report.expired_jobs += 1

        # 2. Drop old terminal rows and their bytes.
        cutoff = utcnow() - JOB_ROW_GRACE
        old_jobs = (
            db.execute(
                select(DownloadJob).where(
                    DownloadJob.status.in_(sorted(JobStatus.terminal())),
                    DownloadJob.created_at <= cutoff,
                )
            )
            .scalars()
            .all()
        )
        for job in old_jobs:
            storage.remove_job_dir(job.id)
            db.delete(job)
            report.deleted_jobs += 1

        # 4. Expired or revoked sessions.
        result = db.execute(
            delete(UserSession).where(
                (UserSession.expires_at <= utcnow()) | (UserSession.revoked_at.is_not(None))
            )
        )
        report.expired_sessions = int(result.rowcount or 0)

        # 5. History retention.
        if retention_days > 0:
            history_cutoff = utcnow() - timedelta(days=retention_days)
            result = db.execute(
                delete(DownloadHistory).where(DownloadHistory.created_at <= history_cutoff)
            )
            report.pruned_history = int(result.rowcount or 0)

        live_ids = set(db.execute(select(DownloadJob.id)).scalars())

    # 3. Directories with no surviving row (outside the transaction).
    report.orphan_dirs = _remove_orphan_directories(live_ids, ttl)

    if report.total_actions:
        log.info("cleanup sweep complete: %s", report.as_dict())
    return report


def _remove_orphan_directories(live_ids: set[str], ttl: int) -> int:
    removed = 0
    root = storage.jobs_root()
    try:
        entries = list(root.iterdir())
    except OSError:
        return 0

    for entry in entries:
        if not entry.is_dir() or entry.name in live_ids:
            continue
        with contextlib.suppress(OSError):
            storage.remove_job_dir(entry.name)
            removed += 1

    # Final backstop for anything the id-based check missed.
    removed += storage.prune_stale_directories(max(ttl * 4, 3600))
    return removed


async def cleanup_loop(stop_event: asyncio.Event) -> None:
    """Background task started by the app lifespan."""
    interval = max(60, settings.CLEANUP_INTERVAL)
    log.info("cleanup scheduler started", interval=interval)
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break  # stop requested
        except TimeoutError:
            pass
        try:
            await asyncio.to_thread(run_cleanup)
        except Exception as exc:
            log.error("cleanup sweep failed: %s", type(exc).__name__, exc_info=True)
    log.info("cleanup scheduler stopped")
