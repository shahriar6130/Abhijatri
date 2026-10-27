"""Work queue and claim leases (Moderation spec 5).

The database is authoritative. A claim re-checks everything under a row lock, so concurrent claims
produce at most one valid lease. A lease expiring never changes the underlying decision state: it
only lets another eligible staff member claim the task, and the previous holder's next write gets a
409 telling them to reload.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.admin import audit
from app.auth.sessions import Principal
from app.errors import ApiError
from app.models import ModerationTask

LEASE_SECONDS = 300


def _now() -> datetime:
    return datetime.now(UTC)


def ensure_task(
    session: Session, task_type: str, subject_id: uuid.UUID, *, priority: int = 0, required_role: str = "moderator"
) -> None:
    """Queue a subject unless it is already queued. Safe to call twice."""
    session.execute(
        insert(ModerationTask)
        .values(id=uuid.uuid4(), task_type=task_type, subject_id=subject_id, priority=priority, required_role=required_role)
        .on_conflict_do_nothing()
    )


def cancel_open_tasks(session: Session, subject_id: uuid.UUID) -> None:
    """The subject left the queue (for example the author withdrew a pending review)."""
    for task in session.scalars(
        select(ModerationTask).where(ModerationTask.subject_id == subject_id, ModerationTask.status == "open").with_for_update()
    ):
        task.status, task.completed_at, task.updated_at = "cancelled", _now(), _now()
        task.claimed_by = task.lease_token = task.lease_expires_at = None
        task.version += 1


def _eligible(task: ModerationTask, principal: Principal) -> bool:
    return task.required_role == "moderator" or principal.role == "superadmin"


def _lease_active(task: ModerationTask, now: datetime) -> bool:
    return task.lease_expires_at is not None and task.lease_expires_at > now


def _locked(session: Session, task_id: uuid.UUID) -> ModerationTask:
    task = session.scalar(select(ModerationTask).where(ModerationTask.id == task_id).with_for_update())
    if task is None:
        raise ApiError("NOT_FOUND")
    return task


def claim(session: Session, principal: Principal, task_id: uuid.UUID, *, request_id: str | None = None) -> ModerationTask:
    task = _locked(session, task_id)
    now = _now()
    if task.status != "open":
        raise ApiError("TASK_NOT_AVAILABLE")
    if not _eligible(task, principal):
        raise ApiError("FORBIDDEN")
    if task.assigned_to is not None and task.assigned_to != principal.user.id and principal.role != "superadmin":
        raise ApiError("FORBIDDEN")
    if _lease_active(task, now) and task.claimed_by != principal.user.id:
        raise ApiError("TASK_NOT_AVAILABLE")
    reclaimed = task.claimed_by is not None and task.claimed_by != principal.user.id
    task.claimed_by, task.claimed_at = principal.user.id, now
    task.lease_expires_at, task.lease_token = now + timedelta(seconds=LEASE_SECONDS), uuid.uuid4()
    task.version += 1
    task.updated_at = now
    audit.record(
        session,
        actor=principal,
        action="task.claimed",
        target_type="task",
        target_id=task.id,
        metadata={"task_type": task.task_type, "reclaimed_expired_lease": reclaimed},
        request_id=request_id,
    )
    return task


def require_lease(
    session: Session, principal: Principal, task_id: uuid.UUID, lease_token: uuid.UUID, subject_id: uuid.UUID | None = None
) -> ModerationTask:
    """Lock the task and prove this actor still holds a live lease on it (spec 8.5, steps 2 to 4).

    ``subject_id`` is checked when given; a caller whose task is linked to the subject (a report task and
    the review it names) checks the link itself.
    """
    task = _locked(session, task_id)
    if subject_id is not None and task.subject_id != subject_id:
        raise ApiError("NOT_FOUND")
    if task.status != "open":
        raise ApiError("LEASE_LOST")
    if not _eligible(task, principal):  # escalated while this staff member had it open
        raise ApiError("FORBIDDEN")
    if task.claimed_by != principal.user.id or task.lease_token != lease_token or not _lease_active(task, _now()):
        raise ApiError("LEASE_LOST")  # never silently reclaim during a decision
    return task


def heartbeat(session: Session, principal: Principal, task_id: uuid.UUID, lease_token: uuid.UUID) -> ModerationTask:
    task = _locked(session, task_id)
    if task.status != "open" or task.claimed_by != principal.user.id or task.lease_token != lease_token:
        raise ApiError("LEASE_LOST")
    if not _lease_active(task, _now()):
        raise ApiError("LEASE_LOST")
    if not _eligible(task, principal):
        raise ApiError("FORBIDDEN")
    task.lease_expires_at = _now() + timedelta(seconds=LEASE_SECONDS)
    task.updated_at = _now()
    return task


def release(session: Session, principal: Principal, task_id: uuid.UUID, lease_token: uuid.UUID, *, request_id: str | None = None) -> ModerationTask:
    task = _locked(session, task_id)
    if task.status != "open" or task.claimed_by != principal.user.id or task.lease_token != lease_token:
        raise ApiError("LEASE_LOST")
    task.claimed_by = task.claimed_at = task.lease_expires_at = task.lease_token = None
    task.version += 1
    task.updated_at = _now()
    audit.record(session, actor=principal, action="task.released", target_type="task", target_id=task.id, request_id=request_id)
    return task


def escalate(
    session: Session, principal: Principal, task_id: uuid.UUID, lease_token: uuid.UUID, reason: str, *, request_id: str | None = None
) -> ModerationTask:
    """Hand the task to a superadmin. The holder's lease ends, so a stale tab cannot decide it."""
    task = require_lease(session, principal, task_id, lease_token)
    task.escalated, task.required_role = True, "superadmin"
    task.claimed_by = task.claimed_at = task.lease_expires_at = task.lease_token = None
    task.version += 1
    task.updated_at = _now()
    audit.record(
        session, actor=principal, action="task.escalated", target_type="task", target_id=task.id, reason=reason, request_id=request_id
    )
    return task


def complete(task: ModerationTask) -> None:
    now = _now()
    task.status, task.completed_at, task.updated_at = "done", now, now
    task.claimed_by = task.claimed_at = task.lease_expires_at = task.lease_token = None
    task.version += 1


def serialize(task: ModerationTask, *, include_lease_token: bool = False) -> dict[str, object]:
    body: dict[str, object] = {
        "id": str(task.id),
        "task_type": task.task_type,
        "subject_id": str(task.subject_id),
        "status": task.status,
        "required_role": task.required_role,
        "escalated": task.escalated,
        "priority": task.priority,
        "assigned_to": str(task.assigned_to) if task.assigned_to else None,
        "claimed_by": str(task.claimed_by) if task.claimed_by else None,
        "lease_expires_at": task.lease_expires_at.isoformat() if task.lease_expires_at else None,
        "version": task.version,
        "created_at": task.created_at.isoformat(),
    }
    if include_lease_token:  # only the holder is told the token
        body["lease_token"] = str(task.lease_token) if task.lease_token else None
    return body
