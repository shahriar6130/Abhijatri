"""Seven category ratings (Review.md 3.1, amendment A2): validation, storage and aggregates."""

import secrets
import uuid
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from receipts import new_receipt
from sqlalchemy import select

from app.api import require_staff
from app.db import get_session
from app.main import create_app
from app.models import (
    Destination,
    DestinationCategoryStats,
    DestinationStatus,
    ModerationDecision,
    RatingAudience,
    Review,
    ReviewCategory,
    ReviewCategoryRating,
    ReviewStatus,
    User,
)
from app.schemas import GuestReviewCreate
from app.services import (
    full_guest_category_recompute,
    moderate_review,
    submit_guest_review,
    withdraw_review,
)

CATEGORIES = {"CLEANLINESS": 3, "FOOD": 4, "SAFETY_PERCEPTION": 5}


def _fields(**overrides: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "destination_id": uuid.uuid4(),
        "client_draft_id": uuid.uuid4(),
        "guest_scope_secret": secrets.token_urlsafe(32),
        "receipt_secret": new_receipt(),
        "guest_display_name": "সাদিয়া রহমান",
        "language": "BN",
        "traveller_type": "FAMILY",
        "comfort_tier": "STANDARD",
        "visit_month": date(2026, 9, 1),
        "title": "পরিবার নিয়ে ভালো অভিজ্ঞতা",
        "body": "যাতায়াত সহজ ছিল এবং স্থানীয় মানুষের সহযোগিতা খুব ভালো পেয়েছি।",
        "overall_rating": 4,
        "consent_version": "2026-10-01",
    }
    fields.update(overrides)
    return fields


# ---- schema (no database) ----


def test_category_ratings_are_optional() -> None:
    assert GuestReviewCreate(**_fields()).category_ratings is None


def test_valid_category_ratings_are_kept_as_enum_keys() -> None:
    payload = GuestReviewCreate(**_fields(category_ratings=CATEGORIES))
    assert payload.category_ratings == {
        ReviewCategory.CLEANLINESS: 3,
        ReviewCategory.FOOD: 4,
        ReviewCategory.SAFETY_PERCEPTION: 5,
    }


def test_all_seven_categories_are_accepted() -> None:
    every = {category.value: 5 for category in ReviewCategory}
    assert len(GuestReviewCreate(**_fields(category_ratings=every)).category_ratings or {}) == 7


def test_empty_category_ratings_mean_none() -> None:
    assert GuestReviewCreate(**_fields(category_ratings={})).category_ratings is None


@pytest.mark.parametrize(
    "ratings",
    [{"FOOD": 0}, {"FOOD": 6}, {"FOOD": 2.5}, {"WIFI": 4}, {"food": 4}],
)
def test_invalid_category_ratings_are_rejected(ratings: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        GuestReviewCreate(**_fields(category_ratings=ratings))


def test_unknown_category_is_a_field_error_over_http() -> None:
    application = create_app()
    application.dependency_overrides[get_session] = lambda: None
    body = _fields(category_ratings={"WIFI": 4})
    body = {key: str(value) if isinstance(value, uuid.UUID | date) else value for key, value in body.items()}
    response = TestClient(application).post("/api/v1/reviews/guest", json=body)
    assert response.status_code == 422
    fields = {error["field"] for error in response.json()["error"]["field_errors"]}
    assert any(field.startswith("category_ratings") for field in fields)


# ---- PostgreSQL ----


def _seed(session) -> tuple[Destination, User]:
    destination = Destination(status=DestinationStatus.PUBLISHED, name_bn="সাজেক", name_en="Sajek")
    moderator = User(email=f"moderator-{uuid.uuid4()}@example.test", display_name="Moderator")
    session.add_all([destination, moderator])
    session.commit()
    return destination, moderator


def _decide(session, review: Review, moderator: User, decision: ModerationDecision) -> None:
    moderate_review(
        session,
        review_id=review.id,
        actor_user_id=moderator.id,
        expected_version=review.version,
        decision=decision,
        reason_code="TEST",
        note=None,
    )
    session.commit()


def _guest_stats(session, destination_id: uuid.UUID) -> dict[ReviewCategory, tuple[int, int]]:
    session.expire_all()
    rows = session.scalars(
        select(DestinationCategoryStats).where(
            DestinationCategoryStats.destination_id == destination_id,
            DestinationCategoryStats.audience == RatingAudience.GUEST,
            DestinationCategoryStats.rating_count > 0,
        )
    )
    return {row.category: (row.rating_sum, row.rating_count) for row in rows}


@pytest.mark.integration
def test_category_rows_follow_every_rating_transition(postgres_session) -> None:
    destination, moderator = _seed(postgres_session)
    created = submit_guest_review(
        postgres_session,
        GuestReviewCreate(**_fields(destination_id=destination.id, category_ratings=CATEGORIES)),
    )
    postgres_session.commit()
    review = created.review

    rows = postgres_session.scalars(
        select(ReviewCategoryRating).where(ReviewCategoryRating.revision_id == review.current_revision_id)
    ).all()
    assert {row.category.value: row.rating for row in rows} == CATEGORIES
    # Pending: stored, but counted nowhere (Review.md 12.2).
    assert _guest_stats(postgres_session, destination.id) == {}

    _decide(postgres_session, review, moderator, ModerationDecision.PUBLISH)
    expected = {ReviewCategory(name): (score, 1) for name, score in CATEGORIES.items()}
    assert _guest_stats(postgres_session, destination.id) == expected
    assert full_guest_category_recompute(postgres_session, destination.id) == expected

    _decide(postgres_session, review, moderator, ModerationDecision.HIDE)
    assert _guest_stats(postgres_session, destination.id) == {}

    _decide(postgres_session, review, moderator, ModerationDecision.RESTORE)
    assert _guest_stats(postgres_session, destination.id) == expected

    withdraw_review(postgres_session, review.id, review.version)
    postgres_session.commit()
    assert review.status == ReviewStatus.WITHDRAWN
    assert _guest_stats(postgres_session, destination.id) == {}
    assert full_guest_category_recompute(postgres_session, destination.id) == {}


@pytest.mark.integration
def test_rejected_review_never_counts_categories(postgres_session) -> None:
    destination, moderator = _seed(postgres_session)
    created = submit_guest_review(
        postgres_session,
        GuestReviewCreate(**_fields(destination_id=destination.id, category_ratings=CATEGORIES)),
    )
    postgres_session.commit()
    _decide(postgres_session, created.review, moderator, ModerationDecision.REJECT)
    assert _guest_stats(postgres_session, destination.id) == {}


@pytest.mark.integration
def test_api_returns_category_ratings_and_averages(postgres_session) -> None:
    destination, moderator = _seed(postgres_session)
    for ratings in (CATEGORIES, {"FOOD": 2}, None):
        created = submit_guest_review(
            postgres_session,
            GuestReviewCreate(**_fields(destination_id=destination.id, category_ratings=ratings)),
        )
        postgres_session.commit()
        _decide(postgres_session, created.review, moderator, ModerationDecision.PUBLISH)

    application = create_app()
    application.dependency_overrides[get_session] = lambda: postgres_session
    client = TestClient(application)

    response = client.get(f"/api/v1/destinations/{destination.id}/reviews")
    feed = response.json()
    assert sorted(len(item["category_ratings"]) for item in feed["items"]) == [0, 1, 3]
    # A guest's typed name is never public: only "Anonymous guest · tag" (owner, 22 Oct 2026).
    assert all(item["author_type"] == "GUEST" and "guest_display_name" not in item for item in feed["items"])
    assert "সাদিয়া রহমান" not in response.text
    averages = {row["category"]: row for row in feed["guest_category_averages"]}
    assert averages["FOOD"] == {"category": "FOOD", "average": 3.0, "count": 2}
    assert averages["CLEANLINESS"]["count"] == 1
    # Display order is the Review.md 3.1 order.
    assert [row["category"] for row in feed["guest_category_averages"]] == [
        "CLEANLINESS",
        "FOOD",
        "SAFETY_PERCEPTION",
    ]

    profile = client.get(f"/api/v1/destinations/{destination.id}").json()
    assert profile["guest_feedback"]["category_averages"] == feed["guest_category_averages"]
    assert profile["community_rating"]["category_averages"] == []
    (item,) = client.get("/api/v1/destinations").json()["items"]
    assert item["guest_feedback"]["category_averages"] == feed["guest_category_averages"]


@pytest.mark.integration
def test_moderation_queue_shows_the_full_review(postgres_session) -> None:
    destination, moderator = _seed(postgres_session)
    created = submit_guest_review(
        postgres_session,
        GuestReviewCreate(**_fields(destination_id=destination.id, category_ratings=CATEGORIES)),
    )
    postgres_session.commit()

    application = create_app()
    application.dependency_overrides[get_session] = lambda: postgres_session
    application.dependency_overrides[require_staff] = lambda: moderator
    (item,) = TestClient(application).get("/api/v1/staff/moderation/reviews").json()
    assert item["review_id"] == str(created.review.id)
    assert item["title"] == "পরিবার নিয়ে ভালো অভিজ্ঞতা"
    assert item["guest_display_name"] == "সাদিয়া রহমান"
    assert item["category_ratings"] == CATEGORIES
