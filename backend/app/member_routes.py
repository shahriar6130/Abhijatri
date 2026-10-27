"""Member routes for reviews with photos and videos, verification, appeals and notifications
(Review.md 3.3 and 8; Moderation spec 6.2, 6.5, 11).

Every route needs a signed-in member; writes need the CSRF token. Notifications are also pushed live
over Server-Sent Events (`GET /notifications/stream`), so a decision reaches the member's open page
within a few seconds without polling from the browser.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import media
from app.admin import cases
from app.auth.sessions import MemberPrincipal, Principal, require_csrf
from app.db import SessionLocal, get_session
from app.errors import ApiError
from app.limits import limiter
from app.models import Appeal, Notification, VerificationCase, VerificationEvidence
from app.ops import events
from app.schemas import (
    GuestReviewCreated,
    MediaIntent,
    MediaIntentRequest,
    MediaStatus,
    MemberReviewCreate,
)
from app.services import ReviewError, submit_member_review
from app.storage import StorageClient, StorageUnavailable, get_storage


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(prefix="/api/v1", tags=["members"], dependencies=[Depends(_no_store)])
DbSession = Annotated[Session, Depends(get_session)]
Writer = Annotated[Principal, Depends(require_csrf)]
Storage = Annotated[StorageClient, Depends(get_storage)]

STREAM_SECONDS = 300  # the browser reconnects by itself after this
STREAM_POLL_SECONDS = 2.0


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationBody(_Body):
    statement: str | None = Field(default=None, max_length=1000)


class EvidenceBody(_Body):
    content_type: str = Field(max_length=80)
    size_bytes: int = Field(ge=1)


class RespondBody(_Body):
    statement: str = Field(min_length=3, max_length=1000)


class AppealBody(_Body):
    target_type: str = Field(pattern="^(moderation_action|enforcement_case|verification_case)$")
    target_id: uuid.UUID
    reason: str = Field(min_length=10, max_length=1000)


def _commit[T](session: Session, work: Callable[[], T]) -> T:
    try:
        result = work()
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise


def _case_view(session: Session, case: VerificationCase) -> dict[str, Any]:
    evidence = session.scalars(select(VerificationEvidence).where(VerificationEvidence.case_id == case.id, VerificationEvidence.status != "deleted").order_by(VerificationEvidence.created_at))
    return {
        "id": str(case.id),
        "state": case.state,
        "version": case.version,
        "statement": case.statement,
        "decision_reason": case.decision_reason,
        "decision_note": case.decision_note if case.state in ("needs_clarification", "rejected", "approved") else None,
        "created_at": case.created_at.isoformat(),
        "decided_at": case.decided_at.isoformat() if case.decided_at else None,
        "evidence": [{"id": str(e.id), "status": e.status, "content_type": e.content_type} for e in evidence],
    }


# ---- verification ----


@router.get("/verifications/mine")
def my_verification(principal: MemberPrincipal, session: DbSession) -> dict[str, Any]:
    latest = session.scalars(select(VerificationCase).where(VerificationCase.applicant_user_id == principal.user.id).order_by(VerificationCase.created_at.desc()).limit(1)).first()
    return {"verified_member": cases.is_verified_member(session, principal.user.id), "case": _case_view(session, latest) if latest else None}


@router.post("/verifications", status_code=201)
def request_verification(body: VerificationBody, principal: Writer, session: DbSession) -> dict[str, Any]:
    case = _commit(session, lambda: cases.open_verification(session, principal, body.statement))
    return _case_view(session, case)


# ---- member reviews and their photos and videos ----


@router.post("/reviews/member", response_model=GuestReviewCreated, status_code=201)
@limiter.limit("20/hour")
def create_member_review(request: Request, response: Response, payload: MemberReviewCreate, principal: Writer, session: DbSession) -> GuestReviewCreated:
    """A signed-in member's review. No Turnstile: the session, CSRF token and rate limit stand in for it."""
    try:
        result = submit_member_review(session, payload, principal.user.id)
        session.commit()
    except ReviewError as error:
        session.rollback()
        raise ApiError(error.code) from error
    if result.duplicate_recovered:
        response.status_code = 200
    else:
        events.count("reviews.submitted")
    return GuestReviewCreated(
        review_id=result.review.id, status=result.review.status, version=result.review.version, duplicate_recovered=result.duplicate_recovered
    )


def _storage_down(error: StorageUnavailable) -> ApiError:
    return ApiError("SERVICE_UNAVAILABLE", headers={"Retry-After": "5"})


@router.post("/reviews/{review_id}/media-intents", response_model=MediaIntent, status_code=201)
@limiter.limit("30/hour")
def media_intent(request: Request, review_id: uuid.UUID, body: MediaIntentRequest, principal: Writer, session: DbSession, storage: Storage) -> MediaIntent:
    """Step 1 of an upload: returns a one-time signed URL for exactly one file (Review.md 8)."""
    try:
        intent = _commit(session, lambda: media.create_intent(
            session, storage, principal, review_id,
            content_type=body.content_type, size_bytes=body.size_bytes, alt_text=body.alt_text.strip(), caption=(body.caption or "").strip() or None,
        ))
    except StorageUnavailable as error:
        raise _storage_down(error) from error
    return MediaIntent(**intent)


@router.post("/reviews/{review_id}/media/{media_id}/complete", response_model=MediaStatus)
def media_complete(review_id: uuid.UUID, media_id: uuid.UUID, principal: Writer, session: DbSession, storage: Storage) -> MediaStatus:
    """Step 2: the server checks the uploaded file and keeps a cleaned copy for the moderator."""
    try:
        item = media.complete_upload(session, storage, principal, review_id, media_id)
        session.commit()
    except media.MediaRejected as rejected:
        session.commit()  # the row is marked removed and the object deleted
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "file", "code": rejected.code}]) from rejected
    except StorageUnavailable as error:
        session.rollback()
        raise _storage_down(error) from error
    except Exception:
        session.rollback()
        raise
    return MediaStatus(**{k: v for k, v in media.describe(item).items() if k in MediaStatus.model_fields})


@router.post("/reviews/{review_id}/media/{media_id}/remove", status_code=204)
def media_remove(review_id: uuid.UUID, media_id: uuid.UUID, principal: Writer, session: DbSession, storage: Storage) -> Response:
    _commit(session, lambda: media.remove(session, storage, principal, review_id, media_id))
    return Response(status_code=204)


@router.post("/verifications/{case_id}/evidence")
def evidence_upload(case_id: uuid.UUID, body: EvidenceBody, principal: Writer, session: DbSession, storage: Storage) -> dict[str, Any]:
    """A one-time signed URL; the browser PUTs the file to it directly. The API never sees the bytes."""
    return _commit(session, lambda: cases.request_evidence_upload(session, storage, principal, case_id, body.content_type, body.size_bytes))


@router.post("/verifications/{case_id}/evidence/{evidence_id}/complete")
def evidence_complete(case_id: uuid.UUID, evidence_id: uuid.UUID, principal: Writer, session: DbSession, storage: Storage) -> dict[str, Any]:
    evidence = _commit(session, lambda: cases.complete_evidence_upload(session, storage, principal, case_id, evidence_id))
    return {"id": str(evidence.id), "status": evidence.status}


@router.post("/verifications/{case_id}/respond")
def verification_respond(case_id: uuid.UUID, body: RespondBody, principal: Writer, session: DbSession) -> dict[str, Any]:
    case = _commit(session, lambda: cases.applicant_transition(session, principal, case_id, "in_review", body.statement))
    return _case_view(session, case)


@router.post("/verifications/{case_id}/withdraw")
def verification_withdraw(case_id: uuid.UUID, principal: Writer, session: DbSession) -> dict[str, Any]:
    case = _commit(session, lambda: cases.applicant_transition(session, principal, case_id, "withdrawn", None))
    return _case_view(session, case)


# ---- appeals ----


def _appeal_view(appeal: Appeal) -> dict[str, Any]:
    target = next((t for t in ("moderation_action", "enforcement_case", "verification_case") if getattr(appeal, f"{t}_id")), None)
    return {
        "id": str(appeal.id),
        "reference": str(appeal.id)[:8],
        "state": appeal.state,
        "target_type": target,
        "target_id": str(getattr(appeal, f"{target}_id")) if target else None,
        "reason": appeal.reason,
        "submitted_at": appeal.submitted_at.isoformat(),
        "deadline_at": appeal.deadline_at.isoformat(),
        "decided_at": appeal.decided_at.isoformat() if appeal.decided_at else None,
        "decision_note": appeal.decision_note,
        "version": appeal.version,
    }


@router.get("/appeals/mine")
def my_appeals(principal: MemberPrincipal, session: DbSession) -> dict[str, Any]:
    appeals = session.scalars(select(Appeal).where(Appeal.appellant_user_id == principal.user.id).order_by(Appeal.submitted_at.desc()))
    return {"appeals": [_appeal_view(a) for a in appeals], "appealable": cases.appealable_decisions(session, principal.user.id)}


@router.post("/appeals", status_code=201)
def create_appeal(body: AppealBody, principal: Writer, session: DbSession) -> dict[str, Any]:
    appeal = _commit(session, lambda: cases.create_appeal(session, principal, target_type=body.target_type, target_id=body.target_id, reason=body.reason))
    return _appeal_view(appeal)


@router.post("/appeals/{appeal_id}/withdraw")
def withdraw_appeal(appeal_id: uuid.UUID, principal: Writer, session: DbSession) -> dict[str, Any]:
    return _appeal_view(_commit(session, lambda: cases.withdraw_appeal(session, principal, appeal_id)))


# ---- notifications ----


def _notification_view(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "kind": n.kind,
        "critical": n.critical,
        "title": {"bn": n.title_bn, "en": n.title_en},
        "body": {"bn": n.body_bn, "en": n.body_en},
        "link": n.link,
        "created_at": n.created_at.isoformat(),
        "read": n.read_at is not None,
    }


def _unread(session: Session, user_id: uuid.UUID) -> int:
    return session.scalar(select(func.count()).select_from(Notification).where(Notification.recipient_user_id == user_id, Notification.read_at.is_(None))) or 0


@router.get("/notifications")
def notifications(
    principal: MemberPrincipal, session: DbSession, limit: Annotated[int, Query(ge=1, le=50)] = 20, before: datetime | None = None
) -> dict[str, Any]:
    statement = select(Notification).where(Notification.recipient_user_id == principal.user.id).order_by(Notification.created_at.desc()).limit(limit)
    if before:
        statement = statement.where(Notification.created_at < before)
    return {"items": [_notification_view(n) for n in session.scalars(statement)], "unread": _unread(session, principal.user.id)}


@router.post("/notifications/{notification_id}/read")
def read_notification(notification_id: uuid.UUID, principal: Writer, session: DbSession) -> dict[str, int]:
    changed = session.execute(
        update(Notification)
        .where(Notification.id == notification_id, Notification.recipient_user_id == principal.user.id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    session.commit()
    if not changed.rowcount and session.scalar(select(Notification.id).where(Notification.id == notification_id, Notification.recipient_user_id == principal.user.id)) is None:  # type: ignore[attr-defined]
        raise ApiError("NOT_FOUND")
    return {"unread": _unread(session, principal.user.id)}


@router.post("/notifications/read-all")
def read_all(principal: Writer, session: DbSession) -> dict[str, int]:
    session.execute(update(Notification).where(Notification.recipient_user_id == principal.user.id, Notification.read_at.is_(None)).values(read_at=datetime.now(UTC)))
    session.commit()
    return {"unread": 0}


def _newer(user_id: uuid.UUID, since: datetime) -> tuple[list[dict[str, Any]], int, datetime]:
    with SessionLocal() as session:
        rows = list(session.scalars(select(Notification).where(Notification.recipient_user_id == user_id, Notification.created_at > since).order_by(Notification.created_at)))
        latest = rows[-1].created_at if rows else since
        return [_notification_view(n) for n in rows], _unread(session, user_id), latest


@router.get("/notifications/stream")
async def notification_stream(request: Request, principal: MemberPrincipal) -> StreamingResponse:
    """Live notifications as Server-Sent Events. The connection lasts 5 minutes; `EventSource` reconnects."""
    user_id = principal.user.id

    async def events() -> AsyncIterator[str]:
        since = datetime.now(UTC)
        _, unread, _ = await run_in_threadpool(_newer, user_id, since)
        yield f"retry: 3000\nevent: unread\ndata: {json.dumps({'unread': unread})}\n\n"
        started = asyncio.get_running_loop().time()
        quiet = 0.0
        while asyncio.get_running_loop().time() - started < STREAM_SECONDS:
            if await request.is_disconnected():
                return
            await asyncio.sleep(STREAM_POLL_SECONDS)
            items, unread, since = await run_in_threadpool(_newer, user_id, since)
            for item in items:
                yield f"event: notification\ndata: {json.dumps({'notification': item, 'unread': unread}, ensure_ascii=False)}\n\n"
            quiet = 0.0 if items else quiet + STREAM_POLL_SECONDS
            if quiet >= 20:  # keep proxies from closing an idle connection
                yield ": keep-alive\n\n"
                quiet = 0.0

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
