"""Provider callbacks about sent email (Notification spec 7.5, 8, 9 "Provider webhook").

``POST /api/v1/webhooks/notifications/{provider}`` needs no member session; it is authenticated by
the provider instead:

- ``resend``: Svix signature (``svix-id``, ``svix-timestamp``, ``svix-signature``), HMAC-SHA256 of
  ``id.timestamp.body`` with the ``whsec_`` secret;
- ``brevo``: ``Authorization: Bearer <BREVO_WEBHOOK_TOKEN>`` (Brevo sends the header set on the webhook).

Both reject a timestamp outside 5 minutes (replay protection) and a body that is not JSON. Each
callback is stored once per ``(provider, provider_event_id)``; a repeat changes nothing. A provider
without a configured secret answers 404. Only a redacted copy of the payload is kept: never the
address, subject or body. Failed verifications are recorded so repeated failures raise an alert.
"""

import base64
import hashlib
import hmac
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.models import NotificationDelivery, NotificationProviderEvent
from app.notify import delivery

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])

REPLAY_WINDOW = timedelta(minutes=5)
MAX_BODY = 256 * 1024

# provider event type -> (our event type, delivery status or None, add a suppression)
RESEND_EVENTS = {
    "email.delivered": ("delivered", "delivered", False),
    "email.bounced": ("bounced", "bounced", True),
    "email.complained": ("complained", None, True),
    "email.delivery_delayed": ("delayed", None, False),
}
BREVO_EVENTS = {
    "delivered": ("delivered", "delivered", False),
    "hard_bounce": ("bounced", "bounced", True),
    "soft_bounce": ("soft_bounce", None, False),
    "blocked": ("blocked", "failed_permanently", False),
    "invalid_email": ("bounced", "bounced", True),
    "spam": ("complained", None, True),
    "unsubscribed": ("unsubscribed", None, True),
}


class Rejected(Exception):
    pass


def _record_rejection(session: Session, provider: str, reason: str) -> None:
    session.execute(
        insert(NotificationProviderEvent)
        .values(id=uuid.uuid4(), provider=provider, provider_event_id=f"rejected:{uuid.uuid4()}", event_type="signature_failure", redacted_payload={"reason": reason})
        .on_conflict_do_nothing()
    )
    session.commit()


def _fresh(timestamp: float, now: datetime) -> bool:
    return abs(now.timestamp() - timestamp) <= REPLAY_WINDOW.total_seconds()


def verify_resend(secret: str, headers: dict[str, str], body: bytes, now: datetime) -> str:
    message_id, stamp, signatures = headers.get("svix-id"), headers.get("svix-timestamp"), headers.get("svix-signature")
    if not (message_id and stamp and signatures):
        raise Rejected("missing signature headers")
    try:
        if not _fresh(float(stamp), now):
            raise Rejected("timestamp outside the replay window")
    except ValueError as error:
        raise Rejected("bad timestamp") from error
    key = base64.b64decode(secret.removeprefix("whsec_"))
    expected = base64.b64encode(hmac.new(key, f"{message_id}.{stamp}.".encode() + body, hashlib.sha256).digest()).decode()
    for candidate in signatures.split():
        version, _, value = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(value, expected):
            return message_id
    raise Rejected("signature mismatch")


def verify_brevo(token: str, headers: dict[str, str], payload: dict[str, Any], now: datetime) -> str:
    supplied = headers.get("authorization", "")
    if not hmac.compare_digest(supplied.encode(), f"Bearer {token}".encode()):
        raise Rejected("bad token")
    stamp = payload.get("ts_event") or payload.get("ts")
    if stamp is None or not _fresh(float(stamp), now):
        raise Rejected("timestamp outside the replay window")
    return f"{payload.get('message-id')}:{payload.get('event')}:{stamp}"


def _redact(provider: str, payload: dict[str, Any]) -> dict[str, Any]:
    if provider == "resend":
        data = payload.get("data") or {}
        return {"type": payload.get("type"), "email_id": data.get("email_id"), "created_at": payload.get("created_at")}
    return {"event": payload.get("event"), "message_id": payload.get("message-id"), "reason": str(payload.get("reason") or "")[:120]}


def handle(session: Session, provider: str, headers: dict[str, str], body: bytes, now: datetime | None = None) -> dict[str, Any]:
    moment = now or datetime.now(UTC)
    settings = get_settings()
    secret = {"resend": settings.resend_webhook_secret, "brevo": settings.brevo_webhook_token}.get(provider)
    if not secret:
        raise ApiError("NOT_FOUND")
    if "application/json" not in headers.get("content-type", "") or len(body) > MAX_BODY:
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "body", "code": "INVALID_VALUE"}])
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError("not an object")
        if provider == "resend":
            event_id = verify_resend(secret, headers, body, moment)
            kind, message_id = str(payload.get("type")), str((payload.get("data") or {}).get("email_id") or "")
            mapping = RESEND_EVENTS.get(kind)
        else:
            event_id = verify_brevo(secret, headers, payload, moment)
            kind, message_id = str(payload.get("event")), str(payload.get("message-id") or "").strip("<>")
            mapping = BREVO_EVENTS.get(kind)
    except (Rejected, ValueError) as error:
        _record_rejection(session, provider, type(error).__name__ if isinstance(error, ValueError) else str(error))
        logger.warning("rejected %s webhook: %s", provider, error)
        raise ApiError("FORBIDDEN") from error

    target = session.scalar(
        select(NotificationDelivery).where(NotificationDelivery.provider_message_id.in_([message_id, f"<{message_id}>"])).with_for_update()
    ) if message_id else None
    stored = session.execute(
        insert(NotificationProviderEvent)
        .values(
            id=uuid.uuid4(), provider=provider, provider_event_id=event_id[:200], event_type=(mapping[0] if mapping else "ignored")[:40],
            delivery_id=target.id if target else None, received_at=moment, redacted_payload=_redact(provider, payload),
        )
        .on_conflict_do_nothing(constraint="uq_notification_provider_events")
        .returning(NotificationProviderEvent.id)
    ).scalar()
    if stored is None:
        session.commit()
        return {"status": "duplicate"}
    if mapping and target is not None:
        _, status, suppress = mapping
        if status and target.status in ("accepted", "ambiguous", "delivered", "sending", "queued"):
            target.status, target.updated_at = status, moment
        if suppress and target.destination_ref:
            delivery.suppress(session, target.destination_ref, f"provider_{mapping[0]}", None)
    session.execute(update(NotificationProviderEvent).where(NotificationProviderEvent.id == stored).values(processed_at=moment))
    session.commit()
    return {"status": "processed"}


@router.post("/notifications/{provider}")
async def provider_webhook(provider: str, request: Request, session: Session = Depends(get_session)) -> Response:
    if provider not in ("resend", "brevo"):
        raise ApiError("NOT_FOUND")
    body = await request.body()
    headers = {key.lower(): value for key, value in request.headers.items()}
    result = handle(session, provider, headers, body)
    return Response(content=json.dumps(result), media_type="application/json")
