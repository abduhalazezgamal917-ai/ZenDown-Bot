"""
services/stats.py — نظام تتبع إحصائيات ZenDown Bot.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("zendown.stats")

_STATS_FILE = "bot_stats.json"
_SAVE_EVERY  = 100
_MAX_DAYS    = 31


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _days_back(n: int) -> set[str]:
    from datetime import timedelta
    base = datetime.now(timezone.utc).date()
    return {str(base - timedelta(days=i)) for i in range(n)}


class StatsTracker:
    def __init__(self) -> None:
        self._lock    = asyncio.Lock()
        self._events  = 0
        self._started = time.time()

        self._active_users: dict[str, set[int]] = {}
        self._all_users: set[int] = set()
        self._downloads = {"total": 0, "success": 0, "failed": 0,
                           "cache_hits": 0, "videos_sent": 0, "rate_limited": 0}
        self._platforms = {"tiktok": 0, "instagram": 0, "youtube": 0,
                           "twitter": 0, "snapchat": 0, "pinterest": 0, "other": 0}
        self._shares      = 0
        self._server_start = time.time()

    async def load(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._load_sync)

    def _load_sync(self) -> None:
        if not os.path.exists(_STATS_FILE):
            return
        try:
            with open(_STATS_FILE, encoding="utf-8") as fh:
                data: dict[str, Any] = json.load(fh)
            self._all_users = set(data.get("all_users", []))
            for date_str, ids in data.get("active_users", {}).items():
                self._active_users[date_str] = set(ids)
            for key in self._downloads:
                self._downloads[key] = int(data.get("downloads", {}).get(key, 0))
            for key in self._platforms:
                self._platforms[key] = int(data.get("platforms", {}).get(key, 0))
            self._shares        = int(data.get("shares", 0))
            self._server_start  = float(data.get("server_start", self._server_start))
            logger.info("إحصائيات محمَّلة: %d مستخدم، %d طلب.",
                        len(self._all_users), self._downloads["total"])
        except Exception as exc:
            logger.warning("فشل تحميل الإحصائيات (%s)؛ يبدأ من الصفر.", exc)

    async def save(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._save_sync)

    def _save_sync(self) -> None:
        payload = {
            "all_users":    list(self._all_users),
            "active_users": {d: list(ids) for d, ids in self._active_users.items()},
            "downloads":    dict(self._downloads),
            "platforms":    dict(self._platforms),
            "shares":       self._shares,
            "server_start": self._server_start,
            "saved_at":     time.time(),
        }
        tmp = _STATS_FILE + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False)
            os.replace(tmp, _STATS_FILE)
        except OSError as exc:
            logger.error("فشل حفظ الإحصائيات: %s", exc)
            if os.path.exists(tmp):
                os.remove(tmp)

    async def _maybe_save(self) -> None:
        self._events += 1
        if self._events % _SAVE_EVERY == 0:
            await asyncio.to_thread(self._save_sync)
            self._cleanup_old_dates()

    def _cleanup_old_dates(self) -> None:
        keep = _days_back(_MAX_DAYS)
        for date_str in list(self._active_users):
            if date_str not in keep:
                del self._active_users[date_str]

    async def record_user(self, user_id: int) -> None:
        async with self._lock:
            self._all_users.add(user_id)
            today = _today()
            if today not in self._active_users:
                self._active_users[today] = set()
            self._active_users[today].add(user_id)
            await self._maybe_save()

    async def record_download_attempt(self, url: str) -> None:
        async with self._lock:
            self._downloads["total"] += 1
            self._platforms[_detect_platform(url)] += 1
            await self._maybe_save()

    async def record_download_success(self) -> None:
        async with self._lock:
            self._downloads["success"] += 1
            await self._maybe_save()

    async def record_download_failed(self) -> None:
        async with self._lock:
            self._downloads["failed"] += 1
            await self._maybe_save()

    async def record_cache_hit(self) -> None:
        async with self._lock:
            self._downloads["cache_hits"] += 1
            await self._maybe_save()

    async def record_video_sent(self, count: int = 1) -> None:
        async with self._lock:
            self._downloads["videos_sent"] += count
            await self._maybe_save()

    async def record_rate_limited(self) -> None:
        async with self._lock:
            self._downloads["rate_limited"] += 1
            await self._maybe_save()

    async def record_share(self) -> None:
        async with self._lock:
            self._shares += 1
            await self._maybe_save()

    async def snapshot(self) -> dict[str, Any]:
        async with self._lock:
            days_1  = _days_back(1)
            days_7  = _days_back(7)
            days_30 = _days_back(30)
            active_1  = len({uid for d in days_1  if d in self._active_users
                              for uid in self._active_users[d]})
            active_7  = len({uid for d in days_7  if d in self._active_users
                              for uid in self._active_users[d]})
            active_30 = len({uid for d in days_30 if d in self._active_users
                              for uid in self._active_users[d]})
            dl   = dict(self._downloads)
            plat = dict(self._platforms)
            total_success = dl["success"]
            total_dl      = dl["total"]
            cache_hits    = dl["cache_hits"]
            total_served  = total_success + cache_hits
            return {
                "users": {
                    "total": len(self._all_users),
                    "active_1": active_1, "active_7": active_7, "active_30": active_30,
                },
                "downloads": dl,
                "platforms": plat,
                "shares": self._shares,
                "cache_rate":   round(cache_hits / max(total_served, 1) * 100, 1),
                "success_rate": round(total_success / max(total_dl, 1) * 100, 1),
                "uptime_secs":  int(time.time() - self._server_start),
            }


def _detect_platform(url: str) -> str:
    u = url.lower()
    if "tiktok.com" in u or "vm.tiktok" in u or "vt.tiktok" in u:
        return "tiktok"
    if "instagram.com" in u:
        return "instagram"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    if "twitter.com" in u or "x.com" in u:
        return "twitter"
    if "snapchat.com" in u:
        return "snapchat"
    if "pinterest.com" in u or "pin.it" in u:
        return "pinterest"
    return "other"


_tracker: StatsTracker | None = None


def init_stats() -> StatsTracker:
    global _tracker
    _tracker = StatsTracker()
    return _tracker


def get_stats() -> StatsTracker:
    if _tracker is None:
        raise RuntimeError("StatsTracker لم يُهيَّأ — استدعِ init_stats() أولاً.")
    return _tracker
