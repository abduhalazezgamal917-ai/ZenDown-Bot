"""
handlers/messages.py — المعالج الرئيسي للرسائل النصية.

تسلسل العمليات المُطوَّر:
  1. بوابة الاشتراك الإجباري (middleware)
  2. Rate limiting (حد الطلبات لكل مستخدم)
  3. التحقق من صحة الرابط وتعقيمه
  4. توليد hash16 للرابط وتخزينه في bot_data
  5. عرض لوحة اختيار النوع: 🎧 موسيقى | 📺 فيديو
  ↳ التحميل الفعلي يحدث في handlers/callbacks.py
"""
from __future__ import annotations

import hashlib
import logging
import time

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from core.config import BOT_USERNAME, URL_PATTERN
from core.exceptions import RateLimitExceededError
from handlers.middleware import enforce_force_join
from services.rate_limiter import get_rate_limiter
from services.stats import get_stats
from utils.validators import validate_url

import ui

logger = logging.getLogger("zendown.handlers.messages")

# ── مفتاح تخزين الروابط المعلقة في bot_data ──────────────────────────────────
PENDING_KEY = "pending_dl"

# مدة صلاحية الرابط المعلق (بالثواني) — يُنظَّف بعدها
PENDING_TTL_SECS = 3600  # ساعة واحدة


def make_short_hash(url: str) -> str:
    """
    يُنتج hash16 (16 حرف hex) من الرابط.
    يُستخدم كمفتاح callback_data — يجب أن يكون قصيراً (≤64 بايت في المجموع).
    """
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()[:16]


async def _get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    return (await context.bot.get_me()).username or BOT_USERNAME


def _store_pending(context: ContextTypes.DEFAULT_TYPE, url_hash: str, url: str,
                   user_id: int, chat_id: int) -> None:
    """يُخزّن الرابط المعلق في bot_data مع طابع زمني للتنظيف لاحقاً."""
    pending = context.application.bot_data.setdefault(PENDING_KEY, {})
    pending[url_hash] = {
        "url":       url,
        "user_id":   user_id,
        "chat_id":   chat_id,
        "timestamp": time.time(),
    }


def cleanup_expired_pending(context: ContextTypes.DEFAULT_TYPE) -> int:
    """يحذف الروابط المعلقة المنتهية الصلاحية. يُعيد عدد المحذوفة."""
    pending = context.application.bot_data.get(PENDING_KEY, {})
    now     = time.time()
    expired = [k for k, v in pending.items()
               if now - v.get("timestamp", 0) > PENDING_TTL_SECS]
    for k in expired:
        del pending[k]
    return len(expired)


# ──────────────────────────────────────────────────────────────────────────────
# المعالج الرئيسي
# ──────────────────────────────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    يعالج كل رسالة نصية:
      1. بوابة الاشتراك الإجباري
      2. فحص حد الطلبات
      3. تحقق من الرابط وتعقيمه
      4. عرض لوحة اختيار النوع (فيديو / موسيقى)

    التحميل الفعلي يحدث في callbacks.py عند ضغط المستخدم على الزر.
    """
    if not update.message:
        return

    user    = update.effective_user
    user_id = user.id if user else 0

    # ── 1. بوابة الاشتراك الإجباري ───────────────────────────────────────────
    if not await enforce_force_join(update, context):
        return

    # ── تسجيل المستخدم النشط ────────────────────────────────────────────────
    if user:
        await get_stats().record_user(user_id)

    # ── 2. حد الطلبات (Rate Limiting) ────────────────────────────────────────
    try:
        await get_rate_limiter().check(user_id)
    except RateLimitExceededError as exc:
        wait = exc.args[0] if exc.args else "?"
        await get_stats().record_rate_limited()
        await update.message.reply_text(
            f"⏳ <b>لقد تجاوزت حد الطلبات!</b>\n"
            f"انتظر <b>{wait} ثانية</b> ثم أعد المحاولة 🙏",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── 3. استخراج الرابط والتحقق منه ────────────────────────────────────────
    user_text = (update.message.text or "").strip()
    url_match = URL_PATTERN.search(user_text)

    if not url_match:
        await update.message.reply_text(
            "⚠️ <b>أرسل رابط فيديو صحيح</b> "
            "(تيك توك، يوتيوب، إنستغرام، تويتر...) لأتمكن من تحميله! 😊",
            parse_mode=ParseMode.HTML,
        )
        return

    raw_url = url_match.group(0)
    valid, url = validate_url(raw_url)

    if not valid:
        logger.warning("المستخدم %d أرسل رابطاً غير صالح: %.100s", user_id, raw_url)
        await update.message.reply_text(
            "⚠️ <b>الرابط غير صالح أو غير مدعوم.</b> "
            "تأكد من نسخ الرابط كاملاً وأعد المحاولة 🙏",
            parse_mode=ParseMode.HTML,
        )
        return

    # ── 4. تخزين الرابط وعرض لوحة الاختيار ──────────────────────────────────
    url_hash = make_short_hash(url)
    chat_id  = update.message.chat_id

    _store_pending(context, url_hash, url, user_id, chat_id)

    logger.info("رابط مُخزَّن [user=%d hash=%s]: %.80s", user_id, url_hash, url)

    await update.message.reply_text(
        ui.media_select_text(url),
        parse_mode=ParseMode.HTML,
        reply_markup=ui.media_select_markup(url_hash),
    )
