"""
services/payment_service.py — خدمة الدفع عبر Telegram Stars لـ ZenDown Bot.

المسؤوليات:
  • التحقق من اشتراك المستخدم (مجاني / مدفوع)
  • منح الاشتراك بعد الدفع الناجح
  • حفظ بيانات الاشتراك بشكل دائم (JSON)
  • إنشاء فواتير Telegram Stars

نظام التسعير (Telegram Stars / XTR):
  • تحميل واحد : 75 XTR  ≈ 0.98 USD  — رخيص ومتاح
  • أسبوعي      : 200 XTR ≈ 2.60 USD  — قيمة جيدة
  • شهري         : 500 XTR ≈ 6.50 USD  — أفضل قيمة (وفر 37%)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Literal

from core.config import (
    DURATION_MONTHLY_SECS,
    DURATION_ONE_TIME_SECS,
    DURATION_WEEKLY_SECS,
    PRICE_MONTHLY_XTR,
    PRICE_ONE_TIME_XTR,
    PRICE_WEEKLY_XTR,
)

logger = logging.getLogger("zendown.payment_service")

_SUBS_FILE = "subscriptions.json"
_lock      = asyncio.Lock()

PlanType = Literal["once", "weekly", "monthly"]


# ──────────────────────────────────────────────────────────────────────────────
# ثوابت الخطط — مرجع مركزي
# ──────────────────────────────────────────────────────────────────────────────

PLANS: dict[PlanType, dict] = {
    "once": {
        "price_xtr":  PRICE_ONE_TIME_XTR,
        "duration":   DURATION_ONE_TIME_SECS,
        "title":      "تحميل واحد",
        "description": f"تحميل ملف كبير مرة واحدة ({PRICE_ONE_TIME_XTR} ⭐)",
    },
    "weekly": {
        "price_xtr":  PRICE_WEEKLY_XTR,
        "duration":   DURATION_WEEKLY_SECS,
        "title":      "اشتراك أسبوعي",
        "description": f"تحميل غير محدود لمدة 7 أيام ({PRICE_WEEKLY_XTR} ⭐)",
    },
    "monthly": {
        "price_xtr":  PRICE_MONTHLY_XTR,
        "duration":   DURATION_MONTHLY_SECS,
        "title":      "اشتراك شهري",
        "description": f"تحميل غير محدود لمدة 30 يوماً ({PRICE_MONTHLY_XTR} ⭐) — الأوفر",
    },
}


# ──────────────────────────────────────────────────────────────────────────────
# التحميل / الحفظ
# ──────────────────────────────────────────────────────────────────────────────

def _load_subs_sync() -> dict[str, dict]:
    if not os.path.exists(_SUBS_FILE):
        return {}
    try:
        with open(_SUBS_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as exc:
        logger.warning("فشل تحميل الاشتراكات: %s", exc)
        return {}


def _save_subs_sync(data: dict) -> None:
    tmp = _SUBS_FILE + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, _SUBS_FILE)
    except OSError as exc:
        logger.error("فشل حفظ الاشتراكات: %s", exc)
        if os.path.exists(tmp):
            os.remove(tmp)


# ──────────────────────────────────────────────────────────────────────────────
# الواجهة العامة
# ──────────────────────────────────────────────────────────────────────────────

async def has_active_subscription(user_id: int) -> bool:
    """يتحقق مما إذا كان المستخدم لديه اشتراك نشط."""
    async with _lock:
        subs = await asyncio.to_thread(_load_subs_sync)
        entry = subs.get(str(user_id))
        if not entry:
            return False
        expires = entry.get("expires", 0)
        return time.time() < expires


async def grant_subscription(user_id: int, plan: PlanType) -> float:
    """
    يمنح المستخدم اشتراكاً من نوع *plan*.
    يُعيد وقت انتهاء الاشتراك (Unix timestamp).
    """
    duration = PLANS[plan]["duration"]
    expires  = time.time() + duration

    async with _lock:
        subs = await asyncio.to_thread(_load_subs_sync)
        subs[str(user_id)] = {
            "plan":       plan,
            "expires":    expires,
            "granted_at": time.time(),
        }
        await asyncio.to_thread(_save_subs_sync, subs)

    logger.info(
        "✅ اشتراك ممنوح: user=%d plan=%s expires=%.0f",
        user_id, plan, expires,
    )
    return expires


async def get_subscription_info(user_id: int) -> dict | None:
    """يُعيد معلومات الاشتراك الحالي أو None إذا لم يوجد."""
    async with _lock:
        subs = await asyncio.to_thread(_load_subs_sync)
        entry = subs.get(str(user_id))
        if not entry:
            return None
        if time.time() >= entry.get("expires", 0):
            return None
        remaining = int(entry["expires"] - time.time())
        return {
            "plan":      entry["plan"],
            "expires":   entry["expires"],
            "remaining": remaining,
        }


def build_invoice_payload(url_hash: str, media_type: str, plan: PlanType) -> str:
    """
    يبني حمولة الفاتورة (≤128 بايت).
    الصيغة: "{media_type_char}:{url_hash16}:{plan}"
    مثال:   "v:abc123def456789a:once"
    """
    media_char = "v" if media_type == "video" else "a"
    return f"{media_char}:{url_hash}:{plan}"


def parse_invoice_payload(payload: str) -> tuple[str, str, PlanType] | None:
    """
    يُحلّل حمولة الفاتورة.
    يُعيد (media_type, url_hash, plan) أو None إذا كانت غير صالحة.
    """
    try:
        parts = payload.split(":", 2)
        if len(parts) != 3:
            return None
        media_char, url_hash, plan = parts
        media_type = "video" if media_char == "v" else "audio"
        if plan not in PLANS:
            return None
        return media_type, url_hash, plan  # type: ignore[return-value]
    except Exception:
        return None
