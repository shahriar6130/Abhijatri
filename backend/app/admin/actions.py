"""Decisions and report handling (Moderation spec 7.2, 8.5; Gantt R10 and R11).

Every function follows the concurrency contract: the caller's role was re-read from the database
by the dependency; here the target and the claim lease are locked and validated, the immutable
action and audit rows are written, any event is queued, and the route commits once.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import media
from app.admin import audit, tasks
from app.auth.sessions import Principal
from app.errors import ApiError
from app.models import ModerationDecision, OutboxEvent, Report, Review, ReviewStatus
from app.services import ReviewError, moderate_review, set_review_conflict

REPORT_REASONS = ("spam", "offensive", "false_information", "privacy", "conflict_of_interest", "other")

# state -> states it may move to (the authoritative table for reports, spec 7)
REPORT_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"in_review", "actioned", "dismissed"}),
    "in_review": frozenset({"actioned", "dismissed"}),
}
REPORT_FINAL = frozenset({"actioned", "dismissed"})


def translate(error: ReviewError) -> ApiError:
    """Review-service failures as the admin API reports them (409 stale version, 422 invalid transition)."""
    if error.code == "INVALID_TRANSITION":
        return ApiError("TRANSITION_NOT_ALLOWED")
    return ApiError(error.code)


def moderate_submission(
    session: Session,
    principal: Principal,
    *,
    review_id: uuid.UUID,
    task_id: uuid.UUID,
    lease_token: uuid.UUID,
    expected_version: int,
    decision: ModerationDecision,
    reason_code: str,
    note: str | None,
    request_id: str | None,
    rejected_media_ids: set[uuid.UUID] | None = None,
) -> dict[str, Any]:
    task = tasks.require_lease(session, principal, task_id, lease_token)
    if task.task_type == "review_moderation":
        linked = task.subject_id == review_id
    elif task.task_type == "report":  # a report task may hide or restore the review the report names
        linked = session.scalar(select(Report.review_id).where(Report.id == task.subject_id)) == review_id
    else:
        linked = False
    if not linked:
        raise ApiError("NOT_FOUND")
    before = session.scalar(select(Review.status).where(Review.id == review_id))
    try:
        review = moderate_review(
            session,
            review_id=review_id,
            actor_user_id=principal.user.id,
            expected_version=expected_version,
            decision=decision,
            reason_code=reason_code,
            note=note,
            task_id=task.id,
            request_id=request_id,
        )
    except ReviewError as error:
        raise translate(error) from error
    decided_media = media.apply_decision(session, review_id, decision, principal.user.id, rejected_media_ids or set())
    if task.task_type == "review_moderation":  # a report task stays open until the report itself is resolved
        tasks.complete(task)
    audit.record(
        session,
        actor=principal,
        action=f"review.{decision.value.lower()}",
        target_type="review",
        target_id=review_id,
        reason=reason_code,
        metadata={
            "from": before.value if before else None,
            "to": review.status.value,
            "version": review.version,
            "task_id": str(task.id),
            **({"media": decided_media} if decided_media["approved"] or decided_media["rejected"] else {}),
        },
        request_id=request_id,
    )
    return {
        "review_id": str(review.id),
        "status": review.status.value,
        "version": review.version,
        "counted_rating": review.counted_rating,
        "task_id": str(task.id),
    }


def change_conflict(
    session: Session,
    principal: Principal,
    *,
    review_id: uuid.UUID,
    expected_version: int,
    conflict_declared: bool,
    reason_code: str,
    note: str | None,
    request_id: str | None,
) -> dict[str, Any]:
    try:
        review = set_review_conflict(
            session,
            review_id=review_id,
            actor_user_id=principal.user.id,
            expected_version=expected_version,
            conflict_declared=conflict_declared,
            reason_code=reason_code,
            note=note,
        )
    except ReviewError as error:
        raise translate(error) from error
    audit.record(
        session,
        actor=principal,
        action="review.conflict_set" if conflict_declared else "review.conflict_cleared",
        target_type="review",
        target_id=review_id,
        reason=reason_code,
        metadata={"version": review.version},
        request_id=request_id,
    )
    return {"review_id": str(review.id), "status": review.status.value, "version": review.version, "counted_rating": review.counted_rating}


# ---- reports (member side) ----


def create_report(session: Session, reporter: Principal, *, review_id: uuid.UUID, reason_code: str, details: str | None) -> Report:
    review = session.get(Review, review_id)
    if review is None or review.status != ReviewStatus.PUBLISHED:
        raise ApiError("NOT_FOUND")  # only published reviews can be reported; others are not disclosed
    if review.author_user_id == reporter.user.id:
        raise ApiError("FORBIDDEN")
    report = Report(review_id=review_id, reporter_user_id=reporter.user.id, reason_code=reason_code, details=details)
    try:
        with session.begin_nested():
            session.add(report)
            session.flush()
    except IntegrityError as error:
        raise ApiError("DUPLICATE_OPEN_REPORT") from error
    tasks.ensure_task(session, "report", report.id, priority=1)
    session.add(
        OutboxEvent(
            topic="report.created",
            aggregate_id=report.id,
            payload={"report_id": str(report.id), "review_id": str(review_id), "reason_code": reason_code},
        )
    )
    return report


# ---- reports (staff side) ----


def transition_report(
    session: Session,
    principal: Principal,
    *,
    report_id: uuid.UUID,
    to: str,
    expected_version: int,
    reason_code: str,
    note: str | None,
    task_id: uuid.UUID,
    lease_token: uuid.UUID,
    request_id: str | None,
) -> dict[str, Any]:
    report = session.scalar(select(Report).where(Report.id == report_id).with_for_update())
    if report is None:
        raise ApiError("NOT_FOUND")
    task = tasks.require_lease(session, principal, task_id, lease_token, report_id)
    if report.version != expected_version:
        raise ApiError("REVIEW_VERSION_CONFLICT")
    if to not in REPORT_TRANSITIONS.get(report.state, frozenset()):
        raise ApiError("TRANSITION_NOT_ALLOWED")
    previous = report.state
    report.state, report.version = to, report.version + 1
    if to in REPORT_FINAL:
        report.resolved_by, report.resolution_note = principal.user.id, note
        report.resolved_at = datetime.now(UTC)
        tasks.complete(task)
    audit.record(
        session,
        actor=principal,
        action=f"report.{to}",
        target_type="report",
        target_id=report.id,
        reason=reason_code,
        metadata={"from": previous, "to": to, "version": report.version, "review_id": str(report.review_id)},
        request_id=request_id,
    )
    session.add(
        OutboxEvent(
            topic="report.state_changed",
            aggregate_id=report.id,
            payload={"report_id": str(report.id), "state": to, "version": report.version},
        )
    )
    return {"report_id": str(report.id), "state": report.state, "version": report.version}
