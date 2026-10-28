"""The one Redis connection for visit counters and ops event counters (Guest-Identity-and-Visits 2, 4.4).

Every key starts with ``abj:{APP_ENV}:`` so development, staging and production never mix, even
on a shared database. Nothing written through this module may identify a person.
"""

import threading
from typing import Annotated

import redis
from fastapi import Depends

from app.config import get_settings

_client: redis.Redis | None = None
_client_url: str | None = None
_lock = threading.Lock()


def get_redis() -> redis.Redis | None:
    """Return the shared client, or ``None`` when ``REDIS_URL`` is not configured."""
    global _client, _client_url  # noqa: PLW0603
    settings = get_settings()
    if not settings.redis_url:
        return None
    with _lock:
        if _client is None or _client_url != settings.redis_url:
            timeout = settings.redis_timeout_ms / 1000
            _client = redis.Redis.from_url(
                settings.redis_url,
                socket_timeout=timeout,
                socket_connect_timeout=timeout,
                decode_responses=True,
            )
            _client_url = settings.redis_url
        return _client


RedisDep = Annotated[redis.Redis | None, Depends(get_redis)]


def key(*parts: str) -> str:
    return ":".join(("abj", get_settings().app_env, *parts))
