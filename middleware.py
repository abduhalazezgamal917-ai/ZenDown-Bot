"""
handlers/middleware.py — وظائف Middleware المشتركة بين جميع المعالجات.
"""
from __future__ import annotations

import logging

from telegram import Bot, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import settings
import ui
from core.config import BOT_USERNAME, VALID_MEMBER_STATUSES

logger = logging.getLogger("zendown.handlers.middleware")


async def is_subscribed(bot: Bot, channel: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
        return member.status in VALID_MEMBER_STATUSES
    except Exception as exc:
        logger.warning("تعذّر فحص العضوية في %s للمستخدم %d: %s", channel, user_id, exc)
        return True  # fail-open


async def _get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    return (await context.bot.get_me()).username or BOT_USERNAME


async def enforce_force_join(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    cfg = await settings.load()
    if not cfg["force_join"]:
        return True

    channel = cfg["channel"]
    if await is_subscribed(context.bot, channel, update.effective_user.id):
        return True

    bot_username = await _get_bot_username(context)
    await update.message.reply_text(
        ui.join_required_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=ui.join_prompt_markup(channel, bot_username),
    )
    return False
