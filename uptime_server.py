"""
services/uptime_server.py — خادم HTTP خفيف الوزن لمراقبة صحة البوت (Layer 2 Uptime).

الطبقات الثلاث لنظام الـ Uptime:
  Layer 1: آلية الإعادة الداخلية (watchdog في bot.py)
  Layer 2: نقطة HTTP /health و /ping (هذا الملف)
  Layer 3: UptimeRobot يراقب نقطة /ping كل 5 دقائق

نقاط الطرف:
  GET /health  — معلومات تفصيلية عن حالة البوت (JSON)
  GET /ping    — رد بسيط سريع للمراقبة الخارجية
  GET /        — توجيه إلى /health
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from aiohttp import web

import core.config as cfg

logger = logging.getLogger("zendown.uptime")

# ── المتغيرات العامة ──────────────────────────────────────────────────────────
_start_time: float = time.time()
_bot_status: dict[str, Any] = {"running": True, "errors": 0}


# ──────────────────────────────────────────────────────────────────────────────
# معالجات الطرف (Endpoint Handlers)
# ──────────────────────────────────────────────────────────────────────────────

async def _handle_health(request: web.Request) -> web.Response:
    """GET /health — معلومات تفصيلية بصيغة JSON."""
    uptime_secs = int(time.time() - _start_time)
    hours, rem  = divmod(uptime_secs, 3600)
    minutes     = rem // 60

    payload = {
        "status":       "ok",
        "bot":          cfg.BOT_USERNAME,
        "uptime_secs":  uptime_secs,
        "uptime_human": f"{hours}h {minutes}m",
        "running":      _bot_status.get("running", True),
        "errors":       _bot_status.get("errors", 0),
        "timestamp":    time.time(),
    }
    return web.Response(
        text=json.dumps(payload, ensure_ascii=False),
        content_type="application/json",
        status=200,
    )


async def _handle_ping(request: web.Request) -> web.Response:
    """GET /ping — رد خفيف للمراقبة الخارجية (UptimeRobot)."""
    return web.Response(text="pong", status=200)


async def _handle_root(request: web.Request) -> web.Response:
    """GET / — توجيه إلى /health."""
    raise web.HTTPFound("/health")


# ──────────────────────────────────────────────────────────────────────────────
# دورة الحياة
# ──────────────────────────────────────────────────────────────────────────────

async def start_uptime_server(port: int | None = None) -> web.AppRunner:
    """
    يُشغّل خادم HTTP على *port* ويُعيد AppRunner (لإيقافه لاحقاً).

    يُسجّل رابط /ping لـ UptimeRobot:
      https://<replit-domain>/ping
    """
    global _start_time
    _start_time = time.time()

    if port is None:
        port = cfg.HEALTH_PORT

    app = web.Application()
    app.router.add_get("/",       _handle_root)
    app.router.add_get("/health", _handle_health)
    app.router.add_get("/ping",   _handle_ping)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()

    logger.info(
        "✅ خادم الصحة يعمل على المنفذ %d — نقاط المراقبة: /health | /ping",
        port,
    )
    logger.info(
        "🔗 رابط UptimeRobot: https://<replit-domain>/ping  (استبدل <replit-domain> بنطاقك)"
    )
    return runner


async def stop_uptime_server(runner: web.AppRunner) -> None:
    """يُوقف خادم HTTP بشكل نظيف."""
    try:
        await runner.cleanup()
        logger.info("تم إيقاف خادم الصحة.")
    except Exception as exc:
        logger.warning("خطأ أثناء إيقاف خادم الصحة: %s", exc)


def record_error() -> None:
    """يُسجّل خطأ في لوحة الصحة."""
    _bot_status["errors"] = _bot_status.get("errors", 0) + 1


def set_running(state: bool) -> None:
    """يُحدّث حالة تشغيل البوت."""
    _bot_status["running"] = state
