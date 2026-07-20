"""
services/download_service.py — خدمة التحميل غير المتزامنة لـ ZenDown Bot.

سلسلة الاحتياط لكل منصة:
  TikTok    → tikwm API    → yt-dlp
  Twitter/X → vxtwitter API → yt-dlp
  Instagram → fastdl.to API → yt-dlp
  Snapchat  → yt-dlp        → snapsave.app
  أخرى     → yt-dlp (مباشرة)

نقطة الدخول: await fetch_videos(url, dest_dir) → list[str]
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from urllib.parse import urlparse

import aiohttp
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError  # noqa: F401

from core.config import (
    FASTDL_API_URL,
    FASTDL_HEADERS,
    FASTDL_VIDEO_LINK_PATTERN,
    HTTP_DOWNLOAD_TIMEOUT,
    HTTP_TIMEOUT,
    INSTAGRAM_HOSTS,
    INSTAGRAM_SHORTCODE_PATTERN,
    MAX_UPLOAD_BYTES,
    SNAPCHAT_HOSTS,
    SNAPSAVE_API_URL,
    SNAPSAVE_FALLBACK_PATTERN,
    SNAPSAVE_HEADERS,
    SNAPSAVE_VIDEO_PATTERN,
    TIKWM_API_URL,
    TIKTOK_SHORT_LINK_HOSTS,
    TWITTER_HOSTS,
    UA_DESKTOP,
    UA_TIKTOK_MOBILE,
    VXTWITTER_API_HOST,
)
from core.exceptions import DownloadFailedError, VideoTooLargeError
from utils.retry import async_retry

logger = logging.getLogger("zendown.download_service")

_session: aiohttp.ClientSession | None = None


def _make_timeout(total: int = HTTP_TIMEOUT) -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(total=total, connect=10, sock_read=total)


async def init_http_session() -> None:
    global _session
    connector = aiohttp.TCPConnector(
        limit=100, ttl_dns_cache=300, enable_cleanup_closed=True,
    )
    _session = aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": UA_DESKTOP},
        timeout=_make_timeout(),
    )
    logger.info("تم تهيئة HTTP session المشتركة.")


async def close_http_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
        _session = None
        logger.info("تم إغلاق HTTP session.")


def _get_session() -> aiohttp.ClientSession:
    if _session is None or _session.closed:
        raise RuntimeError("HTTP session غير مهيّأة — استدعِ init_http_session() أولاً")
    return _session


_YTDLP_BASE_OPTS: dict = {
    "format": (
        f"best[filesize<{MAX_UPLOAD_BYTES}]/"
        f"bestvideo[filesize<{MAX_UPLOAD_BYTES}]+bestaudio/best"
    ),
    "noplaylist":          True,
    "quiet":               True,
    "no_warnings":         True,
    "merge_output_format": "mp4",
    "restrictfilenames":   True,
    "max_filesize":        MAX_UPLOAD_BYTES,
}


async def _stream_to_file(
    video_url: str,
    dest_path: str,
    *,
    headers: dict | None = None,
    timeout: int = HTTP_DOWNLOAD_TIMEOUT,
) -> None:
    session     = _get_session()
    req_headers = {**(headers or {})}
    async with session.get(
        video_url, headers=req_headers,
        timeout=_make_timeout(timeout), allow_redirects=True,
    ) as resp:
        resp.raise_for_status()
        downloaded = 0
        loop = asyncio.get_event_loop()
        with open(dest_path, "wb") as fh:
            async for chunk in resp.content.iter_chunked(1024 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > MAX_UPLOAD_BYTES:
                    raise VideoTooLargeError("الفيديو يتجاوز حد الإرسال (50 MB)")
                await loop.run_in_executor(None, fh.write, chunk)


async def _download_multi(
    video_urls: list[str],
    dest_dir: str,
    filename_stem: str,
    *,
    headers: dict | None = None,
) -> list[str]:
    async def _try_one(idx: int, url: str) -> str | None:
        suffix = f"_{idx}" if len(video_urls) > 1 else ""
        dest   = os.path.join(dest_dir, f"{filename_stem}{suffix}.mp4")
        try:
            await _stream_to_file(url, dest, headers=headers)
            return dest
        except VideoTooLargeError:
            logger.warning("تخطّيت %s — يتجاوز حد الرفع.", url)
            return None
        except Exception as exc:
            logger.warning("فشل تحميل %s: %s", url, exc)
            return None

    results = await asyncio.gather(*[_try_one(i, u) for i, u in enumerate(video_urls)])
    paths   = [p for p in results if p is not None]

    if not paths:
        if all(r is None for r in results):
            raise DownloadFailedError("فشل تحميل أي فيديو من الروابط المتاحة")
        raise VideoTooLargeError("جميع الفيديوهات تتجاوز الحد المسموح به (50 MB)")

    return paths


async def _ytdlp_download(
    url: str,
    dest_dir: str,
    *,
    extra_opts: dict | None = None,
) -> str:
    opts = {
        **_YTDLP_BASE_OPTS,
        "outtmpl": os.path.join(dest_dir, "%(id)s.%(ext)s"),
    }
    if extra_opts:
        opts.update(extra_opts)

    def _run_sync() -> str:
        with YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info and "entries" in info:
                info = info["entries"][0]
            return ydl.prepare_filename(info)

    return await asyncio.to_thread(_run_sync)


# ── TikTok ────────────────────────────────────────────────────────────────────

async def _resolve_tiktok_short_url(url: str) -> str:
    if urlparse(url).netloc.lower() not in TIKTOK_SHORT_LINK_HOSTS:
        return url
    try:
        session = _get_session()
        async with session.get(
            url, headers={"User-Agent": UA_TIKTOK_MOBILE},
            allow_redirects=False, timeout=_make_timeout(10),
        ) as resp:
            location = resp.headers.get("Location", url)
            if "tiktok.com" in location and "/video/" in location:
                return location
    except Exception as exc:
        logger.warning("تعذّر حل رابط TikTok القصير %s: %s", url, exc)
    return url


@async_retry(max_attempts=3, base_delay=1.0, exceptions=(aiohttp.ClientError,))
async def _tiktok_via_tikwm(url: str, dest_dir: str) -> list[str]:
    resolved = await _resolve_tiktok_short_url(url)
    session  = _get_session()
    async with session.get(
        TIKWM_API_URL, params={"url": resolved, "hd": 1},
        headers={"User-Agent": UA_TIKTOK_MOBILE}, timeout=_make_timeout(20),
    ) as resp:
        resp.raise_for_status()
        payload = await resp.json(content_type=None)
    if payload.get("code") != 0:
        raise DownloadFailedError(f"tikwm رفض الرابط: {payload.get('msg')}")
    data      = payload.get("data") or {}
    video_url = data.get("hdplay") or data.get("play")
    if not video_url:
        raise DownloadFailedError("tikwm لم يُرجع رابط فيديو")
    video_id  = data.get("id") or uuid.uuid4().hex
    dest_path = os.path.join(dest_dir, f"{video_id}.mp4")
    await _stream_to_file(video_url, dest_path, headers={"User-Agent": UA_TIKTOK_MOBILE})
    return [dest_path]


async def _tiktok(url: str, dest_dir: str) -> list[str]:
    try:
        return await _tiktok_via_tikwm(url, dest_dir)
    except VideoTooLargeError:
        raise
    except Exception as exc:
        logger.warning("tikwm فشل (%s)؛ أحاول yt-dlp", exc)
    resolved = await _resolve_tiktok_short_url(url)
    return [await _ytdlp_download(
        resolved, dest_dir,
        extra_opts={"http_headers": {"User-Agent": UA_TIKTOK_MOBILE}},
    )]


# ── Twitter / X ───────────────────────────────────────────────────────────────

@async_retry(max_attempts=3, base_delay=1.0, exceptions=(aiohttp.ClientError,))
async def _twitter_via_vxtwitter(url: str, dest_dir: str) -> list[str]:
    path    = urlparse(url).path.strip("/")
    session = _get_session()
    async with session.get(
        f"https://{VXTWITTER_API_HOST}/{path}", timeout=_make_timeout(20),
    ) as resp:
        resp.raise_for_status()
        payload = await resp.json(content_type=None)
    if payload.get("error"):
        raise DownloadFailedError(f"vxtwitter: {payload['error']}")
    tweet_id   = payload.get("tweetID") or uuid.uuid4().hex
    video_urls = [
        m["url"]
        for m in (payload.get("media_extended") or [])
        if m.get("type") in ("video", "gif") and m.get("url")
    ]
    if not video_urls:
        video_urls = [
            u for u in (payload.get("mediaURLs") or [])
            if u.lower().endswith((".mp4", ".m3u8"))
        ]
    if not video_urls:
        raise DownloadFailedError("vxtwitter لم يجد فيديو في هذه التغريدة")
    return await _download_multi(video_urls, dest_dir, tweet_id)


async def _twitter(url: str, dest_dir: str) -> list[str]:
    try:
        return await _twitter_via_vxtwitter(url, dest_dir)
    except VideoTooLargeError:
        raise
    except Exception as exc:
        logger.warning("vxtwitter فشل (%s)؛ أحاول yt-dlp", exc)
    return [await _ytdlp_download(url, dest_dir)]


# ── Instagram ─────────────────────────────────────────────────────────────────

@async_retry(max_attempts=3, base_delay=1.5, exceptions=(aiohttp.ClientError,))
async def _instagram_via_fastdl(url: str, dest_dir: str) -> list[str]:
    match      = INSTAGRAM_SHORTCODE_PATTERN.search(urlparse(url).path)
    normalized = (
        f"https://www.instagram.com/{match.group(1)}/{match.group(2)}/"
        if match else url
    )
    session = _get_session()
    async with session.post(
        FASTDL_API_URL, data={"q": normalized},
        headers=FASTDL_HEADERS, timeout=_make_timeout(20),
    ) as resp:
        resp.raise_for_status()
        payload = await resp.json(content_type=None)
    if payload.get("status") != "ok" or payload.get("p") != "instagram":
        raise DownloadFailedError(f"fastdl.to رفض الرابط: {payload.get('mess', '?')}")
    html       = payload.get("data") or ""
    video_urls = [m.group(1) for m in FASTDL_VIDEO_LINK_PATTERN.finditer(html)]
    if not video_urls:
        raise DownloadFailedError("fastdl.to لم يجد فيديو لهذا الرابط")
    post_id = uuid.uuid4().hex
    return await _download_multi(video_urls, dest_dir, f"instagram_{post_id}")


async def _instagram(url: str, dest_dir: str) -> list[str]:
    try:
        return await _instagram_via_fastdl(url, dest_dir)
    except VideoTooLargeError:
        raise
    except Exception as exc:
        logger.warning("fastdl.to فشل (%s)؛ أحاول yt-dlp", exc)
    return [await _ytdlp_download(url, dest_dir)]


# ── Snapchat ──────────────────────────────────────────────────────────────────

@async_retry(max_attempts=2, base_delay=1.0, exceptions=(aiohttp.ClientError,))
async def _snapchat_via_snapsave(url: str, dest_dir: str) -> str:
    session = _get_session()
    async with session.post(
        SNAPSAVE_API_URL, data={"url": url},
        headers=SNAPSAVE_HEADERS, timeout=_make_timeout(25),
    ) as resp:
        resp.raise_for_status()
        payload = await resp.json(content_type=None)
    html    = payload.get("data") or ""
    matches = SNAPSAVE_VIDEO_PATTERN.findall(html) or SNAPSAVE_FALLBACK_PATTERN.findall(html)
    if not matches:
        raise DownloadFailedError("snapsave لم يجد فيديو في هذا الرابط")
    dest_path = os.path.join(dest_dir, f"snapchat_{uuid.uuid4().hex}.mp4")
    await _stream_to_file(matches[0], dest_path)
    return dest_path


async def _snapchat(url: str, dest_dir: str) -> list[str]:
    try:
        path = await _ytdlp_download(
            url, dest_dir,
            extra_opts={"http_headers": {"User-Agent": UA_DESKTOP, "Accept-Language": "en-US,en;q=0.9"}},
        )
        if path and os.path.exists(path):
            return [path]
    except VideoTooLargeError:
        raise
    except Exception as exc:
        logger.warning("yt-dlp فشل لـ Snapchat (%s)؛ أحاول snapsave", exc)
    return [await _snapchat_via_snapsave(url, dest_dir)]


# ── نقطة الدخول العامة ────────────────────────────────────────────────────────

async def fetch_videos(url: str, dest_dir: str) -> list[str]:
    """
    يُوجّه الرابط إلى استراتيجية التحميل الصحيحة.
    يُعيد قائمة مسارات MP4 المحلية.
    """
    host = urlparse(url).netloc.lower()
    logger.info("بدء تحميل: host=%s url=%.80s", host, url)

    if "tiktok.com" in host:
        return await _tiktok(url, dest_dir)
    if host in TWITTER_HOSTS:
        return await _twitter(url, dest_dir)
    if host in INSTAGRAM_HOSTS:
        return await _instagram(url, dest_dir)
    if host in SNAPCHAT_HOSTS:
        return await _snapchat(url, dest_dir)

    # الاحتياط العام: YouTube، Pinterest، وغيرها
    return [await _ytdlp_download(url, dest_dir)]
