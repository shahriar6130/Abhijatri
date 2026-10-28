"""The guest tag (Guest-Identity-and-Visits 3.1, tests "Tag parity" and "Tag from server only")."""

import secrets
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from receipts import new_receipt

from app.db import get_session
from app.guest_tag import DISPLAY_PATTERN, display_guest_tag, guest_tag, stored_guest_tag
from app.main import create_app
from app.models import Destination, DestinationStatus
from app.schemas import GuestReviewCreate
from app.services import submit_guest_review

VECTOR_SECRET = "Zm9vYmFyLXRlc3QtdmVjdG9yLW5vdC1hLXJlYWwtc2VjcmV0LTAwMDAwMDAwMDAw"


def test_test_vector_matches_the_spec() -> None:
    # The same vector is checked in frontend/src/api/guests.test.ts (parity).
    assert guest_tag(VECTOR_SECRET) == "1C669-J0TDY"
    assert stored_guest_tag(VECTOR_SECRET) == "1C669J0TDY"


def test_tags_use_the_crockford_alphabet_and_differ_per_secret() -> None:
    tags = {guest_tag(secrets.token_urlsafe(48)) for _ in range(200)}
    assert len(tags) == 200
    assert all(DISPLAY_PATTERN.fullmatch(tag) for tag in tags)
    assert not any(letter in "".join(tags) for letter in "ILOU")


def test_display_handles_reviews_written_before_the_tag() -> None:
    assert display_guest_tag(None) is None
    assert display_guest_tag("1C669J0TDY") == "1C669-J0TDY"


def test_a_client_cannot_send_its_own_tag() -> None:
    application = create_app()
    application.dependency_overrides[get_session] = lambda: None
    response = TestClient(application).post("/api/v1/reviews/guest", json={"guest_tag": "1C669-J0TDY"})
    assert response.status_code == 422
    assert {"field": "guest_tag", "code": "UNKNOWN_FIELD"} in response.json()["error"]["field_errors"]


@pytest.mark.integration
def test_the_stored_tag_is_derived_from_the_scope_secret(postgres_session) -> None:
    destination = Destination(status=DestinationStatus.PUBLISHED, name_bn="কক্সবাজার", name_en="Cox's Bazar")
    postgres_session.add(destination)
    postgres_session.commit()
    scope = secrets.token_urlsafe(48)
    payload = GuestReviewCreate(
        destination_id=destination.id,
        client_draft_id=uuid.uuid4(),
        guest_scope_secret=scope,
        receipt_secret=new_receipt(),
        guest_display_name="Rahim",
        language="EN",
        traveller_type="SOLO",
        comfort_tier="STANDARD",
        visit_month=date(2026, 9, 1),
        title="Lovely beach",
        body="A long enough review body for the validation rules.",
        overall_rating=5,
        consent_version="v1",
    )
    result = submit_guest_review(postgres_session, payload)
    postgres_session.commit()
    assert result.review.guest_tag == stored_guest_tag(scope)
