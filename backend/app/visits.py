"""Visit counting (Guest-Identity-and-Visits 4 and 5).

A visit is one visitor on one Asia/Dhaka day. "New" is the visitor's first ever counted day. Today
lives in the Redis hash ``abj:{env}:visits:{YYYY-MM-DD}``; finished days are rolled up into
``visit_daily_stats``. No guest identifier is written anywhere on the server.

Counting is best effort (D7): a Redis failure never reaches the client; it is counted in
``visits_dropped`` and shown on the ops dashboard.
"""

import logging
import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

import redis
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.destination_services import today_in_display_tz
from app.models import VisitDailyStats
from app.ops import events
from app.redis_client import key

logger = logging.getLogger(__name__)

FIELDS = ("guest_new", "guest_returning", "member_new", "member_returning")
TTL_SECONDS = 8 * 86400
ROLLUP_LOCK_SECONDS = 300
ROLLUP_LOOKBACK_DAYS = 7

VisitorKind = Literal["guest", "member"]


class _DropCounter:
    """In-process count of visits Redis did not accept (doc 4.6)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.value = 0

    def add(self) -> None:
        with self._lock:
            self.value += 1
        events.count("visits.dropped")


visits_dropped = _DropCounter()


def visits_key(day: date) -> str:
    return key("visits", day.isoformat())


def rollup_lock_key(day: date) -> str:
    return key("rollup-lock", day.isoformat())


def record_visit(client: redis.Redis | None, kind: VisitorKind, *, new: bool, day: date | None = None) -> bool:
    """Count one visit. Returns ``False`` (and counts a drop) instead of raising when Redis fails."""
    field = f"{kind}_{'new' if new else 'returning'}"
    name = visits_key(day or today_in_display_tz())
    if client is None:
        visits_dropped.add()
        logger.warning("visit not counted: REDIS_URL is not configured")
        return False
    try:
        pipe = client.pipeline(transaction=True)
        pipe.hincrby(name, field, 1)
        pipe.expire(name, TTL_SECONDS)
        pipe.execute()
    except redis.RedisError:
        visits_dropped.add()
        logger.warning("visit not counted: Redis unavailable")
        return False
    return True


@dataclass(frozen=True)
class DayCounts:
    guest_new: int = 0
    guest_returning: int = 0
    member_new: int = 0
    member_returning: int = 0

    @classmethod
    def from_hash(cls, values: dict[str, str]) -> "DayCounts":
        return cls(**{field: int(values.get(field, 0) or 0) for field in FIELDS})

    def __add__(self, other: "DayCounts") -> "DayCounts":
        return DayCounts(*(getattr(self, f) + getattr(other, f) for f in FIELDS))


@dataclass(frozen=True)
class Metrics:
    """The doc 5 metrics. Old visits = A - B holds by construction."""

    guest: int
    verified: int
    new_guest: int
    new_verified: int
    total_visits: int  # A
    new_visits: int  # B
    old_visits: int  # A - B


def metrics(counts: DayCounts) -> Metrics:
    guest = counts.guest_new + counts.guest_returning
    verified = counts.member_new + counts.member_returning
    total = guest + verified
    new = counts.guest_new + counts.member_new
    return Metrics(
        guest=guest,
        verified=verified,
        new_guest=counts.guest_new,
        new_verified=counts.member_new,
        total_visits=total,
        new_visits=new,
        old_visits=total - new,
    )


def read_day(client: redis.Redis, day: date) -> DayCounts | None:
    """The live counters for ``day``; ``None`` when no hash exists. Raises ``redis.RedisError``."""
    values: dict[str, str] = client.hgetall(visits_key(day))  # type: ignore[assignment]
    return DayCounts.from_hash(values) if values else None


def rollup(
    session: Session, client: redis.Redis, *, now: datetime | None = None, lookback: int = ROLLUP_LOOKBACK_DAYS
) -> list[date]:
    """Copy finished days from Redis into ``visit_daily_stats``. Idempotent; returns the days written.

    Absolute values are upserted, so running it twice gives the same row. A day whose hash is gone
    is skipped, never overwritten with zeros. A per-day lock stops two runs racing.
    """
    today = today_in_display_tz(now)
    written: list[date] = []
    for offset in range(lookback, 0, -1):
        day = today - timedelta(days=offset)
        if not client.set(rollup_lock_key(day), "1", nx=True, ex=ROLLUP_LOCK_SECONDS):
            continue
        try:
            counts = read_day(client, day)
            if counts is None:
                continue
            values = {field: getattr(counts, field) for field in FIELDS}
            statement = insert(VisitDailyStats).values(
                day=day, rolled_up_at=datetime.now(UTC), **values
            )
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=[VisitDailyStats.day],
                    set_={**values, "rolled_up_at": statement.excluded.rolled_up_at},
                )
            )
            session.commit()
            written.append(day)
        finally:
            client.delete(rollup_lock_key(day))
    return written


def stored_days(session: Session, first: date, last: date) -> dict[date, VisitDailyStats]:
    rows = session.scalars(
        select(VisitDailyStats).where(VisitDailyStats.day >= first, VisitDailyStats.day <= last)
    ).all()
    return {row.day: row for row in rows}


def record_member_visit(session: Session, user_id: uuid.UUID, today: date) -> bool | None:
    """Mark a member's visit day (doc 4.3). ``True`` new, ``False`` returning, ``None`` already counted.

    Called from ``GET /auth/session`` once member sign-in (R04) exists; Redis is only touched when
    this returns a value.
    """
    row = session.execute(
        text(
            "UPDATE users SET last_visit_on = :today, "
            "first_visit_on = COALESCE(first_visit_on, :today) "
            "WHERE id = :user_id AND last_visit_on IS DISTINCT FROM :today "
            "RETURNING first_visit_on = :today AS is_new"
        ),
        {"today": today, "user_id": user_id},
    ).first()
    return None if row is None else bool(row.is_new)
