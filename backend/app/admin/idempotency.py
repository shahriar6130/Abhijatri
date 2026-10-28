"""Retry-safe decisions (Moderation spec 8.2).

The same key with the same payload returns the original result; the same key with a different
payload is a 409. The key row is written in the same transaction as the decision, so a failed
decision leaves no key behind and can be retried. Idempotency does not replace the database
constraints or the version and lease checks.
"""

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import IdempotencyKey

KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{8,100}$")


def fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run(
    session: Session,
    *,
    actor_id: uuid.UUID,
    operation: str,
    key: str | None,
    payload: dict[str, Any],
    action: Callable[[], tuple[int, dict[str, Any]]],
) -> tuple[int, dict[str, Any]]:
    """Run ``action`` once per (actor, operation, key). Without a key the action simply runs."""
    if key is None:
        return action()
    if not KEY_PATTERN.fullmatch(key):
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "Idempotency-Key", "code": "INVALID_VALUE"}])
    print_ = fingerprint(payload)
    inserted = session.execute(
        insert(IdempotencyKey)
        .values(actor_user_id=actor_id, operation=operation, key=key, fingerprint=print_, status_code=0, response={})
        .on_conflict_do_nothing()
        .returning(IdempotencyKey.key)
    ).first()
    if inserted is None:  # a committed row exists: replay it, or refuse a different payload
        existing = session.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.actor_user_id == actor_id,
                IdempotencyKey.operation == operation,
                IdempotencyKey.key == key,
            )
        )
        if existing is None or existing.fingerprint != print_:
            raise ApiError("IDEMPOTENCY_KEY_REUSED")
        return existing.status_code, dict(existing.response)
    status_code, body = action()
    row = session.get(IdempotencyKey, (actor_id, operation, key))
    if row is not None:
        row.status_code, row.response = status_code, body
    return status_code, body
