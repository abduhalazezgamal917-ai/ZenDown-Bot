"""
handlers/errors.py — المعالج العام للأخطاء غير المعالجة في PTB.
"""
from __future__ import annotations

import logging

from telegram import Update
from telegram.error import BadRequest, Forbidden, NetworkError, RetryAfter, TimedOut

from services.uptime_server import record_error

logger = logging.getLogger("zendown.handlers.errors")


async def error_handler(update: object, context) -> None:
    error = context.error
    record_error()

    if isinstance(error, RetryAfter):
        logger.warning("Telegram rate limit — انتظار %.1f ثانية.", error.retry_after)
        return

    if isinstance(error, (NetworkError, TimedOut)):
        logger.warning("خطأ شبكة مؤقت: %s", error)
        return

    if isinstance(error, Forbidden):
        logger.warning("البوت محظور: %s | update=%s", error, _safe_update_id(update))
        return

    if isinstance(error, BadRequest):
        logger.error("طلب غير صالح: %s | update=%s", error, _safe_update_id(update))
        return

    logger.error(
        "استثناء غير معالج [update=%s]: %s",
        _safe_update_id(update), error, exc_info=error,
    )


def _safe_update_id(update: object) -> str:
    if isinstance(update, Update):
        return str(update.update_id)
    return "N/A"
