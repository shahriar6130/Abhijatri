"""Durable abuse controls for unauthenticated Guest endpoints (Platform Foundation 14.3 to 14.6).

Counters live in ``rate_limit_buckets`` keyed by (rule, key digest, fixed window). Each
increment commits in its own database transaction *before* the business operation runs, so a
later validation failure or rollback never erases the attempt (14.5). Keys are keyed digests;
the raw address, scope secret and receipt never reach the database.
"""

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import crypto
from app.config import Settings, get_settings
from app.db import SessionLocal
from app.errors import ApiError
from app.models import RateLimitBucket, Review, ReviewStatus

logger = logging.getLogger(__name__)

HOUR = 3600
DAY = 86400
QUARTER_HOUR = 900
PENDING_STATUSES = (ReviewStatus.PENDING, ReviewStatus.UNDER_REVIEW, ReviewStatus.CHANGES_REQUESTED)

SessionFactory = Callable[[], Session]


def get_counter_session_factory() -> SessionFactory:
    """Dependency so tests can point counters at the test database."""
    return SessionLocal


CounterSessions = Annotated[SessionFactory, Depends(get_counter_session_factory)]


@dataclass(frozen=True)
class Rule:
    name: str
    window_seconds: int
    limit: int


def scope_key(guest_scope_secret: str) -> bytes:
    return crypto.digest(crypto.GUEST_SCOPE_LABEL + ":limit", crypto.current_key_id(), guest_scope_secret)


def receipt_key(receipt_secret: str) -> bytes:
    return crypto.digest(crypto.RECEIPT_LABEL + ":limit", crypto.current_key_id(), receipt_secret)


def _window_start(now: datetime, window_seconds: int) -> datetime:
    epoch = int(now.timestamp())
    return datetime.fromtimestamp(epoch - epoch % window_seconds, tz=UTC)


def _retry_after(now: datetime, window_start: datetime, window_seconds: int) -> int:
    return max(1, int(window_start.timestamp()) + window_seconds - int(now.timestamp()))


_last_purge = 0.0
_purge_lock = threading.Lock()


def purge_expired_buckets(session: Session, *, now: datetime | None = None) -> int:
    """Delete windows that ended more than a day ago (retention: within 24 hours, Security 3.7)."""
    moment = now or datetime.now(UTC)
    cutoff = datetime.fromtimestamp(int(moment.timestamp()) - 2 * DAY, tz=UTC)
    result = session.execute(delete(RateLimitBucket).where(RateLimitBucket.window_start < cutoff))
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


def _maybe_purge(session: Session, now: datetime) -> None:
    global _last_purge  # noqa: PLW0603
    with _purge_lock:
        # 0.0 means "never purged". Comparing against it directly would skip the purge for the first
        # minute after the machine boots, because time.monotonic() starts near zero there.
        if _last_purge and time.monotonic() - _last_purge < 60:
            return
        _last_purge = time.monotonic()
    purge_expired_buckets(session, now=now)


def hit(
    sessions: SessionFactory,
    rule: Rule,
    key: bytes,
    *,
    now: datetime | None = None,
) -> tuple[int, int | None]:
    """Count one attempt and commit it immediately.

    Returns ``(count, retry_after_seconds)`` where ``retry_after_seconds`` is ``None`` while the
    count is within the limit. The attempt is counted even when it exceeds the limit.
    """
    moment = now or datetime.now(UTC)
    start = _window_start(moment, rule.window_seconds)
    with sessions() as session:
        statement = (
            insert(RateLimitBucket)
            .values(rule=rule.name, key_digest=key, window_start=start, count=1, updated_at=moment)
            .on_conflict_do_update(
                index_elements=[
                    RateLimitBucket.rule,
                    RateLimitBucket.key_digest,
                    RateLimitBucket.window_start,
                ],
                set_={"count": RateLimitBucket.count + 1, "updated_at": moment},
            )
            .returning(RateLimitBucket.count)
        )
        count = int(session.execute(statement).scalar_one())
        _maybe_purge(session, moment)
        session.commit()
    if count > rule.limit:
        return count, _retry_after(moment, start, rule.window_seconds)
    return count, None


def peek(
    sessions: SessionFactory, rule: Rule, key: bytes, *, now: datetime | None = None
) -> int | None:
    """Return Retry-After seconds if ``rule`` is already exhausted, else ``None``. Counts nothing."""
    moment = now or datetime.now(UTC)
    start = _window_start(moment, rule.window_seconds)
    with sessions() as session:
        count = session.scalar(
            select(RateLimitBucket.count).where(
                RateLimitBucket.rule == rule.name,
                RateLimitBucket.key_digest == key,
                RateLimitBucket.window_start == start,
            )
        )
    if count is not None and count >= rule.limit:
        return _retry_after(moment, start, rule.window_seconds)
    return None


def enforce(
    sessions: SessionFactory,
    checks: list[tuple[Rule, bytes]],
    *,
    now: datetime | None = None,
) -> None:
    """Count every check, then raise ``RATE_LIMITED`` with the longest wait if any is over its limit."""
    waits = [
        wait
        for rule, key in checks
        if (wait := hit(sessions, rule, key, now=now)[1]) is not None
    ]
    if waits:
        raise ApiError("RATE_LIMITED", headers={"Retry-After": str(max(waits))})


# ---- rule sets ----


def guest_submit_checks(
    settings: Settings, scope: bytes, network: bytes
) -> list[tuple[Rule, bytes]]:
    return [
        (Rule("guest_submit:scope:24h", DAY, settings.guest_submit_per_scope_per_day), scope),
        (Rule("guest_submit:network:1h", HOUR, settings.guest_submit_per_network_per_hour), network),
        (Rule("guest_submit:network:24h", DAY, settings.guest_submit_per_network_per_day), network),
    ]


def receipt_op_checks(settings: Settings, receipt: bytes, network: bytes) -> list[tuple[Rule, bytes]]:
    return [
        (Rule("receipt_ops:receipt:1h", HOUR, settings.receipt_ops_per_receipt_per_hour), receipt),
        (Rule("receipt_ops:network:1h", HOUR, settings.receipt_ops_per_network_per_hour), network),
    ]


def guest_visit_checks(settings: Settings, network: bytes) -> list[tuple[Rule, bytes]]:
    return [
        (Rule("guest_visit:network:1h", HOUR, settings.guest_visits_per_network_per_hour), network),
    ]


def member_report_checks(settings: Settings, member: bytes, member_review: bytes) -> list[tuple[Rule, bytes]]:
    return [
        (Rule("member_report:member:1h", HOUR, settings.member_report_per_hour), member),
        (Rule("member_report:review:24h", DAY, settings.member_report_per_review_per_day), member_review),
    ]


def anonymous_report_checks(settings: Settings, network: bytes) -> list[tuple[Rule, bytes]]:
    return [
        (Rule("anon_report:network:1h", HOUR, settings.anon_report_per_network_per_hour), network),
        (Rule("anon_report:network:24h", DAY, settings.anon_report_per_network_per_day), network),
    ]


def member_key(user_id: uuid.UUID, review_id: uuid.UUID | None = None) -> bytes:
    """Keyed digest naming a member (and optionally a review) for throttling."""
    value = str(user_id) if review_id is None else f"{user_id}:{review_id}"
    return crypto.digest("abhijatri:member-report:v1", crypto.current_key_id(), value)


AUTH_LABEL = "abhijatri:auth-identifier:v1"


def email_key(email: str) -> bytes:
    """Keyed digest of an email address for throttling; the address itself is never stored."""
    return crypto.digest(AUTH_LABEL, crypto.current_key_id(), email)


def register_checks(settings: Settings, network: bytes) -> list[tuple[Rule, bytes]]:
    return [(Rule("auth_register:network:1h", HOUR, settings.register_per_network_per_hour), network)]


def token_confirm_checks(settings: Settings, network: bytes) -> list[tuple[Rule, bytes]]:
    return [(Rule("auth_token:network:1h", HOUR, settings.token_confirms_per_network_per_hour), network)]


def existing_account_notice_rule(settings: Settings) -> Rule:
    return Rule("auth_existing_notice:email:24h", DAY, settings.existing_account_notices_per_email_per_day)


def reset_request_checks(settings: Settings, email: bytes, network: bytes) -> list[tuple[Rule, bytes]]:
    return [
        (Rule("auth_reset:email:1h", HOUR, settings.reset_requests_per_email_per_hour), email),
        (Rule("auth_reset:network:1h", HOUR, settings.reset_requests_per_network_per_hour), network),
    ]


def login_failure_rules(settings: Settings) -> list[tuple[Rule, str]]:
    """(rule, which key it applies to): progressive refusal after repeated failures."""
    return [
        (Rule("auth_login_fail:email:15m", QUARTER_HOUR, settings.login_failures_per_email_per_15m), "email"),
        (Rule("auth_login_fail:network:1h", HOUR, settings.login_attempts_per_network_per_hour), "network"),
    ]


def guard_login(sessions: SessionFactory, email: bytes, network: bytes) -> None:
    waits = [
        wait
        for rule, which in login_failure_rules(get_settings())
        if (wait := peek(sessions, rule, email if which == "email" else network)) is not None
    ]
    if waits:
        raise ApiError("RATE_LIMITED", headers={"Retry-After": str(max(waits))})


def record_login_failure(sessions: SessionFactory, email: bytes, network: bytes) -> None:
    for rule, which in login_failure_rules(get_settings()):
        hit(sessions, rule, email if which == "email" else network)


def receipt_failure_rules(settings: Settings) -> list[Rule]:
    return [
        Rule("receipt_fail:15m", QUARTER_HOUR, settings.receipt_failures_short_limit),
        Rule("receipt_fail:24h", DAY, settings.receipt_failures_long_limit),
    ]


def guard_receipt_failures(
    sessions: SessionFactory, receipt: bytes, network: bytes, *, now: datetime | None = None
) -> None:
    """Progressive delay: while either tier of recent failures is exhausted, refuse before any lookup."""
    waits = [
        wait
        for rule in receipt_failure_rules(get_settings())
        for key in (receipt, network)
        if (wait := peek(sessions, rule, key, now=now)) is not None
    ]
    if waits:
        raise ApiError("RATE_LIMITED", headers={"Retry-After": str(max(waits))})


def record_receipt_failure(
    sessions: SessionFactory, receipt: bytes, network: bytes, *, now: datetime | None = None
) -> None:
    for rule in receipt_failure_rules(get_settings()):
        for key in (receipt, network):
            hit(sessions, rule, key, now=now)


# ---- pending ceilings and emergency switch ----


def ensure_guest_writes_allowed(settings: Settings | None = None) -> None:
    if (settings or get_settings()).guest_writes_paused:
        logger.warning("guest writes are paused by the emergency switch")
        raise ApiError("GUEST_WRITES_PAUSED", headers={"Retry-After": "300"})


def check_pending_ceilings(session: Session, destination_id: uuid.UUID) -> None:
    """Refuse new Guest submissions when the pending queue is full (PF 14.3); alert at 80 percent."""
    settings = get_settings()
    base = select(func.count(Review.id)).where(
        Review.author_user_id.is_(None), Review.status.in_(PENDING_STATUSES)
    )
    total = int(session.scalar(base) or 0)
    per_destination = int(session.scalar(base.where(Review.destination_id == destination_id)) or 0)
    for label, count, ceiling in (
        ("destination", per_destination, settings.guest_pending_per_destination),
        ("total", total, settings.guest_pending_total),
    ):
        if count >= ceiling * settings.guest_pending_alert_ratio:
            logger.warning("guest pending queue (%s) at %d of %d", label, count, ceiling)
    if (
        per_destination >= settings.guest_pending_per_destination
        or total >= settings.guest_pending_total
    ):
        raise ApiError("GUEST_WRITES_PAUSED", headers={"Retry-After": "300"})
