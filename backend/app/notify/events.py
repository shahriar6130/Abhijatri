"""Writing business events to the shared outbox (Notification spec 4, 7.1).

``emit`` is called inside the business transaction, so the event commits or rolls back with the
decision and its audit row. Staff recipients for role-based notices are captured here, at event
time, together with the policy that chose them; the worker re-checks their current role later.
A ``dedupe_key`` makes an event idempotent: a second emit with the same key is ignored.
"""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import OutboxEvent, UserRole

SCHEMA_VERSION = 1


def staff_ids(session: Session, *, roles: tuple[str, ...] = ("moderator", "superadmin"), exclude: uuid.UUID | None = None) -> list[str]:
    """Current staff holding one of ``roles``: the recipients a role-based notice is meant for."""
    rows = session.scalars(select(UserRole.user_id).where(UserRole.revoked_at.is_(None), UserRole.role.in_(roles)))
    return sorted(str(user_id) for user_id in rows if user_id != exclude)


def emit(
    session: Session,
    topic: str,
    aggregate_id: uuid.UUID,
    payload: dict[str, Any],
    *,
    aggregate_type: str | None = None,
    aggregate_version: int | None = None,
    staff_roles: tuple[str, ...] | None = None,
    exclude: uuid.UUID | None = None,
    dedupe_key: str | None = None,
) -> bool:
    """Queue one event. With ``staff_roles`` the current holders of those roles are captured into
    ``payload["staff_recipients"]``. Returns False when ``dedupe_key`` was already used."""
    body = dict(payload)
    policy: dict[str, Any] = {"members": "named_in_payload"}
    if staff_roles is not None:
        body["staff_recipients"] = staff_ids(session, roles=staff_roles, exclude=exclude)
        policy = {**policy, "staff": "captured_at_event", "roles": list(staff_roles)}
    elif "staff_recipients" in body:
        policy = {**policy, "staff": "captured_at_event"}
    result = session.execute(
        insert(OutboxEvent)
        .values(
            id=uuid.uuid4(),
            topic=topic,
            aggregate_id=aggregate_id,
            aggregate_type=aggregate_type,
            aggregate_version=aggregate_version,
            payload=body,
            schema_version=SCHEMA_VERSION,
            recipient_policy=policy,
            dedupe_key=dedupe_key or f"{topic}:{aggregate_id}:{uuid.uuid4()}",
        )
        .on_conflict_do_nothing(index_elements=[OutboxEvent.dedupe_key])
        .returning(OutboxEvent.id)
    )
    return result.first() is not None
