"""
core/exceptions.py — جميع استثناءات ZenDown Bot المخصصة.

التسلسل الهرمي:
  ZenDownError
    ├── DownloadFailedError    — فشلت جميع استراتيجيات التحميل
    ├── VideoTooLargeError     — الفيديو يتجاوز حد 50 MB (مستخدم مجاني)
    ├── RateLimitExceededError — المستخدم تجاوز حد الطلبات
    ├── UserBusyError          — المستخدم لديه تحميل جارٍ بالفعل
    ├── InvalidURLError        — الرابط غير صالح أو غير آمن
    ├── AudioConversionError   — فشل تحويل MP4 → MP3
    └── PaymentRequiredError   — الملف يتجاوز 50MB ويتطلب اشتراكاً
"""
from __future__ import annotations


class ZenDownError(Exception):
    """الاستثناء الجذر — يُتيح اصطياد أي خطأ داخلي بسطر واحد."""


class DownloadFailedError(ZenDownError):
    """يُرفع عندما تفشل جميع استراتيجيات التحميل لرابط معين."""


class VideoTooLargeError(ZenDownError):
    """يُرفع عندما يتجاوز الفيديو حد الرفع (50 MB) الخاص بـ Telegram."""


class RateLimitExceededError(ZenDownError):
    """يُرفع عندما يتجاوز المستخدم حد الطلبات المسموح به في النافذة الزمنية."""


class UserBusyError(ZenDownError):
    """يُرفع عندما يكون المستخدم لديه عملية تحميل جارية بالفعل."""


class InvalidURLError(ZenDownError):
    """يُرفع عندما يكون الرابط المُدخَل غير صالح أو غير آمن."""


class AudioConversionError(ZenDownError):
    """يُرفع عندما يفشل تحويل ملف MP4 إلى MP3 عبر ffmpeg."""


class PaymentRequiredError(ZenDownError):
    """يُرفع عندما يتجاوز الملف 50MB ويتطلب اشتراكاً مدفوعاً."""

    def __init__(self, file_size_mb: float, file_path: str = "") -> None:
        self.file_size_mb = file_size_mb
        self.file_path = file_path
        super().__init__(
            f"الملف ({file_size_mb:.1f} MB) يتجاوز الحد المجاني ويتطلب اشتراكاً."
        )
