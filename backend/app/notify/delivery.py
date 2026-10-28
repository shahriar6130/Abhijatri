"""Email delivery: one delivery row per notification or digest, an attempt row per try (spec 7.3, 7.4, 8).

Order of a send, never holding a transaction open across the network call:

1. claim due ``queued`` rows (``FOR UPDATE SKIP LOCKED``), resolve the **current verified address**
   now, skip suppressed or unverified addresses, mark ``sending`` with a lease, commit;
2. call the provider;
3. record the outcome and an attempt row: ``accepted``, a transient failure (retried after about
   1 min, 5 min, 30 min and 2 h with jitter, then ``failed_permanently``), a permanent failure, or
   ``ambiguous`` when the provider may have accepted it (a timeout). Ambiguous sends are never resent
   automatically; a superadmin can retry them after checking.

A worker that dies between steps 1 and 3 leaves ``sending`` with an expired lease; ``reconcile``
turns it into ``ambiguous`` rather than pretending the email was or was not sent.
"""

import logging
import random
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import crypto
from app.config import get_settings
from app.models import (
    Notification,
    NotificationDelivery,
    NotificationDeliveryAttempt,
    NotificationDigest,
    NotificationPreference,
    NotificationSuppression,
    User,
)
from app.notify.providers import Email, Provider, SendAmbiguous, SendFailed

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
SEND_LEASE = timedelta(minutes=2)
RETRY_DELAYS = (60, 300, 1800, 7200)  # seconds after attempts 1..4
MAX_ATTEMPTS = len(RETRY_DELAYS) + 1
DEFAULT_TIMEZONE = "Asia/Dhaka"


def _now() -> datetime:
    return datetime.now(UTC)


def destination_hmac(address: str) -> str:
    """HMAC of a normalised address: addresses are guessable, so a plain hash would not protect them."""
    return crypto.digest(crypto.EMAIL_DESTINATION_LABEL, crypto.current_key_id(), address.strip().lower()).hex()


def destination_hmacs(address: str) -> list[str]:
    """Every key's HMAC, so a suppression made before a key rotation still matches."""
    return [value.hex() for _, value in crypto.candidate_digests(crypto.EMAIL_DESTINATION_LABEL, address.strip().lower())]


def is_suppressed(session: Session, address: str) -> bool:
    return session.scalar(
        select(NotificationSuppression.id).where(
            NotificationSuppression.destination_hmac.in_(destination_hmacs(address)),
            NotificationSuppression.channel == "email",
            NotificationSuppression.removed_at.is_(None),
        )
    ) is not None


def suppress(session: Session, address_hmac: str, reason_code: str, actor_id: uuid.UUID | None) -> uuid.UUID | None:
    """Add an active suppression unless one exists. Returns the new id, or None when it already existed."""
    row = session.execute(
        insert(NotificationSuppression)
        .values(id=uuid.uuid4(), destination_hmac=address_hmac, channel="email", reason_code=reason_code, created_by=actor_id)
        .on_conflict_do_nothing(index_elements=["destination_hmac", "channel"], index_where=NotificationSuppression.removed_at.is_(None))
        .returning(NotificationSuppression.id)
    ).first()
    return row[0] if row else None


def retry_delay(attempt: int) -> timedelta:
    base = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS)) - 1]
    return timedelta(seconds=base * random.uniform(0.9, 1.1))  # noqa: S311 - jitter, not security


def _attempt(session: Session, delivery: NotificationDelivery, outcome: str, *, started: datetime, message_id: str | None = None,
             error_class: str | None = None, error_code: str | None = None, summary: str | None = None) -> None:
    session.add(
        NotificationDeliveryAttempt(
            delivery_id=delivery.id, attempt_number=max(delivery.attempt_count, 1), started_at=started, finished_at=_now(),
            outcome=outcome, provider_message_id=message_id, error_class=error_class, error_code=error_code,
            redacted_error_summary=(summary or "")[:300] or None,
        )
    )


def _recipient(session: Session, delivery: NotificationDelivery) -> User | None:
    if delivery.notification_id is not None:
        notification = session.get(Notification, delivery.notification_id)
        return session.get(User, notification.recipient_user_id) if notification else None
    digest = session.get(NotificationDigest, delivery.digest_id)
    return session.get(User, digest.recipient_user_id) if digest else None


def _base_url(link: str | None) -> str:
    settings = get_settings()
    if link and link.startswith("staff:"):
        return settings.staff_base_url.rstrip("/") + link.removeprefix("staff:")
    return settings.frontend_base_url.rstrip("/") + (link or "/account/notifications")


def render_notification(n: Notification) -> tuple[str, str, str]:
    link = _base_url(n.link)
    subject = f"{n.title_en} / {n.title_bn}"
    text = f"{n.title_en}\n{n.body_en}\n\n{n.title_bn}\n{n.body_bn}\n\n{link}"
    html = (
        f"<h2>{escape(n.title_en)}</h2><p>{escape(n.body_en)}</p>"
        f"<h2>{escape(n.title_bn)}</h2><p>{escape(n.body_bn)}</p>"
        f'<p><a href="{escape(link)}">{escape(link)}</a></p>'
    )
    return subject, text, html


def render_digest(items: list[Notification]) -> tuple[str, str, str]:
    inbox = _base_url("/account/notifications")
    subject = f"Your Abhijatri summary / আপনার সারসংক্ষেপ ({len(items)})"
    text = "\n".join(f"- {i.title_en}: {i.body_en} ({_base_url(i.link)})" for i in items)
    text += "\n\n" + "\n".join(f"- {i.title_bn}: {i.body_bn}" for i in items) + f"\n\n{inbox}"
    html = "".join(
        f'<li><a href="{escape(_base_url(i.link))}"><b>{escape(i.title_en)}</b></a> {escape(i.body_en)}<br>{escape(i.title_bn)} {escape(i.body_bn)}</li>'
        for i in items
    )
    return subject, text, f'<ul>{html}</ul><p><a href="{escape(inbox)}">{escape(inbox)}</a></p>'


def reconcile(sessions: SessionFactory, now: datetime | None = None) -> int:
    """A ``sending`` row whose lease ran out: the worker died mid-send, so the outcome is unknown."""
    moment = now or _now()
    with sessions() as session:
        stuck = session.scalars(
            select(NotificationDelivery).where(NotificationDelivery.status == "sending", NotificationDelivery.lease_until < moment).with_for_update(skip_locked=True)
        ).all()
        for delivery in stuck:
            started = delivery.updated_at
            delivery.status, delivery.lease_until, delivery.updated_at = "ambiguous", None, moment
            delivery.last_error_code = "worker_lost"
            _attempt(session, delivery, "ambiguous", started=started, error_class="lease_expired", error_code="worker_lost")
            _sync_digest(session, delivery, "ambiguous")
        session.commit()
        return len(stuck)


def _sync_digest(session: Session, delivery: NotificationDelivery, status: str) -> None:
    if delivery.digest_id is None:
        return
    digest = session.get(NotificationDigest, delivery.digest_id)
    if digest is not None:
        digest.status = {"accepted": "accepted", "delivered": "accepted", "sending": "sending", "ambiguous": "ambiguous"}.get(status, "failed" if status in ("failed_permanently", "skipped", "bounced") else digest.status)


def send_due(sessions: SessionFactory, provider: Provider | None, limit: int = 20, now: datetime | None = None) -> int:
    """Send due email. Returns how many the provider accepted."""
    moment = now or _now()
    reconcile(sessions, moment)
    work: list[tuple[uuid.UUID, str]] = []
    with sessions() as session:
        due = session.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status == "queued",
                (NotificationDelivery.next_attempt_at.is_(None)) | (NotificationDelivery.next_attempt_at <= moment),
            )
            .order_by(NotificationDelivery.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        ).all()
        for delivery in due:
            delivery.updated_at = moment
            user = _recipient(session, delivery)
            # The current verified address, read now: a changed but unverified address is never used.
            address = user.email if user is not None and user.email_verified_at is not None else None
            reason = "no_verified_address" if address is None else ("suppressed" if is_suppressed(session, address) else None)
            if reason is None and provider is None:
                reason = "no_provider"
            if reason is not None or address is None:
                delivery.status, delivery.last_error_code = "skipped", reason
                delivery.attempt_count += 1
                _attempt(session, delivery, "skipped", started=moment, error_code=reason)
                _sync_digest(session, delivery, "skipped")
                continue
            delivery.status, delivery.lease_until = "sending", moment + SEND_LEASE
            delivery.attempt_count += 1
            delivery.provider = provider.name if provider else None
            delivery.destination_ref = destination_hmac(address)
            _sync_digest(session, delivery, "sending")
            work.append((delivery.id, address))
        session.commit()  # nothing is held open while the provider is called

    accepted = 0
    for delivery_id, address in work:
        with sessions() as session:
            claimed = session.get(NotificationDelivery, delivery_id)
            if claimed is None or provider is None:
                continue
            if claimed.notification_id is not None:
                notification = session.get(Notification, claimed.notification_id)
                if notification is None:
                    continue
                subject, text, html = render_notification(notification)
            else:
                items = list(session.scalars(select(Notification).where(Notification.digest_id == claimed.digest_id).order_by(Notification.created_at)))
                subject, text, html = render_digest(items)
            email = Email(to=address, subject=subject, text=text, html=html, idempotency_key=f"delivery-{claimed.id}")
            started = claimed.updated_at
        outcome, message_id, error_class, error_code, summary = "accepted", None, None, None, None
        try:
            message_id = provider.send(email)
            accepted += 1
        except SendAmbiguous as failure:
            outcome, error_class, summary = "ambiguous", "timeout", str(failure)
        except SendFailed as failure:
            outcome = "permanent_failure" if failure.permanent else "transient_failure"
            error_class, summary = ("rejected" if failure.permanent else "temporary"), str(failure)
            error_code = failure.code
        with sessions() as session:
            row = session.scalar(select(NotificationDelivery).where(NotificationDelivery.id == delivery_id).with_for_update())
            if row is None:
                continue
            row.lease_until, row.updated_at = None, _now()
            row.provider_message_id = message_id or row.provider_message_id
            row.last_error_code, row.last_error_summary = error_code or error_class, (summary or "")[:300] or None
            if outcome == "accepted":
                row.status = "accepted"
            elif outcome == "ambiguous":
                row.status = "ambiguous"
            elif outcome == "permanent_failure" or row.attempt_count >= MAX_ATTEMPTS:
                row.status = "failed_permanently"
            else:
                row.status, row.next_attempt_at = "queued", _now() + retry_delay(row.attempt_count)
            _attempt(session, row, outcome, started=started, message_id=message_id, error_class=error_class, error_code=error_code, summary=summary)
            _sync_digest(session, row, row.status)
            session.commit()
    return accepted


# ---- daily digest (spec 6.5, 7.10) ----


def _local_now(pref: NotificationPreference | None, moment: datetime) -> tuple[date, bool]:
    zone = ZoneInfo(pref.digest_timezone if pref else DEFAULT_TIMEZONE)
    local = moment.astimezone(zone)
    send_at = pref.digest_local_time if pref else datetime.strptime("08:00", "%H:%M").time()
    return local.date(), local.time() >= send_at


def build_digests(sessions: SessionFactory, now: datetime | None = None) -> int:
    """Gather each person's waiting non-critical items once per local day, at their chosen time.

    The digest row is unique per recipient and local day, so a retried job cannot send two."""
    moment = now or _now()
    built = 0
    with sessions() as session:
        waiting = session.execute(
            select(Notification.recipient_user_id)
            .where(Notification.delivery_mode == "digest", Notification.digest_id.is_(None), Notification.created_at <= moment)
            .distinct()
        ).scalars().all()
        for user_id in waiting:
            pref = session.get(NotificationPreference, user_id)
            day, due = _local_now(pref, moment)
            if not due:
                continue
            digest_id = session.execute(
                insert(NotificationDigest)
                .values(id=uuid.uuid4(), recipient_user_id=user_id, window_date=day, scheduled_for=moment, status="queued")
                .on_conflict_do_nothing(constraint="uq_notification_digests_window")
                .returning(NotificationDigest.id)
            ).scalar()
            if digest_id is None:
                continue  # today's digest already went out; these wait for tomorrow's
            items = session.scalars(
                select(Notification)
                .where(Notification.recipient_user_id == user_id, Notification.delivery_mode == "digest", Notification.digest_id.is_(None))
                .with_for_update(skip_locked=True)
            ).all()
            for item in items:
                item.digest_id = digest_id
            session.add(NotificationDelivery(digest_id=digest_id, status="queued", next_attempt_at=moment))
            built += 1
        session.commit()
    return built
