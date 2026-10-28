"""Event counters for traffic-style metrics (System-Monitoring-Dashboard 6.3).

Features call ``count("reviews.submitted")`` instead of writing to Redis. Names must be in
``EVENT_NAMES``, or be ``route_5xx:`` plus a route *template* (never a raw path, PF 26), so no
user value can end up in a counter name. Counts are held in memory per process and flushed every
``METRICS_FLUSH_SECONDS`` in one pipeline to ``abj:{env}:events:{YYYY-MM-DD}`` (TTL 8 days).
"""

import logging
import threading
from collections import Counter
from datetime import UTC, date, datetime

import redis

from app.config import get_settings
from app.destination_services import today_in_display_tz
from app.redis_client import get_redis, key

logger = logging.getLogger(__name__)

TTL_SECONDS = 8 * 86400
ROUTE_5XX_PREFIX = "route_5xx:"

EVENT_NAMES = frozenset(
    {
        "http.2xx",
        "http.3xx",
        "http.4xx",
        "http.5xx",
        "http.429",
        "challenge_failed",
        "visits.dropped",
        "reviews.submitted",
        "ops.auth_failed",
    }
)


class UnknownEvent(ValueError):
    pass


def _check(name: str) -> None:
    if name in EVENT_NAMES:
        return
    if name.startswith(ROUTE_5XX_PREFIX) and name[len(ROUTE_5XX_PREFIX) :].startswith("/"):
        return
    raise UnknownEvent(f"event name {name!r} is not in EVENT_NAMES")


_pending: Counter[str] = Counter()
_pending_lock = threading.Lock()
last_flush_at: datetime | None = None


def count(name: str, amount: int = 1) -> None:
    _check(name)
    with _pending_lock:
        _pending[name] += amount


def pending() -> dict[str, int]:
    with _pending_lock:
        return dict(_pending)


def events_key(day: date) -> str:
    return key("events", day.isoformat())


def flush(client: redis.Redis | None = None, *, day: date | None = None) -> bool:
    """Write the pending counts in one pipeline. On failure the counts are kept for the next try."""
    global last_flush_at  # noqa: PLW0603
    client = client if client is not None else get_redis()
    with _pending_lock:
        batch = dict(_pending)
        _pending.clear()
    if not batch:
        return True
    if client is None:
        _restore(batch)
        return False
    name = events_key(day or today_in_display_tz())
    try:
        pipe = client.pipeline(transaction=True)
        for event, amount in batch.items():
            pipe.hincrby(name, event, amount)
        pipe.expire(name, TTL_SECONDS)
        pipe.execute()
    except redis.RedisError:
        _restore(batch)
        logger.warning("event counters not flushed: Redis unavailable")
        return False
    last_flush_at = datetime.now(UTC)
    return True


def _restore(batch: dict[str, int]) -> None:
    with _pending_lock:
        _pending.update(batch)


def read_day(client: redis.Redis, day: date) -> dict[str, int]:
    values: dict[str, str] = client.hgetall(events_key(day))  # type: ignore[assignment]
    return {name: int(value) for name, value in values.items()}


class Flusher:
    """Background thread that flushes every ``METRICS_FLUSH_SECONDS`` (started by the app lifespan)."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None or get_redis() is None:
            return
        self._thread = threading.Thread(target=self._run, name="ops-event-flush", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        interval = get_settings().metrics_flush_seconds
        while not self._stop.wait(interval):
            flush()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            flush()
            self._thread = None
