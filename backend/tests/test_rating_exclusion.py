"""R08: who counts towards a rating, and the Bayesian score (Review.md 6.1, 6.4; Gantt R08).

Every rule of `app.eligibility.evaluate_eligibility` has a test that publishes a real review through
`moderate_review` and then checks the review's rating state, the destination totals, and what the public
sees. A final property test drives random transitions, including reports, and compares the stored totals
with a full recomputation.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import test_auth as support
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin import actions
from app.auth.sessions import Principal
from app.auth.tokens import Claims
from app.destination_services import get_destination_profile
from app.eligibility import SERIOUS_REPORT_REASONS, evaluate_eligibility
from app.models import (
    ComfortTier,
    Destination,
    DestinationRatingStats,
    DestinationStatus,
    ModerationDecision,
    RatingEligibility,
    Report,
    Review,
    ReviewCategory,
    ReviewCategoryRating,
    ReviewLanguage,
    ReviewRevision,
    ReviewStatus,
    RevisionStatus,
    TravellerType,
    User,
    Verification,
)
from app.rating_integrity import reconcile
from app.review_parameters import (
    COMMUNITY_MIN_REVIEWS,
    COMMUNITY_PRIOR_MEAN,
    COMMUNITY_PRIOR_WEIGHT,
    community_score,
)
from app.services import moderate_review, recheck_rating, withdraw_review

auth_env = support.auth_env
fake = support.fake
redis_fake = support.redis_fake
pytestmark = pytest.mark.integration


# ---- builders ----


def _dhaka_today() -> date:
    return datetime.now(ZoneInfo("Asia/Dhaka")).date()


def _destination(session: Session, name: str = "Sajek") -> Destination:
    destination = Destination(status=DestinationStatus.PUBLISHED, name_bn="সাজেক", name_en=name)
    session.add(destination)
    session.commit()
    return destination


def _user(session: Session, name: str = "Member", *, team: bool = False) -> User:
    user = User(email=f"{uuid.uuid4()}@example.test", display_name=name, is_team_account=team)
    session.add(user)
    session.commit()
    return user


def _verify(session: Session, user: User, **overrides: Any) -> Verification:
    row = Verification(user_id=user.id, verification_type="VERIFIED_MEMBER", status="APPROVED", method="TEST_FIXTURE", **overrides)
    session.add(row)
    session.commit()
    return row


def _verified_member(session: Session) -> User:
    user = _user(session)
    _verify(session, user)
    return user


def _review(
    session: Session,
    destination: Destination,
    author: User | None,
    *,
    rating: int = 5,
    month: date | None = None,
    title: str = "Clean and calm",
    duplicate_override: bool = False,
    categories: dict[ReviewCategory, int] | None = None,
) -> Review:
    review = Review(
        destination_id=destination.id,
        author_user_id=author.id if author else None,
        guest_display_name=None if author else "Rahim",
        guest_scope_hash=None if author else b"\x01" * 32,
        guest_scope_key_id=None if author else "k1",
        client_draft_id=uuid.uuid4(),
        status=ReviewStatus.PENDING,
        rating_eligibility=RatingEligibility.NOT_EVALUATED,
        overall_rating=rating,
        visit_month=month or date(2026, 9, 1),
        duplicate_override=duplicate_override,
    )
    session.add(review)
    session.flush()
    revision = ReviewRevision(
        review_id=review.id, sequence=1, status=RevisionStatus.PENDING, language=ReviewLanguage.EN,
        traveller_type=TravellerType.SOLO, comfort_tier=ComfortTier.STANDARD, title=title,
        body="The place was clean and the directions were clear enough to follow.", overall_rating=rating,
        consent_version="v1",
    )
    session.add(revision)
    session.flush()
    review.current_revision_id = revision.id
    for category, score in (categories or {}).items():
        session.add(ReviewCategoryRating(revision_id=revision.id, category=category, rating=score))
    session.commit()
    return review


def _publish(session: Session, review: Review, moderator: User) -> Review:
    moderate_review(
        session, review_id=review.id, actor_user_id=moderator.id, expected_version=review.version,
        decision=ModerationDecision.PUBLISH, reason_code="APPROVED", note=None,
    )
    session.commit()
    session.refresh(review)
    return review


def _stats(session: Session, destination: Destination) -> tuple[tuple[int, int], tuple[int, int]]:
    session.expire_all()
    row = session.get(DestinationRatingStats, destination.id)
    assert row is not None
    return (row.community_rating_sum, row.community_rating_count), (row.guest_rating_sum, row.guest_rating_count)


def _principal(user: User) -> Principal:
    now = datetime.now(UTC)
    claims = Claims(
        user_id=user.id, email=user.email, session_id=uuid.uuid4(), aal="aal1", amr=("password",),
        expires_at=now + timedelta(hours=1), issued_at=now, auth_time=now, display_name=None,
    )
    return Principal(user=user, claims=claims, role=None)


@pytest.fixture()
def moderator(postgres_session: Session) -> User:
    return _user(postgres_session, "Moderator")


# ---- the formula (Review.md 6.1) ----


def test_score_formula_known_values() -> None:
    assert community_score(25, 5) == pytest.approx((25 + 5 * 3.5) / 10)  # five perfect reviews: 4.25, not 5
    assert community_score(10, 5) == pytest.approx((10 + 17.5) / 10)  # five 2-star reviews: 2.75
    assert community_score(15, 5) == pytest.approx(3.25)
    assert community_score(500, 100) == pytest.approx((500 + 17.5) / 105)
    assert (COMMUNITY_PRIOR_MEAN, COMMUNITY_PRIOR_WEIGHT, COMMUNITY_MIN_REVIEWS) == (3.5, 5, 5)


def test_score_is_hidden_below_five_reviews_and_shown_from_five() -> None:
    assert [community_score(4 * n, n) for n in range(0, 5)] == [None] * 5
    assert community_score(20, 5) is not None


@pytest.mark.parametrize("count", [5, 6, 20, 500])
def test_score_stays_between_one_and_five_and_moves_towards_the_mean(count: int) -> None:
    low, high = community_score(count, count), community_score(5 * count, count)
    assert low is not None and high is not None
    assert 1 <= low < high <= 5
    assert low > 1 and high < 5  # the prior always pulls both ends in


def test_score_is_monotonic_in_the_sum_and_in_the_count_of_good_reviews() -> None:
    scores = [community_score(total, 10) for total in range(10, 51)]
    assert scores == sorted(scores)  # type: ignore[type-var]
    assert community_score(55, 11) > community_score(50, 10)  # one more five-star review raises it  # type: ignore[operator]


# ---- every eligibility rule, through a real publish ----


def test_a_verified_member_review_counts(postgres_session: Session, moderator: User) -> None:
    destination, member = _destination(postgres_session), _verified_member(postgres_session)
    review = _publish(postgres_session, _review(postgres_session, destination, member, rating=4), moderator)
    assert review.rating_eligibility == RatingEligibility.ELIGIBLE and review.counted_rating == 4
    assert _stats(postgres_session, destination) == ((4, 1), (0, 0))


def test_guest_review_feeds_guest_feedback_only(postgres_session: Session, moderator: User) -> None:
    destination = _destination(postgres_session)
    review = _publish(postgres_session, _review(postgres_session, destination, None, rating=3), moderator)
    assert review.rating_eligibility == RatingEligibility.INELIGIBLE_GUEST
    assert _stats(postgres_session, destination) == ((0, 0), (3, 1))


def test_conflict_declared_review_counts_nowhere(postgres_session: Session, moderator: User) -> None:
    destination, member = _destination(postgres_session), _verified_member(postgres_session)
    review = _review(postgres_session, destination, member)
    review.conflict_declared = True
    postgres_session.commit()
    _publish(postgres_session, review, moderator)
    assert review.rating_eligibility == RatingEligibility.INELIGIBLE_CONFLICT and review.counted_rating is None
    assert _stats(postgres_session, destination) == ((0, 0), (0, 0))
    guest = _review(postgres_session, destination, None)
    guest.conflict_declared = True
    postgres_session.commit()
    _publish(postgres_session, guest, moderator)
    assert guest.rating_eligibility == RatingEligibility.INELIGIBLE_CONFLICT
    assert _stats(postgres_session, destination) == ((0, 0), (0, 0))


def test_project_team_account_is_excluded(postgres_session: Session, moderator: User) -> None:
    destination, team = _destination(postgres_session), _user(postgres_session, "Team", team=True)
    _verify(postgres_session, team)
    review = _publish(postgres_session, _review(postgres_session, destination, team), moderator)
    assert review.rating_eligibility == RatingEligibility.INELIGIBLE_UNVERIFIED
    assert _stats(postgres_session, destination) == ((0, 0), (0, 0))


@pytest.mark.parametrize("case", ["no record", "expired", "revoked", "pending status"])
def test_only_an_active_verification_counts(postgres_session: Session, moderator: User, case: str) -> None:
    destination, member = _destination(postgres_session), _user(postgres_session)
    now = datetime.now(UTC)
    if case == "expired":
        _verify(postgres_session, member, expires_at=now - timedelta(days=1))
    elif case == "revoked":
        _verify(postgres_session, member, revoked_at=now - timedelta(days=1))
    elif case == "pending status":
        postgres_session.add(Verification(user_id=member.id, verification_type="VERIFIED_MEMBER", status="PENDING", method="TEST_FIXTURE"))
        postgres_session.commit()
    review = _publish(postgres_session, _review(postgres_session, destination, member), moderator)
    assert review.rating_eligibility == RatingEligibility.INELIGIBLE_UNVERIFIED and review.counted_rating is None
    assert _stats(postgres_session, destination) == ((0, 0), (0, 0))


def test_verification_expiry_after_publication_does_not_uncount(postgres_session: Session, moderator: User) -> None:
    """Review.md 6.3: eligibility is frozen at publication; ordinary expiry never removes a rating."""
    destination, member = _destination(postgres_session), _user(postgres_session)
    verification = _verify(postgres_session, member)
    review = _publish(postgres_session, _review(postgres_session, destination, member), moderator)
    verification.expires_at = datetime.now(UTC) - timedelta(days=1)
    postgres_session.commit()
    assert _stats(postgres_session, destination) == ((5, 1), (0, 0))
    assert review.counted_rating == 5


def test_a_future_visit_month_is_not_counted(postgres_session: Session, moderator: User) -> None:
    destination, member = _destination(postgres_session), _verified_member(postgres_session)
    next_month = (_dhaka_today().replace(day=1) + timedelta(days=32)).replace(day=1)  # the app counts months in Dhaka time
    review = _review(postgres_session, destination, member, month=next_month)
    _publish(postgres_session, review, moderator)
    assert review.rating_eligibility == RatingEligibility.INELIGIBLE_INVALID and review.counted_rating is None
    assert _stats(postgres_session, destination) == ((0, 0), (0, 0))


def test_a_review_without_text_is_not_counted(postgres_session: Session, moderator: User) -> None:
    destination, member = _destination(postgres_session), _verified_member(postgres_session)
    review = _review(postgres_session, destination, member, title="   ")
    _publish(postgres_session, review, moderator)
    assert review.rating_eligibility == RatingEligibility.INELIGIBLE_INVALID
    assert _stats(postgres_session, destination) == ((0, 0), (0, 0))


def test_the_current_month_is_allowed(postgres_session: Session, moderator: User) -> None:
    destination, member = _destination(postgres_session), _verified_member(postgres_session)
    review = _publish(postgres_session, _review(postgres_session, destination, member, month=_dhaka_today().replace(day=1)), moderator)
    assert review.rating_eligibility == RatingEligibility.ELIGIBLE


def test_a_duplicate_counts_once_and_takes_over_when_the_first_leaves(postgres_session: Session, moderator: User) -> None:
    destination, member = _destination(postgres_session), _verified_member(postgres_session)
    first = _publish(postgres_session, _review(postgres_session, destination, member, rating=5), moderator)
    second = _publish(postgres_session, _review(postgres_session, destination, member, rating=1, duplicate_override=True), moderator)
    assert first.rating_eligibility == RatingEligibility.ELIGIBLE
    assert second.rating_eligibility == RatingEligibility.INELIGIBLE_DUPLICATE and second.counted_rating is None
    assert _stats(postgres_session, destination) == ((5, 1), (0, 0))
    withdraw_review(postgres_session, first.id, first.version)
    postgres_session.commit()
    assert _stats(postgres_session, destination) == ((0, 0), (0, 0))
    recheck_rating(postgres_session, second.id)  # the duplicate is no longer a duplicate
    postgres_session.commit()
    assert _stats(postgres_session, destination) == ((1, 1), (0, 0))
    assert reconcile(postgres_session).clean


@pytest.mark.parametrize("reason", sorted(SERIOUS_REPORT_REASONS))
def test_an_open_serious_report_suspends_the_rating_until_it_closes(postgres_session: Session, moderator: User, reason: str) -> None:
    destination, member, reporter = _destination(postgres_session), _verified_member(postgres_session), _user(postgres_session, "Reporter")
    review = _publish(postgres_session, _review(postgres_session, destination, member), moderator)
    report = actions.create_report(postgres_session, _principal(reporter), review_id=review.id, reason_code=reason, details=None)
    postgres_session.commit()
    postgres_session.refresh(review)
    assert review.rating_eligibility == RatingEligibility.INELIGIBLE_REPORTED and review.counted_rating is None
    assert review.status == ReviewStatus.PUBLISHED, "a report alone never removes the review text"
    assert _stats(postgres_session, destination) == ((0, 0), (0, 0))
    report.state = "dismissed"
    postgres_session.commit()
    recheck_rating(postgres_session, review.id)
    postgres_session.commit()
    postgres_session.refresh(review)
    assert review.rating_eligibility == RatingEligibility.ELIGIBLE
    assert _stats(postgres_session, destination) == ((5, 1), (0, 0))


@pytest.mark.parametrize("reason", ["spam", "harassment", "false_information", "impersonation", "copyright", "other"])
def test_a_routine_report_does_not_touch_the_rating(postgres_session: Session, moderator: User, reason: str) -> None:
    destination, member, reporter = _destination(postgres_session), _verified_member(postgres_session), _user(postgres_session, "Reporter")
    review = _publish(postgres_session, _review(postgres_session, destination, member), moderator)
    version = review.version
    actions.create_report(postgres_session, _principal(reporter), review_id=review.id, reason_code=reason, details=None)
    postgres_session.commit()
    postgres_session.refresh(review)
    assert review.rating_eligibility == RatingEligibility.ELIGIBLE and review.version == version
    assert _stats(postgres_session, destination) == ((5, 1), (0, 0))


def test_recheck_changes_nothing_when_the_answer_is_the_same(postgres_session: Session, moderator: User) -> None:
    destination, member = _destination(postgres_session), _verified_member(postgres_session)
    review = _publish(postgres_session, _review(postgres_session, destination, member), moderator)
    version, stats_version = review.version, postgres_session.get(DestinationRatingStats, destination.id).version
    recheck_rating(postgres_session, review.id)
    postgres_session.commit()
    postgres_session.expire_all()
    assert review.version == version
    assert postgres_session.get(DestinationRatingStats, destination.id).version == stats_version


def test_an_unpublished_review_is_never_eligible(postgres_session: Session) -> None:
    destination, member = _destination(postgres_session), _verified_member(postgres_session)
    review = _review(postgres_session, destination, member)
    assert evaluate_eligibility(postgres_session, review) == RatingEligibility.INELIGIBLE_REMOVED
    review.status = ReviewStatus.HIDDEN
    assert evaluate_eligibility(postgres_session, review) == RatingEligibility.INELIGIBLE_REPORTED


# ---- the score the public sees ----


def test_the_score_appears_with_the_fifth_eligible_review(postgres_session: Session, moderator: User) -> None:
    destination = _destination(postgres_session)
    ratings = [5, 4, 4, 3, 5]
    for position, rating in enumerate(ratings, start=1):
        _publish(postgres_session, _review(postgres_session, destination, _verified_member(postgres_session), rating=rating), moderator)
        community = get_destination_profile(postgres_session, destination.id).community_rating
        assert community.count == position
        if position < COMMUNITY_MIN_REVIEWS:
            assert community.score is None and community.seeded_selection is True
    assert community.score == pytest.approx((sum(ratings) + 5 * 3.5) / 10)
    assert community.seeded_selection is False and community.average == pytest.approx(4.2)


def test_guest_and_ineligible_reviews_never_reach_the_score(postgres_session: Session, moderator: User) -> None:
    destination = _destination(postgres_session)
    for _ in range(5):
        _publish(postgres_session, _review(postgres_session, destination, None, rating=5), moderator)  # five guests
        _publish(postgres_session, _review(postgres_session, destination, _user(postgres_session), rating=5), moderator)  # unverified
    profile = get_destination_profile(postgres_session, destination.id)
    assert profile.community_rating.count == 0 and profile.community_rating.score is None
    assert profile.guest_feedback.count == 5 and profile.guest_feedback.average == 5


# ---- what the public feed and totals show ----


@pytest.fixture()
def client(auth_env: None, postgres_session: Session, fake: support.FakeGoTrue, redis_fake: Any) -> TestClient:
    return support.make_client(postgres_session, fake, redis_fake)


def _public(client: TestClient, destination: Destination) -> dict[str, Any]:
    anonymous = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.77"})
    feed = anonymous.get(f"/api/v1/destinations/{destination.id}/reviews?limit=50")
    profile = anonymous.get(f"/api/v1/destinations/{destination.id}")
    assert feed.status_code == 200 and profile.status_code == 200
    return {"ids": {item["id"] for item in feed.json()["items"]}, "community": profile.json()["community_rating"], "guest": profile.json()["guest_feedback"]}


def test_hidden_rejected_withdrawn_and_deleted_reviews_are_excluded_everywhere(client: TestClient, postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    destination = _destination(session)
    kept = _publish(session, _review(session, destination, _verified_member(session), rating=4, categories={ReviewCategory.FOOD: 4}), moderator)
    hidden = _publish(session, _review(session, destination, _verified_member(session), rating=1, categories={ReviewCategory.FOOD: 1}), moderator)
    withdrawn = _publish(session, _review(session, destination, _verified_member(session), rating=2, categories={ReviewCategory.FOOD: 2}), moderator)
    deleted = _publish(session, _review(session, destination, _verified_member(session), rating=3, categories={ReviewCategory.FOOD: 3}), moderator)
    rejected = _review(session, destination, _verified_member(session), rating=1)
    moderate_review(session, review_id=rejected.id, actor_user_id=moderator.id, expected_version=rejected.version, decision=ModerationDecision.REJECT, reason_code="SPAM", note=None)
    moderate_review(session, review_id=hidden.id, actor_user_id=moderator.id, expected_version=hidden.version, decision=ModerationDecision.HIDE, reason_code="PRIVACY", note=None)
    session.commit()
    session.refresh(withdrawn)
    withdraw_review(session, withdrawn.id, withdrawn.version)
    # "Deleted" has no workflow yet; the exclusion rule is the state itself. Uncount, then mark deleted.
    session.refresh(deleted)
    moderate_review(session, review_id=deleted.id, actor_user_id=moderator.id, expected_version=deleted.version, decision=ModerationDecision.HIDE, reason_code="REMOVE", note=None)
    deleted.status = ReviewStatus.DELETED
    session.commit()

    seen = _public(client, destination)
    assert seen["ids"] == {str(kept.id)}
    assert seen["community"]["count"] == 1 and seen["community"]["average"] == 4
    assert [(c["category"], c["average"], c["count"]) for c in seen["community"]["category_averages"]] == [("FOOD", 4, 1)]
    assert reconcile(session).clean


def test_restoring_a_hidden_review_brings_it_back(client: TestClient, postgres_session: Session, moderator: User) -> None:
    session, destination = postgres_session, _destination(postgres_session)
    review = _publish(session, _review(session, destination, _verified_member(session), rating=4), moderator)
    moderate_review(session, review_id=review.id, actor_user_id=moderator.id, expected_version=review.version, decision=ModerationDecision.HIDE, reason_code="X", note=None)
    session.commit()
    assert _public(client, destination)["community"]["count"] == 0
    session.refresh(review)
    moderate_review(session, review_id=review.id, actor_user_id=moderator.id, expected_version=review.version, decision=ModerationDecision.RESTORE, reason_code="X", note=None)
    session.commit()
    assert _public(client, destination)["community"]["count"] == 1 and str(review.id) in _public(client, destination)["ids"]


# ---- random transitions never let the totals drift ----


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(
    steps=st.lists(
        st.tuples(st.integers(0, 2), st.sampled_from(["publish", "hide", "restore", "withdraw", "serious_report", "close_report", "conflict"])),
        min_size=1,
        max_size=25,
    )
)
def test_random_transitions_keep_the_totals_equal_to_a_full_recompute(postgres_session: Session, steps: list[tuple[int, str]]) -> None:
    session = postgres_session
    destination, moderator, reporter = _destination(session), _user(session, "Moderator"), _user(session, "Reporter")
    members = [_verified_member(session) for _ in range(2)]
    reviews = [
        _review(session, destination, members[0], rating=5, month=date(2026, 8, 1), categories={ReviewCategory.FOOD: 5}),
        _review(session, destination, members[1], rating=2, month=date(2026, 8, 1), categories={ReviewCategory.VALUE: 2}),
        _review(session, destination, None, rating=4, categories={ReviewCategory.FOOD: 4}),
    ]
    for index, step in steps:
        review = session.get(Review, reviews[index].id)
        assert review is not None
        session.refresh(review)

        def decide(decision: ModerationDecision, review: Review = review) -> None:
            moderate_review(session, review_id=review.id, actor_user_id=moderator.id, expected_version=review.version, decision=decision, reason_code="PROP", note=None)

        if step == "publish" and review.status == ReviewStatus.PENDING:
            decide(ModerationDecision.PUBLISH)
        elif step == "hide" and review.status == ReviewStatus.PUBLISHED:
            decide(ModerationDecision.HIDE)
        elif step == "restore" and review.status == ReviewStatus.HIDDEN:
            decide(ModerationDecision.RESTORE)
        elif step == "withdraw" and review.status not in {ReviewStatus.WITHDRAWN, ReviewStatus.DELETED}:
            withdraw_review(session, review.id, review.version)
        elif step == "serious_report" and review.status == ReviewStatus.PUBLISHED and review.author_user_id is not None:
            if session.scalar(select(Report.id).where(Report.review_id == review.id, Report.state == "open")) is None:
                actions.create_report(session, _principal(reporter), review_id=review.id, reason_code="privacy", details=None)
        elif step == "close_report":
            for report in session.scalars(select(Report).where(Report.review_id == review.id, Report.state == "open")):
                report.state = "dismissed"
            session.flush()
            recheck_rating(session, review.id)
        elif step == "conflict" and review.status == ReviewStatus.PUBLISHED:
            review.conflict_declared = not review.conflict_declared
            session.flush()
            recheck_rating(session, review.id)
        session.commit()
        result = reconcile(session)
        assert result.clean, [(d.kind, d.key, d.stored, d.expected) for d in result.drifts]
