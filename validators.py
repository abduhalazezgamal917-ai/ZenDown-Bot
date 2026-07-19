"""
utils/validators.py — التحقق من صحة وتعقيم مدخلات المستخدم.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

_MAX_URL_LENGTH = 2048
_ALLOWED_SCHEMES = frozenset({"http", "https"})

_BLOCKED_HOSTS = re.compile(
    r"^(localhost|127\.\d+\.\d+\.\d+|0\.0\.0\.0"
    r"|10\.\d+\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+"
    r"|192\.168\.\d+\.\d+|::1|0:0:0:0:0:0:0:1)$",
    re.IGNORECASE,
)


def validate_url(raw: str) -> tuple[bool, str]:
    """
    يتحقق من صحة الرابط ويُعيد (True, sanitized_url) أو (False, "").
    يمنع SSRF ويُزيل الأحرف الخطرة.
    """
    url = raw.strip()
    if not url or len(url) > _MAX_URL_LENGTH:
        return False, ""
    if "\x00" in url or "\r" in url or "\n" in url:
        return False, ""
    try:
        parsed = urlparse(url)
    except Exception:
        return False, ""
    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False, ""
    host = parsed.hostname or ""
    if not host or len(host) > 253:
        return False, ""
    if _BLOCKED_HOSTS.match(host):
        return False, ""
    sanitized = urlunparse((
        parsed.scheme, parsed.netloc, parsed.path,
        parsed.params, parsed.query, "",
    ))
    return True, sanitized


def is_safe_url(raw: str) -> bool:
    valid, _ = validate_url(raw)
    return valid
