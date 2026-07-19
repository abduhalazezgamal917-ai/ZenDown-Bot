"""
utils/retry.py — ديكوراتور إعادة المحاولة مع التراجع الأسّي (Exponential Backoff).
"""
from __future__ import annotations

import asyncio
import functools
import logging
import random
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar

logger = logging.getLogger("zendown.retry")
F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])

_NON_RETRIABLE: tuple[type[Exception], ...] = (KeyboardInterrupt, SystemExit, MemoryError)


def async_retry(
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: bool = True,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except _NON_RETRIABLE:
                    raise
                except exceptions as exc:
                    last_exc = exc
                    if attempt == max_attempts:
                        break
                    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
                    if jitter:
                        delay *= 0.75 + random.random() * 0.5
                    logger.warning(
                        "[%s] المحاولة %d/%d فشلت: %s — إعادة خلال %.2fs",
                        func.__qualname__, attempt, max_attempts, exc, delay,
                    )
                    await asyncio.sleep(delay)
            logger.error("[%s] فشلت جميع %d محاولات.", func.__qualname__, max_attempts)
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator
