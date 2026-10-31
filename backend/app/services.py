from __future__ import annotations

import base64
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crypto
from app.admin.tasks import cancel_open_tasks, ensure_task
from app.config import get_settings
from app.eligibility import evaluate_eligibility
from app.guest_tag import stored_guest_tag
from app.models import (
    Appeal,
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
    ReviewMedia,
    ReviewReceipt,
    ReviewRevision,
    ReviewStatus,
    RevisionStatus,
    User,
)
from app.notify import events
from app.schemas import (
    CategoryAverage,
    GuestReviewCreate,
    MemberReviewCreate,
    OwnerMedia,
    ReviewContent,
    ReviewDetail,
    ReviewEdit,
    ReviewSummary,
    RevisionInfo,
)


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


APPEAL_DAYS = 30


def appeal_deadline(decided_at: datetime) -> datetime:
    """End of the 30th day after the decision, in the policy time zone (Asia/Dhaka)."""
    zone = get_settings().display_tz
    last_day = decided_at.astimezone(zone).date() + timedelta(days=APPEAL_DAYS)
    return datetime.combine(last_day, time(23, 59, 59), tzinfo=zone).astimezone(UTC)


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
    """Public-safe reason and appeal deadline.

    A REJECTED review gives both. A review the moderators sent back (CHANGES_REQUESTED) gives the
    reason only, because there is nothing to appeal. Any other state gives neither.
    """
    if review.status == ReviewStatus.REJECTED:
        decision = ModerationDecision.REJECT
    elif review.status == ReviewStatus.CHANGES_REQUESTED:
        decision = ModerationDecision.REQUEST_CHANGES
    else:
        return RejectionDetails(None, None)
    action = session.scalar(
        select(ModerationActionRecord)
        .where(ModerationActionRecord.review_id == review.id, ModerationActionRecord.decision == decision)
        .order_by(ModerationActionRecord.created_at.desc())
        .limit(1)
    )
    if action is None:
        return RejectionDetails(None, None)
    deadline = appeal_deadline(action.created_at) if decision == ModerationDecision.REJECT else None
    return RejectionDetails(action.reason_code, deadline)


def review_appeal_state(session: Session, review_id: uuid.UUID) -> str | None:
    """State of the newest live appeal against a decision on this review, if any."""
    return session.scalar(
        select(Appeal.state)
        .join(ModerationActionRecord, ModerationActionRecord.id == Appeal.moderation_action_id)
        .where(ModerationActionRecord.review_id == review_id, Appeal.state != "withdrawn")
        .order_by(Appeal.submitted_at.desc())
        .limit(1)
    )


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


def _add_published_rating(
    session: Session,
    review: Review,
    stats: DestinationRatingStats,
) -> None:
    """Count a published review where Review.md 6.1 says it counts, and record why when it does not."""
    eligibility = evaluate_eligibility(session, review)
    review.rating_eligibility = eligibility
    if eligibility == RatingEligibility.INELIGIBLE_GUEST:
        stats.guest_rating_sum += review.overall_rating
        stats.guest_rating_count += 1
    elif eligibility == RatingEligibility.ELIGIBLE:
        stats.community_rating_sum += review.overall_rating
        stats.community_rating_count += 1
    else:
        review.counted_rating = None
        return
    _apply_category_delta(session, review, +1)
    review.counted_rating = review.overall_rating
    stats.version += 1
    stats.updated_at = now_utc()


def recheck_rating(session: Session, review_id: uuid.UUID) -> Review:
    """Re-evaluate one published review and move the aggregates by the difference (Review.md 6.1, 6.3).

    Used when something other than a moderation decision changes whether the review counts: a serious
    report opens or closes, a verification is revoked, a duplicate is cleared. The review row is locked
    first and the aggregate row second, as in every other transition. Nothing changes, and the review
    version stays the same, when the answer is the same as before.
    """
    review = _lock_review(session, review_id)
    if review.status != ReviewStatus.PUBLISHED:
        return review
    now_counted = review.counted_rating is not None
    new_state = evaluate_eligibility(session, review)
    will_count = new_state in (RatingEligibility.ELIGIBLE, RatingEligibility.INELIGIBLE_GUEST)
    if new_state == review.rating_eligibility and will_count == now_counted:
        return review
    stats = _lock_stats(session, review.destination_id)
    _remove_counted_rating(session, review, stats)
    _add_published_rating(session, review, stats)
    review.version += 1
    review.updated_at = now_utc()
    return review


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
    elif decision == ModerationDecision.REQUEST_CHANGES:
        # Sent back to the author, who edits it (PATCH /reviews/{id}/pending) and resubmits.
        # Nothing was counted while it was unpublished, so no aggregate moves.
        if review.status not in {ReviewStatus.PENDING, ReviewStatus.UNDER_REVIEW}:
            raise ReviewConflict("changes can be requested only on a pending review")
        review.status = ReviewStatus.CHANGES_REQUESTED
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
    events.emit(
        session,
        "review.state_changed",
        review.id,
        {
            "review_id": str(review.id),
            "destination_id": str(review.destination_id),
            "status": review.status.value,
            "decision": decision.value,
            "author_id": str(review.author_user_id) if review.author_user_id else None,
            "version": review.version,
        },
        aggregate_type="review",
        aggregate_version=review.version,
        dedupe_key=f"review.state_changed:{review.id}:{review.version}",
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


def withdraw_review(
    session: Session, review_id: uuid.UUID, expected_version: int, *, author_id: uuid.UUID | None = None
) -> Review:
    """Withdraw a review. A Guest route proves ownership with the receipt before calling; a member
    passes ``author_id`` and any other person's review answers as not found."""
    review = _lock_review(session, review_id)
    if author_id is not None and review.author_user_id != author_id:
        raise ReviewNotFound("review not found")
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



# ---- R07: edit an unpublished review, owner reads and history ----

EDITABLE_STATUSES = frozenset({ReviewStatus.PENDING, ReviewStatus.CHANGES_REQUESTED})


@dataclass(frozen=True)
class EditResult:
    review: Review
    revision: int


def edit_pending_review(
    session: Session,
    review_id: uuid.UUID,
    edit: ReviewEdit,
    *,
    author_id: uuid.UUID | None = None,
) -> EditResult:
    """Edit a review that is not yet published (Review.md 5.2, API.md 5.5).

    The edit becomes a new append-only revision and the review goes back to PENDING for moderation.
    Published reviews are never edited in the MVP. A Guest route proves ownership with the receipt
    before calling; a member passes ``author_id`` and any other person's review answers as not found.
    """
    review = _lock_review(session, review_id)
    if author_id is not None and review.author_user_id != author_id:
        raise ReviewNotFound("review not found")
    if review.status not in EDITABLE_STATUSES:
        raise ReviewConflict("only a pending review can be edited")
    if review.version != edit.expected_version:
        raise ReviewConflict("review version changed", "REVIEW_VERSION_CONFLICT")
    current = session.get(ReviewRevision, review.current_revision_id) if review.current_revision_id else None
    if current is None:
        raise ReviewConflict("review has no current revision")

    changes = edit.model_dump(exclude={"expected_version", "receipt_secret"}, exclude_unset=True)
    if "category_ratings" in changes:
        ratings: dict[ReviewCategory, int] = dict(changes["category_ratings"] or {})
    else:
        ratings = dict(revision_category_ratings(session, [current.id])[current.id])

    overall_rating = changes.get("overall_rating", review.overall_rating)
    visit_month: date = changes.get("visit_month", review.visit_month)
    if overall_rating != review.overall_rating or visit_month != review.visit_month:
        review.overall_rating = overall_rating
        review.visit_month = visit_month
        try:
            with session.begin_nested():
                session.flush()  # the member's one-review-per-destination-and-month index is checked here
        except IntegrityError:
            raise ReviewConflict(
                "member already reviewed this destination for that month", "MEMBER_REVIEW_EXISTS"
            ) from None

    sequence = (
        session.scalar(select(func.max(ReviewRevision.sequence)).where(ReviewRevision.review_id == review.id)) or 0
    ) + 1
    current.status = RevisionStatus.SUPERSEDED
    revision = ReviewRevision(
        review_id=review.id,
        sequence=sequence,
        status=RevisionStatus.PENDING,
        language=changes.get("language", current.language),
        traveller_type=changes.get("traveller_type", current.traveller_type),
        comfort_tier=changes.get("comfort_tier", current.comfort_tier),
        title=changes.get("title", current.title),
        body=changes.get("body", current.body),
        overall_rating=overall_rating,
        consent_version=changes.get("consent_version", current.consent_version),
    )
    session.add(revision)
    session.flush()
    for category, rating in ratings.items():
        session.add(ReviewCategoryRating(revision_id=revision.id, category=category, rating=rating))

    review.current_revision_id = revision.id
    review.status = ReviewStatus.PENDING
    review.version += 1
    review.updated_at = now_utc()
    session.add(
        OutboxEvent(
            topic="review.edited",
            aggregate_id=review.id,
            payload={
                "review_id": str(review.id),
                "destination_id": str(review.destination_id),
                "revision": sequence,
                "version": review.version,
            },
        )
    )
    ensure_task(session, "review_moderation", review.id)  # back in the moderators' queue
    return EditResult(review=review, revision=sequence)


def review_detail(session: Session, review: Review, *, staff: bool) -> ReviewDetail:
    """The owner's (or a moderator's) full view. Moderator-only fields are filled only when ``staff``."""
    revision = session.get(ReviewRevision, review.current_revision_id) if review.current_revision_id else None
    if revision is None:
        raise ReviewNotFound("review not found")
    details = rejection_details(session, review)
    revisions = session.scalars(
        select(ReviewRevision).where(ReviewRevision.review_id == review.id).order_by(ReviewRevision.sequence)
    ).all()
    media = session.scalars(
        select(ReviewMedia)
        .where(ReviewMedia.review_id == review.id, ReviewMedia.state != "removed")
        .order_by(ReviewMedia.position, ReviewMedia.id)
    ).all()
    return ReviewDetail(
        id=review.id,
        destination_id=review.destination_id,
        author_type="MEMBER" if review.author_user_id else "GUEST",
        status=review.status,
        version=review.version,
        rating_eligibility=review.rating_eligibility.value,
        language=revision.language,
        traveller_type=revision.traveller_type,
        comfort_tier=revision.comfort_tier,
        visit_month=review.visit_month,
        title=revision.title,
        body=revision.body,
        overall_rating=review.overall_rating,
        category_ratings=revision_category_ratings(session, [revision.id])[revision.id],
        consent_version=revision.consent_version,
        created_at=review.created_at,
        published_at=review.published_at,
        withdrawn_at=review.withdrawn_at,
        decision_reason=details.decision_reason,
        appeal_deadline=details.appeal_deadline,
        appeal_state=review_appeal_state(session, review.id),
        revisions=[
            RevisionInfo(sequence=item.sequence, status=item.status.value, created_at=item.created_at)
            for item in revisions
        ],
        media=[
            OwnerMedia.model_validate(
                {"id": item.id, "kind": item.kind, "state": item.state, "alt_text": item.alt_text, "caption": item.caption}
            )
            for item in media
        ],
        guest_display_name=review.guest_display_name if staff else None,
        author_user_id=review.author_user_id if staff else None,
        conflict_declared=review.conflict_declared if staff else None,
    )


HISTORY_CURSOR_PREFIX = "m1"


def encode_history_cursor(created_at: datetime, review_id: uuid.UUID) -> str:
    """Cursor of the member history. The prefix keeps it from being accepted by another sort (Review.md 9.3)."""
    raw = f"{HISTORY_CURSOR_PREFIX}|{created_at.isoformat()}|{review_id}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_history_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")
        prefix, timestamp, review_id = raw.split("|")
        if prefix != HISTORY_CURSOR_PREFIX:
            raise ValueError("cursor belongs to another listing")
        moment = datetime.fromisoformat(timestamp)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        return moment, uuid.UUID(review_id)
    except (ValueError, UnicodeDecodeError):
        raise ReviewError("page cursor is not valid", "INVALID_CURSOR") from None


def list_member_reviews(
    session: Session,
    author_id: uuid.UUID,
    *,
    status: ReviewStatus | None,
    destination_id: uuid.UUID | None,
    after: str | None,
    limit: int,
) -> tuple[list[ReviewSummary], str | None]:
    """A member's own reviews, newest first, by the stable tuple ``(created_at, id)`` (Review.md 9.3)."""
    statement = (
        select(Review, ReviewRevision)
        .join(ReviewRevision, ReviewRevision.id == Review.current_revision_id)
        .where(Review.author_user_id == author_id)
        .order_by(Review.created_at.desc(), Review.id.desc())
        .limit(limit + 1)
    )
    if status is not None:
        statement = statement.where(Review.status == status)
    if destination_id is not None:
        statement = statement.where(Review.destination_id == destination_id)
    if after:
        created_at, review_id = decode_history_cursor(after)
        statement = statement.where(
            or_(Review.created_at < created_at, and_(Review.created_at == created_at, Review.id < review_id))
        )
    rows = session.execute(statement).all()
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        ReviewSummary(
            id=review.id,
            destination_id=review.destination_id,
            status=review.status,
            version=review.version,
            overall_rating=review.overall_rating,
            title=revision.title,
            visit_month=review.visit_month,
            created_at=review.created_at,
            published_at=review.published_at,
            appeal_deadline=rejection_details(session, review).appeal_deadline,
        )
        for review, revision in rows
    ]
    next_cursor = encode_history_cursor(rows[-1][0].created_at, rows[-1][0].id) if has_more and rows else None
    return items, next_cursor
