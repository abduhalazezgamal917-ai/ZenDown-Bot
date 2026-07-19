"""
services/audio_service.py — خدمة تحويل الصوت لـ ZenDown Bot.

المسؤوليات:
  • تحويل ملفات MP4 → MP3 عبر ffmpeg (غير متزامن)
  • ضغط الصوت للحصول على حجم أصغر مع جودة مقبولة
  • التحقق من حجم الملف الناتج

التقنية:
  • asyncio.create_subprocess_exec — لا blocking I/O في event loop
  • معدل بت 128 kbps — جودة جيدة + حجم معقول
"""
from __future__ import annotations

import asyncio
import logging
import os

from core.exceptions import AudioConversionError

logger = logging.getLogger("zendown.audio_service")

# ── ثوابت ─────────────────────────────────────────────────────────────────────
_AUDIO_BITRATE: str = "128k"   # جودة جيدة مع حجم معقول
_SAMPLE_RATE: str   = "44100"  # معدل العينة (Hz)
_CHANNELS: str      = "2"      # ستيريو


async def convert_mp4_to_mp3(mp4_path: str, output_dir: str) -> str:
    """
    يُحوّل ملف MP4 إلى MP3 مضغوط باستخدام ffmpeg.

    المعاملات:
        mp4_path   — المسار الكامل لملف MP4 المصدر
        output_dir — المجلد الذي سيُحفظ فيه ملف MP3

    يُعيد:
        المسار الكامل لملف MP3 الناتج

    يُرفع:
        AudioConversionError — إذا فشل ffmpeg لأي سبب
        FileNotFoundError    — إذا لم يوجد ملف MP4 المصدر
    """
    if not os.path.exists(mp4_path):
        raise FileNotFoundError(f"ملف MP4 غير موجود: {mp4_path}")

    base_name = os.path.splitext(os.path.basename(mp4_path))[0]
    mp3_path  = os.path.join(output_dir, f"{base_name}.mp3")

    cmd = [
        "ffmpeg",
        "-i",         mp4_path,   # ملف المصدر
        "-vn",                     # بدون فيديو (صوت فقط)
        "-ar",        _SAMPLE_RATE,
        "-ac",        _CHANNELS,
        "-b:a",       _AUDIO_BITRATE,
        "-map_metadata", "0",      # نسخ البيانات الوصفية
        "-id3v2_version", "3",     # نسخة ID3 متوافقة
        "-y",                      # استبدال الملف إن وُجد
        mp3_path,
    ]

    logger.info(
        "تحويل MP4→MP3: %s → %s (bitrate=%s)",
        os.path.basename(mp4_path), os.path.basename(mp3_path), _AUDIO_BITRATE,
    )

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace").strip()[-300:]  # آخر 300 حرف
            logger.error("ffmpeg فشل (code=%d): %s", proc.returncode, err_msg)
            raise AudioConversionError(
                f"فشل تحويل الصوت (exit={proc.returncode}): {err_msg}"
            )

        if not os.path.exists(mp3_path) or os.path.getsize(mp3_path) == 0:
            raise AudioConversionError("ffmpeg أنتج ملفاً فارغاً أو غائباً")

        mp3_size_mb = os.path.getsize(mp3_path) / (1024 * 1024)
        logger.info(
            "✅ تم التحويل بنجاح: %s (%.2f MB)",
            os.path.basename(mp3_path), mp3_size_mb,
        )
        return mp3_path

    except AudioConversionError:
        raise
    except Exception as exc:
        raise AudioConversionError(f"خطأ غير متوقع أثناء التحويل: {exc}") from exc


def get_file_size_mb(path: str) -> float:
    """يُعيد حجم الملف بالميجابايت."""
    return os.path.getsize(path) / (1024 * 1024)
