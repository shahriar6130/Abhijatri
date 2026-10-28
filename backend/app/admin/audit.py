"""Append-only audit events (Moderation spec 6.6).

Written in the same transaction as the change they describe. ``metadata`` carries approved,
non-secret facts: ids, states, versions. Never a password, token, email or free text from a user.
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.auth.sessions import Principal
from app.models import AuditEvent


def record(
    session: Session,
    *,
    actor: Principal | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        actor_user_id=actor.user.id if actor else None,
        actor_role_snapshot=actor.role if actor else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        request_id=request_id,
        reason=reason,
        event_metadata=metadata or {},
    )
    session.add(event)
    session.flush()
    return event
