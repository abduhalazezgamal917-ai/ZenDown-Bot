"""
handlers/callbacks.py — معالجات أزرار Inline Keyboard لـ ZenDown Bot.

الأزرار المدعومة:
  dl_video:{hash}     — تحميل الفيديو بصيغة MP4
  dl_audio:{hash}     — تحميل الصوت بصيغة MP3 (تحويل من MP4)
  pay_once:{hash}:{t} — فاتورة Stars للتحميل الواحد
  pay_weekly:{hash}:{t}  — فاتورة Stars الأسبوعية
  pay_monthly:{hash}:{t} — فاتورة Stars الشهرية
  check_subscription  — التحقق من الاشتراك في القناة
  share_bot           — مشاركة البوت
  refresh_stats       — تحديث إحصائيات المشرف
"""
from __future__ import annotations

import logging
import os
import tempfile
import uuid

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import ContextTypes
from yt_dlp.utils import DownloadError

import settings
import ui
from core.config import ADMIN_ID, BOT_USERNAME, MAX_UPLOAD_BYTES
from core.exceptions import (
    AudioConversionError,
    DownloadFailedError,
    PaymentRequiredError,
    UserBusyError,
    VideoTooLargeError,
)
from handlers.messages import PENDING_KEY
from handlers.middleware import is_subscribed
from services.audio_service import convert_mp4_to_mp3
from services.cache import get_cache, make_url_key
from services.download_service import fetch_videos
from services.payment_service import (
    PLANS,
    build_invoice_payload,
    grant_subscription,
    has_active_subscription,
    parse_invoice_payload,
)
from services.queue_manager import get_queue
from services.stats import get_stats

logger = logging.getLogger("zendown.handlers.callbacks")

_MAX_FILE_BYTES = MAX_UPLOAD_BYTES  # 50 MB


# ──────────────────────────────────────────────────────────────────────────────
# أدوات مساعدة
# ──────────────────────────────────────────────────────────────────────────────

async def _get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    return (await context.bot.get_me()).username or BOT_USERNAME


def _get_pending(context: ContextTypes.DEFAULT_TYPE, url_hash: str) -> dict | None:
    """يُعيد بيانات الرابط المعلق أو None إذا انتهت صلاحيته / غير موجود."""
    return context.application.bot_data.get(PENDING_KEY, {}).get(url_hash)


def _pop_pending(context: ContextTypes.DEFAULT_TYPE, url_hash: str) -> dict | None:
    """يُعيد ويحذف بيانات الرابط المعلق."""
    pending = context.application.bot_data.get(PENDING_KEY, {})
    return pending.pop(url_hash, None)


async def _send_video_file(
    update: Update,
    path: str,
    caption: str,
    index: int = 1,
    total: int = 1,
    url: str = "",
) -> str | None:
    """يرسل ملف MP4 كفيديو (أو document احتياطاً). يُعيد file_id."""
    try:
        with open(path, "rb") as fh:
            sent: Message = await update.effective_message.reply_video(
                video=fh, caption=caption, supports_streaming=True,
            )
        return sent.video.file_id if sent.video else None
    except TelegramError as exc:
        logger.warning("reply_video فشل (%s)؛ أحاول document.", exc)

    try:
        with open(path, "rb") as fh:
            sent = await update.effective_message.reply_document(
                document=fh, caption=caption,
            )
        return sent.document.file_id if sent.document else None
    except TelegramError:
        logger.exception("reply_document فشل أيضاً من %s.", url)
        return None


async def _send_audio_file(
    update: Update,
    path: str,
    caption: str,
) -> str | None:
    """يرسل ملف MP3 كصوت. يُعيد file_id."""
    try:
        with open(path, "rb") as fh:
            sent: Message = await update.effective_message.reply_audio(
                audio=fh, caption=caption,
            )
        return sent.audio.file_id if sent.audio else None
    except TelegramError as exc:
        logger.warning("reply_audio فشل (%s)؛ أحاول document.", exc)

    try:
        with open(path, "rb") as fh:
            sent = await update.effective_message.reply_document(
                document=fh, caption=caption,
            )
        return sent.document.file_id if sent.document else None
    except TelegramError:
        logger.exception("reply_document (audio) فشل.")
        return None


def _check_size_and_raise(path: str) -> None:
    """يُرفع PaymentRequiredError إذا تجاوز الملف حد 50MB."""
    size = os.path.getsize(path)
    if size > _MAX_FILE_BYTES:
        raise PaymentRequiredError(size / (1024 * 1024), path)


# ──────────────────────────────────────────────────────────────────────────────
# منطق التحميل المشترك
# ──────────────────────────────────────────────────────────────────────────────

async def _execute_download(
    *,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    url: str,
    url_hash: str,
    media_type: str,   # "video" | "audio"
    status_msg: Message,
    bot_username: str,
    user_id: int,
) -> None:
    """
    ينفّذ دورة التحميل الكاملة:
      1. تحميل MP4
      2. تحويل إلى MP3 إذا طُلب
      3. فحص الحجم → PaymentRequiredError إذا تجاوز 50MB
      4. إرسال الملف + تخزين file_id في الكاش
    """
    cache_key = make_url_key(url, media_type)
    cache     = get_cache()

    # ── فحص الكاش أولاً ───────────────────────────────────────────────────────
    cached_id = await cache.get(cache_key)
    if cached_id:
        logger.info("كاش مُصاب [%s user=%d]: %.80s", media_type, user_id, url)
        try:
            caption = f"تم التحميل بواسطة @{bot_username} ⚡"
            if media_type == "video":
                await update.effective_message.reply_video(
                    video=cached_id, caption=caption, supports_streaming=True,
                )
            else:
                await update.effective_message.reply_audio(
                    audio=cached_id, caption=caption,
                )
            await get_stats().record_cache_hit()
            await status_msg.delete()
            return
        except TelegramError:
            await cache.delete(cache_key)
            logger.info("كاش منتهي الصلاحية — سيُعاد التحميل.")

    # ── تحميل MP4 ─────────────────────────────────────────────────────────────
    await get_stats().record_download_attempt(url)
    caption = f"تم التحميل بواسطة @{bot_username} ⚡"

    with tempfile.TemporaryDirectory(prefix=f"zendown-{uuid.uuid4().hex}-") as tmp_dir:
        try:
            file_paths = await fetch_videos(url, tmp_dir)

        except VideoTooLargeError:
            await get_stats().record_download_failed()
            await status_msg.edit_text(
                "⚠️ <b>الفيديو أكبر من الحد المسموح به للإرسال (50 ميجابايت).</b>\n"
                "جرب رابطاً بجودة أقل أو فيديو أقصر 🙏",
                parse_mode=ParseMode.HTML,
            )
            return

        except (DownloadError, DownloadFailedError) as exc:
            logger.warning("فشل التحميل [%s user=%d]: %s", url, user_id, exc)
            await get_stats().record_download_failed()
            await status_msg.edit_text(
                "❌ <b>تعذّر تحميل هذا الفيديو.</b>\n"
                "قد يكون الرابط خاصاً أو من منصة غير مدعومة. جرب رابطاً آخر 🙏",
                parse_mode=ParseMode.HTML,
            )
            return

        except Exception:
            logger.exception("خطأ غير متوقع أثناء التحميل [user=%d]", user_id)
            await get_stats().record_download_failed()
            await status_msg.edit_text(
                "❌ <b>حدث خطأ غير متوقع.</b> حاول مرة أخرى بعد قليل 🙏",
                parse_mode=ParseMode.HTML,
            )
            return

        # ── تصفية الملفات الموجودة ────────────────────────────────────────────
        file_paths = [p for p in (file_paths or []) if p and os.path.exists(p)]
        if not file_paths:
            await status_msg.edit_text(
                "❌ <b>لم أتمكن من العثور على ملف الفيديو.</b> جرب رابطاً آخر 🙏",
                parse_mode=ParseMode.HTML,
            )
            return

        # ── تحويل إلى MP3 إذا كان الطلب صوتاً ───────────────────────────────
        if media_type == "audio":
            await status_msg.edit_text(
                "🎵 <b>جاري استخراج الصوت وتحويله إلى MP3...</b> ⚡",
                parse_mode=ParseMode.HTML,
            )
            try:
                mp3_path = await convert_mp4_to_mp3(file_paths[0], tmp_dir)
                send_paths = [mp3_path]
            except AudioConversionError as exc:
                logger.error("فشل تحويل الصوت: %s", exc)
                await get_stats().record_download_failed()
                await status_msg.edit_text(
                    "❌ <b>فشل استخراج الصوت.</b> جرب رابطاً آخر 🙏",
                    parse_mode=ParseMode.HTML,
                )
                return
        else:
            send_paths = file_paths

        # ── فحص الحجم ─────────────────────────────────────────────────────────
        send_paths = [p for p in send_paths if os.path.exists(p)]
        if not send_paths:
            await status_msg.edit_text(
                "❌ <b>الملف غير موجود.</b> جرب رابطاً آخر 🙏",
                parse_mode=ParseMode.HTML,
            )
            return

        for path in send_paths:
            file_size_mb = os.path.getsize(path) / (1024 * 1024)
            if os.path.getsize(path) > _MAX_FILE_BYTES:
                # ── تجاوز الحجم: فحص الاشتراك ────────────────────────────────
                if not await has_active_subscription(user_id):
                    # تخزين مؤقت للملف حتى يتم الدفع
                    context.application.bot_data.setdefault("large_files", {})[url_hash] = {
                        "path":       path,
                        "media_type": media_type,
                        "url_hash":   url_hash,
                        "user_id":    user_id,
                        "size_mb":    file_size_mb,
                    }
                    await status_msg.edit_text(
                        ui.file_too_large_text(file_size_mb),
                        parse_mode=ParseMode.HTML,
                        reply_markup=ui.payment_markup(url_hash, media_type),
                    )
                    return
                # المستخدم لديه اشتراك — تجاوز الحد مسموح

        # ── إرسال الملفات ─────────────────────────────────────────────────────
        total      = len(send_paths)
        sent_count = 0
        file_id_to_cache = None

        await status_msg.edit_text(
            (
                f"<b>✅ تم التحميل بنجاح!</b> جاري الإرسال... 🚀"
            ),
            parse_mode=ParseMode.HTML,
        )

        for idx, path in enumerate(send_paths, 1):
            cap = (
                f"تم التحميل بواسطة @{bot_username} ⚡ ({idx}/{total})"
                if total > 1 else caption
            )
            if media_type == "video":
                file_id = await _send_video_file(update, path, cap, idx, total, url)
            else:
                file_id = await _send_audio_file(update, path, cap)

            if file_id:
                sent_count += 1
                if file_id_to_cache is None:
                    file_id_to_cache = file_id

        # ── تخزين في الكاش ────────────────────────────────────────────────────
        if file_id_to_cache:
            await cache.set(cache_key, file_id_to_cache)

        # ── إحصائيات ──────────────────────────────────────────────────────────
        if sent_count > 0:
            await get_stats().record_download_success()
            await get_stats().record_video_sent(sent_count)
        else:
            await get_stats().record_download_failed()
            await status_msg.edit_text(
                "❌ <b>تم تحميل الملف لكن تعذّر إرساله.</b> جرب رابطاً آخر 🙏",
                parse_mode=ParseMode.HTML,
            )
            return

        try:
            await status_msg.delete()
        except TelegramError:
            pass


# ──────────────────────────────────────────────────────────────────────────────
# معالجات اختيار نوع الوسائط
# ──────────────────────────────────────────────────────────────────────────────

async def _handle_media_download(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    media_type: str,
) -> None:
    """
    المعالج المشترك لتحميل الفيديو أو الصوت بعد ضغط الزر.
    يُشغَّل في سياق callback_query.
    """
    query   = update.callback_query
    await query.answer()  # إزالة مؤشر التحميل فوراً

    data     = query.data or ""
    parts    = data.split(":", 1)
    url_hash = parts[1] if len(parts) == 2 else ""

    user    = update.effective_user
    user_id = user.id if user else 0

    pending = _get_pending(context, url_hash)
    if not pending:
        await query.edit_message_text(
            "⏳ <b>انتهت صلاحية هذا الطلب.</b> أرسل الرابط مرة أخرى 🙏",
            parse_mode=ParseMode.HTML,
        )
        return

    url          = pending["url"]
    bot_username = await _get_bot_username(context)

    icon = "📺" if media_type == "video" else "🎧"
    status_msg = await query.edit_message_text(
        f"⏳ <b>{icon} جاري معالجة الرابط... انتظر لحظة!</b> ⚡",
        parse_mode=ParseMode.HTML,
    )

    queue = get_queue()
    try:
        async with queue.acquire(user_id):
            await _execute_download(
                update=update,
                context=context,
                url=url,
                url_hash=url_hash,
                media_type=media_type,
                status_msg=status_msg,
                bot_username=bot_username,
                user_id=user_id,
            )
    except UserBusyError:
        await status_msg.edit_text(
            "⏳ <b>لديك عملية تحميل جارية بالفعل!</b>\n"
            "انتظر حتى تنتهي ثم أعد الإرسال 🙏",
            parse_mode=ParseMode.HTML,
        )


async def download_video_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """معالج زر '📺 فيديو'."""
    await _handle_media_download(update, context, "video")


async def download_audio_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """معالج زر '🎧 موسيقى'."""
    await _handle_media_download(update, context, "audio")


# ──────────────────────────────────────────────────────────────────────────────
# معالجات الدفع (Telegram Stars)
# ──────────────────────────────────────────────────────────────────────────────

async def _handle_payment_button(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    plan: str,
) -> None:
    """يُرسل فاتورة Telegram Stars عند ضغط زر الدفع."""
    query = update.callback_query
    await query.answer()

    data  = query.data or ""
    parts = data.split(":")
    # صيغة: pay_{plan}:{hash}:{media_type_char}
    if len(parts) != 3:
        await query.answer("خطأ في بيانات الزر.", show_alert=True)
        return

    _, rest = data.split("_", 1)          # rest = "{plan}:{hash}:{type_char}"
    rest_parts = rest.split(":", 2)
    if len(rest_parts) != 3:
        await query.answer("خطأ في البيانات.", show_alert=True)
        return

    _, url_hash, media_char = rest_parts
    media_type = "video" if media_char == "v" else "audio"

    plan_info  = PLANS[plan]
    payload    = build_invoice_payload(url_hash, media_type, plan)   # type: ignore[arg-type]

    try:
        await context.bot.send_invoice(
            chat_id=update.effective_chat.id,
            title=f"ZenDown — {plan_info['title']}",
            description=plan_info["description"],
            payload=payload,
            currency="XTR",
            prices=[{"label": plan_info["title"], "amount": plan_info["price_xtr"]}],
        )
    except Exception as exc:
        logger.exception("فشل إرسال الفاتورة: %s", exc)
        await query.answer("تعذّر إنشاء الفاتورة. حاول مرة أخرى.", show_alert=True)


async def pay_once_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _handle_payment_button(update, context, "once")


async def pay_weekly_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _handle_payment_button(update, context, "weekly")


async def pay_monthly_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _handle_payment_button(update, context, "monthly")


async def pre_checkout_query_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    يُعالج طلب ما قبل الدفع — يجب الرد خلال 10 ثوانٍ.
    نوافق على جميع الطلبات الصالحة.
    """
    query = update.pre_checkout_query
    if not query:
        return

    parsed = parse_invoice_payload(query.invoice_payload)
    if not parsed:
        await query.answer(ok=False, error_message="بيانات الفاتورة غير صالحة.")
        return

    await query.answer(ok=True)
    logger.info(
        "pre_checkout_query موافق عليه: user=%d payload=%s",
        query.from_user.id, query.invoice_payload,
    )


async def successful_payment_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    يُعالج الدفع الناجح:
      1. يمنح الاشتراك
      2. يُنبّه المستخدم
      3. يُعيد تشغيل التحميل إن أمكن
    """
    payment = update.message.successful_payment
    if not payment:
        return

    user_id = update.effective_user.id
    payload = payment.invoice_payload

    parsed = parse_invoice_payload(payload)
    if not parsed:
        logger.error("دفع ناجح لكن payload غير صالح: %s", payload)
        return

    media_type, url_hash, plan = parsed

    # منح الاشتراك
    expires = await grant_subscription(user_id, plan)   # type: ignore[arg-type]

    import time
    remaining   = int(expires - time.time())
    days        = remaining // 86400
    hours       = (remaining % 86400) // 3600
    expires_str = f"{days} يوم و {hours} ساعة"

    await update.message.reply_text(
        ui.payment_success_text(plan, expires_str),
        parse_mode=ParseMode.HTML,
    )

    logger.info(
        "✅ دفع ناجح: user=%d plan=%s media=%s hash=%s",
        user_id, plan, media_type, url_hash,
    )

    # محاولة إعادة التحميل إن كان الرابط لا يزال موجوداً
    pending = _get_pending(context, url_hash)
    if not pending:
        await update.message.reply_text(
            "📎 أرسل الرابط مرة أخرى لتحميل الملف الكبير الآن! ⚡",
            parse_mode=ParseMode.HTML,
        )
        return

    url          = pending["url"]
    bot_username = await _get_bot_username(context)
    icon         = "📺" if media_type == "video" else "🎧"

    status_msg = await update.message.reply_text(
        f"⏳ <b>{icon} جاري تحميل الملف الآن...</b> ⚡",
        parse_mode=ParseMode.HTML,
    )

    queue = get_queue()
    try:
        async with queue.acquire(user_id):
            await _execute_download(
                update=update,
                context=context,
                url=url,
                url_hash=url_hash,
                media_type=media_type,
                status_msg=status_msg,
                bot_username=bot_username,
                user_id=user_id,
            )
    except UserBusyError:
        await status_msg.edit_text(
            "⏳ <b>لديك تحميل جارٍ بالفعل.</b> انتظر قليلاً ثم أرسل الرابط. 🙏",
            parse_mode=ParseMode.HTML,
        )


# ──────────────────────────────────────────────────────────────────────────────
# معالجات الأزرار الأخرى (غير مُعدَّلة)
# ──────────────────────────────────────────────────────────────────────────────

async def check_subscription_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """زر 'تحقق 🚬': يُعيد التحقق من الاشتراك في القناة."""
    query = update.callback_query
    await query.answer()

    user         = update.effective_user
    cfg          = await settings.load()
    bot_username = await _get_bot_username(context)

    if await is_subscribed(context.bot, cfg["channel"], user.id):
        user_name = user.first_name if user else "صديقي"
        await query.edit_message_text(
            ui.welcome_text(user_name),
            reply_markup=ui.welcome_markup(bot_username),
            parse_mode=ParseMode.HTML,
        )
        logger.info("المستخدم %d اجتاز فحص الاشتراك.", user.id if user else -1)
    else:
        await query.answer(
            "⛔ لم تشترك في القناة بعد! اضغط زر الاشتراك أولاً ثم تحقق مجدداً.",
            show_alert=True,
        )


async def share_bot_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """زر 'شارك البوت 🚀': يُسجّل النقرة ويُرسل رابط المشاركة."""
    query = update.callback_query
    await query.answer()

    bot_username = await _get_bot_username(context)
    await get_stats().record_share()

    await query.message.reply_text(
        "🔗 <b>شارك البوت مع أصدقائك!</b>\n\n"
        "اضغط الزر أدناه لمشاركة البوت مباشرة 👇",
        parse_mode=ParseMode.HTML,
        reply_markup=ui.share_link_markup(bot_username),
    )


async def refresh_stats_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """زر 'تحديث 🔄' في لوحة الإحصائيات: يُعيد رسم اللوحة (للمشرف فقط)."""
    query = update.callback_query
    user  = update.effective_user

    if not user or user.id != ADMIN_ID:
        await query.answer("⛔ هذا الزر للمشرف فقط.", show_alert=True)
        return

    await query.answer("🔄 جاري تحديث الإحصائيات...")
    data = await get_stats().snapshot()

    await query.edit_message_text(
        ui.stats_text(data),
        parse_mode=ParseMode.HTML,
        reply_markup=ui.stats_markup(),
    )
