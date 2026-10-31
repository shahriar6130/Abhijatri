"""Append-only audit events (Moderation spec 6.6).

Written in the same transaction as the change they describe. ``metadata`` carries approved,
non-secret facts: ids, states, versions. Never a password, token, email or free text from a user.
"""

import base64
import csv
import io
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.audit_actions import is_known
from app.auth.sessions import Principal
from app.errors import ApiError
from app.models import AuditEvent

logger = logging.getLogger(__name__)

# The test suite sets this so an action missing from ``app.audit_actions`` fails loudly; production only logs it.
STRICT = False


def record(
    session: Session,
    *,
    actor: Principal | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str,
    reason: str | None = None,
    metadata: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> AuditEvent:
    if not is_known(action):
        if STRICT:
            raise AssertionError(f"audit action {action!r} is not listed in app.audit_actions")
        logger.warning("audit action %s is not listed in app.audit_actions", action)
    event = AuditEvent(
        actor_user_id=actor.user.id if actor else None,
        actor_role_snapshot=actor.role if actor else None,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        request_id=request_id,
        reason=reason,
        event_metadata=metadata or {},
    )
    session.add(event)
    session.flush()
    return event


# ---- search, paging and export (Moderation spec 12.6) ----

EXPORT_LIMIT = 10_000
_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class AuditFilter:
    action: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    actor_user_id: uuid.UUID | None = None
    actor_role: str | None = None
    request_id: str | None = None
    since: datetime | None = None  # inclusive
    until: datetime | None = None  # exclusive

    def as_metadata(self) -> dict[str, str]:
        return {key: str(value) for key, value in self.__dict__.items() if value is not None}


def encode_cursor(event: AuditEvent) -> str:
    raw = f"{event.occurred_at.isoformat()}|{event.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        stamp, identifier = raw.split("|", 1)
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is None:
            raise ValueError("naive timestamp")
        return moment, uuid.UUID(identifier)
    except (ValueError, UnicodeDecodeError) as error:
        raise ApiError("INVALID_CURSOR") from error


def _statement(filters: AuditFilter) -> Select[Any]:
    statement = select(AuditEvent).order_by(AuditEvent.occurred_at.desc(), AuditEvent.id.desc())
    for column, value in (
        (AuditEvent.action, filters.action),
        (AuditEvent.target_type, filters.target_type),
        (AuditEvent.target_id, filters.target_id),
        (AuditEvent.actor_user_id, filters.actor_user_id),
        (AuditEvent.actor_role_snapshot, filters.actor_role),
        (AuditEvent.request_id, filters.request_id),
    ):
        if value:
            statement = statement.where(column == value)
    if filters.since is not None:
        statement = statement.where(AuditEvent.occurred_at >= filters.since)
    if filters.until is not None:
        statement = statement.where(AuditEvent.occurred_at < filters.until)
    return statement


def search(
    session: Session, filters: AuditFilter, *, limit: int, cursor: str | None = None, before: datetime | None = None
) -> tuple[list[AuditEvent], str | None]:
    """Newest first. The cursor is a keyset on (occurred_at, id), so rows that share a timestamp are neither
    skipped nor repeated. ``before`` is the older timestamp-only form, kept for existing clients."""
    statement = _statement(filters)
    if cursor:
        moment, identifier = decode_cursor(cursor)
        statement = statement.where(
            or_(AuditEvent.occurred_at < moment, and_(AuditEvent.occurred_at == moment, AuditEvent.id < identifier))
        )
    elif before is not None:
        statement = statement.where(AuditEvent.occurred_at < before)
    rows = list(session.scalars(statement.limit(limit + 1)))
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, (encode_cursor(rows[-1]) if more and rows else None)


def _safe_cell(value: object) -> str:
    """A spreadsheet runs text that starts with = + - @ as a formula; a leading quote makes it plain text."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_FORMULA_START) else text


def export_csv(session: Session, filters: AuditFilter) -> tuple[str, int, bool]:
    """At most ``EXPORT_LIMIT`` rows as CSV; the flag says whether more matched."""
    rows = list(session.scalars(_statement(filters).limit(EXPORT_LIMIT + 1)))
    truncated = len(rows) > EXPORT_LIMIT
    rows = rows[:EXPORT_LIMIT]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["id", "occurred_at", "actor_user_id", "actor_role", "action", "target_type", "target_id", "request_id", "reason", "metadata"])
    for event in rows:
        writer.writerow(
            [
                _safe_cell(value)
                for value in (
                    event.id, event.occurred_at.isoformat(), event.actor_user_id, event.actor_role_snapshot, event.action,
                    event.target_type, event.target_id, event.request_id, event.reason, json.dumps(event.event_metadata, sort_keys=True),
                )
            ]
        )
    return buffer.getvalue(), len(rows), truncated
