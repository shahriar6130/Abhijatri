from __future__ import annotations

import base64
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crypto
from app.admin.tasks import cancel_open_tasks, ensure_task
from app.guest_tag import stored_guest_tag
from app.models import (
    Destination,
    DestinationCategoryStats,
    DestinationRatingStats,
    DestinationStatus,
    ModerationActionRecord,
    ModerationDecision,
    OutboxEvent,
    RatingAudience,
    RatingEligibility,
    Review,
    ReviewCategory,
    ReviewCategoryRating,
    ReviewReceipt,
    ReviewRevision,
    ReviewStatus,
    RevisionStatus,
    User,
    Verification,
)
from app.schemas import CategoryAverage, GuestReviewCreate, MemberReviewCreate, ReviewContent


class ReviewError(Exception):
    """A domain failure. ``code`` is a key of ``app.errors.CATALOGUE``."""

    default_code = "INTERNAL_ERROR"

    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code or self.default_code


class ReviewNotFound(ReviewError):
    default_code = "NOT_FOUND"


class ReviewConflict(ReviewError):
    default_code = "INVALID_TRANSITION"


class ReviewForbidden(ReviewError):
    default_code = "FORBIDDEN"


@dataclass(frozen=True)
class GuestSubmissionResult:
    review: Review
    duplicate_recovered: bool


RESERVED_NAME_SKELETONS = {
    "admin",
    "administrator",
    "moderator",
    "official",
    "verified",
    "abhijatristaff",
}


def now_utc() -> datetime:
    return datetime.now(UTC)


def _name_skeleton(value: str) -> str:
    folded = value.casefold()
    return "".join(character for character in folded if character.isalnum())


def normalize_guest_name(value: str) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized or len(normalized) > 80:
        raise ReviewConflict("invalid guest display name", "RESERVED_DISPLAY_NAME")
    skeleton = _name_skeleton(normalized)
    if skeleton in RESERVED_NAME_SKELETONS or "✓" in normalized or "✔" in normalized:
        raise ReviewConflict("reserved or misleading guest display name", "RESERVED_DISPLAY_NAME")
    return normalized


APPEAL_WINDOW = timedelta(days=30)


def require_receipt_format(receipt_secret: str) -> None:
    if crypto.receipt_format_problem(receipt_secret) is not None:
        raise ReviewError("receipt format is not valid", "INVALID_RECEIPT_FORMAT")


def _receipt_matches(session: Session, review_id: uuid.UUID, receipt_secret: str) -> ReviewReceipt | None:
    """The live receipt row of ``review_id`` that ``receipt_secret`` digests to, under any retained key."""
    for key_id, value in crypto.candidate_digests(crypto.RECEIPT_LABEL, receipt_secret):
        receipt = session.scalar(
            select(ReviewReceipt).where(
                ReviewReceipt.review_id == review_id,
                ReviewReceipt.key_id == key_id,
                ReviewReceipt.digest == value,
                ReviewReceipt.revoked_at.is_(None),
            )
        )
        if receipt is not None:
            return receipt
    return None


def _find_guest_draft(session: Session, scope_secret: str, draft_id: uuid.UUID) -> Review | None:
    hashes = [value for _, value in crypto.candidate_digests(crypto.GUEST_SCOPE_LABEL, scope_secret)]
    return session.scalar(
        select(Review).where(
            Review.author_user_id.is_(None),
            Review.guest_scope_hash.in_(hashes),
            Review.client_draft_id == draft_id,
        )
    )


def _recover_duplicate(session: Session, existing: Review, receipt_secret: str) -> GuestSubmissionResult:
    # The same Guest scope and draft id identify the draft. Only the same receipt may recover it:
    # a different receipt is refused and never reveals the review (PF 13.3).
    if _receipt_matches(session, existing.id, receipt_secret) is None:
        raise ReviewConflict("draft already submitted with a different receipt", "DRAFT_ALREADY_SUBMITTED")
    return GuestSubmissionResult(review=existing, duplicate_recovered=True)


def find_recoverable_draft(session: Session, payload: GuestReviewCreate) -> Review | None:
    """Step 2 of the submission order (API.md 5.2).

    Returns the existing review when the same Guest scope and draft id arrive with the same
    receipt. A different receipt raises ``DRAFT_ALREADY_SUBMITTED``. Nothing is counted and no
    challenge is consumed on this path, so a retry after a lost response is free.
    """
    require_receipt_format(payload.receipt_secret)
    existing = _find_guest_draft(session, payload.guest_scope_secret, payload.client_draft_id)
    if existing is None:
        return None
    return _recover_duplicate(session, existing, payload.receipt_secret).review


def submit_guest_review(session: Session, payload: GuestReviewCreate) -> GuestSubmissionResult:
    require_receipt_format(payload.receipt_secret)
    destination = session.scalar(
        select(Destination).where(
            Destination.id == payload.destination_id,
            Destination.status == DestinationStatus.PUBLISHED,
        )
    )
    if destination is None:
        raise ReviewNotFound("published destination not found")

    existing = _find_guest_draft(session, payload.guest_scope_secret, payload.client_draft_id)
    if existing is not None:
        return _recover_duplicate(session, existing, payload.receipt_secret)

    key_id = crypto.current_key_id()
    receipt_digest = crypto.digest(crypto.RECEIPT_LABEL, key_id, payload.receipt_secret)
    if session.scalar(
        select(ReviewReceipt.id).where(
            ReviewReceipt.key_id == key_id, ReviewReceipt.digest == receipt_digest
        )
    ):
        # A receipt is bound to exactly one review.
        raise ReviewConflict("receipt already bound to another review", "DRAFT_ALREADY_SUBMITTED")

    review = Review(
        destination_id=payload.destination_id,
        guest_display_name=normalize_guest_name(payload.guest_display_name),
        guest_scope_hash=crypto.digest(crypto.GUEST_SCOPE_LABEL, key_id, payload.guest_scope_secret),
        guest_scope_key_id=key_id,
        # Computed here from the secret, never accepted from the client (Guest-Identity 3.1, D3).
        guest_tag=stored_guest_tag(payload.guest_scope_secret),
        client_draft_id=payload.client_draft_id,
        status=ReviewStatus.PENDING,
        rating_eligibility=RatingEligibility.NOT_EVALUATED,
        overall_rating=payload.overall_rating,
        visit_month=payload.visit_month,
    )
    try:
        with session.begin_nested():
            session.add(review)
            session.flush()
            session.add(ReviewReceipt(review_id=review.id, key_id=key_id, digest=receipt_digest))
            session.flush()
    except IntegrityError:
        # A simultaneous retry can pass the read check while the first request
        # is still uncommitted. The unique indexes are authoritative.
        existing = _find_guest_draft(session, payload.guest_scope_secret, payload.client_draft_id)
        if existing is None:
            raise ReviewConflict(
                "receipt already bound to another review", "DRAFT_ALREADY_SUBMITTED"
            ) from None
        return _recover_duplicate(session, existing, payload.receipt_secret)

    _add_content(session, review, payload)
    return GuestSubmissionResult(review=review, duplicate_recovered=False)


def _add_content(session: Session, review: Review, payload: ReviewContent) -> None:
    """First revision, category ratings, stats row, outbox event and the moderation task."""
    revision = ReviewRevision(
        review_id=review.id,
        sequence=1,
        status=RevisionStatus.PENDING,
        language=payload.language,
        traveller_type=payload.traveller_type,
        comfort_tier=payload.comfort_tier,
        title=payload.title,
        body=payload.body,
        overall_rating=payload.overall_rating,
        consent_version=payload.consent_version,
    )
    session.add(revision)
    session.flush()
    review.current_revision_id = revision.id
    for category, rating in (payload.category_ratings or {}).items():
        session.add(ReviewCategoryRating(revision_id=revision.id, category=category, rating=rating))

    session.execute(
        insert(DestinationRatingStats)
        .values(destination_id=payload.destination_id)
        .on_conflict_do_nothing(index_elements=[DestinationRatingStats.destination_id])
    )
    session.add(
        OutboxEvent(
            topic="review.submitted",
            aggregate_id=review.id,
            payload={"review_id": str(review.id), "destination_id": str(review.destination_id)},
        )
    )
    ensure_task(session, "review_moderation", review.id)  # the review appears in the moderators' queue


def _published_destination(session: Session, destination_id: uuid.UUID) -> Destination:
    destination = session.scalar(
        select(Destination).where(Destination.id == destination_id, Destination.status == DestinationStatus.PUBLISHED)
    )
    if destination is None:
        raise ReviewNotFound("published destination not found")
    return destination


def submit_member_review(session: Session, payload: MemberReviewCreate, author_id: uuid.UUID) -> GuestSubmissionResult:
    """A signed-in member's review (Review.md 3.3). The same draft id and receipt make a retry safe;
    one active review per member, destination and visit month (``uq_reviews_member_active_visit``)."""
    require_receipt_format(payload.receipt_secret)
    _published_destination(session, payload.destination_id)

    def existing_draft() -> Review | None:
        return session.scalar(
            select(Review).where(Review.author_user_id == author_id, Review.client_draft_id == payload.client_draft_id)
        )

    existing = existing_draft()
    if existing is not None:
        return _recover_duplicate(session, existing, payload.receipt_secret)
    key_id = crypto.current_key_id()
    receipt_digest = crypto.digest(crypto.RECEIPT_LABEL, key_id, payload.receipt_secret)
    if session.scalar(select(ReviewReceipt.id).where(ReviewReceipt.key_id == key_id, ReviewReceipt.digest == receipt_digest)):
        raise ReviewConflict("receipt already bound to another review", "DRAFT_ALREADY_SUBMITTED")
    review = Review(
        destination_id=payload.destination_id,
        author_user_id=author_id,
        client_draft_id=payload.client_draft_id,
        status=ReviewStatus.PENDING,
        rating_eligibility=RatingEligibility.NOT_EVALUATED,
        overall_rating=payload.overall_rating,
        visit_month=payload.visit_month,
    )
    try:
        with session.begin_nested():
            session.add(review)
            session.flush()
            session.add(ReviewReceipt(review_id=review.id, key_id=key_id, digest=receipt_digest))
            session.flush()
    except IntegrityError:
        existing = existing_draft()
        if existing is not None:  # a simultaneous retry of the same draft
            return _recover_duplicate(session, existing, payload.receipt_secret)
        raise ReviewConflict("member already reviewed this destination for that month", "MEMBER_REVIEW_EXISTS") from None
    _add_content(session, review, payload)
    return GuestSubmissionResult(review=review, duplicate_recovered=False)


def verify_receipt(session: Session, review_id: uuid.UUID, receipt_secret: str) -> Review:
    """Return the review a receipt belongs to, or raise RECEIPT_NOT_FOUND.

    A wrong receipt and a missing review give the same answer so existence is not leaked.
    A receipt stored under an older key is re-digested under the current key in this transaction.
    """
    require_receipt_format(receipt_secret)
    receipt = _receipt_matches(session, review_id, receipt_secret)
    review = session.get(Review, review_id) if receipt is not None else None
    if receipt is None or review is None:
        raise ReviewNotFound("receipt not found", "RECEIPT_NOT_FOUND")
    current = crypto.current_key_id()
    if receipt.key_id != current:
        receipt.key_id = current
        receipt.digest = crypto.digest(crypto.RECEIPT_LABEL, current, receipt_secret)
    return review


@dataclass(frozen=True)
class RejectionDetails:
    decision_reason: str | None
    appeal_deadline: datetime | None


def rejection_details(session: Session, review: Review) -> RejectionDetails:
    """Public-safe reason and appeal deadline; both are None unless the review is REJECTED."""
    if review.status != ReviewStatus.REJECTED:
        return RejectionDetails(None, None)
    action = session.scalar(
        select(ModerationActionRecord)
        .where(
            ModerationActionRecord.review_id == review.id,
            ModerationActionRecord.decision == ModerationDecision.REJECT,
        )
        .order_by(ModerationActionRecord.created_at.desc())
        .limit(1)
    )
    if action is None:
        return RejectionDetails(None, None)
    return RejectionDetails(action.reason_code, action.created_at + APPEAL_WINDOW)


def _lock_review(session: Session, review_id: uuid.UUID) -> Review:
    review = session.scalar(select(Review).where(Review.id == review_id).with_for_update())
    if review is None:
        raise ReviewNotFound("review not found")
    return review


def _lock_stats(session: Session, destination_id: uuid.UUID) -> DestinationRatingStats:
    stats = session.scalar(
        select(DestinationRatingStats)
        .where(DestinationRatingStats.destination_id == destination_id)
        .with_for_update()
    )
    if stats is None:
        session.execute(
            insert(DestinationRatingStats)
            .values(destination_id=destination_id)
            .on_conflict_do_nothing(index_elements=[DestinationRatingStats.destination_id])
        )
        stats = session.scalar(
            select(DestinationRatingStats)
            .where(DestinationRatingStats.destination_id == destination_id)
            .with_for_update()
        )
    if stats is None:
        raise RuntimeError("rating aggregate could not be created")
    return stats


def revision_category_ratings(
    session: Session, revision_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[ReviewCategory, int]]:
    """Category scores of several revisions in one query, keyed by revision id."""
    ratings: dict[uuid.UUID, dict[ReviewCategory, int]] = {revision_id: {} for revision_id in revision_ids}
    if not revision_ids:
        return ratings
    rows = session.scalars(
        select(ReviewCategoryRating).where(ReviewCategoryRating.revision_id.in_(revision_ids))
    )
    for row in rows:
        ratings[row.revision_id][row.category] = row.rating
    return ratings


def _audience(review: Review) -> RatingAudience:
    return RatingAudience.GUEST if review.author_user_id is None else RatingAudience.COMMUNITY


def _apply_category_delta(session: Session, review: Review, sign: int) -> None:
    """Add (+1) or remove (-1) the current revision's category scores, in the caller's transaction.

    Called exactly where the overall rating is counted or uncounted, so both aggregates move
    together. Published revisions are not editable in the MVP, so the rows being removed are the
    rows that were added. Rows are locked in category order to keep a fixed lock order.
    """
    if review.current_revision_id is None:
        return
    scores = revision_category_ratings(session, [review.current_revision_id])[review.current_revision_id]
    if not scores:
        return
    audience = _audience(review)
    categories = sorted(scores, key=lambda category: category.value)
    session.execute(
        insert(DestinationCategoryStats)
        .values(
            [
                {
                    "destination_id": review.destination_id,
                    "category": category,
                    "audience": audience,
                    "rating_sum": 0,
                    "rating_count": 0,
                    "updated_at": now_utc(),
                }
                for category in categories
            ]
        )
        .on_conflict_do_nothing()
    )
    rows = session.scalars(
        select(DestinationCategoryStats)
        .where(
            DestinationCategoryStats.destination_id == review.destination_id,
            DestinationCategoryStats.audience == audience,
            DestinationCategoryStats.category.in_(categories),
        )
        .order_by(DestinationCategoryStats.category)
        .with_for_update()
    ).all()
    for row in rows:
        row.rating_sum += sign * scores[row.category]
        row.rating_count += sign
        row.updated_at = now_utc()


def category_averages(
    session: Session, destination_ids: list[uuid.UUID]
) -> dict[tuple[uuid.UUID, RatingAudience], list[CategoryAverage]]:
    """Per-category averages for several destinations in one query; empty categories are left out."""
    averages: dict[tuple[uuid.UUID, RatingAudience], list[CategoryAverage]] = {}
    if not destination_ids:
        return averages
    rows = session.scalars(
        select(DestinationCategoryStats).where(
            DestinationCategoryStats.destination_id.in_(destination_ids),
            DestinationCategoryStats.rating_count > 0,
        )
    ).all()
    order = list(ReviewCategory)
    for row in sorted(rows, key=lambda row: order.index(row.category)):
        averages.setdefault((row.destination_id, row.audience), []).append(
            CategoryAverage(
                category=row.category,
                average=row.rating_sum / row.rating_count,
                count=row.rating_count,
            )
        )
    return averages


def _remove_counted_rating(session: Session, review: Review, stats: DestinationRatingStats) -> None:
    if review.counted_rating is None:
        return
    _apply_category_delta(session, review, -1)
    if review.author_user_id is None:
        stats.guest_rating_sum -= review.counted_rating
        stats.guest_rating_count -= 1
    else:
        stats.community_rating_sum -= review.counted_rating
        stats.community_rating_count -= 1
    review.counted_rating = None
    stats.version += 1
    stats.updated_at = now_utc()


def _is_verified_member_eligible(session: Session, review: Review) -> bool:
    if review.author_user_id is None or review.conflict_declared:
        return False
    author = session.get(User, review.author_user_id)
    if author is None or author.is_team_account:
        return False
    now = now_utc()
    return (
        session.scalar(
            select(Verification.id).where(
                Verification.user_id == review.author_user_id,
                Verification.verification_type == "VERIFIED_MEMBER",
                Verification.status == "APPROVED",
                Verification.revoked_at.is_(None),
                or_(Verification.expires_at.is_(None), Verification.expires_at > now),
            )
        )
        is not None
    )


def _add_published_rating(
    session: Session,
    review: Review,
    stats: DestinationRatingStats,
) -> None:
    if review.conflict_declared:
        review.rating_eligibility = RatingEligibility.INELIGIBLE_CONFLICT
        review.counted_rating = None
        return
    if review.author_user_id is None:
        review.rating_eligibility = RatingEligibility.INELIGIBLE_GUEST
        stats.guest_rating_sum += review.overall_rating
        stats.guest_rating_count += 1
    elif _is_verified_member_eligible(session, review):
        review.rating_eligibility = RatingEligibility.ELIGIBLE
        stats.community_rating_sum += review.overall_rating
        stats.community_rating_count += 1
    else:
        review.rating_eligibility = RatingEligibility.INELIGIBLE_UNVERIFIED
        review.counted_rating = None
        return
    _apply_category_delta(session, review, +1)
    review.counted_rating = review.overall_rating
    stats.version += 1
    stats.updated_at = now_utc()


def moderate_review(
    session: Session,
    *,
    review_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_version: int,
    decision: ModerationDecision,
    reason_code: str,
    note: str | None,
    task_id: uuid.UUID | None = None,
    request_id: str | None = None,
) -> Review:
    review = _lock_review(session, review_id)
    if review.version != expected_version:
        raise ReviewConflict("review version changed", "REVIEW_VERSION_CONFLICT")
    if review.author_user_id == actor_user_id:
        raise ReviewForbidden("moderators cannot act on their own reviews", "SELF_MODERATION_FORBIDDEN")

    actor = session.get(User, actor_user_id)
    if actor is None:
        raise ReviewForbidden("moderator not found")

    previous_status = review.status
    stats = _lock_stats(session, review.destination_id)
    revision = session.get(ReviewRevision, review.current_revision_id)
    if revision is None:
        raise ReviewConflict("review has no current revision")

    if decision == ModerationDecision.PUBLISH:
        if review.status not in {ReviewStatus.PENDING, ReviewStatus.UNDER_REVIEW}:
            raise ReviewConflict("review cannot be published from its current state")
        _remove_counted_rating(session, review, stats)
        review.status = ReviewStatus.PUBLISHED
        review.published_at = now_utc()
        revision.status = RevisionStatus.PUBLISHED
        _add_published_rating(session, review, stats)
    elif decision == ModerationDecision.REJECT:
        if review.status not in {ReviewStatus.PENDING, ReviewStatus.UNDER_REVIEW}:
            raise ReviewConflict("review cannot be rejected from its current state")
        _remove_counted_rating(session, review, stats)
        review.status = ReviewStatus.REJECTED
        review.rating_eligibility = RatingEligibility.INELIGIBLE_REMOVED
        revision.status = RevisionStatus.REJECTED
    elif decision == ModerationDecision.HIDE:
        if review.status != ReviewStatus.PUBLISHED:
            raise ReviewConflict("only a published review can be hidden")
        _remove_counted_rating(session, review, stats)
        review.status = ReviewStatus.HIDDEN
        review.rating_eligibility = RatingEligibility.INELIGIBLE_REPORTED
    elif decision == ModerationDecision.RESTORE:
        if review.status != ReviewStatus.HIDDEN:
            raise ReviewConflict("only a hidden review can be restored")
        _remove_counted_rating(session, review, stats)
        review.status = ReviewStatus.PUBLISHED
        _add_published_rating(session, review, stats)
    else:
        raise ReviewConflict("unsupported moderation decision")

    review.version += 1
    review.updated_at = now_utc()
    session.add(
        ModerationActionRecord(
            review_id=review.id,
            actor_user_id=actor_user_id,
            decision=decision,
            previous_status=previous_status,
            new_status=review.status,
            reason_code=reason_code,
            note=note,
            task_id=task_id,
            request_id=request_id,
        )
    )
    session.add(
        OutboxEvent(
            topic="review.state_changed",
            aggregate_id=review.id,
            payload={
                "review_id": str(review.id),
                "destination_id": str(review.destination_id),
                "status": review.status.value,
                "version": review.version,
            },
        )
    )
    return review


def set_review_conflict(
    session: Session,
    *,
    review_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    expected_version: int,
    conflict_declared: bool,
    reason_code: str,
    note: str | None,
) -> Review:
    review = _lock_review(session, review_id)
    if review.version != expected_version:
        raise ReviewConflict("review version changed", "REVIEW_VERSION_CONFLICT")
    if review.author_user_id == actor_user_id:
        raise ReviewForbidden("moderators cannot act on their own reviews", "SELF_MODERATION_FORBIDDEN")
    if session.get(User, actor_user_id) is None:
        raise ReviewForbidden("moderator not found")
    if review.conflict_declared == conflict_declared:
        return review

    stats = _lock_stats(session, review.destination_id)
    previous_status = review.status
    _remove_counted_rating(session, review, stats)
    review.conflict_declared = conflict_declared
    if review.status == ReviewStatus.PUBLISHED:
        _add_published_rating(session, review, stats)
    review.version += 1
    review.updated_at = now_utc()

    decision = (
        ModerationDecision.SET_CONFLICT
        if conflict_declared
        else ModerationDecision.CLEAR_CONFLICT
    )
    session.add(
        ModerationActionRecord(
            review_id=review.id,
            actor_user_id=actor_user_id,
            decision=decision,
            previous_status=previous_status,
            new_status=review.status,
            reason_code=reason_code,
            note=note,
        )
    )
    session.add(
        OutboxEvent(
            topic="review.conflict_changed",
            aggregate_id=review.id,
            payload={
                "review_id": str(review.id),
                "destination_id": str(review.destination_id),
                "conflict_declared": conflict_declared,
                "version": review.version,
            },
        )
    )
    return review


def withdraw_review(session: Session, review_id: uuid.UUID, expected_version: int) -> Review:
    review = _lock_review(session, review_id)
    # Withdrawal is idempotent: a retry after a lost response must succeed, so the
    # already-withdrawn answer comes before the version check (API.md 5.4).
    if review.status in {ReviewStatus.WITHDRAWN, ReviewStatus.DELETED}:
        return review
    if review.version != expected_version:
        raise ReviewConflict("review version changed", "REVIEW_VERSION_CONFLICT")
    stats = _lock_stats(session, review.destination_id)
    _remove_counted_rating(session, review, stats)
    review.status = ReviewStatus.WITHDRAWN
    review.rating_eligibility = RatingEligibility.INELIGIBLE_REMOVED
    review.withdrawn_at = now_utc()
    review.updated_at = now_utc()
    review.version += 1
    session.add(
        OutboxEvent(
            topic="review.withdrawn",
            aggregate_id=review.id,
            payload={"review_id": str(review.id), "destination_id": str(review.destination_id)},
        )
    )
    cancel_open_tasks(session, review.id)  # a withdrawn review leaves the queue
    return review


def full_guest_recompute(session: Session, destination_id: uuid.UUID) -> tuple[int, int]:
    result = session.execute(
        select(func.coalesce(func.sum(Review.counted_rating), 0), func.count(Review.id)).where(
            Review.destination_id == destination_id,
            Review.author_user_id.is_(None),
            Review.status == ReviewStatus.PUBLISHED,
            Review.counted_rating.is_not(None),
        )
    ).one()
    return int(result[0] or 0), int(result[1])


def full_guest_category_recompute(
    session: Session, destination_id: uuid.UUID
) -> dict[ReviewCategory, tuple[int, int]]:
    """Expected Guest category (sum, count) from published source rows, for reconciliation (6.3)."""
    rows = session.execute(
        select(
            ReviewCategoryRating.category,
            func.sum(ReviewCategoryRating.rating),
            func.count(ReviewCategoryRating.rating),
        )
        .join(Review, Review.current_revision_id == ReviewCategoryRating.revision_id)
        .where(
            Review.destination_id == destination_id,
            Review.author_user_id.is_(None),
            Review.status == ReviewStatus.PUBLISHED,
            Review.counted_rating.is_not(None),
        )
        .group_by(ReviewCategoryRating.category)
    ).all()
    return {category: (int(total), int(count)) for category, total, count in rows}


def encode_cursor(published_at: datetime, review_id: uuid.UUID) -> str:
    raw = f"{published_at.isoformat()}|{review_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

