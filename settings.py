"""
settings.py — إدارة إعدادات البوت المستمرة (القناة + force_join).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

logger = logging.getLogger("zendown.settings")

_SETTINGS_FILE: str = "bot_settings.json"
_DEFAULTS: dict = {"channel": "@ZenoX_Tools", "force_join": True}

_lock = asyncio.Lock()


async def load() -> dict:
    async with _lock:
        return await asyncio.to_thread(_load_sync)


def _load_sync() -> dict:
    if not os.path.exists(_SETTINGS_FILE):
        return dict(_DEFAULTS)
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("ملف الإعدادات ليس JSON object صحيح")
        return {**_DEFAULTS, **data}
    except Exception as exc:
        logger.warning("فشل تحميل %s (%s)؛ الإعدادات الافتراضية.", _SETTINGS_FILE, exc)
        return dict(_DEFAULTS)


async def save(new_settings: dict) -> None:
    async with _lock:
        await asyncio.to_thread(_save_sync, new_settings)


def _save_sync(new_settings: dict) -> None:
    tmp_path = _SETTINGS_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(new_settings, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, _SETTINGS_FILE)
    except OSError as exc:
        logger.error("فشل حفظ الإعدادات: %s", exc)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
