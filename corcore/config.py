"""
core/config.py — إعدادات ZenDown Bot المُحمَّلة من متغيرات البيئة.

الأولوية: متغير البيئة (Replit Secret) → القيمة المُضمَّنة (للانتقال فقط).
للإنتاج الكامل: احذف القيم المُضمَّنة واستخدم Replit Secrets حصراً.
"""
from __future__ import annotations

import os
import re

# ── بيانات البوت ──────────────────────────────────────────────────────────────
BOT_TOKEN: str    = os.environ.get("BOT_TOKEN", "8835267124:AAEpX8FR4CqIZzpiagU-pLcSZsioaGA49xw")
ADMIN_ID: int     = int(os.environ.get("ADMIN_ID", "6043858925"))
BOT_USERNAME: str = os.environ.get("BOT_USERNAME", "ZenDown_bot")

# ── حدود الأداء ───────────────────────────────────────────────────────────────
MAX_UPLOAD_BYTES: int          = int(os.environ.get("MAX_UPLOAD_BYTES",          "52428800"))  # 50 MB
MAX_CONCURRENT_DOWNLOADS: int  = int(os.environ.get("MAX_CONCURRENT_DOWNLOADS",  "10"))
MAX_CONCURRENT_PER_USER: int   = int(os.environ.get("MAX_CONCURRENT_PER_USER",   "1"))

# ── Rate Limiting ─────────────────────────────────────────────────────────────
RATE_LIMIT_REQUESTS: int = int(os.environ.get("RATE_LIMIT_REQUESTS", "5"))
RATE_LIMIT_WINDOW: int   = int(os.environ.get("RATE_LIMIT_WINDOW",   "60"))

# ── Cache ─────────────────────────────────────────────────────────────────────
CACHE_TTL: int = int(os.environ.get("CACHE_TTL", "3600"))

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()

# ── خادم الصحة (Uptime) ───────────────────────────────────────────────────────
# على Koyeb يُوفَّر $PORT تلقائياً — نستخدمه إن وُجد، وإلا نرجع لـ 8090
HEALTH_PORT: int = int(os.environ.get("PORT", os.environ.get("HEALTH_PORT", "8090")))

# ── نظام الدفع — Telegram Stars (XTR) ────────────────────────────────────────
# 1 XTR ≈ 0.013 USD (حسب سعر تيليجرام)
# تسعير تنافسي ومنطقي ومتدرج:
PRICE_ONE_TIME_XTR: int  = 75   # تحميل واحد  ≈ 0.98 USD  — رخيص جداً ومتاح للجميع
PRICE_WEEKLY_XTR: int    = 200  # اشتراك أسبوعي ≈ 2.60 USD — قيمة جيدة للمستخدم المنتظم
PRICE_MONTHLY_XTR: int   = 500  # اشتراك شهري   ≈ 6.50 USD — أفضل قيمة (وفر ~37% مقارنة بالأسبوعي)

# مدة الاشتراك (بالثواني)
DURATION_ONE_TIME_SECS: int = 86_400       # 24 ساعة للتحميل الواحد
DURATION_WEEKLY_SECS: int   = 7 * 86_400   # 7 أيام
DURATION_MONTHLY_SECS: int  = 30 * 86_400  # 30 يوم

# ── روابط APIs الخارجية ───────────────────────────────────────────────────────
TIKWM_API_URL: str       = "https://www.tikwm.com/api/"
VXTWITTER_API_HOST: str  = "api.vxtwitter.com"
FASTDL_API_URL: str      = "https://fastdl.to/api/ajaxSearch"
SNAPSAVE_API_URL: str    = "https://snapsave.app/action.php"

# ── User-Agents ───────────────────────────────────────────────────────────────
UA_TIKTOK_MOBILE: str = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1"
)
UA_DESKTOP: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# ── نطاقات المنصات ────────────────────────────────────────────────────────────
TIKTOK_SHORT_LINK_HOSTS: frozenset[str] = frozenset({"vm.tiktok.com", "vt.tiktok.com"})

TWITTER_HOSTS: frozenset[str] = frozenset({
    "twitter.com", "www.twitter.com",
    "x.com", "www.x.com",
    "mobile.twitter.com",
})

INSTAGRAM_HOSTS: frozenset[str] = frozenset({
    "instagram.com", "www.instagram.com", "m.instagram.com",
})

SNAPCHAT_HOSTS: frozenset[str] = frozenset({
    "snapchat.com", "www.snapchat.com", "story.snapchat.com",
    "t.snapchat.com", "m.snapchat.com",
})

# ── ترويسات HTTP لكل خدمة ────────────────────────────────────────────────────
FASTDL_HEADERS: dict[str, str] = {
    "User-Agent": UA_DESKTOP,
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://fastdl.to",
    "Referer": "https://fastdl.to/en",
}

SNAPSAVE_HEADERS: dict[str, str] = {
    "User-Agent": UA_DESKTOP,
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://snapsave.app/",
    "Origin": "https://snapsave.app",
    "X-Requested-With": "XMLHttpRequest",
}

# ── أنماط Regex ───────────────────────────────────────────────────────────────
URL_PATTERN: re.Pattern = re.compile(r"https?://\S+")

FASTDL_VIDEO_LINK_PATTERN: re.Pattern = re.compile(
    r'<a href="([^"]+)"[^>]*title="Download( HD)? Video"'
)
INSTAGRAM_SHORTCODE_PATTERN: re.Pattern = re.compile(
    r"/(p|reel|reels|tv)/([A-Za-z0-9_-]+)"
)
SNAPSAVE_VIDEO_PATTERN: re.Pattern = re.compile(
    r'href="(https://[^"]+\.mp4[^"]*)"[^>]*>(?:Download|HD Download)',
    re.IGNORECASE,
)
SNAPSAVE_FALLBACK_PATTERN: re.Pattern = re.compile(
    r'href="(https://[^"]+\.mp4[^"]*)"',
    re.IGNORECASE,
)

# ── حالات العضوية المقبولة في تيليجرام ───────────────────────────────────────
VALID_MEMBER_STATUSES: frozenset[str] = frozenset({
    "member", "creator", "administrator",
})

# ── حد زمني لطلبات HTTP (بالثواني) ───────────────────────────────────────────
HTTP_TIMEOUT: int = 30
HTTP_DOWNLOAD_TIMEOUT: int = 120

# ── إعدادات خادم الصحة ────────────────────────────────────────────────────────
BOT_START_TIME: float = 0.0  # يُضبط في bot.py عند بدء التشغيل

