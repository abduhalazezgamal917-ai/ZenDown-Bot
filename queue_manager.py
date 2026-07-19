"""
services/queue_manager.py — إدارة قائمة انتظار التحميل وحدود التزامن.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from core.exceptions import UserBusyError

logger = logging.getLogger("zendown.queue")


class DownloadQueueManager:
    def __init__(self, max_global: int, max_per_user: int) -> None:
        self._global_sem   = asyncio.Semaphore(max_global)
        self._max_per_user = max_per_user
        self._user_active: dict[int, int] = {}
        self._lock         = asyncio.Lock()
        logger.info("Queue: عالمي=%d | لكل مستخدم=%d", max_global, max_per_user)

    async def _user_can_proceed(self, user_id: int) -> bool:
        async with self._lock:
            return self._user_active.get(user_id, 0) < self._max_per_user

    async def _increment(self, user_id: int) -> None:
        async with self._lock:
            self._user_active[user_id] = self._user_active.get(user_id, 0) + 1

    async def _decrement(self, user_id: int) -> None:
        async with self._lock:
            count = self._user_active.get(user_id, 1) - 1
            if count <= 0:
                self._user_active.pop(user_id, None)
            else:
                self._user_active[user_id] = count

    @contextlib.asynccontextmanager
    async def acquire(self, user_id: int) -> AsyncIterator[None]:
        if not await self._user_can_proceed(user_id):
            raise UserBusyError("لديك عملية تحميل جارية بالفعل")
        await self._increment(user_id)
        try:
            async with self._global_sem:
                yield
        finally:
            await self._decrement(user_id)

    @property
    def active_count(self) -> int:
        return sum(self._user_active.values())

    @property
    def active_users(self) -> int:
        return len(self._user_active)


_queue: DownloadQueueManager | None = None


def init_queue(max_global: int, max_per_user: int) -> DownloadQueueManager:
    global _queue
    _queue = DownloadQueueManager(max_global, max_per_user)
    return _queue


def get_queue() -> DownloadQueueManager:
    if _queue is None:
        raise RuntimeError("لم يُهيَّأ Queue — استدعِ init_queue() أولاً")
    return _queue
