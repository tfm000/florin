"""Tests for AsyncRateLimiter."""

import asyncio
import time

import pytest

from core.rate_limiter import AsyncRateLimiter


class TestAsyncRateLimiter:
    @pytest.mark.asyncio
    async def test_first_call_no_delay(self):
        limiter = AsyncRateLimiter(5, 60, name="test")
        t0 = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - t0
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_enforces_minimum_interval(self):
        limiter = AsyncRateLimiter(10, 1.0, name="test")  # 0.1s interval
        await limiter.acquire()
        t0 = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.08  # allow small timing slack

    @pytest.mark.asyncio
    async def test_single_request_per_window(self):
        limiter = AsyncRateLimiter(1, 0.3, name="test")  # 1 req per 0.3s
        await limiter.acquire()
        t0 = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.25

    @pytest.mark.asyncio
    async def test_concurrent_acquires_serialized(self):
        limiter = AsyncRateLimiter(10, 1.0, name="test")  # 0.1s interval
        t0 = time.monotonic()
        await asyncio.gather(
            limiter.acquire(),
            limiter.acquire(),
            limiter.acquire(),
        )
        elapsed = time.monotonic() - t0
        # 3 calls with 0.1s interval: first is instant, 2nd waits ~0.1s, 3rd ~0.2s
        assert elapsed >= 0.15
