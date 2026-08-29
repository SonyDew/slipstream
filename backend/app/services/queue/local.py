"""In-process asyncio job queue.

Workers *claim* rows from ``download_jobs`` with a conditional UPDATE, so no job
is ever run twice even if several workers wake simultaneously. A submit() call
nudges the pool for low latency; a slow poll provides recovery when a nudge is
lost (process restart, job inserted by another worker/process).
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from sqlalchemy import func, select, update

from app.core.config import settings
from app.core.logging import get_logger
from app.core.settings_store import store
from app.db.session import session_scope
from app.models.job import DownloadJob, JobStatus
from app.services.queue.base import JobQueue, QueueStats

log = get_logger("slipstream.queue")

# How often a worker checks the table when no nudge arrives.
POLL_INTERVAL = 2.0
# How often the supervisor reconciles worker count with the admin setting.
SUPERVISOR_INTERVAL = 15.0


class LocalJobQueue(JobQueue):
    backend = "local-asyncio"

    def __init__(self) -> None:
        self._workers: list[asyncio.Task] = []
        self._supervisor: asyncio.Task | None = None
        self._nudge = asyncio.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._running = False
        self._active: dict[str, float] = {}
        self._cancelled: set[str] = set()
        self._processed = 0
        self._failed = 0
        self._desired_workers = 0
        self._shutdown = asyncio.Event()

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._shutdown.clear()
        self._loop = asyncio.get_running_loop()
        self._desired_workers = self._configured_workers()
        self._spawn_workers(self._desired_workers)
        self._supervisor = asyncio.create_task(self._supervise(), name="queue-supervisor")
        # Recover anything left mid-flight by an unclean shutdown.
        await asyncio.to_thread(self._requeue_orphans)
        self._nudge.set()
        log.info("job queue started", workers=self._desired_workers, backend=self.backend)

    async def stop(self, *, timeout: float = 10.0) -> None:
        if not self._running:
            return
        self._running = False
        self._shutdown.set()
        self._nudge.set()

        tasks = [*self._workers]
        if self._supervisor:
            tasks.append(self._supervisor)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=timeout)
        self._workers.clear()
        self._supervisor = None

        # Any job still marked active belongs to a process that is going away.
        await asyncio.to_thread(self._release_active)
        log.info("job queue stopped", processed=self._processed, failed=self._failed)

    def _spawn_workers(self, count: int) -> None:
        for index in range(count):
            task = asyncio.create_task(self._worker_loop(index), name=f"queue-worker-{index}")
            self._workers.append(task)

    @staticmethod
    def _configured_workers() -> int:
        """Concurrency from admin settings, falling back to the env default."""
        try:
            with session_scope() as db:
                value = store.get_int(db, "max_concurrent_downloads")
        except Exception:
            value = settings.MAX_CONCURRENT_DOWNLOADS
        return max(1, min(32, value))

    async def _supervise(self) -> None:
        """Reconcile the live worker count with the configured concurrency."""
        while self._running:
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=SUPERVISOR_INTERVAL)
                return
            except TimeoutError:
                pass

            # Drop finished tasks so the list reflects reality.
            self._workers = [t for t in self._workers if not t.done()]

            desired = await asyncio.to_thread(self._configured_workers)
            self._desired_workers = desired
            current = len(self._workers)
            if desired > current:
                log.info("scaling queue up", workers=desired)
                self._spawn_workers(desired - current)
            elif desired < current:
                log.info("scaling queue down", workers=desired)
                for task in self._workers[desired:]:
                    task.cancel()
                self._workers = self._workers[:desired]

    # ------------------------------------------------------------------ #
    # Producer API
    # ------------------------------------------------------------------ #
    def submit(self, job_id: str) -> None:
        """Nudge the pool. Safe from any thread."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        # A closing loop raises; the persisted row is still picked up by the
        # next poll, so there is nothing to recover here.
        with contextlib.suppress(RuntimeError):
            loop.call_soon_threadsafe(self._nudge.set)

    def request_cancel(self, job_id: str) -> None:
        self._cancelled.add(job_id)

    def is_cancelled(self, job_id: str) -> bool:
        if job_id in self._cancelled:
            return True
        # Another worker/process may have set the flag; check the row.
        try:
            with session_scope() as db:
                flag = db.execute(
                    select(DownloadJob.cancel_requested).where(DownloadJob.id == job_id)
                ).scalar_one_or_none()
            if flag:
                self._cancelled.add(job_id)
                return True
        except Exception as exc:
            log.warning("cancel flag lookup failed: %s", type(exc).__name__, job_id=job_id)
            return False
        return False

    def stats(self) -> QueueStats:
        queued = 0
        try:
            with session_scope() as db:
                queued = int(
                    db.execute(
                        select(func.count())
                        .select_from(DownloadJob)
                        .where(DownloadJob.status == JobStatus.QUEUED.value)
                    ).scalar()
                    or 0
                )
        except Exception as exc:
            # stats() feeds the dashboard and health probe; a transient database
            # error must degrade the number, not fail the request.
            log.warning("queue depth lookup failed: %s", type(exc).__name__)
        return QueueStats(
            backend=self.backend,
            running=self._running,
            workers=len([t for t in self._workers if not t.done()]),
            active=len(self._active),
            queued=queued,
            capacity=settings.JOB_QUEUE_SIZE,
            processed=self._processed,
            failed=self._failed,
        )

    # ------------------------------------------------------------------ #
    # Worker
    # ------------------------------------------------------------------ #
    async def _worker_loop(self, index: int) -> None:
        while self._running:
            try:
                job_id = await asyncio.to_thread(self._claim_next)
                if job_id is None:
                    # Nothing to do: wait for a nudge or poll again.
                    self._nudge.clear()
                    with contextlib.suppress(asyncio.TimeoutError):
                        await asyncio.wait_for(self._nudge.wait(), timeout=POLL_INTERVAL)
                    continue

                self._active[job_id] = time.monotonic()
                try:
                    await self._run_job(job_id)
                finally:
                    self._active.pop(job_id, None)
                    self._cancelled.discard(job_id)
                    # A finished job may free capacity for a queued one.
                    self._nudge.set()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("worker %s crashed: %s", index, type(exc).__name__, exc_info=True)
                await asyncio.sleep(1.0)

    async def _run_job(self, job_id: str) -> None:
        from app.services.downloader import process_job

        timeout = settings.JOB_TIMEOUT
        try:
            await asyncio.wait_for(process_job(job_id, self), timeout=timeout)
            self._processed += 1
        except TimeoutError:
            self._failed += 1
            log.warning("job timed out", job_id=job_id, timeout=timeout)
            await asyncio.to_thread(self._mark_timeout, job_id, timeout)
        except asyncio.CancelledError:
            await asyncio.to_thread(self._release_one, job_id)
            raise
        except Exception as exc:
            self._failed += 1
            log.error("job failed unexpectedly: %s", type(exc).__name__, job_id=job_id)
            await asyncio.to_thread(self._mark_internal_error, job_id)

    # ------------------------------------------------------------------ #
    # Database transitions (run on a thread)
    # ------------------------------------------------------------------ #
    def _claim_next(self) -> str | None:
        """Atomically take the oldest queued job, or return None."""
        with session_scope() as db:
            candidate = db.execute(
                select(DownloadJob.id)
                .where(DownloadJob.status == JobStatus.QUEUED.value)
                .order_by(DownloadJob.created_at)
                .limit(1)
            ).scalar_one_or_none()
            if candidate is None:
                return None

            # The WHERE clause on status is the claim: only one worker can flip
            # a given row out of `queued`.
            result = db.execute(
                update(DownloadJob)
                .where(
                    DownloadJob.id == candidate,
                    DownloadJob.status == JobStatus.QUEUED.value,
                )
                .values(
                    status=JobStatus.ANALYZING.value,
                    started_at=func.now(),
                    attempts=DownloadJob.attempts + 1,
                    progress=0,
                    progress_label="Starting",
                )
            )
            if result.rowcount != 1:
                return None  # lost the race
            return candidate

    def _requeue_orphans(self) -> None:
        """Reset jobs stuck in an active state by a previous process."""
        with session_scope() as db:
            result = db.execute(
                update(DownloadJob)
                .where(
                    DownloadJob.status.in_(sorted(JobStatus.active() - {JobStatus.QUEUED.value}))
                )
                .values(
                    status=JobStatus.QUEUED.value,
                    progress=0,
                    progress_label="Requeued after restart",
                )
            )
            if result.rowcount:
                log.info("requeued orphaned jobs", count=result.rowcount)

    def _release_active(self) -> None:
        for job_id in list(self._active):
            self._release_one(job_id)

    def _release_one(self, job_id: str) -> None:
        with session_scope() as db:
            db.execute(
                update(DownloadJob)
                .where(
                    DownloadJob.id == job_id,
                    DownloadJob.status.in_(sorted(JobStatus.active())),
                )
                .values(status=JobStatus.QUEUED.value, progress=0, progress_label="Requeued")
            )

    def _mark_timeout(self, job_id: str, timeout: int) -> None:
        from app.services.downloader import fail_job

        fail_job(
            job_id,
            code="job_timeout",
            message=f"This download exceeded the {timeout // 60} minute time limit.",
        )

    def _mark_internal_error(self, job_id: str) -> None:
        from app.services.downloader import fail_job

        fail_job(job_id, code="internal_error", message="An unexpected server error occurred.")
