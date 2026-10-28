"""Reminders and operational alerts (Notification spec 3, 8, 11).

Each scanner turns a condition into one outbox event per time window. The window is part of the
``dedupe_key``, so running a scanner twice (or on two workers) never produces two alerts. Every
alert is also logged at ERROR: the notification system must not be the only one to report its own
failure, and the independent ops dashboard reads the same counts from the database.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    AuditEvent,
    ModerationTask,
    NotificationDelivery,
    NotificationProviderEvent,
    OutboxEvent,
)
from app.notify import events

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], Session]
LEASE_WARNING = timedelta(seconds=60)
DENIAL_WINDOW = timedelta(minutes=15)
DENIAL_THRESHOLD = 5
SYSTEM = uuid.UUID(int=0)  # aggregate id of platform-wide alerts


def _hour(moment: datetime) -> str:
    return moment.strftime("%Y%m%d%H")


def _alert(session: Session, topic: str, count: int, moment: datetime, window: str) -> bool:
    created = events.emit(
        session, topic, SYSTEM, {"count": count}, aggregate_type="platform", staff_roles=("superadmin",), dedupe_key=f"{topic}:{window}"
    )
    if created:
        logger.error("operational alert %s count=%s", topic, count)
    return created


def scan(sessions: SessionFactory, now: datetime | None = None) -> dict[str, int]:
    moment = now or datetime.now(UTC)
    settings = get_settings()
    found: dict[str, int] = {}
    with sessions() as session:
        # A holder whose claim ends within a minute is reminded once per lease.
        expiring = session.scalars(
            select(ModerationTask).where(
                ModerationTask.status == "open",
                ModerationTask.claimed_by.is_not(None),
                ModerationTask.lease_expires_at > moment,
                ModerationTask.lease_expires_at <= moment + LEASE_WARNING,
            )
        ).all()
        found["lease_expiring"] = sum(
            events.emit(
                session, "task.lease_expiring", task.id, {"task_id": str(task.id), "holder_id": str(task.claimed_by)},
                aggregate_type="task", dedupe_key=f"task.lease_expiring:{task.id}:{task.lease_token}",
            )
            for task in expiring
        )
        # Tasks waiting longer than the target: one summary a day to the current moderators.
        overdue = session.scalar(
            select(func.count()).select_from(ModerationTask).where(
                ModerationTask.status == "open", ModerationTask.created_at < moment - timedelta(hours=settings.notify_queue_overdue_hours)
            )
        ) or 0
        found["queue_overdue"] = int(
            overdue > 0
            and events.emit(
                session, "moderation.queue_overdue", SYSTEM, {"count": overdue}, aggregate_type="platform",
                staff_roles=("moderator", "superadmin"), dedupe_key=f"moderation.queue_overdue:{moment.astimezone(settings.display_tz).date()}",
            )
        )
        hour_ago = moment - timedelta(hours=1)
        failures = session.scalar(
            select(func.count()).select_from(NotificationDelivery).where(
                NotificationDelivery.status.in_(("failed_permanently", "ambiguous", "bounced")), NotificationDelivery.updated_at >= hour_ago
            )
        ) or 0
        found["delivery_failures"] = int(
            failures >= settings.notify_failure_alert_per_hour
            and _alert(session, "notification.delivery_failure_threshold_reached", failures, moment, _hour(moment))
        )
        backlog = session.scalar(
            select(func.count()).select_from(OutboxEvent).where(
                OutboxEvent.status.in_(("pending", "retry")), OutboxEvent.created_at < moment - timedelta(minutes=settings.notify_backlog_alert_minutes)
            )
        ) or 0
        found["outbox_backlog"] = int(backlog > 0 and _alert(session, "notification.outbox_backlog_threshold_reached", backlog, moment, _hour(moment)))
        rejected = session.scalar(
            select(func.count()).select_from(NotificationProviderEvent).where(
                NotificationProviderEvent.event_type == "signature_failure", NotificationProviderEvent.received_at >= hour_ago
            )
        ) or 0
        found["webhook_anomaly"] = int(
            rejected >= settings.notify_webhook_anomaly_per_hour
            and _alert(session, "notification.provider_webhook_anomaly", rejected, moment, _hour(moment))
        )
        session.commit()
    return found


def check_denials(session: Session, actor_id: uuid.UUID, now: datetime | None = None) -> bool:
    """Called after a denied staff action is audited: many denials in a short time alert superadmins."""
    moment = now or datetime.now(UTC)
    denied = session.scalar(
        select(func.count()).select_from(AuditEvent).where(
            AuditEvent.actor_user_id == actor_id, AuditEvent.action.like("denied.%"), AuditEvent.occurred_at >= moment - DENIAL_WINDOW
        )
    ) or 0
    if denied < DENIAL_THRESHOLD:
        return False
    return events.emit(
        session, "moderation.security_anomaly", actor_id, {"actor_id": str(actor_id), "count": denied}, aggregate_type="user",
        staff_roles=("superadmin",), exclude=actor_id, dedupe_key=f"moderation.security_anomaly:{actor_id}:{_hour(moment)}",
    )
