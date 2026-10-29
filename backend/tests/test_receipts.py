"""Client-generated receipts, the keyring, and the receipt endpoints (API.md 5.1 to 5.4)."""

import base64
import json
import uuid
from collections.abc import Generator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient
from receipts import new_receipt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import crypto
from app.config import get_settings
from app.db import get_session
from app.limits import limiter
from app.main import create_app
from app.models import (
    Destination,
    DestinationStatus,
    Review,
    ReviewReceipt,
    User,
)
from app.ops import events

KEY_V1 = "k1-" + "a" * 40
KEY_V2 = "k2-" + "b" * 40


@pytest.fixture(autouse=True)
def _reset_limiter() -> None:
    limiter.reset()


def _b64(raw: bytes) -> str:
    return "abr1_" + base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


@pytest.fixture()
def keyring(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("RECEIPT_KEYS", json.dumps({"v1": KEY_V1, "v2": KEY_V2}))
    monkeypatch.setenv("RECEIPT_KEY_CURRENT", "v1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _rotate_to(monkeypatch: pytest.MonkeyPatch, key_id: str) -> None:
    monkeypatch.setenv("RECEIPT_KEY_CURRENT", key_id)
    get_settings.cache_clear()


# ---------- format ----------


def test_generated_receipt_is_accepted() -> None:
    receipt = new_receipt()
    assert len(receipt) == 48
    assert crypto.receipt_format_problem(receipt) is None


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("", "prefix"),
        ("abr2_" + "A" * 43, "prefix"),
        (new_receipt()[:-1], "length_or_alphabet"),
        (new_receipt() + "A", "length_or_alphabet"),
        ("abr1_" + "!" * 43, "length_or_alphabet"),
        (_b64(b"\x00" * 32), "weak"),
        (_b64(b"\xff" * 32), "weak"),
        (_b64(b"ab" * 16), "weak"),
        (_b64(bytes(range(8)) * 4), "weak"),
        ("abr1_" + "A" * 42 + "B", "encoding"),  # last symbol carries non-zero padding bits
    ],
)
def test_bad_receipts_are_rejected(value: str, problem: str) -> None:
    assert crypto.receipt_format_problem(value) == problem


def test_documentation_placeholder_is_not_a_receipt() -> None:
    assert crypto.receipt_format_problem("abr1_<43 base64url characters>") is not None


# ---------- digests and keyring ----------


def test_labels_separate_receipt_scope_and_network_digests() -> None:
    value = new_receipt()
    digests = {
        crypto.digest(label, "v1", value)
        for label in (crypto.RECEIPT_LABEL, crypto.GUEST_SCOPE_LABEL, crypto.NETWORK_LABEL)
    }
    assert len(digests) == 3
    assert all(len(d) == 32 for d in digests)


def test_digest_is_deterministic_and_value_dependent() -> None:
    a, b = new_receipt(), new_receipt()
    assert crypto.digest(crypto.RECEIPT_LABEL, "v1", a) == crypto.digest(crypto.RECEIPT_LABEL, "v1", a)
    assert crypto.digest(crypto.RECEIPT_LABEL, "v1", a) != crypto.digest(crypto.RECEIPT_LABEL, "v1", b)


@pytest.mark.usefixtures("keyring")
def test_candidates_cover_every_retained_key_current_first(monkeypatch: pytest.MonkeyPatch) -> None:
    value = new_receipt()
    assert [key for key, _ in crypto.candidate_digests(crypto.RECEIPT_LABEL, value)] == ["v1", "v2"]
    _rotate_to(monkeypatch, "v2")
    assert [key for key, _ in crypto.candidate_digests(crypto.RECEIPT_LABEL, value)] == ["v2", "v1"]
    first, second = (d for _, d in crypto.candidate_digests(crypto.RECEIPT_LABEL, value))
    assert first != second


def test_default_keyring_is_the_pepper() -> None:
    settings = get_settings()
    assert settings.hmac_keyring == {"v1": settings.receipt_pepper}


@pytest.mark.parametrize(
    "value",
    ["not json", "[]", "{}", json.dumps({"v1": "short"}), json.dumps({"bad id!": "k" * 40})],
)
def test_invalid_keyring_is_rejected(value: str) -> None:
    from app.config import Settings

    with pytest.raises(ValueError):
        Settings(_env_file=None, receipt_keys=value)


def test_current_key_must_exist() -> None:
    from app.config import Settings

    with pytest.raises(ValueError, match="RECEIPT_KEY_CURRENT"):
        Settings(_env_file=None, receipt_keys=json.dumps({"v1": KEY_V1}), receipt_key_current="v9")


# ---------- endpoints (real PostgreSQL) ----------

integration = pytest.mark.integration


def _payload(destination_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "destination_id": str(destination_id),
        "client_draft_id": str(uuid.uuid4()),
        "guest_scope_secret": "s" * 43,
        "receipt_secret": new_receipt(),
        "guest_display_name": "Rahim",
        "language": "EN",
        "traveller_type": "SOLO",
        "comfort_tier": "STANDARD",
        "visit_month": date.today().replace(day=1).isoformat(),
        "title": "Lovely beach",
        "body": "A long enough review body for the validation rules.",
        "overall_rating": 5,
        "consent_version": "v1",
    }
    body.update(overrides)
    return body


@pytest.fixture()
def api(postgres_session: Session) -> Generator[tuple[TestClient, Session, Destination], None, None]:
    destination = Destination(status=DestinationStatus.PUBLISHED, name_bn="কক্সবাজার", name_en="Cox")
    postgres_session.add(destination)
    postgres_session.commit()
    application = create_app()

    def override() -> Generator[Session, None, None]:
        yield postgres_session

    application.dependency_overrides[get_session] = override
    yield TestClient(application), postgres_session, destination


@integration
def test_submit_returns_201_without_any_receipt(api: Any) -> None:
    client, session, destination = api
    body = _payload(destination.id)
    before = events.pending().get("reviews.submitted", 0)
    response = client.post("/api/v1/reviews/guest", json=body)
    assert response.status_code == 201, response.text
    assert events.pending().get("reviews.submitted", 0) == before + 1
    data = response.json()
    assert set(data) == {"review_id", "status", "version", "duplicate_recovered"}
    assert data["duplicate_recovered"] is False
    assert body["receipt_secret"] not in response.text
    stored = session.scalars(select(ReviewReceipt)).all()
    assert len(stored) == 1 and stored[0].key_id == "v1"
    assert body["receipt_secret"].encode() not in stored[0].digest


@integration
def test_retry_with_the_same_receipt_is_200_and_creates_nothing_new(api: Any) -> None:
    client, session, destination = api
    body = _payload(destination.id)
    first = client.post("/api/v1/reviews/guest", json=body)
    retry = client.post("/api/v1/reviews/guest", json=body)
    assert (first.status_code, retry.status_code) == (201, 200)
    assert retry.json()["review_id"] == first.json()["review_id"]
    assert retry.json()["duplicate_recovered"] is True
    assert len(session.scalars(select(Review)).all()) == 1
    assert len(session.scalars(select(ReviewReceipt)).all()) == 1  # never reissued


@integration
def test_retry_with_a_different_receipt_is_409_and_hides_the_review(api: Any) -> None:
    client, _, destination = api
    body = _payload(destination.id)
    first = client.post("/api/v1/reviews/guest", json=body)
    other = {**body, "receipt_secret": new_receipt()}
    response = client.post("/api/v1/reviews/guest", json=other)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DRAFT_ALREADY_SUBMITTED"
    assert first.json()["review_id"] not in response.text


@integration
def test_a_receipt_cannot_be_bound_to_two_reviews(api: Any) -> None:
    client, session, destination = api
    body = _payload(destination.id)
    assert client.post("/api/v1/reviews/guest", json=body).status_code == 201
    second = _payload(destination.id, receipt_secret=body["receipt_secret"], guest_scope_secret="t" * 43)
    response = client.post("/api/v1/reviews/guest", json=second)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "DRAFT_ALREADY_SUBMITTED"
    assert len(session.scalars(select(Review)).all()) == 1


@integration
@pytest.mark.parametrize("bad", ["abr1_short", "x" * 48, _b64(b"\x00" * 32)])
def test_malformed_or_weak_receipt_is_422_invalid_receipt_format(api: Any, bad: str) -> None:
    client, session, destination = api
    response = client.post("/api/v1/reviews/guest", json=_payload(destination.id, receipt_secret=bad))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_RECEIPT_FORMAT"
    assert session.scalars(select(Review)).all() == []


@integration
def test_unknown_request_fields_are_422(api: Any) -> None:
    client, _, destination = api
    response = client.post("/api/v1/reviews/guest", json=_payload(destination.id, receipt_token="x"))
    assert response.status_code == 422
    error = response.json()["error"]
    assert {"field": "receipt_token", "code": "UNKNOWN_FIELD"} in error["field_errors"]


@integration
def test_status_requires_the_right_receipt(api: Any) -> None:
    client, _, destination = api
    body = _payload(destination.id)
    review_id = client.post("/api/v1/reviews/guest", json=body).json()["review_id"]

    ok = client.post(
        "/api/v1/review-receipts/status",
        json={"review_id": review_id, "receipt_secret": body["receipt_secret"]},
    )
    assert ok.status_code == 200
    assert ok.json() == {
        "review_id": review_id,
        "status": "PENDING",
        "version": 1,
        "published_at": None,
        "decision_reason": None,
        "appeal_deadline": None,
        "appeal_state": None,
    }

    wrong = client.post(
        "/api/v1/review-receipts/status", json={"review_id": review_id, "receipt_secret": new_receipt()}
    )
    missing = client.post(
        "/api/v1/review-receipts/status",
        json={"review_id": str(uuid.uuid4()), "receipt_secret": body["receipt_secret"]},
    )
    assert wrong.status_code == missing.status_code == 404
    assert wrong.json()["error"]["code"] == missing.json()["error"]["code"] == "RECEIPT_NOT_FOUND"
    assert wrong.json()["error"]["message"] == missing.json()["error"]["message"]


@integration
def test_legacy_exchange_route_is_gone(api: Any) -> None:
    client, _, _ = api
    response = client.post(
        "/api/v1/review-receipts/exchange",
        json={"review_id": str(uuid.uuid4()), "receipt_secret": new_receipt()},
    )
    assert response.status_code in {404, 405}


@integration
def test_rejected_review_reports_reason_and_appeal_deadline(api: Any) -> None:
    from datetime import timedelta

    from app.models import ModerationDecision, PlatformRole, UserPlatformRole
    from app.services import moderate_review

    client, session, destination = api
    body = _payload(destination.id)
    review_id = client.post("/api/v1/reviews/guest", json=body).json()["review_id"]
    moderator = User(email=f"m-{uuid.uuid4()}@example.test", display_name="Mod")
    role = PlatformRole(code="MODERATOR")
    session.add_all([moderator, role])
    session.flush()
    session.add(UserPlatformRole(user_id=moderator.id, role_id=role.id))
    session.commit()
    moderate_review(
        session,
        review_id=uuid.UUID(review_id),
        actor_user_id=moderator.id,
        expected_version=1,
        decision=ModerationDecision.REJECT,
        reason_code="PERSONAL_INFORMATION",
        note="internal note never shown",
    )
    session.commit()

    response = client.post(
        "/api/v1/review-receipts/status",
        json={"review_id": review_id, "receipt_secret": body["receipt_secret"]},
    )
    data = response.json()
    assert data["status"] == "REJECTED"
    assert data["decision_reason"] == "PERSONAL_INFORMATION"
    assert "internal note" not in response.text
    from datetime import datetime

    deadline = datetime.fromisoformat(data["appeal_deadline"])
    action_time = session.scalars(select(Review)).one().updated_at
    assert timedelta(days=29) < deadline - action_time < timedelta(days=31)


@integration
def test_withdraw_is_idempotent_and_checks_the_receipt(api: Any) -> None:
    client, _, destination = api
    body = _payload(destination.id)
    review_id = client.post("/api/v1/reviews/guest", json=body).json()["review_id"]
    url = f"/api/v1/reviews/{review_id}/withdraw"

    assert client.post(url, json={"receipt_secret": new_receipt(), "expected_version": 1}).status_code == 404

    first = client.post(url, json={"receipt_secret": body["receipt_secret"], "expected_version": 1})
    assert first.status_code == 200
    assert first.json()["status"] == "WITHDRAWN"
    assert first.json()["version"] == 2

    # A retry after a lost response still carries the old version and must still succeed.
    retry = client.post(url, json={"receipt_secret": body["receipt_secret"], "expected_version": 1})
    assert retry.status_code == 200
    assert retry.json() == first.json()


@integration
def test_withdraw_with_a_stale_version_conflicts_while_active(api: Any) -> None:
    client, _, destination = api
    body = _payload(destination.id)
    review_id = client.post("/api/v1/reviews/guest", json=body).json()["review_id"]
    response = client.post(
        f"/api/v1/reviews/{review_id}/withdraw",
        json={"receipt_secret": body["receipt_secret"], "expected_version": 7},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REVIEW_VERSION_CONFLICT"


@integration
@pytest.mark.usefixtures("keyring")
def test_key_rotation_keeps_receipts_and_drafts_working(
    api: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, session, destination = api
    body = _payload(destination.id)
    first = client.post("/api/v1/reviews/guest", json=body)
    assert first.status_code == 201
    review = session.scalars(select(Review)).one()
    assert review.guest_scope_key_id == "v1"
    old_digest = session.scalars(select(ReviewReceipt)).one().digest

    _rotate_to(monkeypatch, "v2")

    # Draft deduplication survives rotation: the same scope and receipt still recover the draft.
    retry = client.post("/api/v1/reviews/guest", json=body)
    assert retry.status_code == 200
    assert retry.json()["review_id"] == first.json()["review_id"]
    assert len(session.scalars(select(Review)).all()) == 1

    # A successful receipt use re-digests under the current key in the same transaction.
    status = client.post(
        "/api/v1/review-receipts/status",
        json={"review_id": first.json()["review_id"], "receipt_secret": body["receipt_secret"]},
    )
    assert status.status_code == 200
    session.expire_all()
    receipt = session.scalars(select(ReviewReceipt)).one()
    assert receipt.key_id == "v2"
    assert receipt.digest != old_digest
    assert receipt.digest == crypto.digest(crypto.RECEIPT_LABEL, "v2", body["receipt_secret"])
