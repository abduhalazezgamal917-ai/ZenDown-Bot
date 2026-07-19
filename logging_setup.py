"""
utils/logging_setup.py — إعداد نظام السجلات الهيكلي لـ ZenDown Bot.
"""
from __future__ import annotations

import logging
import sys

_NOISY_LOGGERS = (
    "httpx", "httpcore", "telegram", "telegram.ext",
    "yt_dlp", "aiohttp", "asyncio",
)


def setup_logging(level: str = "INFO") -> None:
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)-28s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.setLevel(numeric_level)

    root = logging.getLogger()
    root.setLevel(numeric_level)
    root.handlers.clear()
    root.addHandler(handler)

    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("zendown").setLevel(numeric_level)
    logging.getLogger("zendown").info("نظام السجلات جاهز — المستوى: %s", level.upper())
