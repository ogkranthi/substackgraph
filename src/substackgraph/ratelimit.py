"""A trivial single-process rate limiter. Enforces the ≤1 req/sec Substack guard."""

from __future__ import annotations

import time

from .config import RATE_LIMIT_S


class RateLimiter:
    """Blocks on `acquire()` until at least `min_interval` seconds have elapsed since
    the previous acquire. Process-local; the crawler is single-process by design.

    The limiter is invoked only on a genuine cache *miss* — cached re-runs never sleep.
    """

    def __init__(self, min_interval: float = RATE_LIMIT_S, sleep=time.sleep, clock=time.monotonic):
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def acquire(self) -> None:
        now = self._clock()
        if self._last is not None:
            wait = self.min_interval - (now - self._last)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last = now
