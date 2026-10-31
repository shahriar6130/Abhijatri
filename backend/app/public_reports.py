"""Reports and removal requests from people who are not signed in (Review.md 5.4, 9.2; Gantt R11).

``POST /api/v1/public/review-reports`` and ``POST /api/v1/public/removal-requests`` always answer ``202 received``
once the request is well formed, the challenge passed and the limits allow it. They never say whether the review
exists, is published, or already has a report from the same visitor, so the endpoints cannot be used to probe.

Order of checks, cheapest and least revealing first: Origin, body shape, Turnstile (single use), durable
rate limits (committed before the work), then the transaction.
"""

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app import abuse, crypto, report_reasons
from app.admin import actions
from app.auth import csrf
from app.client_address import network_digest, normalise, trusted_client_address
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.limits import guest_submit_limit, limiter
from app.turnstile import ACTION_GUEST_REMOVAL, ACTION_GUEST_REPORT, TurnstileDep

router = APIRouter(prefix="/api/v1/public", tags=["public-reports"])


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AnonymousReportBody(_Body):
    review_id: uuid.UUID
    reason_code: str = Field(min_length=2, max_length=40)
    details: str | None = Field(default=None, max_length=1000)
    contact: str | None = Field(default=None, max_length=200)
    turnstile_token: str | None = Field(default=None, max_length=2048)


class RemovalRequestBody(_Body):
    review_id: uuid.UUID
    statement: str = Field(min_length=10, max_length=1000)
    contact: str = Field(min_length=3, max_length=200)
    turnstile_token: str | None = Field(default=None, max_length=2048)


def _scope(request: Request) -> bytes:
    """Who the visitor is for duplicate control: a keyed digest of the client network, never the address."""
    return crypto.digest(crypto.REPORT_SCOPE_LABEL, crypto.current_key_id(), normalise(trusted_client_address(request)))


def _gate(
    request: Request, sessions: abuse.SessionFactory, verify: Callable[..., None], token: str | None, action: str
) -> bytes:
    csrf.check_origin(request)
    address = trusted_client_address(request)
    verify(token, action=action, remote_address=str(address) if address else None)
    abuse.enforce(sessions, abuse.anonymous_report_checks(get_settings(), network_digest(request)))
    return _scope(request)


@router.post("/review-reports", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(guest_submit_limit)
def report_review_anonymously(
    request: Request,
    body: AnonymousReportBody,
    sessions: abuse.CounterSessions,
    verify_challenge: TurnstileDep,
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    reason = report_reasons.normalise(body.reason_code)
    if reason is None:
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "reason_code", "code": "INVALID_VALUE"}])
    contact = actions.clean_contact(body.contact)
    scope = _gate(request, sessions, verify_challenge, body.turnstile_token, ACTION_GUEST_REPORT)
    try:
        actions.create_anonymous_report(
            session, review_id=body.review_id, reason=reason, details=body.details or None, contact=contact, scope=scope
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"received": True}


@router.post("/removal-requests", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit(guest_submit_limit)
def request_removal_without_receipt(
    request: Request,
    body: RemovalRequestBody,
    sessions: abuse.CounterSessions,
    verify_challenge: TurnstileDep,
    session: Session = Depends(get_session),
) -> dict[str, bool]:
    """The author lost the receipt. A moderator checks ownership out of band using the contact given here."""
    contact = actions.clean_contact(body.contact, required=True)
    scope = _gate(request, sessions, verify_challenge, body.turnstile_token, ACTION_GUEST_REMOVAL)
    try:
        actions.create_anonymous_report(
            session,
            review_id=body.review_id,
            reason=report_reasons.REMOVAL_REQUEST,
            details=body.statement.strip(),
            contact=contact,
            scope=scope,
        )
        session.commit()
    except Exception:
        session.rollback()
        raise
    return {"received": True}
