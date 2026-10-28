"""Superadmin notification operations (Notification spec 9 "Admin delivery monitoring" and "Template management").

Superadmin only (``staff_principal("superadmin")``: 404 for non-staff, 403 for moderators, TOTP
required). General views are redacted: no email address, subject or body, only the HMAC reference.
Every write (retry, suppression add/remove, template draft and activation) is audited.
"""

import logging
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin import audit
from app.auth.sessions import Principal, staff_principal
from app.auth.validation import normalize_email
from app.db import get_session
from app.errors import ApiError
from app.models import (
    Notification,
    NotificationDelivery,
    NotificationDeliveryAttempt,
    NotificationRule,
    NotificationSuppression,
    NotificationTemplate,
    OutboxEvent,
)
from app.notify import delivery, registry
from app.notify.messages import template_variables

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/admin", tags=["notification-admin"])
Superadmin = Annotated[Principal, Depends(staff_principal("superadmin"))]
DbSession = Annotated[Session, Depends(get_session)]
RETRYABLE = ("ambiguous", "failed_permanently")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RetryBody(_Body):
    reason: str = Field(min_length=3, max_length=300)


class SuppressionBody(_Body):
    email: str = Field(min_length=3, max_length=254)
    channel: str = Field(default="email", pattern="^email$")
    reason_code: str = Field(min_length=2, max_length=60)


class RemovalBody(_Body):
    removal_reason: str = Field(min_length=3, max_length=300)


class TemplateDraftBody(_Body):
    channel: str = Field(pattern="^(in_app|email)$")
    locale: str = Field(pattern="^(bn|en)$")
    subject_template: str | None = Field(default=None, max_length=200)
    title_template: str | None = Field(default=None, max_length=160)
    body_template: str = Field(min_length=1, max_length=600)


class ActivateBody(_Body):
    channel: str = Field(pattern="^(in_app|email)$")
    locale: str = Field(pattern="^(bn|en)$")


class RuleBody(_Body):
    priority: str | None = Field(default=None, pattern="^(critical|high|normal|low)$")
    email: bool | None = None
    enabled: bool | None = None

    @field_validator("priority")
    @classmethod
    def _known(cls, value: str | None) -> str | None:
        return value


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "-"))


def _commit(session: Session) -> None:
    try:
        session.commit()
    except Exception:
        session.rollback()
        raise


# ---- deliveries and outbox ----


def _delivery_view(d: NotificationDelivery, kind: str | None) -> dict[str, Any]:
    return {
        "id": str(d.id),
        "notification_id": str(d.notification_id) if d.notification_id else None,
        "digest_id": str(d.digest_id) if d.digest_id else None,
        "kind": kind,
        "channel": d.channel,
        "status": d.status,
        "attempt_count": d.attempt_count,
        "next_attempt_at": d.next_attempt_at.isoformat() if d.next_attempt_at else None,
        "provider": d.provider,
        "destination_ref": d.destination_ref[:12] if d.destination_ref else None,  # redacted: a prefix of the HMAC only
        "last_error_code": d.last_error_code,
        "created_at": d.created_at.isoformat(),
        "updated_at": d.updated_at.isoformat(),
    }


@router.get("/notification-deliveries")
def list_deliveries(
    principal: Superadmin,
    session: DbSession,
    status: Annotated[str | None, Query(pattern="^(queued|sending|accepted|delivered|bounced|failed_permanently|skipped|ambiguous)$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    statement = (
        select(NotificationDelivery, Notification.kind)
        .outerjoin(Notification, Notification.id == NotificationDelivery.notification_id)
        .order_by(NotificationDelivery.updated_at.desc())
        .limit(limit)
    )
    if status:
        statement = statement.where(NotificationDelivery.status == status)
    counts = dict(session.execute(select(NotificationDelivery.status, func.count()).group_by(NotificationDelivery.status)).all())
    return {"items": [_delivery_view(d, kind) for d, kind in session.execute(statement).all()], "counts": counts}


@router.get("/notification-deliveries/{delivery_id}")
def get_delivery(delivery_id: uuid.UUID, principal: Superadmin, session: DbSession) -> dict[str, Any]:
    row = session.execute(
        select(NotificationDelivery, Notification.kind)
        .outerjoin(Notification, Notification.id == NotificationDelivery.notification_id)
        .where(NotificationDelivery.id == delivery_id)
    ).first()
    if row is None:
        raise ApiError("NOT_FOUND")
    attempts = session.scalars(
        select(NotificationDeliveryAttempt).where(NotificationDeliveryAttempt.delivery_id == delivery_id).order_by(NotificationDeliveryAttempt.attempt_number)
    )
    return _delivery_view(row[0], row[1]) | {
        "provider_message_id": row[0].provider_message_id,
        "last_error_summary": row[0].last_error_summary,
        "attempts": [
            {
                "attempt_number": a.attempt_number,
                "outcome": a.outcome,
                "started_at": a.started_at.isoformat(),
                "finished_at": a.finished_at.isoformat() if a.finished_at else None,
                "error_class": a.error_class,
                "error_code": a.error_code,
                "redacted_error_summary": a.redacted_error_summary,
            }
            for a in attempts
        ],
    }


@router.post("/notification-deliveries/{delivery_id}/retry")
def retry_delivery(delivery_id: uuid.UUID, body: RetryBody, request: Request, principal: Superadmin, session: DbSession) -> dict[str, Any]:
    """Send again after checking: only ambiguous or permanently failed deliveries; the attempt count goes on."""
    target = session.scalar(select(NotificationDelivery).where(NotificationDelivery.id == delivery_id).with_for_update())
    if target is None:
        raise ApiError("NOT_FOUND")
    if target.status not in RETRYABLE:
        raise ApiError("TRANSITION_NOT_ALLOWED")
    previous = target.status
    target.status, target.next_attempt_at, target.updated_at = "queued", datetime.now(UTC), datetime.now(UTC)
    audit.record(
        session, actor=principal, action="notification.delivery_retried", target_type="notification_delivery", target_id=target.id,
        reason=body.reason, metadata={"from": previous, "attempts": target.attempt_count}, request_id=_request_id(request),
    )
    _commit(session)
    return _delivery_view(target, None)


@router.get("/notification-outbox")
def list_outbox(
    principal: Superadmin,
    session: DbSession,
    status: Annotated[str | None, Query(pattern="^(pending|processing|processed|retry|dead_letter)$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> dict[str, Any]:
    statement = select(OutboxEvent).order_by(OutboxEvent.created_at.desc()).limit(limit)
    if status:
        statement = statement.where(OutboxEvent.status == status)
    counts = dict(session.execute(select(OutboxEvent.status, func.count()).group_by(OutboxEvent.status)).all())
    oldest = session.scalar(select(func.min(OutboxEvent.created_at)).where(OutboxEvent.status.in_(("pending", "retry", "processing"))))
    return {
        "items": [
            {
                "id": str(e.id),
                "event_type": e.topic,
                "aggregate_type": e.aggregate_type,
                "aggregate_id": str(e.aggregate_id),
                "status": e.status,
                "attempts": e.attempts,
                "next_attempt_at": e.available_at.isoformat(),
                "last_error_code": e.last_error_code,
                "created_at": e.created_at.isoformat(),
                "processed_at": e.processed_at.isoformat() if e.processed_at else None,
            }
            for e in session.scalars(statement)
        ],
        "counts": counts,
        "oldest_unprocessed_at": oldest.isoformat() if oldest else None,
    }


# ---- suppressions ----


def _suppression_view(s: NotificationSuppression) -> dict[str, Any]:
    return {
        "id": str(s.id),
        "destination_ref": s.destination_hmac[:12],
        "channel": s.channel,
        "reason_code": s.reason_code,
        "created_by": str(s.created_by) if s.created_by else None,
        "created_at": s.created_at.isoformat(),
        "removed_at": s.removed_at.isoformat() if s.removed_at else None,
        "removal_reason": s.removal_reason,
    }


@router.get("/notification-suppressions")
def list_suppressions(principal: Superadmin, session: DbSession, active: bool = True) -> dict[str, Any]:
    statement = select(NotificationSuppression).order_by(NotificationSuppression.created_at.desc()).limit(100)
    if active:
        statement = statement.where(NotificationSuppression.removed_at.is_(None))
    return {"items": [_suppression_view(s) for s in session.scalars(statement)]}


@router.post("/notification-suppressions", status_code=201)
def add_suppression(body: SuppressionBody, request: Request, principal: Superadmin, session: DbSession) -> dict[str, Any]:
    address_hmac = delivery.destination_hmac(normalize_email(body.email))
    created = delivery.suppress(session, address_hmac, body.reason_code, principal.user.id)
    if created is None:
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "email", "code": "ALREADY_SUPPRESSED"}])
    audit.record(
        session, actor=principal, action="notification.suppression_added", target_type="notification_suppression", target_id=created,
        reason=body.reason_code, request_id=_request_id(request),
    )
    _commit(session)
    row = session.get(NotificationSuppression, created)
    assert row is not None
    return _suppression_view(row)


@router.delete("/notification-suppressions/{suppression_id}")
def remove_suppression(suppression_id: uuid.UUID, body: RemovalBody, request: Request, principal: Superadmin, session: DbSession) -> dict[str, Any]:
    row = session.scalar(select(NotificationSuppression).where(NotificationSuppression.id == suppression_id).with_for_update())
    if row is None or row.removed_at is not None:
        raise ApiError("NOT_FOUND")
    row.removed_at, row.removed_by, row.removal_reason = datetime.now(UTC), principal.user.id, body.removal_reason
    audit.record(
        session, actor=principal, action="notification.suppression_removed", target_type="notification_suppression", target_id=row.id,
        reason=body.removal_reason, request_id=_request_id(request),
    )
    _commit(session)
    return _suppression_view(row)


# ---- templates and rules ----


def _template_view(t: NotificationTemplate) -> dict[str, Any]:
    return {
        "id": str(t.id),
        "template_key": t.template_key,
        "channel": t.channel,
        "locale": t.locale,
        "version": t.version,
        "status": t.status,
        "subject_template": t.subject_template,
        "title_template": t.title_template,
        "body_template": t.body_template,
        "variable_schema": t.variable_schema,
        "created_by": str(t.created_by) if t.created_by else None,
        "created_at": t.created_at.isoformat(),
        "activated_at": t.activated_at.isoformat() if t.activated_at else None,
    }


def _known(key: str) -> registry.Template:
    template = registry.TEMPLATES.get(key)
    if template is None:
        raise ApiError("NOT_FOUND")
    return template


@router.get("/notification-templates")
def list_templates(principal: Superadmin, session: DbSession) -> dict[str, Any]:
    active = {
        (t.template_key, t.channel, t.locale): t.version
        for t in session.scalars(select(NotificationTemplate).where(NotificationTemplate.status == "active"))
    }
    rules = {r.template_key: r for r in session.scalars(select(NotificationRule))}
    items = []
    for key, template in registry.TEMPLATES.items():
        code_rule = next((r for r in registry.RULES if r.template_key == key), None)
        live = rules.get(key)
        items.append({
            "template_key": key,
            "variables": list(template.variables),
            "audience": code_rule.audience if code_rule else None,
            "priority": live.priority if live else (code_rule.priority if code_rule else None),
            "email": live.email if live else (code_rule.email if code_rule else None),
            "enabled": live.enabled if live else True,
            "active_versions": {f"{channel}:{locale}": version for (k, channel, locale), version in active.items() if k == key},
        })
    return {"items": items}


@router.get("/notification-templates/{template_key}/versions")
def template_versions(template_key: str, principal: Superadmin, session: DbSession) -> dict[str, Any]:
    _known(template_key)
    rows = session.scalars(
        select(NotificationTemplate)
        .where(NotificationTemplate.template_key == template_key)
        .order_by(NotificationTemplate.channel, NotificationTemplate.locale, NotificationTemplate.version)
    )
    return {"items": [_template_view(t) for t in rows]}


@router.post("/notification-templates/{template_key}/versions", status_code=201)
def create_template_version(template_key: str, body: TemplateDraftBody, request: Request, principal: Superadmin, session: DbSession) -> dict[str, Any]:
    """A new draft version. Only the variables this notice allows may appear; published versions never change."""
    allowed = set(_known(template_key).variables)
    for text in (body.subject_template, body.title_template, body.body_template):
        if text is None:
            continue
        try:
            used = template_variables(text)
        except ValueError as error:
            raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "body_template", "code": "BAD_PLACEHOLDER"}]) from error
        if not used <= allowed:
            raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "body_template", "code": "UNKNOWN_VARIABLE"}])
    if body.channel == "in_app" and not body.title_template:
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "title_template", "code": "REQUIRED"}])
    latest = session.scalar(
        select(func.max(NotificationTemplate.version)).where(
            NotificationTemplate.template_key == template_key, NotificationTemplate.channel == body.channel, NotificationTemplate.locale == body.locale
        )
    ) or 0
    row = NotificationTemplate(
        template_key=template_key, channel=body.channel, locale=body.locale, version=latest + 1,
        subject_template=body.subject_template, title_template=body.title_template, body_template=body.body_template,
        variable_schema={"allowed": sorted(allowed)}, status="draft", created_by=principal.user.id,
    )
    session.add(row)
    session.flush()
    audit.record(
        session, actor=principal, action="notification.template_drafted", target_type="notification_template", target_id=row.id,
        metadata={"template_key": template_key, "channel": body.channel, "locale": body.locale, "version": row.version}, request_id=_request_id(request),
    )
    _commit(session)
    return _template_view(row)


@router.post("/notification-templates/{template_key}/versions/{version}/activate")
def activate_template_version(
    template_key: str, version: int, body: ActivateBody, request: Request, principal: Superadmin, session: DbSession
) -> dict[str, Any]:
    """Make one version the active text; the previously active one is retired (one active per key/channel/locale)."""
    _known(template_key)
    rows = list(
        session.scalars(
            select(NotificationTemplate)
            .where(NotificationTemplate.template_key == template_key, NotificationTemplate.channel == body.channel, NotificationTemplate.locale == body.locale)
            .with_for_update()
        )
    )
    target = next((t for t in rows if t.version == version), None)
    if target is None:
        raise ApiError("NOT_FOUND")
    if target.status == "active":
        return _template_view(target)
    if target.status == "retired":
        raise ApiError("TRANSITION_NOT_ALLOWED")
    previous = next((t for t in rows if t.status == "active"), None)
    if previous is not None:
        previous.status = "retired"
        session.flush()  # the partial unique index allows the new active row only after this
    target.status, target.activated_at = "active", datetime.now(UTC)
    audit.record(
        session, actor=principal, action="notification.template_activated", target_type="notification_template", target_id=target.id,
        metadata={"template_key": template_key, "channel": body.channel, "locale": body.locale, "version": version,
                  "previous_version": previous.version if previous else None},
        request_id=_request_id(request),
    )
    _commit(session)
    return _template_view(target)


@router.patch("/notification-rules/{template_key}")
def update_rule(template_key: str, body: RuleBody, request: Request, principal: Superadmin, session: DbSession) -> dict[str, Any]:
    """Tune an existing catalogue rule: priority, email on/off, enabled. Events and recipients stay in code."""
    code_rule = next((r for r in registry.RULES if r.template_key == template_key), None)
    if code_rule is None:
        raise ApiError("NOT_FOUND")
    row = session.get(NotificationRule, template_key)
    if row is None:
        row = NotificationRule(template_key=template_key, event_type=code_rule.event_type, priority=code_rule.priority, email=code_rule.email, enabled=True)
        session.add(row)
    before = {"priority": row.priority, "email": row.email, "enabled": row.enabled}
    for name in ("priority", "email", "enabled"):
        value = getattr(body, name)
        if value is not None:
            setattr(row, name, value)
    row.updated_at = datetime.now(UTC)
    audit.record(
        session, actor=principal, action="notification.rule_changed", target_type="notification_rule", target_id=template_key,
        metadata={"from": before, "to": {"priority": row.priority, "email": row.email, "enabled": row.enabled}}, request_id=_request_id(request),
    )
    _commit(session)
    return {"template_key": template_key, "priority": row.priority, "email": row.email, "enabled": row.enabled}
