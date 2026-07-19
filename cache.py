"""
services/cache.py — كاش TTL غير متزامن للذاكرة.

التحديث: make_url_key يقبل الآن media_type لتمييز كاش الفيديو عن الصوت.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

logger = logging.getLogger("zendown.cache")


class TTLCache:
    __slots__ = ("_ttl", "_store", "_lock", "_hits", "_misses")

    def __init__(self, ttl: int = 3600) -> None:
        self._ttl    = ttl
        self._store: dict[str, tuple[Any, float]] = {}
        self._lock   = asyncio.Lock()
        self._hits   = 0
        self._misses = 0

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                self._misses += 1
                return None
            value, expires_at = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                self._misses += 1
                return None
            self._hits += 1
            return value

    async def set(self, key: str, value: Any) -> None:
        expires_at = time.monotonic() + self._ttl
        async with self._lock:
            self._store[key] = (value, expires_at)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._store.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._store.clear()
            self._hits = 0
            self._misses = 0

    async def evict_expired(self) -> int:
        now = time.monotonic()
        async with self._lock:
            expired = [k for k, (_, exp) in self._store.items() if now > exp]
            for k in expired:
                del self._store[k]
        return len(expired)

    @property
    def stats(self) -> dict[str, int]:
        return {"size": len(self._store), "hits": self._hits, "misses": self._misses}

    def __len__(self) -> int:
        return len(self._store)


def make_url_key(url: str, media_type: str = "video") -> str:
    """
    يُنتج مفتاح كاش فريد من الرابط ونوع الوسائط.
    media_type: "video" أو "audio"
    """
    normalized = f"{url.strip().lower()}:{media_type}"
    return hashlib.sha256(normalized.encode()).hexdigest()


# ── Singleton ─────────────────────────────────────────────────────────────────
video_cache: TTLCache | None = None


def init_cache(ttl: int) -> TTLCache:
    global video_cache
    video_cache = TTLCache(ttl=ttl)
    logger.info("تم تهيئة الكاش — TTL: %d ثانية", ttl)
    return video_cache


def get_cache() -> TTLCache:
    if video_cache is None:
        raise RuntimeError("لم يُهيَّأ الكاش — استدعِ init_cache() أولاً")
    return video_cache
