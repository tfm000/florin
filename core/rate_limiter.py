"""Reusable async rate limiter for external API providers."""

from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class AsyncRateLimiter:
    """Minimum-interval rate limiter for external API calls.

    Enforces a minimum time gap between consecutive requests, computed as
    ``window_seconds / max_requests``. This prevents burst-then-wait
    patterns and provides steady pacing.

    Parameters
    ----------
    max_requests : int
        Maximum number of requests allowed within *window_seconds*.
    window_seconds : float
        Time window in seconds.
    name : str
        Label for debug logging (e.g. "SEC", "AlphaVantage").
    """

    def __init__(
        self,
        max_requests: int,
        window_seconds: float,
        name: str = "",
    ) -> None:
        self._min_interval = window_seconds / max_requests
        self._lock = asyncio.Lock()
        # -inf (not 0.0): time.monotonic()'s epoch is arbitrary (~boot time), so a
        # 0.0 seed makes the first acquire() compute elapsed == uptime. On a freshly
        # booted host (uptime < _min_interval) that triggers a spurious multi-minute
        # sleep. -inf means "no prior request" so the first call never waits.
        self._last_request_time: float = float("-inf")
        self._name = name

    async def acquire(self) -> None:
        """Wait until a request is allowed, then mark the slot as used."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request_time
            if elapsed < self._min_interval:
                delay = self._min_interval - elapsed
                logger.debug("%s: rate limit wait %.2fs", self._name, delay)
                await asyncio.sleep(delay)
            self._last_request_time = time.monotonic()
