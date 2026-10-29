"""R07: edit an unpublished review, owner reads, member history, member withdraw, guest appeal,
and the request-changes decision (Review.md 4.2, 5.1, 5.2, 9.2, 9.3; API.md 5.4 to 5.6)."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import test_admin as admin
import test_auth as support
from fastapi.testclient import TestClient
from receipts import new_receipt
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (
    Appeal,
    AuditEvent,
    Destination,
    DestinationRatingStats,
    DestinationStatus,
    ModerationActionRecord,
    ModerationTask,
    Review,
    ReviewCategory,
    ReviewCategoryRating,
    ReviewRevision,
    ReviewStatus,
    RevisionStatus,
)
from app.schemas import GuestReviewCreate
from app.services import encode_cursor, submit_guest_review

auth_env = support.auth_env
fake = support.fake
redis_fake = support.redis_fake
_reset_limiter = support._reset_limiter  # noqa: SLF001
pytestmark = pytest.mark.integration
BASE = "/api/v1/admin"
API = "/api/v1"


@pytest.fixture()
def client(auth_env: None, postgres_session: Session, fake: support.FakeGoTrue, redis_fake: Any) -> TestClient:
    return support.make_client(postgres_session, fake, redis_fake)


def _destination(session: Session, name: str = "Sajek") -> Destination:
    destination = Destination(status=DestinationStatus.PUBLISHED, name_bn="সাজেক", name_en=name)
    session.add(destination)
    session.commit()
    return destination


def _month(offset: int = 0) -> str:
    first = date.today().replace(day=1)
    for _ in range(offset):
        first = (first - timedelta(days=1)).replace(day=1)
    return first.isoformat()


def _body(destination: Destination, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "destination_id": str(destination.id),
        "client_draft_id": str(uuid.uuid4()),
        "receipt_secret": new_receipt(),
        "language": "EN",
        "traveller_type": "SOLO",
        "comfort_tier": "STANDARD",
        "visit_month": _month(),
        "title": "Clouds over the hills",
        "body": "We watched the clouds roll over the hills at sunrise.",
        "overall_rating": 5,
        "category_ratings": {"FOOD": 4, "SAFETY_PERCEPTION": 5},
        "consent_version": "v1",
    }
    body.update(overrides)
    return body


def _member(client: TestClient, session: Session, fake: support.FakeGoTrue, email: str, ip: str) -> TestClient:
    return admin.staff_client(client, session, fake, email, None, ip, aal="aal1")


def _anonymous(client: TestClient, ip: str = "203.0.113.200") -> TestClient:
    return TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": ip})


def _member_review(browser: TestClient, destination: Destination, **overrides: Any) -> str:
    response = browser.post(f"{API}/reviews/member", json=_body(destination, **overrides))
    assert response.status_code == 201, response.text
    return str(response.json()["review_id"])


def _guest_review(session: Session, destination: Destination, receipt: str, secret: str = "g" * 43) -> Review:
    payload = GuestReviewCreate.model_validate(
        {
            **_body(destination, receipt_secret=receipt),
            "guest_scope_secret": secret,
            "guest_display_name": "Rahim",
        }
    )
    review = submit_guest_review(session, payload).review
    session.commit()
    return review


def _moderate(
    client: TestClient,
    session: Session,
    fake: support.FakeGoTrue,
    review_id: uuid.UUID,
    decision: str,
    email: str,
    ip: str,
    reason: str = "meets-policy",
    moderator: TestClient | None = None,
) -> Any:
    session.expire_all()
    moderator = moderator or admin.staff_client(client, session, fake, email, "moderator", ip)
    task = session.scalar(select(ModerationTask).where(ModerationTask.subject_id == review_id, ModerationTask.status == "open"))
    assert task is not None
    lease = admin._claim(moderator, task)["lease_token"]  # noqa: SLF001
    review = session.get(Review, review_id)
    assert review is not None
    return moderator.post(
        f"{BASE}/submissions/{review_id}/moderation-actions",
        json=admin._decision(task, lease, review, decision=decision, reason_code=reason),  # noqa: SLF001
    )


def _edit(browser: TestClient, review_id: str, version: int, **fields: Any) -> Any:
    return browser.patch(f"{API}/reviews/{review_id}/pending", json={"expected_version": version, **fields})


# ============================ edit ============================


def test_a_member_edits_a_pending_review_as_a_new_revision(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    destination = _destination(postgres_session)
    nila = _member(client, postgres_session, fake, "nila@example.com", "203.0.113.10")
    review_id = _member_review(nila, destination)

    edited = _edit(nila, review_id, 1, title="Sunrise over the clouds", overall_rating=4, category_ratings={"CLEANLINESS": 3})
    assert edited.status_code == 200, edited.text
    assert edited.json() == {"review_id": review_id, "status": "PENDING", "version": 2, "revision": 2}

    postgres_session.expire_all()
    review = postgres_session.get(Review, uuid.UUID(review_id))
    assert review is not None and review.version == 2 and review.overall_rating == 4
    revisions = postgres_session.scalars(select(ReviewRevision).where(ReviewRevision.review_id == review.id).order_by(ReviewRevision.sequence)).all()
    assert [(r.sequence, r.status) for r in revisions] == [(1, RevisionStatus.SUPERSEDED), (2, RevisionStatus.PENDING)]
    assert review.current_revision_id == revisions[1].id
    assert revisions[1].title == "Sunrise over the clouds" and revisions[1].body == revisions[0].body, "omitted fields carry over"
    ratings = {row.category: row.rating for row in postgres_session.scalars(select(ReviewCategoryRating).where(ReviewCategoryRating.revision_id == revisions[1].id))}
    assert ratings == {ReviewCategory.CLEANLINESS: 3}, "a sent category set replaces the old one"
    old = postgres_session.scalars(select(ReviewCategoryRating).where(ReviewCategoryRating.revision_id == revisions[0].id)).all()
    assert len(old) == 2, "the superseded revision keeps its history"
    assert postgres_session.scalar(select(ModerationTask).where(ModerationTask.subject_id == review.id, ModerationTask.status == "open"))
    stats = postgres_session.get(DestinationRatingStats, destination.id)
    assert stats is not None and stats.guest_rating_count == 0 and stats.community_rating_count == 0, "nothing is counted before publication"

    cleared = _edit(nila, review_id, 2, category_ratings={})
    assert cleared.status_code == 200
    postgres_session.expire_all()
    assert not postgres_session.scalars(select(ReviewCategoryRating).where(ReviewCategoryRating.revision_id == postgres_session.get(Review, review.id).current_revision_id)).all()


def test_edit_validation_and_credentials(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    destination = _destination(postgres_session)
    nila = _member(client, postgres_session, fake, "nila@example.com", "203.0.113.11")
    omar = _member(client, postgres_session, fake, "omar@example.com", "203.0.113.12")
    review_id = _member_review(nila, destination)

    assert _edit(nila, review_id, 1).status_code == 422, "at least one field"
    assert _edit(nila, review_id, 1, title=None).status_code == 422, "null is not a value"
    assert _edit(nila, review_id, 1, overall_rating=9).status_code == 422
    assert _edit(nila, review_id, 1, destination_id=str(destination.id)).status_code == 422, "the destination cannot change"
    assert _edit(nila, review_id, 1, visit_month=_month().replace("-01", "-15")).status_code == 422
    stale = _edit(nila, review_id, 7, title="A different title")
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "REVIEW_VERSION_CONFLICT"

    not_owner = _edit(omar, review_id, 1, title="Someone else's review")
    assert not_owner.status_code == 404, "another person's review is not disclosed"
    assert _edit(_anonymous(client), review_id, 1, title="Anonymous attempt").status_code == 401
    no_csrf = _anonymous(client, "203.0.113.201")
    no_csrf.cookies.set("__Host-abhijatri_session", fake.mint("nila@example.com").access_token)
    assert _edit(no_csrf, review_id, 1, title="No token").status_code == 403
    postgres_session.expire_all()
    review = postgres_session.get(Review, uuid.UUID(review_id))
    assert review is not None and review.version == 1, "refused edits change nothing"


def test_a_guest_edits_with_the_receipt(client: TestClient, postgres_session: Session) -> None:
    destination = _destination(postgres_session)
    receipt = new_receipt()
    review = _guest_review(postgres_session, destination, receipt)
    guest = _anonymous(client)

    wrong = _edit(guest, str(review.id), 1, receipt_secret=new_receipt(), title="Not mine")
    assert wrong.status_code == 404 and wrong.json()["error"]["code"] == "RECEIPT_NOT_FOUND"
    ok = _edit(guest, str(review.id), 1, receipt_secret=receipt, body="An edited note that is long enough to pass.")
    assert ok.status_code == 200 and ok.json()["version"] == 2 and ok.json()["revision"] == 2
    again = _edit(guest, str(review.id), 1, receipt_secret=receipt, title="Stale version")
    assert again.status_code == 409 and again.json()["error"]["code"] == "REVIEW_VERSION_CONFLICT"


@pytest.mark.parametrize("state", [ReviewStatus.PUBLISHED, ReviewStatus.REJECTED, ReviewStatus.WITHDRAWN, ReviewStatus.UNDER_REVIEW, ReviewStatus.HIDDEN])
def test_only_unpublished_reviews_can_be_edited(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, state: ReviewStatus) -> None:
    destination = _destination(postgres_session)
    nila = _member(client, postgres_session, fake, "nila@example.com", "203.0.113.13")
    review_id = _member_review(nila, destination)
    postgres_session.execute(update(Review).where(Review.id == uuid.UUID(review_id)).values(status=state))
    postgres_session.commit()
    refused = _edit(nila, review_id, 1, title="Too late to edit")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "INVALID_TRANSITION"


def test_moving_a_member_review_onto_a_taken_month_is_refused(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    destination = _destination(postgres_session)
    nila = _member(client, postgres_session, fake, "nila@example.com", "203.0.113.14")
    _member_review(nila, destination, visit_month=_month())
    second = _member_review(nila, destination, visit_month=_month(1))
    clash = _edit(nila, second, 1, visit_month=_month())
    assert clash.status_code == 409 and clash.json()["error"]["code"] == "MEMBER_REVIEW_EXISTS"
    postgres_session.expire_all()
    review = postgres_session.get(Review, uuid.UUID(second))
    assert review is not None and review.version == 1 and review.visit_month.isoformat() == _month(1)
    assert _edit(nila, second, 1, visit_month=_month(2)).status_code == 200


# ============================ request changes ============================


def test_request_changes_sends_a_review_back_and_the_author_resubmits(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    destination = _destination(postgres_session)
    receipt = new_receipt()
    review = _guest_review(postgres_session, destination, receipt)
    result = _moderate(client, postgres_session, fake, review.id, "REQUEST_CHANGES", "mod@example.com", "203.0.113.20", reason="remove-phone-number")
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "CHANGES_REQUESTED"
    postgres_session.expire_all()
    assert postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "review.request_changes"))
    action = postgres_session.scalar(select(ModerationActionRecord).where(ModerationActionRecord.review_id == review.id))
    assert action is not None and action.new_status == ReviewStatus.CHANGES_REQUESTED
    stats = postgres_session.get(DestinationRatingStats, destination.id)
    assert stats is not None and stats.guest_rating_count == 0

    guest = _anonymous(client)
    status = guest.post(f"{API}/review-receipts/status", json={"review_id": str(review.id), "receipt_secret": receipt}).json()
    assert status["status"] == "CHANGES_REQUESTED" and status["decision_reason"] == "remove-phone-number" and status["appeal_deadline"] is None

    resubmitted = _edit(guest, str(review.id), status["version"], receipt_secret=receipt, body="The note without the phone number, long enough.")
    assert resubmitted.status_code == 200 and resubmitted.json()["status"] == "PENDING"
    postgres_session.expire_all()
    assert postgres_session.scalar(select(ModerationTask).where(ModerationTask.subject_id == review.id, ModerationTask.status == "open")), "back in the queue"
    published = _moderate(client, postgres_session, fake, review.id, "PUBLISH", "mod2@example.com", "203.0.113.21")
    assert published.status_code == 200 and published.json()["status"] == "PUBLISHED"
    refused = _moderate_again(client, postgres_session, fake, review.id)
    assert refused.status_code in (404, 409, 422), "a published review cannot be sent back"


def _moderate_again(client: TestClient, session: Session, fake: support.FakeGoTrue, review_id: uuid.UUID) -> Any:
    session.expire_all()
    moderator = admin.staff_client(client, session, fake, "mod3@example.com", "moderator", "203.0.113.22")
    review = session.get(Review, review_id)
    assert review is not None
    return moderator.post(
        f"{BASE}/submissions/{review_id}/moderation-actions",
        json={"task_id": str(uuid.uuid4()), "lease_token": str(uuid.uuid4()), "expected_version": review.version, "decision": "REQUEST_CHANGES", "reason_code": "late"},
    )


# ============================ owner reads ============================


def test_the_owner_and_staff_can_read_one_review_and_nobody_else(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    destination = _destination(postgres_session)
    nila = _member(client, postgres_session, fake, "nila@example.com", "203.0.113.30")
    omar = _member(client, postgres_session, fake, "omar@example.com", "203.0.113.31")
    review_id = _member_review(nila, destination)
    _edit(nila, review_id, 1, title="Edited once")

    mine = nila.get(f"{API}/reviews/{review_id}")
    assert mine.status_code == 200, mine.text
    detail = mine.json()
    assert mine.headers["cache-control"] == "no-store"
    assert detail["status"] == "PENDING" and detail["version"] == 2 and detail["title"] == "Edited once"
    assert [(r["sequence"], r["status"]) for r in detail["revisions"]] == [(1, "SUPERSEDED"), (2, "PENDING")]
    assert detail["author_type"] == "MEMBER" and detail["guest_display_name"] is None and detail["author_user_id"] is None
    assert detail["conflict_declared"] is None, "moderator-only fields are hidden from the author"

    assert omar.get(f"{API}/reviews/{review_id}").status_code == 404
    assert omar.get(f"{API}/reviews/{uuid.uuid4()}").status_code == 404, "missing and foreign look the same"
    assert _anonymous(client).get(f"{API}/reviews/{review_id}").status_code == 401

    moderator = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.32")
    seen = moderator.get(f"{API}/reviews/{review_id}")
    assert seen.status_code == 200 and seen.json()["author_user_id"] == str(fake.users["nila@example.com"]["id"])
    assert seen.json()["conflict_declared"] is False


def test_member_history_pages_without_gaps_or_repeats(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    destination = _destination(postgres_session)
    other_destination = _destination(postgres_session, "Bandarban")
    nila = _member(client, postgres_session, fake, "nila@example.com", "203.0.113.40")
    omar = _member(client, postgres_session, fake, "omar@example.com", "203.0.113.41")
    ids = [_member_review(nila, destination, visit_month=_month(i)) for i in range(5)]
    _member_review(nila, other_destination)
    _member_review(omar, destination)
    # two reviews share a timestamp: the id breaks the tie
    tied = datetime(2026, 1, 1, tzinfo=UTC)
    postgres_session.execute(update(Review).where(Review.id.in_([uuid.UUID(ids[0]), uuid.UUID(ids[1])])).values(created_at=tied))
    postgres_session.commit()

    seen: list[str] = []
    cursor: str | None = None
    while True:
        page = nila.get(f"{API}/reviews/mine", params={"limit": 2, **({"after": cursor} if cursor else {})})
        assert page.status_code == 200, page.text
        assert page.headers["cache-control"] == "no-store"
        seen += [item["id"] for item in page.json()["items"]]
        cursor = page.json()["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 6 and len(set(seen)) == 6, "every own review exactly once"
    assert set(ids) <= set(seen)

    only = nila.get(f"{API}/reviews/mine", params={"destination_id": str(other_destination.id)}).json()
    assert len(only["items"]) == 1 and only["next_cursor"] is None
    postgres_session.execute(update(Review).where(Review.id == uuid.UUID(ids[2])).values(status=ReviewStatus.WITHDRAWN))
    postgres_session.commit()
    withdrawn = nila.get(f"{API}/reviews/mine", params={"status": "WITHDRAWN"}).json()
    assert [item["id"] for item in withdrawn["items"]] == [ids[2]]
    assert nila.get(f"{API}/reviews/mine", params={"status": "NOPE"}).status_code == 422
    assert nila.get(f"{API}/reviews/mine", params={"limit": 51}).status_code == 422
    assert nila.get(f"{API}/reviews/mine", params={"after": "not-a-cursor"}).status_code == 422
    feed_cursor = encode_cursor(datetime.now(UTC), uuid.uuid4())
    wrong = nila.get(f"{API}/reviews/mine", params={"after": feed_cursor})
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "INVALID_CURSOR", "cursors are not shared between listings"
    assert _anonymous(client).get(f"{API}/reviews/mine").status_code == 401


# ============================ withdraw ============================


def test_a_member_withdraws_their_own_review_by_session(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    destination = _destination(postgres_session)
    nila = _member(client, postgres_session, fake, "nila@example.com", "203.0.113.50")
    omar = _member(client, postgres_session, fake, "omar@example.com", "203.0.113.51")
    review_id = _member_review(nila, destination)

    assert omar.post(f"{API}/reviews/{review_id}/withdraw", json={"expected_version": 1}).status_code == 404
    assert _anonymous(client).post(f"{API}/reviews/{review_id}/withdraw", json={"expected_version": 1}).status_code == 401
    stale = nila.post(f"{API}/reviews/{review_id}/withdraw", json={"expected_version": 5})
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "REVIEW_VERSION_CONFLICT"
    done = nila.post(f"{API}/reviews/{review_id}/withdraw", json={"expected_version": 1})
    assert done.status_code == 200 and done.json()["status"] == "WITHDRAWN"
    retry = nila.post(f"{API}/reviews/{review_id}/withdraw", json={"expected_version": 1})
    assert retry.status_code == 200 and retry.json()["status"] == "WITHDRAWN", "a lost response can be retried"
    postgres_session.expire_all()
    assert not postgres_session.scalar(select(ModerationTask).where(ModerationTask.subject_id == uuid.UUID(review_id), ModerationTask.status == "open"))
    assert _edit(nila, review_id, 2, title="After withdrawal").status_code == 409


def test_a_guest_still_withdraws_with_the_receipt(client: TestClient, postgres_session: Session) -> None:
    destination = _destination(postgres_session)
    receipt = new_receipt()
    review = _guest_review(postgres_session, destination, receipt)
    guest = _anonymous(client)
    wrong = guest.post(f"{API}/reviews/{review.id}/withdraw", json={"expected_version": 1, "receipt_secret": new_receipt()})
    assert wrong.status_code == 404
    ok = guest.post(f"{API}/reviews/{review.id}/withdraw", json={"expected_version": 1, "receipt_secret": receipt})
    assert ok.status_code == 200 and ok.json()["status"] == "WITHDRAWN"


# ============================ guest appeal ============================


def test_a_guest_appeals_a_rejection_with_the_receipt(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    destination = _destination(postgres_session)
    receipt = new_receipt()
    review = _guest_review(postgres_session, destination, receipt)
    guest = _anonymous(client)
    statement = "This is my honest account of the trip, please look again."
    request = {"review_id": str(review.id), "receipt_secret": receipt, "statement": statement}

    early = guest.post(f"{API}/review-receipts/appeals", json=request)
    assert early.status_code == 409 and early.json()["error"]["code"] == "APPEAL_WINDOW_CLOSED", "nothing to appeal yet"

    decider = admin.staff_client(client, postgres_session, fake, "decider@example.com", "moderator", "203.0.113.60")
    assert _moderate(client, postgres_session, fake, review.id, "REJECT", "decider@example.com", "203.0.113.60", reason="spam", moderator=decider).status_code == 200
    short = guest.post(f"{API}/review-receipts/appeals", json={**request, "statement": "too short"})
    assert short.status_code == 422
    wrong = guest.post(f"{API}/review-receipts/appeals", json={**request, "receipt_secret": new_receipt()})
    assert wrong.status_code == 404 and wrong.json()["error"]["code"] == "RECEIPT_NOT_FOUND"

    created = guest.post(f"{API}/review-receipts/appeals", json=request)
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "OPEN"
    second = guest.post(f"{API}/review-receipts/appeals", json=request)
    assert second.status_code == 409 and second.json()["error"]["code"] == "DUPLICATE_APPEAL"

    postgres_session.expire_all()
    appeal = postgres_session.get(Appeal, uuid.UUID(created.json()["appeal_id"]))
    assert appeal is not None and appeal.appellant_user_id is None and appeal.state == "received" and appeal.reason == statement
    assert postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "appeal.received", AuditEvent.target_id == str(appeal.id)))
    status = guest.post(f"{API}/review-receipts/status", json={"review_id": str(review.id), "receipt_secret": receipt}).json()
    assert status["status"] == "REJECTED" and status["appeal_state"] == "received"

    own_task = postgres_session.scalar(select(ModerationTask).where(ModerationTask.subject_id == appeal.id))
    assert own_task is not None
    other = admin.staff_client(client, postgres_session, fake, "other-mod@example.com", "moderator", "203.0.113.61")
    lease = admin._claim(other, own_task)["lease_token"]  # noqa: SLF001
    refused = decider.post(f"{BASE}/appeals/{appeal.id}/decision", json={"outcome": "overturned", "expected_version": 1, "note": "Looks real.", "task_id": str(own_task.id), "lease_token": lease})
    assert refused.status_code in (403, 409), "the original decider may not decide the appeal"
    ok = other.post(f"{BASE}/appeals/{appeal.id}/decision", json={"outcome": "overturned", "expected_version": 1, "note": "Looks real.", "task_id": str(own_task.id), "lease_token": lease})
    assert ok.status_code == 200 and ok.json()["state"] == "overturned", ok.text
    after = guest.post(f"{API}/review-receipts/status", json={"review_id": str(review.id), "receipt_secret": receipt}).json()
    assert after["status"] == "PENDING" and after["appeal_state"] == "overturned"


def test_a_late_guest_appeal_is_refused(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    destination = _destination(postgres_session)
    receipt = new_receipt()
    review = _guest_review(postgres_session, destination, receipt)
    assert _moderate(client, postgres_session, fake, review.id, "REJECT", "decider@example.com", "203.0.113.70", reason="spam").status_code == 200
    postgres_session.execute(update(ModerationActionRecord).where(ModerationActionRecord.review_id == review.id).values(created_at=datetime.now(UTC) - timedelta(days=32)))
    postgres_session.commit()
    guest = _anonymous(client)
    late = guest.post(f"{API}/review-receipts/appeals", json={"review_id": str(review.id), "receipt_secret": receipt, "statement": "Please reconsider this decision."})
    assert late.status_code == 409 and late.json()["error"]["code"] == "APPEAL_WINDOW_CLOSED"
    status = guest.post(f"{API}/review-receipts/status", json={"review_id": str(review.id), "receipt_secret": receipt}).json()
    assert status["appeal_deadline"] is not None and datetime.fromisoformat(status["appeal_deadline"]) < datetime.now(UTC)
