"""
bot.py — نقطة الدخول لـ ZenDown Bot (نظام الاستقرار الكامل).

طبقات الاستقرار:
  Layer 1 (Python Watchdog) : إعادة تشغيل تلقائية داخلية (100 محاولة)
  Layer 2 (Shell Watchdog)  : start.sh — exponential backoff (200 محاولة)
  Layer 3 (Replit Workflow) : Replit يُعيد تشغيل العملية عند الإيقاف
  Layer 4 (HTTP Server)     : /health و /ping على منفذ 8090
  Layer 5 (Self-Keepalive)  : ping ذاتي كل 4 دقائق داخل event loop
  Layer 6 (UptimeRobot)     : مراقبة خارجية كل 5 دقائق (يُعدّ خارجياً)

إعدادات PTB للاستقرار:
  - connect/read/write/pool timeout: 30s لكل منها
  - connection_pool_size: 8 اتصالات متزامنة
  - retry_on_conflict: True (خلل الجلسات)
  - get_updates_*timeout: مُعيَّنة بشكل مستقل
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

# ── إعداد السجلات أولاً ──────────────────────────────────────────────────────
from core.config import (
    BOT_TOKEN,
    CACHE_TTL,
    HEALTH_PORT,
    LOG_LEVEL,
    MAX_CONCURRENT_DOWNLOADS,
    MAX_CONCURRENT_PER_USER,
    RATE_LIMIT_REQUESTS,
    RATE_LIMIT_WINDOW,
)
import core.config as cfg
from utils.logging_setup import setup_logging

setup_logging(LOG_LEVEL)
logger = logging.getLogger("zendown.bot")

# ── المعالجات ─────────────────────────────────────────────────────────────────
from handlers.callbacks import (
    check_subscription_callback,
    download_audio_callback,
    download_video_callback,
    pay_monthly_callback,
    pay_once_callback,
    pay_weekly_callback,
    pre_checkout_query_handler,
    refresh_stats_callback,
    share_bot_callback,
    successful_payment_handler,
)
from handlers.commands import (
    forcejoin_command,
    setchannel_command,
    start_command,
    stats_command,
    stats_keyword_handler,
)
from handlers.errors import error_handler
from handlers.messages import handle_message

# ── الخدمات ───────────────────────────────────────────────────────────────────
from services.cache import init_cache
from services.download_service import close_http_session, init_http_session
from services.queue_manager import init_queue
from services.rate_limiter import init_rate_limiter
from services.stats import init_stats
from services.uptime_server import (
    record_error,
    set_running,
    start_uptime_server,
    stop_uptime_server,
)

# ── ثوابت ────────────────────────────────────────────────────────────────────
_MAX_RESTARTS     = 100
_RESTART_DELAY    = 3       # ثوانٍ بين محاولات Python watchdog
_KEEPALIVE_SECS   = 240     # self-ping كل 4 دقائق
_CONNECT_TIMEOUT  = 30.0    # ثوانٍ — timeout اتصال PTB
_READ_TIMEOUT     = 30.0
_WRITE_TIMEOUT    = 30.0
_POOL_TIMEOUT     = 30.0
_POOL_SIZE        = 8       # اتصالات HTTP متزامنة في pool PTB


# ──────────────────────────────────────────────────────────────────────────────
# مهام الخلفية
# ──────────────────────────────────────────────────────────────────────────────

async def _self_keepalive_loop() -> None:
    """
    Layer 5: Self-Keepalive
    يُنفَّذ كل 4 دقائق داخل event loop:
      • يُرسل GET /health لنفسه → يُبقي event loop نشطاً
      • يُسجّل heartbeat في السجلات
      • يتحقق من صحة خادم الـ uptime
    """
    import aiohttp

    url = f"http://127.0.0.1:{HEALTH_PORT}/health"
    await asyncio.sleep(30)   # انتظر حتى يستقر البوت

    logger.info("💓 Self-Keepalive بدأ — يُنبض كل %ds", _KEEPALIVE_SECS)
    consecutive_fails = 0

    while True:
        try:
            await asyncio.sleep(_KEEPALIVE_SECS)
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        consecutive_fails = 0
                        logger.info(
                            "💓 Heartbeat ✅ | uptime=%ds | errors=%d",
                            data.get("uptime_secs", 0),
                            data.get("errors", 0),
                        )
                    else:
                        consecutive_fails += 1
                        logger.warning("💓 Heartbeat ⚠️ status=%d", resp.status)
        except asyncio.CancelledError:
            logger.info("💓 Self-Keepalive أُوقف.")
            break
        except Exception as exc:
            consecutive_fails += 1
            logger.warning("💓 Heartbeat فشل (%d) : %s", consecutive_fails, exc)


async def _cache_cleanup_loop() -> None:
    """تنظيف الكاش والـ rate limiter كل 10 دقائق."""
    from services.cache import get_cache
    from services.rate_limiter import get_rate_limiter

    while True:
        try:
            await asyncio.sleep(600)
            evicted = await get_cache().evict_expired()
            cleaned = await get_rate_limiter().cleanup()
            if evicted or cleaned:
                logger.debug("تنظيف: %d كاش | %d rate limiter", evicted, cleaned)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("خطأ في تنظيف الكاش.")


async def _pending_cleanup_loop(application: Application) -> None:
    """تنظيف الروابط المعلقة المنتهية الصلاحية كل 30 دقيقة."""
    from handlers.messages import PENDING_TTL_SECS

    while True:
        try:
            await asyncio.sleep(1800)
            pending = application.bot_data.get("pending_dl", {})
            now     = time.time()
            expired = [k for k, v in list(pending.items())
                       if now - v.get("timestamp", 0) > PENDING_TTL_SECS]
            for k in expired:
                pending.pop(k, None)
            if expired:
                logger.debug("تنظيف: %d رابط معلق منتهٍ.", len(expired))
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("خطأ في تنظيف الروابط.")


async def _stats_autosave_loop() -> None:
    """حفظ الإحصائيات تلقائياً كل 15 دقيقة."""
    from services.stats import get_stats

    while True:
        try:
            await asyncio.sleep(900)
            await get_stats().save()
            logger.debug("📊 إحصائيات محفوظة تلقائياً.")
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("خطأ في الحفظ التلقائي للإحصائيات.")


# ──────────────────────────────────────────────────────────────────────────────
# Hooks دورة الحياة
# ──────────────────────────────────────────────────────────────────────────────

async def _post_init(application: Application) -> None:
    """يُهيّئ جميع الخدمات ويُشغّل المهام الخلفية."""
    logger.info("جاري تهيئة الخدمات...")

    await init_http_session()
    init_cache(ttl=CACHE_TTL)
    init_rate_limiter(max_requests=RATE_LIMIT_REQUESTS, window_secs=RATE_LIMIT_WINDOW)
    init_queue(max_global=MAX_CONCURRENT_DOWNLOADS, max_per_user=MAX_CONCURRENT_PER_USER)

    tracker = init_stats()
    await tracker.load()

    # ── تشغيل المهام الخلفية ──────────────────────────────────────────────────
    loop = asyncio.get_event_loop()
    loop.create_task(_cache_cleanup_loop(),                  name="cache-cleanup")
    loop.create_task(_pending_cleanup_loop(application),     name="pending-cleanup")
    loop.create_task(_stats_autosave_loop(),                 name="stats-autosave")
    loop.create_task(_self_keepalive_loop(),                 name="self-keepalive")   # Layer 5

    # ── Layer 4: خادم HTTP ────────────────────────────────────────────────────
    cfg.BOT_START_TIME = time.time()
    try:
        runner = await start_uptime_server(port=HEALTH_PORT)
        application.bot_data["uptime_runner"] = runner
        logger.info(
            "🌐 خادم الصحة على المنفذ %d → UptimeRobot: أضف /ping لمراقبتك",
            HEALTH_PORT,
        )
    except Exception as exc:
        logger.warning("تعذّر تشغيل خادم الصحة: %s", exc)

    set_running(True)
    logger.info("✅ جميع الخدمات جاهزة.")


async def _post_shutdown(application: Application) -> None:
    """يُغلق الموارد ويحفظ البيانات عند الإيقاف."""
    logger.info("جاري الإغلاق النظيف...")
    set_running(False)

    from services.stats import get_stats
    try:
        await get_stats().save()
    except Exception:
        logger.exception("فشل حفظ الإحصائيات.")

    await close_http_session()

    runner = application.bot_data.get("uptime_runner")
    if runner:
        await stop_uptime_server(runner)

    logger.info("✅ تم الإغلاق النظيف.")


# ──────────────────────────────────────────────────────────────────────────────
# بناء التطبيق
# ──────────────────────────────────────────────────────────────────────────────

def _build_app() -> Application:
    """
    يبني Application بإعدادات PTB المُحسَّنة للاستقرار:
      • timeouts: 30s لكل عملية
      • connection_pool_size: 8 اتصالات متزامنة
      • get_updates_*: timeout مستقل لـ polling
    """
    app = (
        ApplicationBuilder()
        .token(BOT_TOKEN)
        # ── Timeouts اتصال HTTP ───────────────────────────────────────────────
        .connect_timeout(_CONNECT_TIMEOUT)
        .read_timeout(_READ_TIMEOUT)
        .write_timeout(_WRITE_TIMEOUT)
        .pool_timeout(_POOL_TIMEOUT)
        .connection_pool_size(_POOL_SIZE)
        # ── Timeouts polling (get_updates) مستقلة ────────────────────────────
        .get_updates_connect_timeout(_CONNECT_TIMEOUT)
        .get_updates_read_timeout(60.0)   # polling يحتاج وقتاً أطول
        .get_updates_write_timeout(_WRITE_TIMEOUT)
        .get_updates_pool_timeout(_POOL_TIMEOUT)
        # ── Hooks دورة الحياة ─────────────────────────────────────────────────
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        # ── تفعيل التحديثات المتزامنة ─────────────────────────────────────────
        .concurrent_updates(True)
        .build()
    )

    # ── اختيار نوع الوسائط ──────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",      start_command))
    app.add_handler(CommandHandler("setchannel", setchannel_command))
    app.add_handler(CommandHandler("forcejoin",  forcejoin_command))
    app.add_handler(CommandHandler("stats",      stats_command))

    app.add_handler(CallbackQueryHandler(download_video_callback, pattern=r"^dl_video:"))
    app.add_handler(CallbackQueryHandler(download_audio_callback, pattern=r"^dl_audio:"))

    # ── الدفع ────────────────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(pay_once_callback,    pattern=r"^pay_once:"))
    app.add_handler(CallbackQueryHandler(pay_weekly_callback,  pattern=r"^pay_weekly:"))
    app.add_handler(CallbackQueryHandler(pay_monthly_callback, pattern=r"^pay_monthly:"))
    app.add_handler(PreCheckoutQueryHandler(pre_checkout_query_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))

    # ── الأزرار الأخرى ───────────────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))
    app.add_handler(CallbackQueryHandler(share_bot_callback,          pattern="^share_bot$"))
    app.add_handler(CallbackQueryHandler(refresh_stats_callback,      pattern="^refresh_stats$"))

    # ── الكلمات المفتاحية للمشرف ─────────────────────────────────────────────
    _stats_filter = filters.TEXT & ~filters.COMMAND & filters.Regex(
        r"^(إحصائيات|احصائيات|stats|الإحصائيات)$"
    )
    app.add_handler(MessageHandler(_stats_filter, stats_keyword_handler))

    # ── الرسائل النصية ───────────────────────────────────────────────────────
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # ── معالج الأخطاء ────────────────────────────────────────────────────────
    app.add_error_handler(error_handler)

    return app


# ──────────────────────────────────────────────────────────────────────────────
# Layer 1: Python Watchdog
# ──────────────────────────────────────────────────────────────────────────────

_shutdown_requested = False


def _handle_signal(signum: int, frame) -> None:
    """معالج إشارات SIGTERM/SIGINT للإيقاف النظيف."""
    global _shutdown_requested
    sig_name = signal.Signals(signum).name
    logger.info("📡 استُقبلت إشارة %s — بدء الإيقاف النظيف...", sig_name)
    _shutdown_requested = True


def main() -> None:
    """
    نقطة الدخول الرئيسية مع Python watchdog.

    تسلسل الاستقرار:
      1. تسجيل معالجات SIGTERM/SIGINT
      2. بناء Application بإعدادات PTB المُحسَّنة
      3. run_polling مع إعادة تشغيل تلقائية عند الانهيار
      4. تأخير بين المحاولات لمنع CPU spike
    """
    # ── تسجيل معالجات الإشارة ────────────────────────────────────────────────
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT,  _handle_signal)

    logger.info("═" * 55)
    logger.info("  ZenDown Bot يبدأ")
    logger.info("  Layer 1: Python Watchdog (%d محاولة | delay=%ds)", _MAX_RESTARTS, _RESTART_DELAY)
    logger.info("  Layer 2: Shell Watchdog  (start.sh)")
    logger.info("  Layer 3: Replit Workflow auto-restart")
    logger.info("  Layer 4: HTTP /health /ping (port %d)", HEALTH_PORT)
    logger.info("  Layer 5: Self-Keepalive (كل %ds)", _KEEPALIVE_SECS)
    logger.info("═" * 55)

    for attempt in range(1, _MAX_RESTARTS + 1):
        if _shutdown_requested:
            logger.info("إيقاف نظيف مطلوب — خروج.")
            break

        logger.info("▶ محاولة %d/%d", attempt, _MAX_RESTARTS)
        t_start = time.monotonic()

        try:
            app = _build_app()
            app.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True,
                close_loop=False,
            )
            logger.info("✅ البوت أُوقف بشكل نظيف.")
            break

        except KeyboardInterrupt:
            logger.info("⌨️  Ctrl+C — إيقاف يدوي.")
            break

        except SystemExit as exc:
            if exc.code == 0:
                logger.info("✅ SystemExit(0) — خروج نظيف.")
                break
            logger.warning("SystemExit(%s) — قد يُعاد التشغيل.", exc.code)

        except Exception as exc:
            runtime = time.monotonic() - t_start
            record_error()
            logger.error(
                "❌ انهيار بعد %.1fs (محاولة %d): %s",
                runtime, attempt, exc, exc_info=True,
            )

        if attempt < _MAX_RESTARTS and not _shutdown_requested:
            logger.info("⏳ إعادة خلال %ds...", _RESTART_DELAY)
            time.sleep(_RESTART_DELAY)

    logger.info("═" * 55)
    logger.info("  ZenDown Bot أُوقف — sys.exit(0)")
    logger.info("═" * 55)
    sys.exit(0)


if __name__ == "__main__":
    main()
