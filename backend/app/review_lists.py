"""Staff lists of Rejected and Hidden reviews with their recovery window (Moderation spec P-03; Gantt R11).

A rejected review can be reopened by a superadmin for 30 days after the rejection; after that retention redacts its
text. A hidden review has no deadline. The list never returns text that retention already removed.
"""

import base64
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import ApiError
from app.models import (
    ModerationActionRecord,
    ModerationDecision,
    Review,
    ReviewRevision,
    ReviewStatus,
)
from app.services import REOPEN_WINDOW

DECISION_FOR_STATUS = {ReviewStatus.REJECTED: ModerationDecision.REJECT, ReviewStatus.HIDDEN: ModerationDecision.HIDE}
REMOVED_TEXT = "[removed]"


def _encode(moment: datetime, identifier: uuid.UUID) -> str:
    return base64.urlsafe_b64encode(f"{moment.isoformat()}|{identifier}".encode()).decode().rstrip("=")


def _decode(value: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        stamp, identifier = raw.split("|", 1)
        moment = datetime.fromisoformat(stamp)
        if moment.tzinfo is None:
            raise ValueError("naive timestamp")
        return moment, uuid.UUID(identifier)
    except (ValueError, UnicodeDecodeError) as error:
        raise ApiError("INVALID_CURSOR") from error


def list_decided(session: Session, *, status: ReviewStatus, limit: int, after: str | None) -> dict[str, Any]:
    """Reviews in ``status`` ordered by the time of the decision that put them there, newest first."""
    decision = DECISION_FOR_STATUS[status]
    decided = (
        select(ModerationActionRecord.review_id, func.max(ModerationActionRecord.created_at).label("decided_at"))
        .where(ModerationActionRecord.decision == decision)
        .group_by(ModerationActionRecord.review_id)
        .subquery()
    )
    statement = (
        select(Review, decided.c.decided_at)
        .join(decided, decided.c.review_id == Review.id)
        .where(Review.status == status)
        .order_by(decided.c.decided_at.desc(), Review.id.desc())
        .limit(limit + 1)
    )
    if after:
        moment, identifier = _decode(after)
        statement = statement.where(
            (decided.c.decided_at < moment) | ((decided.c.decided_at == moment) & (Review.id < identifier))
        )
    rows: list[tuple[Review, datetime]] = [(row[0], row[1]) for row in session.execute(statement)]
    more = len(rows) > limit
    rows = rows[:limit]
    items: list[dict[str, Any]] = []
    for review, decided_at in rows:
        revision = session.get(ReviewRevision, review.current_revision_id) if review.current_revision_id else None
        purged = review.purged_at is not None
        reason = session.scalar(
            select(ModerationActionRecord.reason_code)
            .where(ModerationActionRecord.review_id == review.id, ModerationActionRecord.decision == decision)
            .order_by(ModerationActionRecord.created_at.desc())
            .limit(1)
        )
        items.append(
            {
                "review_id": str(review.id),
                "destination_id": str(review.destination_id),
                "status": review.status.value,
                "version": review.version,
                "author": "member" if review.author_user_id else "guest",
                "title": REMOVED_TEXT if purged or revision is None else revision.title,
                "overall_rating": review.overall_rating,
                "counted_rating": review.counted_rating,
                "decided_at": decided_at.isoformat(),
                "reason_code": reason,
                "purged": purged,
                # Only a rejected review has a deadline, and only while its text still exists.
                "recoverable_until": (decided_at + REOPEN_WINDOW).isoformat() if status == ReviewStatus.REJECTED and not purged else None,
            }
        )
    last = rows[-1] if rows else None
    return {"items": items, "next_cursor": _encode(last[1], last[0].id) if more and last else None}
