"""Keeping the stored rating totals true (Review.md 6.3, 6.4).

Three operations live here, all outside the ordinary one-review-at-a-time moderation path:

- ``revoke_verification_for_abuse``: a moderator removes a member's Verified status for abuse and every
  rating that member contributed is taken out of the destination totals. This is the documented exception
  to the "no full scan" rule, and it only touches that one author's counted reviews.
- ``reconcile``: recompute every destination's totals from the published source rows and compare them with
  the stored totals. Detecting never writes. Repair is a separate, explicit, audited choice.
- ``rating_evidence``: the semester evidence figures required by Review.md 6.4.

Lock order is the same as everywhere else: review rows first, then destination aggregate rows in
destination-id order, so two of these operations, or one of them and a moderator's decision, cannot deadlock.
"""

import statistics
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.admin import audit
from app.admin.cases import emit
from app.auth.sessions import Principal
from app.errors import ApiError
from app.models import (
    Destination,
    DestinationCategoryStats,
    DestinationRatingStats,
    DestinationStatus,
    RatingAudience,
    RatingEligibility,
    Review,
    ReviewCategory,
    ReviewCategoryRating,
    ReviewStatus,
    Verification,
    VerificationCase,
)
from app.notify import events
from app.review_parameters import COMMUNITY_MIN_REVIEWS
from app.services import _lock_stats, recheck_rating

Pair = tuple[int, int]  # (sum, count)
COUNTED_STATES = (RatingEligibility.ELIGIBLE, RatingEligibility.INELIGIBLE_GUEST)
# A review counts while it is public, or while it is hidden by a takedown that keeps its rating (Moderation spec P-00).
COUNTING_STATUSES = (ReviewStatus.PUBLISHED, ReviewStatus.HIDDEN)


# ---- verification revoked for abuse (Review.md 6.3) ----


def revoke_verification_for_abuse(
    session: Session, actor: Principal, *, user_id: uuid.UUID, reason_code: str, request_id: str | None
) -> dict[str, Any]:
    """End a member's Verified status and uncount their ratings, in one transaction.

    Ordinary expiry never does this (Review.md 6.3: eligibility is frozen at publication); only an
    explicit abuse decision does. The reviews stay published, they just stop feeding the Community Rating.
    """
    if user_id == actor.user.id:
        raise ApiError("FORBIDDEN")
    verification = session.scalar(
        select(Verification)
        .where(
            Verification.user_id == user_id,
            Verification.verification_type == "VERIFIED_MEMBER",
            Verification.status == "APPROVED",
            Verification.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if verification is None:
        raise ApiError("NOT_FOUND")  # nothing active to revoke
    verification.revoked_at = datetime.now(UTC)
    verification.revocation_reason = reason_code[:240]
    session.flush()

    # Every review row first, in id order; the aggregate rows are then locked destination by destination.
    reviews = session.scalars(
        select(Review)
        .where(Review.author_user_id == user_id, Review.status == ReviewStatus.PUBLISHED, Review.counted_rating.is_not(None))
        .order_by(Review.id)
        .with_for_update()
    ).all()
    recounted = 0
    for review in sorted(reviews, key=lambda row: (row.destination_id, row.id)):
        recheck_rating(session, review.id)
        recounted += 1
    audit.record(
        session, actor=actor, action="verification.revoke_for_abuse", target_type="user", target_id=user_id,
        reason=reason_code, metadata={"verification_id": str(verification.id), "reviews_uncounted": recounted},
        request_id=request_id,
    )
    emit(session, "verification.state_changed", verification.id, {"state": "revoked", "applicant_id": str(user_id)})
    return {"user_id": str(user_id), "verification_id": str(verification.id), "reviews_uncounted": recounted}


# ---- reconciliation (Review.md 6.3) ----


@dataclass(frozen=True)
class Drift:
    destination_id: uuid.UUID
    kind: str  # community | guest | category | review
    key: str
    stored: Pair | None
    expected: Pair | None
    repairable: bool = True


@dataclass
class ReconcileResult:
    destinations_checked: int = 0
    drifts: list[Drift] = field(default_factory=list)
    repaired: int = 0

    @property
    def clean(self) -> bool:
        return not self.drifts


@dataclass
class _Expected:
    community: Pair = (0, 0)
    guest: Pair = (0, 0)
    categories: dict[tuple[RatingAudience, ReviewCategory], Pair] = field(default_factory=dict)


def _expected_totals(session: Session, destination_id: uuid.UUID | None) -> dict[uuid.UUID, _Expected]:
    """What the totals must be, summed from the review rows that currently count."""
    counted: list[ColumnElement[bool]] = [Review.status.in_(COUNTING_STATUSES), Review.counted_rating.is_not(None)]
    if destination_id is not None:
        counted.append(Review.destination_id == destination_id)
    expected: dict[uuid.UUID, _Expected] = defaultdict(_Expected)
    for dest, is_guest, total, count in session.execute(
        select(Review.destination_id, Review.author_user_id.is_(None), func.sum(Review.counted_rating), func.count(Review.id))
        .where(*counted)
        .group_by(Review.destination_id, Review.author_user_id.is_(None))
    ):
        pair = (int(total or 0), int(count))
        if is_guest:
            expected[dest].guest = pair
        else:
            expected[dest].community = pair
    for dest, is_guest, category, total, count in session.execute(
        select(
            Review.destination_id,
            Review.author_user_id.is_(None),
            ReviewCategoryRating.category,
            func.sum(ReviewCategoryRating.rating),
            func.count(ReviewCategoryRating.rating),
        )
        .join(ReviewCategoryRating, ReviewCategoryRating.revision_id == Review.current_revision_id)
        .where(*counted)
        .group_by(Review.destination_id, Review.author_user_id.is_(None), ReviewCategoryRating.category)
    ):
        audience = RatingAudience.GUEST if is_guest else RatingAudience.COMMUNITY
        expected[dest].categories[(audience, category)] = (int(total or 0), int(count))
    return expected


def _review_row_drifts(session: Session, destination_id: uuid.UUID | None) -> list[Drift]:
    """Review rows whose own counted state disagrees with their status or eligibility (reported, not repaired)."""
    scope = [Review.destination_id == destination_id] if destination_id is not None else []
    counts_wrongly = select(Review.id, Review.destination_id).where(
        *scope,
        Review.counted_rating.is_not(None),
        Review.status.not_in(COUNTING_STATUSES) | Review.rating_eligibility.not_in(COUNTED_STATES),
    )
    missing_count = select(Review.id, Review.destination_id).where(
        *scope,
        Review.status == ReviewStatus.PUBLISHED,
        Review.rating_eligibility.in_(COUNTED_STATES),
        Review.counted_rating.is_(None),
    )
    drifts = [Drift(dest, "review", f"{review_id} is counted but should not be", None, None, False) for review_id, dest in session.execute(counts_wrongly)]
    drifts += [Drift(dest, "review", f"{review_id} should be counted but is not", None, None, False) for review_id, dest in session.execute(missing_count)]
    return drifts


def reconcile(
    session: Session, *, destination_id: uuid.UUID | None = None, repair: bool = False,
    actor: Principal | None = None, request_id: str | None = None,
) -> ReconcileResult:
    """Compare stored totals with a full recomputation. Writes nothing unless ``repair`` is true."""
    expected = _expected_totals(session, destination_id)
    stat_scope = [DestinationRatingStats.destination_id == destination_id] if destination_id is not None else []
    stored = {row.destination_id: row for row in session.scalars(select(DestinationRatingStats).where(*stat_scope))}
    cat_scope = [DestinationCategoryStats.destination_id == destination_id] if destination_id is not None else []
    stored_cats: dict[uuid.UUID, dict[tuple[RatingAudience, ReviewCategory], Pair]] = defaultdict(dict)
    for row in session.scalars(select(DestinationCategoryStats).where(*cat_scope)):
        stored_cats[row.destination_id][(row.audience, row.category)] = (row.rating_sum, row.rating_count)

    result = ReconcileResult()
    drifting: list[uuid.UUID] = []
    for dest in sorted(set(stored) | set(expected) | set(stored_cats)):
        result.destinations_checked += 1
        want, have = expected.get(dest, _Expected()), stored.get(dest)
        found: list[Drift] = []
        for kind, want_pair, have_pair in (
            ("community", want.community, (have.community_rating_sum, have.community_rating_count) if have else (0, 0)),
            ("guest", want.guest, (have.guest_rating_sum, have.guest_rating_count) if have else (0, 0)),
        ):
            if want_pair != have_pair:
                found.append(Drift(dest, kind, kind, have_pair, want_pair))
        have_cats = stored_cats.get(dest, {})
        for key in sorted(set(want.categories) | set(have_cats), key=lambda k: (k[0].value, k[1].value)):
            want_pair, have_pair = want.categories.get(key, (0, 0)), have_cats.get(key, (0, 0))
            if want_pair != have_pair:
                found.append(Drift(dest, "category", f"{key[0].value}:{key[1].value}", have_pair, want_pair))
        if found:
            drifting.append(dest)
            result.drifts.extend(found)
    result.drifts.extend(_review_row_drifts(session, destination_id))

    if repair:
        for dest in drifting:  # destination-id order, like every other multi-aggregate lock
            _repair_destination(session, dest, actor, request_id)
            result.repaired += 1
    return result


def _repair_destination(session: Session, destination_id: uuid.UUID, actor: Principal | None, request_id: str | None) -> None:
    """Overwrite one destination's totals with the recomputed values, under the usual locks, and audit it."""
    stats = _lock_stats(session, destination_id)
    want = _expected_totals(session, destination_id).get(destination_id, _Expected())  # re-read under the lock
    before: dict[str, Any] = {
        "community": [stats.community_rating_sum, stats.community_rating_count],
        "guest": [stats.guest_rating_sum, stats.guest_rating_count],
    }
    stats.community_rating_sum, stats.community_rating_count = want.community
    stats.guest_rating_sum, stats.guest_rating_count = want.guest
    stats.version += 1
    stats.updated_at = datetime.now(UTC)
    rows = session.scalars(
        select(DestinationCategoryStats)
        .where(DestinationCategoryStats.destination_id == destination_id)
        .order_by(DestinationCategoryStats.audience, DestinationCategoryStats.category)
        .with_for_update()
    ).all()
    seen: set[tuple[RatingAudience, ReviewCategory]] = set()
    for row in rows:
        seen.add((row.audience, row.category))
        row.rating_sum, row.rating_count = want.categories.get((row.audience, row.category), (0, 0))
        row.updated_at = datetime.now(UTC)
    for (audience, category), (total, count) in want.categories.items():
        if (audience, category) not in seen:
            session.add(
                DestinationCategoryStats(
                    destination_id=destination_id, audience=audience, category=category,
                    rating_sum=total, rating_count=count, updated_at=datetime.now(UTC),
                )
            )
    audit.record(
        session, actor=actor, action="ratings.reconcile_repair", target_type="destination", target_id=destination_id,
        reason="reconciliation", metadata={"before": before, "after": {"community": list(want.community), "guest": list(want.guest)}},
        request_id=request_id,
    )


def run_reconciliation(
    session: Session, *, repair: bool, actor: Principal | None, request_id: str | None = None
) -> ReconcileResult:
    """One nightly or on-demand run: reconcile, write the result to the audit log, alert on drift."""
    result = reconcile(session, repair=repair, actor=actor, request_id=request_id)
    audit.record(
        session, actor=actor, action="ratings.reconcile_run", target_type="system", target_id="ratings",
        reason="repair" if repair else "detect",
        metadata={"destinations_checked": result.destinations_checked, "drifts": len(result.drifts), "repaired": result.repaired},
        request_id=request_id,
    )
    if result.drifts and not repair:
        day = datetime.now(UTC).date().isoformat()
        events.emit(
            session, "ratings.drift_detected", uuid.uuid5(uuid.NAMESPACE_URL, f"ratings.drift:{day}"),
            {"count": len({drift.destination_id for drift in result.drifts})}, staff_roles=("superadmin",),
            dedupe_key=f"ratings.drift:{day}",
        )
    return result


# ---- semester evidence (Review.md 6.4) ----


def rating_evidence(session: Session) -> dict[str, Any]:
    """Figures the semester evidence must include: Verified Members, turnaround, per-destination counts and mode."""
    active = session.scalar(
        select(func.count(func.distinct(Verification.user_id))).where(
            Verification.verification_type == "VERIFIED_MEMBER", Verification.status == "APPROVED", Verification.revoked_at.is_(None)
        )
    ) or 0
    ever = session.scalar(
        select(func.count(func.distinct(Verification.user_id))).where(
            Verification.verification_type == "VERIFIED_MEMBER", Verification.status == "APPROVED"
        )
    ) or 0
    hours = [
        (decided - created).total_seconds() / 3600
        for created, decided in session.execute(
            select(VerificationCase.created_at, VerificationCase.decided_at).where(
                VerificationCase.state == "approved", VerificationCase.decided_at.is_not(None)
            )
        )
        if decided is not None
    ]
    destinations = []
    for destination, stats in session.execute(
        select(Destination, DestinationRatingStats)
        .outerjoin(DestinationRatingStats, DestinationRatingStats.destination_id == Destination.id)
        .where(Destination.status == DestinationStatus.PUBLISHED)
        .order_by(Destination.name_en, Destination.id)
    ):
        count = stats.community_rating_count if stats else 0
        destinations.append(
            {
                "destination_id": str(destination.id),
                "name_en": destination.name_en,
                "eligible_reviews": count,
                "mode": "top_rated" if count >= COMMUNITY_MIN_REVIEWS else "seeded",
            }
        )
    return {
        "threshold": COMMUNITY_MIN_REVIEWS,
        "verified_members": {"active": active, "ever_approved": ever},
        "verification_turnaround_hours": {
            "decisions": len(hours),
            "median": round(statistics.median(hours), 2) if hours else None,
            "maximum": round(max(hours), 2) if hours else None,
        },
        "destinations": destinations,
    }
