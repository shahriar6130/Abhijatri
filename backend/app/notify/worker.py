"""The outbox relay and email sender (Moderation spec 6.7).

1. Claim a batch of due events with ``FOR UPDATE SKIP LOCKED`` and a short lease, then commit.
2. For each event, insert its notifications (``ON CONFLICT DO NOTHING`` on the notification identity)
   and mark the event done in one transaction. A failure retries with backoff; after 6 tries the
   event is ``failed`` and visible on the dashboard.
3. Send pending emails with no transaction open: mark the row ``ambiguous`` and commit, call the
   provider, then record ``sent`` or ``failed``. A crash between the two leaves ``ambiguous``, which is
   reconciled by hand rather than resent blindly. Processing is at-least-once; effects are idempotent.
"""

import logging
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import DeliveryAttempt, Notification, OutboxEvent, User
from app.notify.messages import messages_for
from app.notify.providers import Email, Provider, SendAmbiguous, SendFailed, get_provider

logger = logging.getLogger(__name__)

LEASE = timedelta(minutes=2)
MAX_EVENT_ATTEMPTS = 6
MAX_EMAIL_ATTEMPTS = 5

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
                or_(OutboxEvent.status == "pending", and_(OutboxEvent.status == "processing", OutboxEvent.lease_until < moment)),
            )
            .order_by(OutboxEvent.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for event in rows:
            event.status, event.lease_until, event.attempts = "processing", moment + LEASE, event.attempts + 1
        session.commit()
        return [event.id for event in rows]


def process_event(sessions: SessionFactory, event_id: uuid.UUID) -> int:
    """Fan one event out to notifications. Returns how many notifications it created."""
    with sessions() as session:
        event = session.get(OutboxEvent, event_id)
        if event is None or event.status != "processing":
            return 0
        try:
            created = 0
            for message in messages_for(session, event):
                result = session.execute(
                    insert(Notification)
                    .values(
                        id=uuid.uuid4(), event_id=event.id, recipient_user_id=message.recipient, kind=message.kind, critical=message.critical,
                        title_bn=message.title_bn, title_en=message.title_en, body_bn=message.body_bn, body_en=message.body_en,
                        link=message.link, appeal_id=message.appeal_id, email_status="pending" if message.critical else "digest",
                    )
                    .on_conflict_do_nothing(constraint="uq_notifications_identity")
                    .returning(Notification.id)
                )
                created += 1 if result.first() is not None else 0
            event.status, event.processed_at, event.lease_until, event.last_error = "done", _now(), None, None
            session.commit()
            return created
        except Exception as error:  # noqa: BLE001 - any failure is retried, never lost
            session.rollback()
            event = session.get(OutboxEvent, event_id)
            if event is not None:
                event.last_error = f"{type(error).__name__}: {error}"[:300]
                event.lease_until = None
                if event.attempts >= MAX_EVENT_ATTEMPTS:
                    event.status = "failed"
                else:
                    event.status, event.available_at = "pending", _now() + timedelta(seconds=30 * 2 ** event.attempts)
                session.commit()
            logger.warning("outbox event %s failed: %s", event_id, type(error).__name__)
            return 0


def _render(notification: Notification, base_url: str) -> tuple[str, str, str]:
    link = f"{base_url}{notification.link}" if notification.link else base_url
    subject = f"{notification.title_en} / {notification.title_bn}"
    text = f"{notification.title_en}\n{notification.body_en}\n\n{notification.title_bn}\n{notification.body_bn}\n\n{link}"
    html = (
        f"<h2>{escape(notification.title_en)}</h2><p>{escape(notification.body_en)}</p>"
        f"<h2>{escape(notification.title_bn)}</h2><p>{escape(notification.body_bn)}</p>"
        f'<p><a href="{escape(link)}">{escape(link)}</a></p>'
    )
    return subject, text, html


def send_pending_emails(sessions: SessionFactory, provider: Provider | None, limit: int = 20) -> int:
    if provider is None:
        return 0
    with sessions() as session:
        batch = session.scalars(
            select(Notification)
            .where(Notification.email_status == "pending", Notification.email_attempts < MAX_EMAIL_ATTEMPTS)
            .order_by(Notification.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        work: list[tuple[uuid.UUID, str | None]] = []
        for notification in batch:
            user = session.get(User, notification.recipient_user_id)
            address = user.email if user is not None and user.email_verified_at is not None else None  # current verified address, now
            notification.email_attempts += 1
            notification.email_status = "ambiguous" if address else "failed"
            if not address:
                session.add(DeliveryAttempt(notification_id=notification.id, provider=provider.name, status="failed", error="no verified address"))
            work.append((notification.id, address))
        session.commit()  # nothing is held open while the provider is called

    sent = 0
    base_url = get_settings().frontend_base_url.rstrip("/")
    for notification_id, address in work:
        if address is None:
            continue
        with sessions() as session:
            pending = session.get(Notification, notification_id)
            if pending is None:
                continue
            subject, text, html = _render(pending, base_url)
            email = Email(to=address, subject=subject, text=text, html=html, idempotency_key=f"notification-{pending.id}")
        try:
            message_id = provider.send(email)
            status, error, sent = "sent", None, sent + 1
        except SendAmbiguous as failure:
            message_id, status, error = None, "ambiguous", str(failure)[:300]
        except SendFailed as failure:
            message_id, status, error = None, "failed", str(failure)[:300]
        with sessions() as session:
            row = session.get(Notification, notification_id)
            if row is None:
                continue
            session.add(DeliveryAttempt(notification_id=notification_id, provider=provider.name, status=status, provider_message_id=message_id, error=error))
            if status == "failed" and row.email_attempts < MAX_EMAIL_ATTEMPTS:
                row.email_status = "pending"  # retried on a later pass
            else:
                row.email_status = status
            session.commit()
    return sent


def send_daily_digest(sessions: SessionFactory, provider: Provider | None, now: datetime | None = None) -> int:
    """One email per person with the day's non-critical notifications (spec 11: critical ones never wait for it).

    The send time is the recipient's configured zone; accounts have no zone of their own yet, so the
    platform display zone (Asia/Dhaka) is used for everyone.
    """
    if provider is None:
        return 0
    moment = now or _now()
    with sessions() as session:
        rows = session.scalars(
            select(Notification).where(Notification.email_status == "digest", Notification.created_at <= moment).order_by(Notification.recipient_user_id, Notification.created_at).with_for_update(skip_locked=True)
        ).all()
        groups: dict[uuid.UUID, list[Notification]] = {}
        for row in rows:
            groups.setdefault(row.recipient_user_id, []).append(row)
        mails: list[tuple[list[uuid.UUID], Email]] = []
        for user_id, items in groups.items():
            user = session.get(User, user_id)
            for item in items:
                item.email_status = "ambiguous"
            if user is None or user.email_verified_at is None:
                for item in items:
                    item.email_status = "failed"
                continue
            lines_en = "\n".join(f"- {item.title_en}: {item.body_en}" for item in items)
            lines_bn = "\n".join(f"- {item.title_bn}: {item.body_bn}" for item in items)
            html = "".join(f"<li><b>{escape(i.title_en)}</b> {escape(i.body_en)}<br>{escape(i.title_bn)} {escape(i.body_bn)}</li>" for i in items)
            day = moment.astimezone(get_settings().display_tz).date().isoformat()
            mails.append(([i.id for i in items], Email(
                to=user.email, subject=f"Your Abhijatri summary / আপনার সারসংক্ষেপ ({len(items)})",
                text=f"{lines_en}\n\n{lines_bn}", html=f"<ul>{html}</ul>", idempotency_key=f"digest-{user_id}-{day}",
            )))
        session.commit()
    sent = 0
    for ids, email in mails:
        try:
            provider.send(email)
            status, sent = "sent", sent + 1
        except SendAmbiguous:
            status = "ambiguous"
        except SendFailed:
            status = "digest"  # try again with the next digest
        with sessions() as session:
            for notification in session.scalars(select(Notification).where(Notification.id.in_(ids))):
                notification.email_status = status
                session.add(DeliveryAttempt(notification_id=notification.id, provider=provider.name, status="sent" if status == "sent" else ("ambiguous" if status == "ambiguous" else "failed")))
            session.commit()
    return sent


def run_once(sessions: SessionFactory, provider: Provider | None) -> dict[str, int]:
    events = claim_events(sessions)
    created = sum(process_event(sessions, event_id) for event_id in events)
    emailed = send_pending_emails(sessions, provider)
    return {"events": len(events), "notifications": created, "emails": emailed}


class NotificationWorker:
    """In-process relay started with the API (one per process; `SKIP LOCKED` makes several safe)."""

    def __init__(self, sessions: SessionFactory) -> None:
        self._sessions = sessions
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_digest_day: str | None = None

    def start(self) -> None:
        if not get_settings().notify_worker_enabled:
            return
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
                run_once(self._sessions, get_provider())
                local = _now().astimezone(settings.display_tz)
                if local.hour >= settings.digest_hour and self._last_digest_day != local.date().isoformat():
                    send_daily_digest(self._sessions, get_provider())
                    self._last_digest_day = local.date().isoformat()
            except Exception:  # noqa: BLE001 - the loop must survive a bad pass
                logger.exception("notification worker pass failed")
