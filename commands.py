"""
handlers/commands.py — معالجات أوامر تيليجرام لـ ZenDown Bot.

الأوامر:
  /start       — رسالة الترحيب مع فحص الاشتراك الإجباري
  /setchannel  — تعيين أو عرض قناة الاشتراك (للمشرف فقط)
  /forcejoin   — تفعيل/تعطيل بوابة الاشتراك الإجباري (للمشرف فقط)
  /stats       — لوحة الإحصائيات الكاملة (للمشرف فقط)
"""
from __future__ import annotations

import functools
import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import settings
import ui
from core.config import ADMIN_ID, BOT_USERNAME
from handlers.middleware import enforce_force_join, is_subscribed
from services.stats import get_stats

logger = logging.getLogger("zendown.handlers.commands")


def admin_only(func):
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ هذا الأمر متاح للمشرفين فقط.")
            return
        return await func(update, context)
    return wrapper


async def _get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    return (await context.bot.get_me()).username or BOT_USERNAME


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user      = update.effective_user
    user_name = user.first_name if user else "صديقي"
    cfg       = await settings.load()

    if user:
        await get_stats().record_user(user.id)

    if cfg["force_join"]:
        channel = cfg["channel"]
        if not await is_subscribed(context.bot, channel, user.id):
            bot_username = await _get_bot_username(context)
            await update.message.reply_text(
                ui.join_required_text(),
                parse_mode=ParseMode.HTML,
                reply_markup=ui.join_prompt_markup(channel, bot_username),
            )
            return

    bot_username = await _get_bot_username(context)
    await update.message.reply_text(
        ui.welcome_text(user_name),
        reply_markup=ui.welcome_markup(bot_username),
        parse_mode=ParseMode.HTML,
    )
    logger.info("المستخدم %d أرسل /start", user.id if user else -1)


@admin_only
async def setchannel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg  = await settings.load()
    args = context.args or []

    if not args:
        await update.message.reply_text(
            f"📢 القناة الحالية: <code>{cfg['channel']}</code>\n"
            "الاستخدام: <code>/setchannel @ChannelUsername</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    new_channel = args[0] if args[0].startswith("@") else f"@{args[0]}"
    cfg["channel"] = new_channel
    await settings.save(cfg)
    logger.info("المشرف %d غيّر القناة إلى %s", update.effective_user.id, new_channel)
    await update.message.reply_text(
        f"✅ تم تغيير القناة إلى: <code>{new_channel}</code>",
        parse_mode=ParseMode.HTML,
    )


@admin_only
async def forcejoin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg  = await settings.load()
    args = context.args or []

    if not args or args[0].lower() not in {"on", "off"}:
        status = "مفعّل ✅" if cfg["force_join"] else "معطّل ❌"
        await update.message.reply_text(
            f"🔒 الاشتراك الإجباري: {status}\n"
            "الاستخدام: <code>/forcejoin on</code> أو <code>/forcejoin off</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    cfg["force_join"] = args[0].lower() == "on"
    await settings.save(cfg)
    status = "مفعّل ✅" if cfg["force_join"] else "معطّل ❌"
    await update.message.reply_text(f"✅ الاشتراك الإجباري: {status}")


@admin_only
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _send_stats(update)


async def stats_keyword_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return
    await _send_stats(update)


async def _send_stats(update: Update) -> None:
    data = await get_stats().snapshot()
    await update.message.reply_text(
        ui.stats_text(data),
        parse_mode=ParseMode.HTML,
        reply_markup=ui.stats_markup(),
    )
