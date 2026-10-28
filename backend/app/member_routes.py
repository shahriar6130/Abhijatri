"""Member routes for reviews with photos and videos, verification, appeals and notifications
(Review.md 3.3 and 8; Moderation spec 6.2, 6.5, 11).

Every route needs a signed-in member; writes need the CSRF token. Notifications are also pushed live
over Server-Sent Events (`GET /notifications/stream`), so a decision reaches the member's open page
within a few seconds without polling from the browser.
"""

import asyncio
import base64
import json
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from datetime import time as dt_time
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.orm import Session

from app import media
from app.admin import cases
from app.auth.sessions import MemberPrincipal, Principal, require_csrf
from app.db import SessionLocal, get_session
from app.errors import ApiError
from app.limits import limiter
from app.models import (
    Appeal,
    Notification,
    NotificationPreference,
    UserRole,
    VerificationCase,
    VerificationEvidence,
)
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


# ---- notifications (Notification spec 9 "Member inbox") ----


class NotificationPatch(_Body):
    read: bool | None = None
    archived: bool | None = None


class PreferencesBody(_Body):
    standard_email_mode: str = Field(pattern="^(immediate|digest|off)$")
    digest_timezone: str = Field(min_length=1, max_length=64)
    digest_local_time: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @field_validator("digest_timezone")
    @classmethod
    def known_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError("not an IANA time zone") from error
        return value


def _notification_view(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "kind": n.kind,
        "category": n.kind.split(".", 1)[0],
        "priority": n.priority,
        "critical": n.critical,
        "audience": n.audience,
        "title": {"bn": n.title_bn, "en": n.title_en},
        "body": {"bn": n.body_bn, "en": n.body_en},
        "link": n.link,
        "created_at": n.created_at.isoformat(),
        "read": n.read_at is not None,
        "archived": n.archived_at is not None,
    }


def _visible(user_id: uuid.UUID, is_staff: bool) -> Any:
    """Own rows only; staff notices only while the person still holds a staff role (spec 5)."""
    condition = Notification.recipient_user_id == user_id
    return condition if is_staff else and_(condition, Notification.audience == "member")


def _is_staff(session: Session, user_id: uuid.UUID) -> bool:
    return session.scalar(select(UserRole.id).where(UserRole.user_id == user_id, UserRole.revoked_at.is_(None))) is not None


def _unread(session: Session, user_id: uuid.UUID, is_staff: bool) -> int:
    return session.scalar(
        select(func.count()).select_from(Notification).where(_visible(user_id, is_staff), Notification.read_at.is_(None), Notification.archived_at.is_(None))
    ) or 0


def _cursor(n: Notification) -> str:
    return base64.urlsafe_b64encode(f"{n.created_at.isoformat()}|{n.id}".encode()).decode("ascii").rstrip("=")


def _decode(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")
        moment, notification_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(moment), uuid.UUID(notification_id)
    except (ValueError, UnicodeDecodeError) as error:
        raise ApiError("INVALID_CURSOR") from error


@router.get("/notifications")
def notifications(
    principal: MemberPrincipal,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    archived: bool = False,
    unread_only: bool = False,
) -> dict[str, Any]:
    is_staff = principal.role is not None
    statement = (
        select(Notification)
        .where(_visible(principal.user.id, is_staff), Notification.archived_at.is_not(None) if archived else Notification.archived_at.is_(None))
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit + 1)
    )
    if unread_only:
        statement = statement.where(Notification.read_at.is_(None))
    if cursor:
        moment, last_id = _decode(cursor)
        statement = statement.where(or_(Notification.created_at < moment, and_(Notification.created_at == moment, Notification.id < last_id)))
    rows = list(session.scalars(statement))
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [_notification_view(n) for n in rows],
        "next_cursor": _cursor(rows[-1]) if more and rows else None,
        "unread": _unread(session, principal.user.id, is_staff),
    }


@router.get("/notifications/unread-count")
def unread_count(principal: MemberPrincipal, session: DbSession) -> dict[str, int]:
    return {"unread": _unread(session, principal.user.id, principal.role is not None)}


@router.patch("/notifications/{notification_id}")
def update_notification(notification_id: uuid.UUID, body: NotificationPatch, principal: Writer, session: DbSession) -> dict[str, Any]:
    """Mark read/unread or archive/unarchive one of your own notifications. Nothing else can change."""
    is_staff = principal.role is not None
    row = session.scalar(select(Notification).where(Notification.id == notification_id, _visible(principal.user.id, is_staff)).with_for_update())
    if row is None:
        raise ApiError("NOT_FOUND")
    now = datetime.now(UTC)
    if body.read is not None:
        row.read_at = (row.read_at or now) if body.read else None
    if body.archived is not None:
        row.archived_at = (row.archived_at or now) if body.archived else None
    session.commit()
    return _notification_view(row) | {"unread": _unread(session, principal.user.id, is_staff)}


@router.post("/notifications/mark-all-read")
def mark_all_read(principal: Writer, session: DbSession) -> dict[str, int]:
    is_staff = principal.role is not None
    session.execute(
        update(Notification).where(_visible(principal.user.id, is_staff), Notification.read_at.is_(None)).values(read_at=datetime.now(UTC))
    )
    session.commit()
    return {"unread": 0}


def _preference_view(pref: NotificationPreference | None) -> dict[str, Any]:
    return {
        "standard_email_mode": pref.standard_email_mode if pref else "digest",
        "digest_timezone": pref.digest_timezone if pref else "Asia/Dhaka",
        "digest_local_time": pref.digest_local_time.strftime("%H:%M") if pref else "08:00",
        "always_immediate": ["critical", "high"],  # never delayed or switched off by a preference
    }


@router.get("/notification-preferences")
def get_preferences(principal: MemberPrincipal, session: DbSession) -> dict[str, Any]:
    return _preference_view(session.get(NotificationPreference, principal.user.id))


@router.put("/notification-preferences")
def put_preferences(body: PreferencesBody, principal: Writer, session: DbSession) -> dict[str, Any]:
    pref = session.get(NotificationPreference, principal.user.id) or NotificationPreference(recipient_user_id=principal.user.id)
    pref.standard_email_mode = body.standard_email_mode
    pref.digest_timezone = body.digest_timezone
    pref.digest_local_time = dt_time.fromisoformat(body.digest_local_time)
    pref.updated_at = datetime.now(UTC)
    session.add(pref)
    session.commit()
    return _preference_view(pref)


def _newer(user_id: uuid.UUID, since: datetime) -> tuple[list[dict[str, Any]], int, datetime]:
    with SessionLocal() as session:
        is_staff = _is_staff(session, user_id)
        rows = list(
            session.scalars(
                select(Notification).where(_visible(user_id, is_staff), Notification.created_at > since).order_by(Notification.created_at)
            )
        )
        latest = rows[-1].created_at if rows else since
        return [_notification_view(n) for n in rows], _unread(session, user_id, is_staff), latest


@router.get("/notifications/stream")
async def notification_stream(request: Request, principal: MemberPrincipal) -> StreamingResponse:
    """Live notifications as Server-Sent Events: a best-effort signal, the inbox stays the source of truth
    (spec 1, 10). The connection lasts 5 minutes; `EventSource` reconnects and the page refetches."""
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
