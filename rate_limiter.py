"""
services/rate_limiter.py — محدِّد معدل الطلبات (Sliding Window).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque

from core.exceptions import RateLimitExceededError

logger = logging.getLogger("zendown.rate_limiter")


class SlidingWindowRateLimiter:
    __slots__ = ("_max", "_window", "_users", "_lock")

    def __init__(self, max_requests: int, window_secs: int) -> None:
        if max_requests < 1 or window_secs < 1:
            raise ValueError("max_requests و window_secs يجب أن يكونا > 0")
        self._max    = max_requests
        self._window = window_secs
        self._users: dict[int, deque[float]] = {}
        self._lock   = asyncio.Lock()

    async def check(self, user_id: int) -> None:
        now    = time.monotonic()
        cutoff = now - self._window
        async with self._lock:
            timestamps = self._users.setdefault(user_id, deque())
            while timestamps and timestamps[0] < cutoff:
                timestamps.popleft()
            if len(timestamps) >= self._max:
                wait_secs = int(self._window - (now - timestamps[0])) + 1
                raise RateLimitExceededError(wait_secs)
            timestamps.append(now)

    async def cleanup(self) -> int:
        cutoff = time.monotonic() - (self._window * 2)
        async with self._lock:
            inactive = [uid for uid, ts in self._users.items()
                        if not ts or ts[-1] < cutoff]
            for uid in inactive:
                del self._users[uid]
        return len(inactive)

    @property
    def active_users(self) -> int:
        return len(self._users)


_limiter: SlidingWindowRateLimiter | None = None


def init_rate_limiter(max_requests: int, window_secs: int) -> SlidingWindowRateLimiter:
    global _limiter
    _limiter = SlidingWindowRateLimiter(max_requests, window_secs)
    logger.info("Rate limiter: %d طلبات / %d ثانية", max_requests, window_secs)
    return _limiter


def get_rate_limiter() -> SlidingWindowRateLimiter:
    if _limiter is None:
        raise RuntimeError("لم يُهيَّأ Rate Limiter — استدعِ init_rate_limiter() أولاً")
    return _limiter
