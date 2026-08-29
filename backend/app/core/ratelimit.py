"""Rate limiting.

An in-process sliding-window limiter. This is deliberately simple: the default
deployment is a single Uvicorn process on a small VPS, where a shared external
store would add a dependency without adding protection.

The :class:`RateLimiter` interface is the seam for a future Redis backend —
:class:`InMemoryRateLimiter` can be swapped out without touching call sites.
Nginx-level limits (see nginx/conf.d) provide defence in depth for multi-worker
deployments, where per-process counters would otherwise be N times too lax.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    limit: int
    retry_after: int
    reset_at: float


class RateLimiter(ABC):
    """Backend-agnostic limiter contract."""

    @abstractmethod
    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Consume one unit for ``key``. Does not raise."""

    @abstractmethod
    def reset(self, key: str | None = None) -> None:
        """Clear one key, or everything when ``key`` is None."""

    @abstractmethod
    def peek(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        """Report state without consuming a unit."""


class InMemoryRateLimiter(RateLimiter):
    """Sliding-window log, bounded per key.

    Memory is O(sum of active limits). With the shipped defaults and a few
    thousand distinct clients this stays in the low megabytes; ``_prune`` keeps
    idle keys from accumulating forever.
    """

    def __init__(self, *, prune_interval: float = 300.0, max_keys: int = 50_000) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()
        self._prune_interval = prune_interval
        self._max_keys = max_keys
        self._last_prune = time.monotonic()

    # -- internals ------------------------------------------------------- #
    def _trim(self, bucket: deque[float], cutoff: float) -> None:
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()

    def _maybe_prune(self, now: float) -> None:
        if now - self._last_prune < self._prune_interval:
            return
        self._last_prune = now
        # Drop keys whose newest hit is older than the longest plausible window.
        stale_cutoff = now - 3600.0
        for key in [k for k, v in self._hits.items() if not v or v[-1] < stale_cutoff]:
            self._hits.pop(key, None)
        # Hard cap as a memory backstop under a distributed flood.
        if len(self._hits) > self._max_keys:
            overflow = len(self._hits) - self._max_keys
            for key in list(self._hits.keys())[:overflow]:
                self._hits.pop(key, None)

    # -- API ------------------------------------------------------------- #
    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        if limit <= 0:
            # 0 or negative means "unlimited"; used by admin-configurable limits.
            return RateLimitResult(True, -1, limit, 0, 0.0)

        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            self._maybe_prune(now)
            bucket = self._hits[key]
            self._trim(bucket, cutoff)

            if len(bucket) >= limit:
                oldest = bucket[0]
                retry_after = max(1, int(oldest + window_seconds - now) + 1)
                return RateLimitResult(False, 0, limit, retry_after, time.time() + retry_after)

            bucket.append(now)
            remaining = limit - len(bucket)
            reset_in = int(bucket[0] + window_seconds - now) if bucket else window_seconds
            return RateLimitResult(True, remaining, limit, 0, time.time() + max(0, reset_in))

    def peek(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        if limit <= 0:
            return RateLimitResult(True, -1, limit, 0, 0.0)
        now = time.monotonic()
        with self._lock:
            bucket = self._hits.get(key)
            if not bucket:
                return RateLimitResult(True, limit, limit, 0, time.time() + window_seconds)
            self._trim(bucket, now - window_seconds)
            used = len(bucket)
            if used >= limit:
                retry_after = max(1, int(bucket[0] + window_seconds - now) + 1)
                return RateLimitResult(False, 0, limit, retry_after, time.time() + retry_after)
            return RateLimitResult(True, limit - used, limit, 0, time.time() + window_seconds)

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(key, None)


# Module-level singleton. Swap the class here to change backend globally.
limiter: RateLimiter = InMemoryRateLimiter()


def client_identity(ip: str, user_id: int | None) -> str:
    """Build the limiter key.

    Authenticated users are limited per account so that rotating IPs does not
    reset the counter; guests are limited per IP.
    """
    return f"user:{user_id}" if user_id else f"ip:{ip}"
