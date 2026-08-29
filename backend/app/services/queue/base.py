"""Job queue abstraction.

The shipped implementation is an in-process asyncio worker pool
(:mod:`app.services.queue.local`) because the default deployment is a single
container on a small VPS, where adding Redis would cost memory without buying
capability.

Everything the application calls lives on :class:`JobQueue`, so a Celery/Redis
backend can be dropped in by implementing this interface and changing the single
construction site in :func:`app.services.queue.get_queue`. Jobs are persisted in
SQLite and *claimed* by workers, which is what makes the swap possible: an
external worker fleet can claim from the same table without any producer-side
change.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueStats:
    backend: str
    running: bool
    workers: int
    active: int
    queued: int
    capacity: int
    processed: int
    failed: int


class JobQueue(ABC):
    """Producer/consumer contract for download jobs."""

    backend: str = "abstract"

    @abstractmethod
    async def start(self) -> None:
        """Begin consuming. Idempotent."""

    @abstractmethod
    async def stop(self, *, timeout: float = 10.0) -> None:
        """Stop consuming and let in-flight jobs finish or be marked failed."""

    @abstractmethod
    def submit(self, job_id: str) -> None:
        """Signal that a persisted job is ready to run.

        Must be safe to call from a worker thread (FastAPI runs sync endpoints
        off the event loop), and must not raise if the queue is not running —
        a persisted job is picked up by the next poll regardless.
        """

    @abstractmethod
    def request_cancel(self, job_id: str) -> None:
        """Ask a running job to stop at its next checkpoint."""

    @abstractmethod
    def is_cancelled(self, job_id: str) -> bool:
        """True when cancellation was requested for this job."""

    @abstractmethod
    def stats(self) -> QueueStats:
        """Snapshot for the admin dashboard and health endpoint."""
