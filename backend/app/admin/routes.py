"""Staff API under `/api/v1/admin` (Moderation-Dashboard-Specification 8.3; Gantt R10 and R11).

Non-staff callers get 404 (the routes' existence is not disclosed, spec 2.4); staff of a lower role
get 403. Everything is `no-store`. Writes need a CSRF token; decisions accept an `Idempotency-Key`.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import media
from app.admin import actions, audit, cases, idempotency, roles, tasks
from app.auth.sessions import MemberPrincipal, Principal, require_recent_auth, staff_principal
from app.db import get_session
from app.errors import ApiError
from app.models import (
    Appeal,
    AuditEvent,
    EnforcementCase,
    ModerationDecision,
    ModerationTask,
    NotificationDelivery,
    OutboxEvent,
    Report,
    Review,
    ReviewMedia,
    ReviewRevision,
    Sanction,
    User,
    UserRole,
    VerificationCase,
    VerificationEvidence,
)
from app.notify import alerts
from app.storage import StorageClient, StorageUnavailable, get_storage

logger = logging.getLogger(__name__)


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(_no_store)])
member_router = APIRouter(prefix="/api/v1", tags=["reports"], dependencies=[Depends(_no_store)])

Staff = Annotated[Principal, Depends(staff_principal("moderator", "superadmin"))]
Superadmin = Annotated[Principal, Depends(staff_principal("superadmin"))]
StorageDep = Annotated[StorageClient, Depends(get_storage)]
DbSession = Annotated[Session, Depends(get_session)]
IdempotencyHeader = Annotated[str | None, Header(alias="Idempotency-Key")]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LeaseBody(_Body):
    lease_token: uuid.UUID


class EscalateBody(LeaseBody):
    reason: str = Field(min_length=3, max_length=500)


class DecisionBody(_Body):
    task_id: uuid.UUID
    lease_token: uuid.UUID
    expected_version: int = Field(ge=1)
    decision: str = Field(pattern="^(PUBLISH|REJECT|HIDE|RESTORE|REQUEST_CHANGES)$")
    reason_code: str = Field(min_length=2, max_length=60)
    note: str | None = Field(default=None, max_length=500)
    # PUBLISH only: photos or videos to reject while the review itself is published. The rest are approved.
    rejected_media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=10)


class ConflictBody(_Body):
    expected_version: int = Field(ge=1)
    conflict_declared: bool
    reason_code: str = Field(min_length=2, max_length=60)
    note: str | None = Field(default=None, max_length=500)


class ReportTransitionBody(_Body):
    to: str = Field(pattern="^(in_review|actioned|dismissed)$")
    expected_version: int = Field(ge=1)
    reason_code: str = Field(min_length=2, max_length=60)
    note: str | None = Field(default=None, max_length=500)
    task_id: uuid.UUID
    lease_token: uuid.UUID


class RoleBody(_Body):
    role: str | None = Field(default=None, pattern="^(moderator|superadmin)$")
    reason: str = Field(min_length=3, max_length=500)


class ReportBody(_Body):
    reason_code: str = Field(pattern="^(spam|offensive|false_information|privacy|conflict_of_interest|other)$")
    details: str | None = Field(default=None, max_length=1000)


class BulkItem(DecisionBody):
    review_id: uuid.UUID


class BulkBody(_Body):
    items: list[BulkItem] = Field(min_length=1, max_length=25)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "-"))


def _deny(session: Session, principal: Principal, request: Request, action: str, target_type: str, target_id: Any) -> None:
    """Record a denied high-risk attempt in its own committed transaction (spec 8.1)."""
    session.rollback()
    try:
        audit.record(
            session,
            actor=principal,
            action=f"denied.{action}",
            target_type=target_type,
            target_id=target_id,
            request_id=_request_id(request),
        )
        session.commit()
        if alerts.check_denials(session, principal.user.id):  # many denials in a short time alert superadmins
            session.commit()
    except Exception:  # noqa: BLE001 - the original error is what the caller needs
        session.rollback()
        logger.warning("could not record a denied attempt")


def _commit_or_rollback(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


def _run[T](session: Session, principal: Principal, request: Request, action: str, target_type: str, target_id: Any, work: Callable[[], T]) -> T:
    """One unit of work: commit on success, roll back on any failure, log a 403 as a denied attempt."""
    try:
        result = work()
        _commit_or_rollback(session)
        return result
    except ApiError as error:
        if error.code == "FORBIDDEN":
            _deny(session, principal, request, action, target_type, target_id)
        else:
            session.rollback()
        raise
    except Exception:
        session.rollback()
        raise


# ---- queue and claims ----


@router.get("/queue")
def queue(
    principal: Staff,
    session: DbSession,
    task_type: Annotated[str | None, Query(pattern="^(review_moderation|report|verification|appeal|enforcement)$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    statement = (
        select(ModerationTask)
        .where(ModerationTask.status == "open")
        .order_by(ModerationTask.priority.desc(), ModerationTask.created_at.asc(), ModerationTask.id.asc())
        .limit(limit)
    )
    if task_type:
        statement = statement.where(ModerationTask.task_type == task_type)
    now = datetime.now(UTC)
    items: list[dict[str, Any]] = []
    for task in session.scalars(statement):
        item = tasks.serialize(task, include_lease_token=task.claimed_by == principal.user.id)
        item["claimable"] = (
            (task.required_role == "moderator" or principal.role == "superadmin")
            and not (task.lease_expires_at and task.lease_expires_at > now and task.claimed_by != principal.user.id)
        )
        item["lease_active"] = bool(task.lease_expires_at and task.lease_expires_at > now)
        subject = _subject_summary(session, task)
        if subject and subject.get("kind") == "appeal":  # the original decider must not take their own appeal
            subject["original_decider_is_you"] = subject.pop("original_decider_id") == str(principal.user.id)
            item["claimable"] = bool(item["claimable"]) and not subject["original_decider_is_you"]
        item["subject"] = subject
        items.append(item)
    return {"items": items, "generated_at": now.isoformat()}


def _subject_summary(session: Session, task: ModerationTask) -> dict[str, Any] | None:
    if task.task_type == "review_moderation":
        row = session.execute(
            select(Review, ReviewRevision)
            .join(ReviewRevision, ReviewRevision.id == Review.current_revision_id)
            .where(Review.id == task.subject_id)
        ).first()
        if row is None:
            return None
        review, revision = row
        return {
            "kind": "review",
            "review_id": str(review.id),
            "status": review.status.value,
            "version": review.version,
            "overall_rating": review.overall_rating,
            "title": revision.title,
            "body": revision.body,
            "author": "member" if review.author_user_id else "guest",
            "guest_display_name": review.guest_display_name,
            "author_display_name": session.scalar(select(User.display_name).where(User.id == review.author_user_id)) if review.author_user_id else None,
            "media": [
                media.describe(item)
                for item in session.scalars(
                    select(ReviewMedia).where(ReviewMedia.review_id == review.id, ReviewMedia.state == "pending").order_by(ReviewMedia.position)
                )
            ],
            "created_at": review.created_at.isoformat(),
        }
    if task.task_type == "report":
        report = session.get(Report, task.subject_id)
        if report is None:
            return None
        reported = session.get(Review, report.review_id)
        reported_revision = session.get(ReviewRevision, reported.current_revision_id) if reported else None
        return {
            "kind": "report",
            "report_id": str(report.id),
            "state": report.state,
            "version": report.version,
            "reason_code": report.reason_code,
            "details": report.details,
            "review_id": str(report.review_id),
            "review_status": reported.status.value if reported else None,
            "review_version": reported.version if reported else None,
            "review_title": reported_revision.title if reported_revision else None,
            "review_body": reported_revision.body if reported_revision else None,
            "created_at": report.created_at.isoformat(),
        }
    return _case_summary(session, task)


def _case_summary(session: Session, task: ModerationTask) -> dict[str, Any] | None:
    """Queue summaries for verification, appeal and emergency-enforcement tasks (no evidence URLs here)."""
    if task.task_type == "verification":
        case = session.get(VerificationCase, task.subject_id)
        if case is None:
            return None
        applicant = session.get(User, case.applicant_user_id)
        evidence = session.scalars(select(VerificationEvidence).where(VerificationEvidence.case_id == case.id, VerificationEvidence.status == "uploaded"))
        return {
            "kind": "verification",
            "case_id": str(case.id),
            "state": case.state,
            "version": case.version,
            "statement": case.statement,
            "applicant": {"display_name": applicant.display_name, "email": applicant.email} if applicant else None,
            "evidence": [{"id": str(e.id), "content_type": e.content_type} for e in evidence],
            "created_at": case.created_at.isoformat(),
        }
    if task.task_type == "appeal":
        appeal = session.get(Appeal, task.subject_id)
        if appeal is None:
            return None
        target = next(t for t in ("moderation_action", "enforcement_case", "verification_case") if getattr(appeal, f"{t}_id"))
        return {
            "kind": "appeal",
            "appeal_id": str(appeal.id),
            "reference": str(appeal.id)[:8],
            "state": appeal.state,
            "version": appeal.version,
            "reason": appeal.reason,
            "target_type": target,
            "target_id": str(getattr(appeal, f"{target}_id")),
            "original_decider_is_you": None,  # filled per viewer in queue()
            "original_decider_id": str(appeal.original_decider_id) if appeal.original_decider_id else None,
            "deadline_at": appeal.deadline_at.isoformat(),
            "submitted_at": appeal.submitted_at.isoformat(),
        }
    if task.task_type == "enforcement":
        ecase = session.get(EnforcementCase, task.subject_id)
        if ecase is None:
            return None
        return _enforcement_view(session, ecase) | {"kind": "enforcement"}
    return None


def _enforcement_view(session: Session, case: EnforcementCase) -> dict[str, Any]:
    review = session.get(Review, case.review_id) if case.review_id else None
    revision = session.get(ReviewRevision, review.current_revision_id) if review and review.current_revision_id else None
    subject = session.get(User, case.subject_user_id) if case.subject_user_id else None
    sanctions = session.scalars(select(Sanction).where(Sanction.enforcement_case_id == case.id).order_by(Sanction.created_at))
    return {
        "case_id": str(case.id),
        "case_kind": case.kind,
        "state": case.state,
        "version": case.version,
        "emergency": case.emergency,
        "counts_toward_rating": case.counts_toward_rating,
        "follow_up_due_at": case.follow_up_due_at.isoformat() if case.follow_up_due_at else None,
        "reason_code": case.reason_code,
        "note": case.note,
        "review": {"id": str(review.id), "status": review.status.value, "title": revision.title if revision else None} if review else None,
        "user": {"id": str(subject.id), "display_name": subject.display_name, "email": subject.email, "status": subject.status} if subject else None,
        "sanctions": [
            {"id": str(s.id), "kind": s.kind, "state": s.state, "ends_at": s.ends_at.isoformat() if s.ends_at else None, "review_on": s.review_on.isoformat() if s.review_on else None}
            for s in sanctions
        ],
        "created_at": case.created_at.isoformat(),
    }


@router.post("/tasks/{task_id}/claim")
def claim_task(task_id: uuid.UUID, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    task = _run(session, principal, request, "task.claim", "task", task_id,
                lambda: tasks.claim(session, principal, task_id, request_id=_request_id(request)))
    return tasks.serialize(task, include_lease_token=True)


@router.post("/tasks/{task_id}/heartbeat")
def heartbeat_task(task_id: uuid.UUID, body: LeaseBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    task = _run(session, principal, request, "task.heartbeat", "task", task_id,
                lambda: tasks.heartbeat(session, principal, task_id, body.lease_token))
    return tasks.serialize(task, include_lease_token=True)


@router.post("/tasks/{task_id}/release")
def release_task(task_id: uuid.UUID, body: LeaseBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    task = _run(session, principal, request, "task.release", "task", task_id,
                lambda: tasks.release(session, principal, task_id, body.lease_token, request_id=_request_id(request)))
    return tasks.serialize(task)


class AssignBody(_Body):
    user_id: uuid.UUID | None


@router.post("/tasks/{task_id}/assign")
def assign_task(task_id: uuid.UUID, body: AssignBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    """A superadmin gives a task to one staff member, or back to the shared queue with ``user_id: null``."""
    task = _run(session, principal, request, "task.assign", "task", task_id,
                lambda: tasks.assign(session, principal, task_id, body.user_id, request_id=_request_id(request)))
    return tasks.serialize(task)


@router.post("/tasks/{task_id}/escalate")
def escalate_task(task_id: uuid.UUID, body: EscalateBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    task = _run(session, principal, request, "task.escalate", "task", task_id,
                lambda: tasks.escalate(session, principal, task_id, body.lease_token, body.reason, request_id=_request_id(request)))
    return tasks.serialize(task)


# ---- decisions ----


def _decide(session: Session, principal: Principal, request: Request, review_id: uuid.UUID, body: DecisionBody) -> tuple[int, dict[str, Any]]:
    result = actions.moderate_submission(
        session,
        principal,
        review_id=review_id,
        task_id=body.task_id,
        lease_token=body.lease_token,
        expected_version=body.expected_version,
        decision=ModerationDecision(body.decision),
        reason_code=body.reason_code,
        note=body.note,
        request_id=_request_id(request),
        rejected_media_ids=set(body.rejected_media_ids),
    )
    return 200, result


@router.post("/submissions/{review_id}/moderation-actions")
def moderate(
    review_id: uuid.UUID,
    body: DecisionBody,
    request: Request,
    response: Response,
    principal: Staff,
    session: DbSession,
    idempotency_key: IdempotencyHeader = None,
) -> dict[str, Any]:
    def work() -> tuple[int, dict[str, Any]]:
        return idempotency.run(
            session,
            actor_id=principal.user.id,
            operation=f"moderate:{review_id}",
            key=idempotency_key,
            payload=body.model_dump(mode="json"),
            action=lambda: _decide(session, principal, request, review_id, body),
        )

    status_code, result = _run(session, principal, request, "review.moderate", "review", review_id, work)
    response.status_code = status_code
    return result


@router.post("/submissions/{review_id}/media/{media_id}/url")
def media_url(review_id: uuid.UUID, media_id: uuid.UUID, principal: Staff, session: DbSession, storage: StorageDep) -> dict[str, Any]:
    """A five-minute link to a checked photo or video, so a moderator can look before deciding."""
    try:
        url = media.staff_url(session, storage, review_id, media_id)
    except StorageUnavailable as error:
        raise ApiError("SERVICE_UNAVAILABLE", headers={"Retry-After": "5"}) from error
    return {"url": url, "expires_in": media.STAFF_URL_SECONDS}


class MediaDecisionBody(_Body):
    decision: str = Field(pattern="^(approve|reject)$")
    reason_code: str = Field(min_length=2, max_length=60)


@router.get("/media")
def list_media(
    principal: Staff,
    session: DbSession,
    state: Annotated[str | None, Query(pattern="^(pending|approved|rejected)$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """Recent review photos and videos, to find and correct a media decision."""
    return {"items": media.staff_list(session, state, limit)}


@router.post("/media/{media_id}/decision")
def decide_media(media_id: uuid.UUID, body: MediaDecisionBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    """Approve or reject one photo or video after its review was decided; audited as media.approve / media.reject."""

    def work() -> dict[str, Any]:
        item, previous = media.change_decision(session, media_id, body.decision == "approve", principal.user.id)
        audit.record(
            session, actor=principal, action=f"media.{body.decision}", target_type="review_media", target_id=item.id,
            reason=body.reason_code, metadata={"from": previous, "to": item.state, "review_id": str(item.review_id)},
            request_id=_request_id(request),
        )
        return media.describe(item)

    return _run(session, principal, request, f"media.{body.decision}", "review_media", media_id, work)


@router.post("/submissions/{review_id}/conflict")
def set_conflict(review_id: uuid.UUID, body: ConflictBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    return _run(
        session, principal, request, "review.conflict", "review", review_id,
        lambda: actions.change_conflict(
            session, principal, review_id=review_id, expected_version=body.expected_version,
            conflict_declared=body.conflict_declared, reason_code=body.reason_code, note=body.note,
            request_id=_request_id(request),
        ),
    )


@router.post("/bulk/moderation-actions")
def bulk_moderate(body: BulkBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    """Each item is atomic on its own; the batch may partly succeed (spec 8.4)."""
    results: list[dict[str, Any]] = []
    for item in body.items:
        try:
            with session.begin_nested():
                _, result = _decide(session, principal, request, item.review_id, item)
            results.append({"review_id": str(item.review_id), "ok": True, "result": result})
        except ApiError as error:
            results.append({"review_id": str(item.review_id), "ok": False, "error": error.code})
    _commit_or_rollback(session)
    return {"results": results, "succeeded": sum(1 for r in results if r["ok"]), "failed": sum(1 for r in results if not r["ok"])}


# ---- reports ----


@router.post("/reports/{report_id}/transition")
def transition_report(report_id: uuid.UUID, body: ReportTransitionBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    return _run(
        session, principal, request, "report.transition", "report", report_id,
        lambda: actions.transition_report(
            session, principal, report_id=report_id, to=body.to, expected_version=body.expected_version,
            reason_code=body.reason_code, note=body.note, task_id=body.task_id, lease_token=body.lease_token,
            request_id=_request_id(request),
        ),
    )


@member_router.post("/reviews/{review_id}/reports", status_code=201)
def report_review(review_id: uuid.UUID, body: ReportBody, principal: MemberPrincipal, request: Request, session: DbSession) -> dict[str, Any]:
    """A signed-in member reports a published review (API.md 4.4)."""
    from app.auth import csrf  # noqa: PLC0415 - a member write needs the same CSRF proof as staff writes

    csrf.check_origin(request)
    csrf.require_valid(request, principal.csrf_binding)
    report = _run(session, principal, request, "report.create", "review", review_id,
                  lambda: actions.create_report(session, principal, review_id=review_id, reason_code=body.reason_code, details=body.details))
    return {"report_id": str(report.id), "state": report.state, "version": report.version}


# ---- audit ----


def _audit_item(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "occurred_at": event.occurred_at.isoformat(),
        "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
        "actor_role": event.actor_role_snapshot,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "request_id": event.request_id,
        "reason": event.reason,
        "metadata": event.event_metadata,
    }


@router.get("/audit-events")
def audit_events(
    principal: Staff,
    session: DbSession,
    action: Annotated[str | None, Query(max_length=80)] = None,
    target_type: Annotated[str | None, Query(max_length=40)] = None,
    target_id: Annotated[str | None, Query(max_length=64)] = None,
    actor_user_id: uuid.UUID | None = None,
    before: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    del principal
    statement = select(AuditEvent).order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc()).limit(limit)
    if action:
        statement = statement.where(AuditEvent.action == action)
    if target_type:
        statement = statement.where(AuditEvent.target_type == target_type)
    if target_id:
        statement = statement.where(AuditEvent.target_id == target_id)
    if actor_user_id:
        statement = statement.where(AuditEvent.actor_user_id == actor_user_id)
    if before:
        statement = statement.where(AuditEvent.occurred_at < before)
    items = [_audit_item(event) for event in session.scalars(statement)]
    return {"items": items, "next_before": items[-1]["occurred_at"] if len(items) == limit else None}


@router.get("/audit-events/{event_id}")
def audit_event(event_id: uuid.UUID, principal: Staff, session: DbSession) -> dict[str, Any]:
    del principal
    event = session.get(AuditEvent, event_id)
    if event is None:
        raise ApiError("NOT_FOUND")
    return _audit_item(event)


# ---- staff roles ----


@router.get("/staff")
def list_staff(principal: Superadmin, session: DbSession) -> dict[str, Any]:
    del principal
    rows = session.execute(
        select(User, UserRole)
        .join(UserRole, UserRole.user_id == User.id)
        .where(UserRole.revoked_at.is_(None))
        .order_by(User.display_name)
    ).all()
    return {
        "items": [
            {"user_id": str(user.id), "display_name": user.display_name, "email": user.email, "role": role.role, "granted_at": role.granted_at.isoformat()}
            for user, role in rows
        ]
    }


@router.get("/users")
def search_users(principal: Superadmin, session: DbSession, q: Annotated[str, Query(min_length=3, max_length=100)]) -> dict[str, Any]:
    """Find accounts by part of an email address, to grant a role (superadmin only, at most 10 rows)."""
    del principal
    escaped = q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = session.execute(
        select(User, UserRole.role)
        .outerjoin(UserRole, (UserRole.user_id == User.id) & UserRole.revoked_at.is_(None))
        .where(func.lower(User.email).like(f"%{escaped}%", escape="\\"))
        .order_by(User.email)
        .limit(10)
    ).all()
    return {
        "items": [
            {"user_id": str(user.id), "display_name": user.display_name, "email": user.email, "status": user.status, "role": role}
            for user, role in rows
        ]
    }


@router.post("/staff/{user_id}/role")
def change_staff_role(user_id: uuid.UUID, body: RoleBody, request: Request, principal: Superadmin, session: DbSession) -> dict[str, Any]:
    """Grant, change or revoke a staff role. Needs a superadmin who confirmed their password in the last 10 minutes."""
    def work() -> dict[str, Any]:
        require_recent_auth(principal)
        roles.set_staff_role(
            session, actor=principal, target_user_id=user_id, role=body.role, reason=body.reason, request_id=_request_id(request)
        )
        return {"user_id": str(user_id), "role": body.role}

    return _run(session, principal, request, "staff.role", "user", user_id, work)


# ---- monitoring ----


# ---- verification cases (spec 6.2, 7.1) ----


class VerificationTransitionBody(_Body):
    to: str = Field(pattern="^(in_review|needs_clarification|approved|rejected|escalated)$")
    expected_version: int = Field(ge=1)
    reason_code: str = Field(min_length=2, max_length=60)
    note: str | None = Field(default=None, max_length=500)
    task_id: uuid.UUID
    lease_token: uuid.UUID


@router.post("/verification-cases/{case_id}/transition")
def verification_transition(case_id: uuid.UUID, body: VerificationTransitionBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    return _run(
        session, principal, request, "verification.transition", "verification_case", case_id,
        lambda: cases.staff_verification_transition(
            session, principal, case_id=case_id, to=body.to, expected_version=body.expected_version, task_id=body.task_id,
            lease_token=body.lease_token, reason_code=body.reason_code, note=body.note, request_id=_request_id(request),
        ),
    )


@router.post("/verification-cases/{case_id}/evidence/{evidence_id}/url")
def evidence_url(case_id: uuid.UUID, evidence_id: uuid.UUID, request: Request, principal: Staff, session: DbSession, storage: StorageDep) -> dict[str, Any]:
    """A 60-second private link for the staff member holding the case. Every view is audited."""
    return _run(session, principal, request, "evidence.view", "verification_case", case_id,
                lambda: cases.evidence_download(session, storage, principal, case_id, evidence_id, request_id=_request_id(request)))


# ---- enforcement and sanctions (spec 6.4, 7.3) ----


class SanctionBody(_Body):
    kind: str = Field(pattern="^(warning|posting_restriction|suspension)$")
    ends_at: datetime | None = None
    review_on: date | None = None


class EnforcementBody(_Body):
    review_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    reason_code: str = Field(min_length=2, max_length=60)
    note: str | None = Field(default=None, max_length=500)
    emergency: bool = False
    counts_toward_rating: bool = True
    sanction: SanctionBody | None = None


class EnforcementActionBody(_Body):
    action: str = Field(pattern="^(remove|restore|close|reverse_sanction)$")
    expected_version: int = Field(ge=1)
    reason_code: str = Field(min_length=2, max_length=60)
    note: str | None = Field(default=None, max_length=500)
    counts_toward_rating: bool | None = None
    sanction_id: uuid.UUID | None = None


@router.get("/enforcement-cases")
def enforcement_cases(principal: Staff, session: DbSession, state: Annotated[str | None, Query(max_length=12)] = None) -> dict[str, Any]:
    del principal
    statement = select(EnforcementCase).order_by(EnforcementCase.created_at.desc()).limit(100)
    if state:
        statement = statement.where(EnforcementCase.state == state)
    return {"items": [_enforcement_view(session, case) for case in session.scalars(statement)]}


@router.post("/enforcement-cases", status_code=201)
def open_enforcement(body: EnforcementBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    case = _run(
        session, principal, request, "enforcement.open", "enforcement_case", body.review_id or body.user_id,
        lambda: cases.open_enforcement(
            session, principal, review_id=body.review_id, user_id=body.user_id, reason_code=body.reason_code, note=body.note,
            emergency=body.emergency, counts_toward_rating=body.counts_toward_rating,
            sanction=body.sanction.model_dump() if body.sanction else None, request_id=_request_id(request),
        ),
    )
    return _enforcement_view(session, case)


@router.post("/enforcement-cases/{case_id}/actions")
def enforcement_action(case_id: uuid.UUID, body: EnforcementActionBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    return _run(
        session, principal, request, "enforcement.action", "enforcement_case", case_id,
        lambda: cases.enforcement_action(
            session, principal, case_id=case_id, action=body.action, expected_version=body.expected_version, reason_code=body.reason_code,
            note=body.note, counts_toward_rating=body.counts_toward_rating, sanction_id=body.sanction_id, request_id=_request_id(request),
        ),
    )


# ---- appeals (spec 6.5, 7.4) ----


class AppealDecisionBody(_Body):
    outcome: str = Field(pattern="^(upheld|overturned)$")
    expected_version: int = Field(ge=1)
    note: str = Field(min_length=3, max_length=500)
    task_id: uuid.UUID
    lease_token: uuid.UUID


@router.post("/appeals/{appeal_id}/decision")
def decide_appeal(appeal_id: uuid.UUID, body: AppealDecisionBody, request: Request, principal: Staff, session: DbSession) -> dict[str, Any]:
    return _run(
        session, principal, request, "appeal.decide", "appeal", appeal_id,
        lambda: cases.decide_appeal(
            session, principal, appeal_id=appeal_id, outcome=body.outcome, expected_version=body.expected_version, note=body.note,
            task_id=body.task_id, lease_token=body.lease_token, request_id=_request_id(request),
        ),
    )


@router.get("/monitoring/summary")
def monitoring_summary(principal: Staff, session: DbSession) -> dict[str, Any]:
    del principal
    now = datetime.now(UTC)
    open_tasks = ModerationTask.status == "open"
    oldest = session.scalar(select(func.min(ModerationTask.created_at)).where(open_tasks))
    return {
        "generated_at": now.isoformat(),
        "queue_depth": session.scalar(select(func.count()).select_from(ModerationTask).where(open_tasks)) or 0,
        "oldest_open_task_age_seconds": int((now - oldest).total_seconds()) if oldest else None,
        "escalated_open": session.scalar(select(func.count()).select_from(ModerationTask).where(open_tasks, ModerationTask.escalated.is_(True))) or 0,
        "expired_claims": session.scalar(
            select(func.count()).select_from(ModerationTask).where(open_tasks, ModerationTask.claimed_by.is_not(None), ModerationTask.lease_expires_at < now)
        ) or 0,
        "open_reports": session.scalar(select(func.count()).select_from(Report).where(Report.state.in_(("open", "in_review")))) or 0,
        "outbox_pending": session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status.in_(("pending", "processing", "retry")))) or 0,
        "outbox_failed": session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "dead_letter")) or 0,
        "oldest_pending_event_age_seconds": _age(now, session.scalar(select(func.min(OutboxEvent.created_at)).where(OutboxEvent.status.in_(("pending", "processing", "retry"))))),
        "emails_failed_or_ambiguous": session.scalar(
            select(func.count()).select_from(NotificationDelivery).where(NotificationDelivery.status.in_(("failed_permanently", "ambiguous", "bounced")))
        ) or 0,
        "open_verification_cases": session.scalar(select(func.count()).select_from(VerificationCase).where(VerificationCase.state.in_(("submitted", "in_review", "needs_clarification", "escalated")))) or 0,
        "open_appeals": session.scalar(select(func.count()).select_from(Appeal).where(Appeal.state.in_(("received", "in_review")))) or 0,
        "emergency_overdue": session.scalar(
            select(func.count()).select_from(EnforcementCase).where(EnforcementCase.emergency.is_(True), EnforcementCase.state == "taken_down", EnforcementCase.follow_up_due_at < now)
        ) or 0,
        "active_sanctions": session.scalar(select(func.count()).select_from(Sanction).where(Sanction.state == "active")) or 0,
        "denied_last_24h": session.scalar(
            select(func.count()).select_from(AuditEvent).where(AuditEvent.action.like("denied.%"), AuditEvent.occurred_at > now - timedelta(hours=24))
        ) or 0,
    }


def _age(now: datetime, moment: datetime | None) -> int | None:
    return int((now - moment).total_seconds()) if moment else None
