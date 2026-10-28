"""The outbox relay (Notification spec 4, 8; Moderation spec 6.7).

1. Claim due events (``pending`` or ``retry``, or ``processing`` with an expired lease) with
   ``FOR UPDATE SKIP LOCKED``, record the lease owner, commit.
2. For each event, in one short transaction: create its notifications (``ON CONFLICT DO NOTHING`` on
   event + recipient + kind), choose each one's email mode, queue an immediate delivery, and mark the
   event ``processed``. A failure is retried with backoff; after 6 tries the event is
   ``dead_letter`` and visible to superadmins and the ops dashboard.
3. Email goes out in ``delivery.send_due`` with no transaction open; digests are built per person at
   their local time; scanners raise reminders and operational alerts.

Processing is at-least-once and every effect is idempotent, so a crash at any point is safe.
"""

import logging
import os
import socket
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
    NotificationRule,
    NotificationTemplate,
    OutboxEvent,
)
from app.notify import alerts, delivery, registry
from app.notify.messages import Message, messages_for
from app.notify.providers import Provider, get_provider

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=2)
MAX_EVENT_ATTEMPTS = 6
STANDARD_RETENTION = timedelta(days=90)
CRITICAL_RETENTION = timedelta(days=730)
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}"[:80]

SessionFactory = Callable[[], Session]


def _now() -> datetime:
    return datetime.now(UTC)


def claim_events(sessions: SessionFactory, limit: int = 25, now: datetime | None = None) -> list[uuid.UUID]:
    moment = now or _now()
    with sessions() as session:
        rows = session.scalars(
            select(OutboxEvent)
            .where(
                OutboxEvent.available_at <= moment,
                or_(OutboxEvent.status.in_(("pending", "retry")), and_(OutboxEvent.status == "processing", OutboxEvent.lease_until < moment)),
            )
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for event in rows:
            event.status, event.lease_until, event.lease_owner, event.attempts = "processing", moment + LEASE, WORKER_ID, event.attempts + 1
        session.commit()
        return [event.id for event in rows]


def email_mode(message: Message, preference: NotificationPreference | None) -> str:
    """Critical and high-priority notices are emailed at once whatever the preference (spec 2, 6.5);
    standard ones follow the person's choice (default: the daily digest)."""
    if not message.email:
        return "none"
    if message.priority in ("critical", "high"):
        return "immediate"
    mode = preference.standard_email_mode if preference else "digest"
    return {"immediate": "immediate", "digest": "digest"}.get(mode, "none")


def process_event(sessions: SessionFactory, event_id: uuid.UUID) -> int:
    """Fan one event out to notifications. Returns how many notifications it created."""
    with sessions() as session:
        event = session.get(OutboxEvent, event_id)
        if event is None or event.status != "processing":
            return 0
        try:
            created = 0
            now = _now()
            for message in messages_for(session, event):
                mode = email_mode(message, session.get(NotificationPreference, message.recipient))
                notification_id = session.execute(
                    insert(Notification)
                    .values(
                        id=uuid.uuid4(), event_id=event.id, recipient_user_id=message.recipient, kind=message.kind,
                        priority=message.priority, audience=message.audience, template_key=message.kind,
                        template_version=message.template_version, title_bn=message.title_bn, title_en=message.title_en,
                        body_bn=message.body_bn, body_en=message.body_en, link=message.link, appeal_id=message.appeal_id,
                        delivery_mode=mode, created_at=now,
                        expires_at=now + (CRITICAL_RETENTION if message.critical else STANDARD_RETENTION),
                    )
                    .on_conflict_do_nothing(constraint="uq_notifications_identity")
                    .returning(Notification.id)
                ).scalar()
                if notification_id is None:
                    continue  # already created by an earlier attempt
                created += 1
                if mode == "immediate":
                    session.add(NotificationDelivery(notification_id=notification_id, status="queued", next_attempt_at=now))
            event.status, event.processed_at, event.lease_until = "processed", now, None
            event.last_error = event.last_error_code = None
            session.commit()
            return created
        except Exception as error:  # noqa: BLE001 - any failure is retried, never lost
            session.rollback()
            event = session.get(OutboxEvent, event_id)
            if event is not None:
                event.last_error = f"{type(error).__name__}: {error}"[:300]
                event.last_error_code = type(error).__name__[:60]
                event.lease_until = None
                if event.attempts >= MAX_EVENT_ATTEMPTS:
                    event.status = "dead_letter"
                    logger.error("outbox event %s dead-lettered after %s attempts", event_id, event.attempts)
                else:
                    event.status, event.available_at = "retry", _now() + timedelta(seconds=30 * 2 ** event.attempts)
                session.commit()
            logger.warning("outbox event %s failed: %s", event_id, type(error).__name__)
            return 0


def sync_defaults(sessions: SessionFactory) -> int:
    """Store the version-1 templates and rule settings of the code catalogue if they are missing.

    Existing rows (including newer template versions a superadmin activated) are left alone."""
    added = 0
    with sessions() as session:
        for key, template in registry.TEMPLATES.items():
            for locale, (title, body) in (("bn", (template.title_bn, template.body_bn)), ("en", (template.title_en, template.body_en))):
                exists = session.scalar(
                    select(NotificationTemplate.id).where(
                        NotificationTemplate.template_key == key, NotificationTemplate.channel == "in_app", NotificationTemplate.locale == locale
                    )
                )
                if exists is None:
                    session.add(NotificationTemplate(
                        template_key=key, channel="in_app", locale=locale, version=1, title_template=title, body_template=body,
                        variable_schema={"allowed": list(template.variables)}, status="active", activated_at=_now(),
                    ))
                    added += 1
        seen: set[str] = set()
        for rule in registry.RULES:
            if rule.template_key in seen:
                continue
            seen.add(rule.template_key)
            added += session.execute(
                insert(NotificationRule)
                .values(template_key=rule.template_key, event_type=rule.event_type, priority=rule.priority, email=rule.email, enabled=True)
                .on_conflict_do_nothing()
                .returning(NotificationRule.template_key)
            ).first() is not None
        session.commit()
    return added


def run_once(sessions: SessionFactory, provider: Provider | None) -> dict[str, int]:
    events = claim_events(sessions)
    created = sum(process_event(sessions, event_id) for event_id in events)
    emailed = delivery.send_due(sessions, provider)
    return {"events": len(events), "notifications": created, "emails": emailed}


class NotificationWorker:
    """In-process relay started with the API (one per process; ``SKIP LOCKED`` makes several safe)."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_scan = 0.0

    def start(self) -> None:
        if not get_settings().notify_worker_enabled:
            return
        try:
            sync_defaults(self._sessions)
        except Exception:  # noqa: BLE001 - the code defaults still apply without the rows
            logger.exception("notification defaults were not stored")
        self._thread = threading.Thread(target=self._loop, name="notification-worker", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        settings = get_settings()
        while not self._stop.wait(settings.notify_poll_seconds):
            try:
                provider = get_provider()
                run_once(self._sessions, provider)
                if time.monotonic() - self._last_scan >= settings.notify_scan_seconds:
                    self._last_scan = time.monotonic()
                    delivery.build_digests(self._sessions)
                    alerts.scan(self._sessions)
            except Exception:  # noqa: BLE001 - the loop must survive a bad pass
                logger.exception("notification worker pass failed")
