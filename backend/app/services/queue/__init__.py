"""Queue construction.

The single place that decides which backend is used. Swapping to Redis/Celery
means adding a branch here and an implementation of :class:`JobQueue` — no call
site in the API or services layer changes.
"""

from __future__ import annotations

from app.services.queue.base import JobQueue, QueueStats
from app.services.queue.local import LocalJobQueue

_queue: JobQueue | None = None


def get_queue() -> JobQueue:
    """Return the process-wide queue instance."""
    global _queue
    if _queue is None:
        _queue = LocalJobQueue()
    return _queue


def set_queue(queue: JobQueue | None) -> None:
    """Override the queue (used by tests to install a synchronous fake)."""
    global _queue
    _queue = queue


__all__ = ["JobQueue", "LocalJobQueue", "QueueStats", "get_queue", "set_queue"]
