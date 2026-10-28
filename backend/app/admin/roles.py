"""Staff role grants and revocations (Moderation spec 2.2 and 6.1).

One active role per user is enforced by a partial unique index. Granting or revoking serialises on
the single ``role_admin_guard`` row, and the superadmin count is re-read inside that lock, so two
concurrent requests can never remove the last superadmin. The change and its audit event commit
together.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.admin import audit
from app.auth.sessions import Principal
from app.errors import ApiError
from app.models import RoleAdminGuard, User, UserRole
from app.notify import events

ROLES = ("moderator", "superadmin")


def set_staff_role(
    session: Session,
    *,
    actor: Principal | None,
    target_user_id: uuid.UUID,
    role: str | None,
    reason: str | None,
    request_id: str | None = None,
) -> UserRole | None:
    """Make ``role`` the user's only active staff role, or remove it with ``role=None``.

    ``actor`` is None only for the bootstrap command. Callers have already required a superadmin and
    a recent re-authentication.
    """
    if role is not None and role not in ROLES:
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "role", "code": "INVALID_VALUE"}])
    # The guard row is created on first use if it is missing, so the lock always has something to lock.
    session.execute(insert(RoleAdminGuard).values(id=1).on_conflict_do_nothing())
    session.execute(select(RoleAdminGuard).where(RoleAdminGuard.id == 1).with_for_update())
    target = session.get(User, target_user_id)
    if target is None or target.status != "active":
        raise ApiError("NOT_FOUND")
    current = session.scalar(
        select(UserRole).where(UserRole.user_id == target_user_id, UserRole.revoked_at.is_(None)).with_for_update()
    )
    if (current.role if current else None) == role:
        return current

    if current is not None and current.role == "superadmin" and role != "superadmin":
        active_superadmins = session.scalar(
            select(func.count()).select_from(UserRole).where(UserRole.role == "superadmin", UserRole.revoked_at.is_(None))
        )
        if (active_superadmins or 0) <= 1:
            raise ApiError("LAST_SUPERADMIN")

    now = datetime.now(UTC)
    previous = current.role if current else None
    if current is not None:
        current.revoked_at, current.revoked_by = now, actor.user.id if actor else None
        session.flush()  # the unique index allows the new row only after the old one is revoked
    granted: UserRole | None = None
    if role is not None:
        granted = UserRole(user_id=target_user_id, role=role, granted_by=actor.user.id if actor else None, granted_at=now)
        session.add(granted)
        session.flush()
    audit.record(
        session,
        actor=actor,
        action="staff.role_changed" if previous and role else ("staff.role_granted" if role else "staff.role_revoked"),
        target_type="user",
        target_id=target_user_id,
        reason=reason,
        metadata={"from": previous, "to": role},
        request_id=request_id,
    )
    events.emit(
        session,
        "staff.role_changed",
        target_user_id,
        {"target_id": str(target_user_id), "from": previous, "role": role or "none", "granted": "true" if role else "false"},
        aggregate_type="user",
        staff_roles=("superadmin",),
        exclude=actor.user.id if actor else None,
    )
    return granted
