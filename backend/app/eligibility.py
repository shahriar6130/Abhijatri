"""Who counts towards a destination's Community Rating (Review.md 6.1).

``evaluate_eligibility`` is the single place that decides it. The rating code in ``services.py`` calls it
when a review is published, restored or re-checked, so the rules cannot drift between code paths. It reads
the database but never writes, and it imports nothing from ``services`` so both can use it.

The checks run in this order and the first one that fails names the reason:

1. not published                       -> INELIGIBLE_REMOVED (INELIGIBLE_REPORTED while hidden)
2. conflict of interest declared       -> INELIGIBLE_CONFLICT (also keeps a Guest review out of Guest Feedback)
3. a Guest review                      -> INELIGIBLE_GUEST (it feeds Guest Feedback, never the Community Rating)
4. project-team account                -> INELIGIBLE_UNVERIFIED
5. no active Verified Member record    -> INELIGIBLE_UNVERIFIED
6. future visit month or incomplete    -> INELIGIBLE_INVALID
7. an earlier counted review of the same destination and month by the same author
                                       -> INELIGIBLE_DUPLICATE
8. an open serious report              -> INELIGIBLE_REPORTED
9. otherwise                           -> ELIGIBLE
"""

import uuid
from datetime import date, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (
    RatingEligibility,
    Report,
    Review,
    ReviewRevision,
    ReviewStatus,
    User,
    Verification,
)
from app.models import utcnow as _utcnow

# Report reasons that take a review out of the rating while the report is open (Review.md 5.4, 6.1:
# "a serious unresolved report"). Spam, offensive wording, false information and "other" are handled
# by moderators through the normal queue and do not suspend a rating (Decisions.md).
SERIOUS_REPORT_REASONS = frozenset({"privacy", "conflict_of_interest"})
OPEN_REPORT_STATES = ("open", "in_review")


def _today() -> date:
    return datetime.now(get_settings().display_tz).date()


def _has_active_verification(session: Session, user_id: uuid.UUID) -> bool:
    now = _utcnow()
    return (
        session.scalar(
            select(Verification.id).where(
                Verification.user_id == user_id,
                Verification.verification_type == "VERIFIED_MEMBER",
                Verification.status == "APPROVED",
                Verification.revoked_at.is_(None),
                or_(Verification.expires_at.is_(None), Verification.expires_at > now),
            )
        )
        is not None
    )


def _is_complete(session: Session, review: Review, today: date) -> bool:
    """A rateable review has a current revision with text, a rating in range and a visit month not in the future."""
    if review.current_revision_id is None or not 1 <= review.overall_rating <= 5:
        return False
    if review.visit_month > today.replace(day=1):
        return False
    revision = session.get(ReviewRevision, review.current_revision_id)
    return revision is not None and bool(revision.title.strip()) and bool(revision.body.strip())


def _is_duplicate(session: Session, review: Review) -> bool:
    """True when the same author already has a counted, published review of this destination and month.

    Only a moderator override (``duplicate_override``) lets two reviews coexist. The earlier one keeps
    its count; the later one, by publication time and then id, is the duplicate.
    """
    if review.published_at is None:
        return False
    return (
        session.scalar(
            select(Review.id).where(
                Review.id != review.id,
                Review.author_user_id == review.author_user_id,
                Review.destination_id == review.destination_id,
                Review.visit_month == review.visit_month,
                Review.status == ReviewStatus.PUBLISHED,
                Review.counted_rating.is_not(None),
                or_(
                    Review.published_at < review.published_at,
                    and_(Review.published_at == review.published_at, Review.id < review.id),
                ),
            )
        )
        is not None
    )


def has_serious_open_report(session: Session, review_id: uuid.UUID) -> bool:
    return (
        session.scalar(
            select(Report.id).where(
                Report.review_id == review_id,
                Report.state.in_(OPEN_REPORT_STATES),
                Report.reason_code.in_(SERIOUS_REPORT_REASONS),
            )
        )
        is not None
    )


def evaluate_eligibility(session: Session, review: Review, *, today: date | None = None) -> RatingEligibility:
    """The rating state a review would have if it were counted now (Review.md 6.1)."""
    if review.status != ReviewStatus.PUBLISHED:
        return (
            RatingEligibility.INELIGIBLE_REPORTED
            if review.status == ReviewStatus.HIDDEN
            else RatingEligibility.INELIGIBLE_REMOVED
        )
    if review.conflict_declared:
        return RatingEligibility.INELIGIBLE_CONFLICT
    if review.author_user_id is None:
        return RatingEligibility.INELIGIBLE_GUEST
    author = session.get(User, review.author_user_id)
    if author is None or author.is_team_account:
        return RatingEligibility.INELIGIBLE_UNVERIFIED
    if not _has_active_verification(session, review.author_user_id):
        return RatingEligibility.INELIGIBLE_UNVERIFIED
    if not _is_complete(session, review, today or _today()):
        return RatingEligibility.INELIGIBLE_INVALID
    if _is_duplicate(session, review):
        return RatingEligibility.INELIGIBLE_DUPLICATE
    if has_serious_open_report(session, review.id):
        return RatingEligibility.INELIGIBLE_REPORTED
    return RatingEligibility.ELIGIBLE
