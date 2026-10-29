"""Verification cases, enforcement and sanctions, and appeals (Moderation spec 6.2 to 6.5, 7.1 to 7.4).

Each workflow has an explicit transition table below; anything not listed is refused with 422. Every
change re-checks state, version and (for staff) the claim lease, writes an audit event and an outbox
event, and is committed once by the route. Times are server UTC; appeal deadlines are the end of the
30th day in the display time zone (Asia/Dhaka).
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.admin import audit, tasks
from app.auth.sessions import Principal
from app.errors import ApiError
from app.models import (
    Appeal,
    EnforcementCase,
    ModerationActionRecord,
    ModerationDecision,
    ModerationTask,
    Review,
    ReviewStatus,
    Sanction,
    User,
    UserRole,
    Verification,
    VerificationCase,
    VerificationEvidence,
)
from app.notify import events
from app.services import ReviewError, appeal_deadline, moderate_review
from app.storage import ALLOWED_TYPES, MAX_BYTES, StorageClient

APPROVED_EVIDENCE_HOURS = 24  # Security 3.7: evidence is erased within 24 hours of a decision
REJECTED_CASE_DAYS = 30  # spec 10: rejected verification cases are kept 30 days
EMERGENCY_FOLLOW_UP_HOURS = 24
MAX_EVIDENCE = 3

# ---- transition tables (spec 7) ----

# (from, to) -> who may request it
VERIFICATION_TRANSITIONS: dict[tuple[str, str], frozenset[str]] = {
    ("submitted", "in_review"): frozenset({"moderator", "superadmin"}),
    ("in_review", "needs_clarification"): frozenset({"moderator", "superadmin"}),
    ("needs_clarification", "in_review"): frozenset({"applicant"}),
    ("in_review", "approved"): frozenset({"moderator", "superadmin"}),
    ("in_review", "rejected"): frozenset({"moderator", "superadmin"}),
    ("submitted", "escalated"): frozenset({"moderator", "superadmin"}),
    ("in_review", "escalated"): frozenset({"moderator", "superadmin"}),
    ("escalated", "approved"): frozenset({"superadmin"}),
    ("escalated", "rejected"): frozenset({"superadmin"}),
    ("submitted", "withdrawn"): frozenset({"applicant"}),
    ("in_review", "withdrawn"): frozenset({"applicant"}),
    ("needs_clarification", "withdrawn"): frozenset({"applicant"}),
}
ENFORCEMENT_ACTIONS: dict[str, frozenset[str]] = {  # action -> states it may start from
    "remove": frozenset({"taken_down"}),
    "restore": frozenset({"taken_down", "removed"}),
    "close": frozenset({"open"}),
}
APPEAL_OUTCOMES = frozenset({"upheld", "overturned"})
APPEALABLE_DECISIONS = frozenset({ModerationDecision.REJECT, ModerationDecision.HIDE})


def _now() -> datetime:
    return datetime.now(UTC)


def active_staff_ids(session: Session, *, exclude: uuid.UUID | None = None, roles: tuple[str, ...] = ("moderator", "superadmin")) -> list[str]:
    """The intended staff recipients of an event; re-checked when the notification is created (spec 11)."""
    rows = session.scalars(select(UserRole.user_id).where(UserRole.revoked_at.is_(None), UserRole.role.in_(roles)))
    return [str(user_id) for user_id in rows if user_id != exclude]


def emit(session: Session, topic: str, aggregate_id: uuid.UUID, payload: dict[str, Any]) -> None:
    events.emit(session, topic, aggregate_id, payload, aggregate_type=topic.split(".", 1)[0])


def is_verified_member(session: Session, user_id: uuid.UUID) -> bool:
    now = _now()
    return (
        session.scalar(
            select(Verification.id).where(
                Verification.user_id == user_id,
                Verification.verification_type == "VERIFIED_MEMBER",
                Verification.status == "APPROVED",
                Verification.revoked_at.is_(None),
                (Verification.expires_at.is_(None)) | (Verification.expires_at > now),
            )
        )
        is not None
    )


def ensure_not_restricted(session: Session, user_id: uuid.UUID) -> None:
    """An active posting restriction or suspension blocks member writes (spec 6.4)."""
    restricted = session.scalar(
        select(Sanction.id).where(
            Sanction.user_id == user_id,
            Sanction.state == "active",
            Sanction.kind.in_(("posting_restriction", "suspension")),
        )
    )
    if restricted is not None:
        raise ApiError("ACCOUNT_RESTRICTED")


# =========================================================================================
# Verification (spec 6.2, 7.1)
# =========================================================================================


def open_verification(session: Session, applicant: Principal, statement: str | None) -> VerificationCase:
    ensure_not_restricted(session, applicant.user.id)
    if is_verified_member(session, applicant.user.id):
        raise ApiError("ALREADY_VERIFIED")
    case = VerificationCase(applicant_user_id=applicant.user.id, statement=statement)
    try:
        with session.begin_nested():
            session.add(case)
            session.flush()
    except IntegrityError as error:
        raise ApiError("VERIFICATION_ALREADY_OPEN") from error
    tasks.ensure_task(session, "verification", case.id)
    audit.record(session, actor=applicant, action="verification.submitted", target_type="verification_case", target_id=case.id)
    emit(session, "verification.submitted", case.id, {"case_id": str(case.id), "applicant_id": str(applicant.user.id), "staff_recipients": active_staff_ids(session, exclude=applicant.user.id)})
    return case


def _own_case(session: Session, applicant: Principal, case_id: uuid.UUID) -> VerificationCase:
    case = session.scalar(select(VerificationCase).where(VerificationCase.id == case_id).with_for_update())
    if case is None or case.applicant_user_id != applicant.user.id:
        raise ApiError("NOT_FOUND")
    return case


def request_evidence_upload(
    session: Session, storage: StorageClient, applicant: Principal, case_id: uuid.UUID, content_type: str, size_bytes: int
) -> dict[str, Any]:
    case = _own_case(session, applicant, case_id)
    if case.state not in ("submitted", "in_review", "needs_clarification"):
        raise ApiError("TRANSITION_NOT_ALLOWED")
    if content_type not in ALLOWED_TYPES or not 0 < size_bytes <= MAX_BYTES:
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "content_type" if content_type not in ALLOWED_TYPES else "size_bytes", "code": "INVALID_VALUE"}])
    count = session.scalar(
        select(func.count()).select_from(VerificationEvidence).where(VerificationEvidence.case_id == case.id, VerificationEvidence.status != "deleted")
    )
    if (count or 0) >= MAX_EVIDENCE:
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "evidence", "code": "TOO_MANY"}])
    extension = {"image/jpeg": "jpg", "image/png": "png", "application/pdf": "pdf"}[content_type]
    evidence = VerificationEvidence(
        case_id=case.id, object_key=f"{case.id}/{uuid.uuid4()}.{extension}", content_type=content_type, uploaded_by=applicant.user.id
    )
    session.add(evidence)
    session.flush()
    upload_url = storage.signed_upload_url(evidence.object_key)
    audit.record(session, actor=applicant, action="evidence.upload_requested", target_type="verification_case", target_id=case.id, metadata={"evidence_id": str(evidence.id), "content_type": content_type})
    return {"evidence_id": str(evidence.id), "upload_url": upload_url, "content_type": content_type, "max_bytes": MAX_BYTES}


def complete_evidence_upload(session: Session, storage: StorageClient, applicant: Principal, case_id: uuid.UUID, evidence_id: uuid.UUID) -> VerificationEvidence:
    _own_case(session, applicant, case_id)
    evidence = session.get(VerificationEvidence, evidence_id)
    if evidence is None or evidence.case_id != case_id or evidence.status == "deleted":
        raise ApiError("NOT_FOUND")
    if evidence.status == "uploaded":
        return evidence
    if not storage.exists(evidence.object_key):
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "evidence", "code": "NOT_UPLOADED"}])
    evidence.status = "uploaded"
    audit.record(session, actor=applicant, action="evidence.uploaded", target_type="verification_case", target_id=case_id, metadata={"evidence_id": str(evidence.id)})
    return evidence


def applicant_transition(session: Session, applicant: Principal, case_id: uuid.UUID, to: str, statement: str | None) -> VerificationCase:
    case = _own_case(session, applicant, case_id)
    if "applicant" not in VERIFICATION_TRANSITIONS.get((case.state, to), frozenset()):
        raise ApiError("TRANSITION_NOT_ALLOWED")
    previous = case.state
    case.state, case.version, case.updated_at = to, case.version + 1, _now()
    if statement:
        case.statement = statement
    if to == "withdrawn":
        case.purge_after = _now() + timedelta(days=REJECTED_CASE_DAYS)
    if to == "in_review":  # the applicant answered: back into the queue
        tasks.ensure_task(session, "verification", case.id)
    else:
        tasks.cancel_open_tasks(session, case.id)
    audit.record(session, actor=applicant, action=f"verification.{to}", target_type="verification_case", target_id=case.id, metadata={"from": previous, "to": to})
    emit(session, "verification.state_changed", case.id, {"case_id": str(case.id), "state": to, "applicant_id": str(case.applicant_user_id)})
    return case


def staff_verification_transition(
    session: Session,
    principal: Principal,
    *,
    case_id: uuid.UUID,
    to: str,
    expected_version: int,
    task_id: uuid.UUID,
    lease_token: uuid.UUID,
    reason_code: str,
    note: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    case = session.scalar(select(VerificationCase).where(VerificationCase.id == case_id).with_for_update())
    if case is None:
        raise ApiError("NOT_FOUND")
    task = tasks.require_lease(session, principal, task_id, lease_token, case_id)
    if case.applicant_user_id == principal.user.id:
        raise ApiError("FORBIDDEN")  # nobody decides their own case
    if case.version != expected_version:
        raise ApiError("REVIEW_VERSION_CONFLICT")
    allowed = VERIFICATION_TRANSITIONS.get((case.state, to))
    if allowed is None:
        raise ApiError("TRANSITION_NOT_ALLOWED")
    if principal.role not in allowed:
        raise ApiError("FORBIDDEN")
    if to == "needs_clarification" and not note:
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "note", "code": "REQUIRED"}])
    now = _now()
    if to == "approved":
        uploaded = session.scalar(
            select(func.count()).select_from(VerificationEvidence).where(VerificationEvidence.case_id == case.id, VerificationEvidence.status == "uploaded")
        )
        if not uploaded:
            raise ApiError("EVIDENCE_REQUIRED")
        session.add(
            Verification(
                user_id=case.applicant_user_id, verification_type="VERIFIED_MEMBER", status="APPROVED",
                method="MANUAL_REVIEW", approved_by=principal.user.id, decided_at=now,
            )
        )
    previous = case.state
    case.state, case.version, case.updated_at = to, case.version + 1, now
    if to in ("approved", "rejected"):
        case.decided_by, case.decided_at, case.decision_reason, case.decision_note = principal.user.id, now, reason_code, note
        case.purge_after = now + (timedelta(hours=APPROVED_EVIDENCE_HOURS) if to == "approved" else timedelta(days=REJECTED_CASE_DAYS))
        tasks.complete(task)
    elif to == "needs_clarification":
        case.decision_note = note  # the question the applicant sees
        tasks.complete(task)  # waits for the applicant; their answer queues it again
    elif to == "escalated":
        task.escalated, task.required_role = True, "superadmin"
        task.claimed_by = task.claimed_at = task.lease_expires_at = task.lease_token = None
        task.version += 1
    audit.record(
        session, actor=principal, action=f"verification.{to}", target_type="verification_case", target_id=case.id,
        reason=reason_code, metadata={"from": previous, "to": to, "version": case.version}, request_id=request_id,
    )
    facts = {"case_id": str(case.id), "state": to, "applicant_id": str(case.applicant_user_id)}
    if to == "needs_clarification":
        facts["question"] = (note or "")[:300]  # meant for the applicant; moderator-only notes are never sent
    emit(session, "verification.state_changed", case.id, facts)
    return {"case_id": str(case.id), "state": case.state, "version": case.version}


def evidence_download(
    session: Session, storage: StorageClient, principal: Principal, case_id: uuid.UUID, evidence_id: uuid.UUID, *, request_id: str | None
) -> dict[str, Any]:
    """A 60-second link, only for the staff member holding this case (or a superadmin). Every view is audited."""
    evidence = session.get(VerificationEvidence, evidence_id)
    if evidence is None or evidence.case_id != case_id or evidence.status != "uploaded":
        raise ApiError("NOT_FOUND")
    case = session.get(VerificationCase, case_id)
    if case is None or case.applicant_user_id == principal.user.id:
        raise ApiError("FORBIDDEN")
    if principal.role != "superadmin":
        holder = session.scalar(
            select(ModerationTask.id).where(
                ModerationTask.subject_id == case_id,
                ModerationTask.status == "open",
                ModerationTask.claimed_by == principal.user.id,
                ModerationTask.lease_expires_at > _now(),
            )
        )
        if holder is None:
            raise ApiError("FORBIDDEN")
    url = storage.signed_download_url(evidence.object_key)
    audit.record(session, actor=principal, action="evidence.viewed", target_type="verification_case", target_id=case_id, metadata={"evidence_id": str(evidence.id)}, request_id=request_id)
    return {"url": url, "expires_in": 60, "content_type": evidence.content_type}


# =========================================================================================
# Enforcement and sanctions (spec 6.4, 7.3)
# =========================================================================================


def _hide_review(session: Session, principal: Principal, review: Review, reason_code: str, request_id: str | None) -> None:
    try:
        moderate_review(
            session, review_id=review.id, actor_user_id=principal.user.id, expected_version=review.version,
            decision=ModerationDecision.HIDE, reason_code=reason_code, note=None, request_id=request_id,
        )
    except ReviewError as error:
        raise ApiError("TRANSITION_NOT_ALLOWED" if error.code == "INVALID_TRANSITION" else error.code) from error


def _restore_review(session: Session, principal: Principal, review: Review, reason_code: str, request_id: str | None) -> None:
    if review.status != ReviewStatus.HIDDEN:
        return
    try:
        moderate_review(
            session, review_id=review.id, actor_user_id=principal.user.id, expected_version=review.version,
            decision=ModerationDecision.RESTORE, reason_code=reason_code, note=None, request_id=request_id,
        )
    except ReviewError as error:
        raise ApiError(error.code) from error


def _set_account_state(session: Session, user_id: uuid.UUID) -> None:
    """A user is disabled exactly while an active suspension exists."""
    user = session.get(User, user_id)
    if user is None:
        return
    suspended = session.scalar(select(Sanction.id).where(Sanction.user_id == user_id, Sanction.state == "active", Sanction.kind == "suspension"))
    user.status = "disabled" if suspended is not None else "active"
    user.disabled_at = _now() if suspended is not None else None


def open_enforcement(
    session: Session,
    principal: Principal,
    *,
    review_id: uuid.UUID | None,
    user_id: uuid.UUID | None,
    reason_code: str,
    note: str | None,
    emergency: bool,
    counts_toward_rating: bool,
    sanction: dict[str, Any] | None,
    request_id: str | None,
) -> EnforcementCase:
    if (review_id is None) == (user_id is None):
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "target", "code": "INVALID_VALUE"}])
    now = _now()
    if review_id is not None:
        review = session.scalar(select(Review).where(Review.id == review_id).with_for_update())
        if review is None:
            raise ApiError("NOT_FOUND")
        if review.author_user_id == principal.user.id:
            raise ApiError("SELF_MODERATION_FORBIDDEN")
        if review.status != ReviewStatus.PUBLISHED:
            raise ApiError("TRANSITION_NOT_ALLOWED")
        _hide_review(session, principal, review, reason_code, request_id)
        case = EnforcementCase(
            kind="takedown", review_id=review_id, state="taken_down", emergency=emergency, counts_toward_rating=counts_toward_rating,
            follow_up_due_at=now + timedelta(hours=EMERGENCY_FOLLOW_UP_HOURS) if emergency else None,
            opened_by=principal.user.id, reason_code=reason_code, note=note,
        )
        subject_id: uuid.UUID | None = review.author_user_id
    else:
        assert user_id is not None
        if user_id == principal.user.id:
            raise ApiError("FORBIDDEN")
        target = session.get(User, user_id)
        if target is None:
            raise ApiError("NOT_FOUND")
        if session.scalar(select(UserRole.id).where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))) is not None and principal.role != "superadmin":
            raise ApiError("FORBIDDEN")  # only a superadmin acts against staff accounts
        case = EnforcementCase(kind="account", subject_user_id=user_id, state="open", emergency=emergency, counts_toward_rating=True, opened_by=principal.user.id, reason_code=reason_code, note=note)
        subject_id = user_id
    session.add(case)
    session.flush()
    if emergency:  # an emergency takedown always gets a superadmin follow-up (spec 6.4)
        tasks.ensure_task(session, "enforcement", case.id, priority=2, required_role="superadmin")
    audit.record(session, actor=principal, action="enforcement.opened", target_type="enforcement_case", target_id=case.id, reason=reason_code, metadata={"kind": case.kind, "emergency": emergency, "review_id": str(review_id) if review_id else None, "user_id": str(user_id) if user_id else None}, request_id=request_id)
    emit(session, "enforcement.opened", case.id, {"case_id": str(case.id), "kind": case.kind, "subject_id": str(subject_id) if subject_id else None, "emergency": emergency, "staff_recipients": active_staff_ids(session, exclude=principal.user.id, roles=("superadmin",)) if emergency else []})
    if sanction is not None:
        if subject_id is None:
            raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "sanction", "code": "NO_ACCOUNT"}])  # a guest review has no account
        add_sanction(session, principal, case, subject_id, **sanction, request_id=request_id)
    return case


def add_sanction(
    session: Session,
    principal: Principal,
    case: EnforcementCase,
    user_id: uuid.UUID,
    *,
    kind: str,
    ends_at: datetime | None = None,
    review_on: Any = None,
    scope: str = "reviews",
    request_id: str | None = None,
) -> Sanction:
    if kind not in ("warning", "posting_restriction", "suspension"):
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "sanction.kind", "code": "INVALID_VALUE"}])
    if ends_at is None and review_on is None:
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "sanction.ends_at", "code": "REQUIRED"}])
    if ends_at is not None and ends_at <= _now():
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "sanction.ends_at", "code": "TOO_SMALL"}])
    if kind == "suspension" and principal.role != "superadmin":
        raise ApiError("FORBIDDEN")
    sanction = Sanction(user_id=user_id, enforcement_case_id=case.id, kind=kind, scope=scope, ends_at=ends_at, review_on=review_on, reason_code=case.reason_code, created_by=principal.user.id)
    session.add(sanction)
    session.flush()
    _set_account_state(session, user_id)
    audit.record(session, actor=principal, action="sanction.created", target_type="user", target_id=user_id, reason=case.reason_code, metadata={"sanction_id": str(sanction.id), "kind": kind, "ends_at": ends_at.isoformat() if ends_at else None}, request_id=request_id)
    emit(session, "sanction.created", sanction.id, {"sanction_id": str(sanction.id), "user_id": str(user_id), "kind": kind})
    return sanction


def reverse_sanction(session: Session, principal: Principal | None, sanction: Sanction, *, expired: bool = False, request_id: str | None = None) -> None:
    if sanction.state != "active":
        raise ApiError("TRANSITION_NOT_ALLOWED")
    sanction.state = "expired" if expired else "reversed"
    sanction.reversed_at = _now()
    sanction.reversed_by = principal.user.id if principal else None
    _set_account_state(session, sanction.user_id)
    audit.record(session, actor=principal, action="sanction.expired" if expired else "sanction.reversed", target_type="user", target_id=sanction.user_id, metadata={"sanction_id": str(sanction.id)}, request_id=request_id)
    emit(session, "sanction.ended", sanction.id, {"sanction_id": str(sanction.id), "user_id": str(sanction.user_id), "kind": sanction.kind, "how": sanction.state})


def enforcement_action(
    session: Session, principal: Principal, *, case_id: uuid.UUID, action: str, expected_version: int,
    reason_code: str, note: str | None, counts_toward_rating: bool | None, sanction_id: uuid.UUID | None, request_id: str | None,
) -> dict[str, Any]:
    case = session.scalar(select(EnforcementCase).where(EnforcementCase.id == case_id).with_for_update())
    if case is None:
        raise ApiError("NOT_FOUND")
    if case.version != expected_version:
        raise ApiError("REVIEW_VERSION_CONFLICT")
    if case.opened_by == principal.user.id and case.emergency and principal.role != "superadmin":
        raise ApiError("FORBIDDEN")  # an emergency takedown is followed up by someone else
    if action == "reverse_sanction":
        sanction = session.get(Sanction, sanction_id) if sanction_id else None
        if sanction is None or sanction.enforcement_case_id != case.id:
            raise ApiError("NOT_FOUND")
        reverse_sanction(session, principal, sanction, request_id=request_id)
    else:
        if case.state not in ENFORCEMENT_ACTIONS.get(action, frozenset()):
            raise ApiError("TRANSITION_NOT_ALLOWED")
        if case.emergency and principal.role != "superadmin":
            raise ApiError("FORBIDDEN")
        review = session.get(Review, case.review_id) if case.review_id else None
        previous = case.state
        if action == "remove":
            case.state = "removed"
            if counts_toward_rating is not None:
                case.counts_toward_rating = counts_toward_rating
        elif action == "restore":
            assert review is not None
            _restore_review(session, principal, review, reason_code, request_id)
            case.state, case.counts_toward_rating = "restored", True
        elif action == "close":
            case.state = "closed"
        if case.state in ("removed", "restored", "closed"):
            case.closed_at = _now()
            for task in session.scalars(select(ModerationTask).where(ModerationTask.subject_id == case.id, ModerationTask.status == "open").with_for_update()):
                tasks.complete(task)
        audit.record(session, actor=principal, action=f"enforcement.{action}", target_type="enforcement_case", target_id=case.id, reason=reason_code, metadata={"from": previous, "to": case.state, "counts_toward_rating": case.counts_toward_rating}, request_id=request_id)
        emit(session, "enforcement.state_changed", case.id, {"case_id": str(case.id), "kind": case.kind, "state": case.state, "subject_id": str(case.subject_user_id or (review.author_user_id if review else None) or "")})
    case.version += 1
    case.updated_at = _now()
    if note:
        case.note = note
    return {"case_id": str(case.id), "state": case.state, "version": case.version, "counts_toward_rating": case.counts_toward_rating}


# =========================================================================================
# Appeals (spec 6.5, 7.4)
# =========================================================================================


def appealable_decisions(session: Session, user_id: uuid.UUID) -> list[dict[str, Any]]:
    """Decisions this member may appeal now, with their deadlines (the member's own content and cases)."""
    now = _now()
    items: list[dict[str, Any]] = []
    actions = session.execute(
        select(ModerationActionRecord, Review)
        .join(Review, Review.id == ModerationActionRecord.review_id)
        .where(Review.author_user_id == user_id, ModerationActionRecord.decision.in_(APPEALABLE_DECISIONS))
        .order_by(ModerationActionRecord.created_at.desc())
    ).all()
    for action, review in actions:
        if review.status.value != action.new_status.value:
            continue  # superseded by a later decision
        items.append({"target_type": "moderation_action", "target_id": str(action.id), "label": f"review {review.status.value.lower()}", "decided_at": action.created_at, "review_id": str(review.id)})
    for case in session.scalars(select(VerificationCase).where(VerificationCase.applicant_user_id == user_id, VerificationCase.state == "rejected")):
        items.append({"target_type": "verification_case", "target_id": str(case.id), "label": "verification rejected", "decided_at": case.decided_at or case.updated_at})
    enforcement = session.execute(
        select(EnforcementCase).outerjoin(Review, Review.id == EnforcementCase.review_id).where(
            (EnforcementCase.subject_user_id == user_id) | (Review.author_user_id == user_id),
            EnforcementCase.state.in_(("taken_down", "removed", "open")),
        )
    ).scalars()
    for ecase in enforcement:
        items.append({"target_type": "enforcement_case", "target_id": str(ecase.id), "label": f"enforcement {ecase.state}", "decided_at": ecase.created_at})
    result = []
    for item in items:
        deadline = appeal_deadline(item["decided_at"])
        existing = session.scalar(select(Appeal.state).where(getattr(Appeal, f"{item['target_type']}_id") == uuid.UUID(item["target_id"]), Appeal.state != "withdrawn"))
        result.append({**item, "decided_at": item["decided_at"].isoformat(), "deadline_at": deadline.isoformat(), "open": deadline > now and existing is None, "appeal_state": existing})
    return result


def _appeal_target(session: Session, user_id: uuid.UUID, target_type: str, target_id: uuid.UUID) -> tuple[datetime, uuid.UUID | None]:
    """Validate standing and appealability; return (decision time, original decider)."""
    if target_type == "moderation_action":
        action = session.get(ModerationActionRecord, target_id)
        review = session.get(Review, action.review_id) if action else None
        if action is None or review is None or review.author_user_id != user_id or action.decision not in APPEALABLE_DECISIONS:
            raise ApiError("NOT_FOUND")
        if review.status.value != action.new_status.value:
            raise ApiError("TRANSITION_NOT_ALLOWED")  # a later decision already replaced it
        return action.created_at, action.actor_user_id
    if target_type == "verification_case":  # locked: the retention job deletes this row under the same lock
        case = session.scalar(select(VerificationCase).where(VerificationCase.id == target_id).with_for_update())
        if case is None or case.applicant_user_id != user_id or case.state != "rejected":
            raise ApiError("NOT_FOUND")
        return case.decided_at or case.updated_at, case.decided_by
    if target_type == "enforcement_case":
        enforcement = session.get(EnforcementCase, target_id)
        review = session.get(Review, enforcement.review_id) if enforcement and enforcement.review_id else None
        owner = enforcement.subject_user_id if enforcement else None
        if enforcement is None or (owner != user_id and (review is None or review.author_user_id != user_id)):
            raise ApiError("NOT_FOUND")
        if enforcement.state not in ("taken_down", "removed", "open"):
            raise ApiError("TRANSITION_NOT_ALLOWED")
        return enforcement.created_at, enforcement.opened_by
    raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "target_type", "code": "INVALID_VALUE"}])


def create_appeal(session: Session, appellant: Principal, *, target_type: str, target_id: uuid.UUID, reason: str) -> Appeal:
    if target_type in ("moderation_action", "enforcement_case", "verification_case"):
        earlier = session.scalar(
            select(Appeal.id).where(getattr(Appeal, f"{target_type}_id") == target_id, Appeal.appellant_user_id == appellant.user.id, Appeal.state != "withdrawn")
        )
        if earlier is not None:  # one appeal per decision, decided or not (spec 6.5)
            raise ApiError("DUPLICATE_APPEAL")
    decided_at, decider = _appeal_target(session, appellant.user.id, target_type, target_id)
    deadline = appeal_deadline(decided_at)
    if _now() > deadline:
        raise ApiError("APPEAL_WINDOW_CLOSED")
    appeal = Appeal(appellant_user_id=appellant.user.id, reason=reason, original_decider_id=decider, deadline_at=deadline, **{f"{target_type}_id": target_id})
    try:
        with session.begin_nested():
            session.add(appeal)
            session.flush()
    except IntegrityError as error:
        raise ApiError("DUPLICATE_APPEAL") from error
    tasks.ensure_task(session, "appeal", appeal.id, priority=1)
    audit.record(session, actor=appellant, action="appeal.received", target_type="appeal", target_id=appeal.id, metadata={"target_type": target_type, "target_id": str(target_id), "deadline_at": deadline.isoformat()})
    emit(session, "appeal.received", appeal.id, {"appeal_id": str(appeal.id), "appellant_id": str(appellant.user.id), "deadline_at": deadline.isoformat(), "staff_recipients": active_staff_ids(session, exclude=decider)})
    return appeal


def create_guest_appeal(session: Session, review_id: uuid.UUID, *, statement: str) -> Appeal:
    """A Guest's appeal against the rejection of their review (Review.md 4.2, API.md 5.6).

    The caller has already proved ownership with the receipt. The appeal targets the rejection
    decision itself, so it follows the same rules as a member's: one per decision, 30-day window,
    independent reviewer. ``appellant_user_id`` stays empty because a Guest has no account.
    """
    review = session.scalar(select(Review).where(Review.id == review_id).with_for_update())
    if review is None:
        raise ApiError("NOT_FOUND")
    action = session.scalar(
        select(ModerationActionRecord)
        .where(ModerationActionRecord.review_id == review.id, ModerationActionRecord.decision == ModerationDecision.REJECT)
        .order_by(ModerationActionRecord.created_at.desc())
        .limit(1)
    )
    if review.status != ReviewStatus.REJECTED or action is None:
        raise ApiError("APPEAL_WINDOW_CLOSED")  # nothing to appeal (API.md 5.6)
    if session.scalar(select(Appeal.id).where(Appeal.moderation_action_id == action.id, Appeal.state != "withdrawn")) is not None:
        raise ApiError("DUPLICATE_APPEAL")
    deadline = appeal_deadline(action.created_at)
    if _now() > deadline:
        raise ApiError("APPEAL_WINDOW_CLOSED")
    appeal = Appeal(
        appellant_user_id=None,
        moderation_action_id=action.id,
        reason=statement,
        original_decider_id=action.actor_user_id,
        deadline_at=deadline,
    )
    try:
        with session.begin_nested():
            session.add(appeal)
            session.flush()
    except IntegrityError as error:
        raise ApiError("DUPLICATE_APPEAL") from error
    tasks.ensure_task(session, "appeal", appeal.id, priority=1)
    audit.record(
        session,
        actor=None,
        action="appeal.received",
        target_type="appeal",
        target_id=appeal.id,
        metadata={"target_type": "moderation_action", "target_id": str(action.id), "deadline_at": deadline.isoformat(), "by": "guest_receipt"},
    )
    emit(
        session,
        "appeal.received",
        appeal.id,
        {
            "appeal_id": str(appeal.id),
            "appellant_id": None,  # a Guest has no inbox; the receipt status shows the outcome
            "deadline_at": deadline.isoformat(),
            "staff_recipients": active_staff_ids(session, exclude=action.actor_user_id),
        },
    )
    return appeal


def withdraw_appeal(session: Session, appellant: Principal, appeal_id: uuid.UUID) -> Appeal:
    appeal = session.scalar(select(Appeal).where(Appeal.id == appeal_id).with_for_update())
    if appeal is None or appeal.appellant_user_id != appellant.user.id:
        raise ApiError("NOT_FOUND")
    if appeal.state not in ("received", "in_review"):
        raise ApiError("TRANSITION_NOT_ALLOWED")
    appeal.state, appeal.version = "withdrawn", appeal.version + 1
    tasks.cancel_open_tasks(session, appeal.id)
    audit.record(session, actor=appellant, action="appeal.withdrawn", target_type="appeal", target_id=appeal.id)
    return appeal


def _overturn(session: Session, principal: Principal, appeal: Appeal, request_id: str | None) -> None:
    """Undo the appealed decision. The original action and its audit history stay untouched."""
    if appeal.moderation_action_id:
        action = session.get(ModerationActionRecord, appeal.moderation_action_id)
        review = session.scalar(select(Review).where(Review.id == action.review_id).with_for_update()) if action else None
        if review is None:
            return
        if review.status == ReviewStatus.HIDDEN:
            _restore_review(session, principal, review, "appeal-overturned", request_id)
        elif review.status == ReviewStatus.REJECTED:  # back to the queue for a fresh, independent review
            review.status, review.version, review.updated_at = ReviewStatus.PENDING, review.version + 1, _now()
            tasks.ensure_task(session, "review_moderation", review.id)
    elif appeal.verification_case_id:
        vcase = session.get(VerificationCase, appeal.verification_case_id)
        if vcase is not None and not is_verified_member(session, vcase.applicant_user_id):
            session.add(Verification(user_id=vcase.applicant_user_id, verification_type="VERIFIED_MEMBER", status="APPROVED", method="APPEAL", approved_by=principal.user.id, decided_at=_now()))
    elif appeal.enforcement_case_id:
        ecase = session.scalar(select(EnforcementCase).where(EnforcementCase.id == appeal.enforcement_case_id).with_for_update())
        if ecase is None:
            return
        if ecase.review_id:
            target = session.get(Review, ecase.review_id)
            if target is not None:
                _restore_review(session, principal, target, "appeal-overturned", request_id)
            ecase.state = "restored"
        else:
            ecase.state = "closed"
        ecase.counts_toward_rating, ecase.closed_at, ecase.version = True, _now(), ecase.version + 1
        for sanction in session.scalars(select(Sanction).where(Sanction.enforcement_case_id == ecase.id, Sanction.state == "active")):
            reverse_sanction(session, principal, sanction, request_id=request_id)


def decide_appeal(
    session: Session, principal: Principal, *, appeal_id: uuid.UUID, outcome: str, expected_version: int,
    note: str | None, task_id: uuid.UUID, lease_token: uuid.UUID, request_id: str | None,
) -> dict[str, Any]:
    appeal = session.scalar(select(Appeal).where(Appeal.id == appeal_id).with_for_update())
    if appeal is None:
        raise ApiError("NOT_FOUND")
    task = tasks.require_lease(session, principal, task_id, lease_token, appeal_id)
    if appeal.original_decider_id == principal.user.id:
        raise ApiError("APPEAL_REVIEWER_NOT_INDEPENDENT")
    if appeal.appellant_user_id is not None and appeal.appellant_user_id == principal.user.id:
        raise ApiError("FORBIDDEN")
    if appeal.version != expected_version:
        raise ApiError("REVIEW_VERSION_CONFLICT")
    if outcome not in APPEAL_OUTCOMES or appeal.state not in ("received", "in_review"):
        raise ApiError("TRANSITION_NOT_ALLOWED")
    if outcome == "overturned":
        _overturn(session, principal, appeal, request_id)
    appeal.state, appeal.version = outcome, appeal.version + 1
    appeal.decided_by, appeal.decided_at, appeal.decision_note = principal.user.id, _now(), note
    tasks.complete(task)
    audit.record(session, actor=principal, action=f"appeal.{outcome}", target_type="appeal", target_id=appeal.id, reason=note, metadata={"version": appeal.version}, request_id=request_id)
    emit(
        session,
        "appeal.decided",
        appeal.id,
        {"appeal_id": str(appeal.id), "appellant_id": str(appeal.appellant_user_id) if appeal.appellant_user_id else None, "outcome": outcome},
    )
    return {"appeal_id": str(appeal.id), "state": appeal.state, "version": appeal.version}
