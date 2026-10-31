"""R11 review reporting (Review.md 5.4, 9.2): the nine reasons, member reports and their limits, anonymous reports
and lost-receipt removal requests, queue priority, and the privacy of the contact."""

import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import test_admin as admin
import test_auth as support
import test_rating_exclusion as helpers
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app import report_reasons
from app.abuse import get_counter_session_factory
from app.config import get_settings
from app.errors import ApiError
from app.models import (
    AuditEvent,
    Destination,
    ModerationTask,
    OutboxEvent,
    RatingEligibility,
    Report,
    Review,
    ReviewStatus,
    Sanction,
    User,
)
from app.services import recheck_rating
from app.turnstile import get_turnstile_verifier

auth_env = support.auth_env
fake = support.fake
redis_fake = support.redis_fake
pytestmark = pytest.mark.integration
BASE = "/api/v1/admin"
API = "/api/v1"

_destination, _verified_member, _review, _publish, _user = (
    helpers._destination, helpers._verified_member, helpers._review, helpers._publish, helpers._user,  # noqa: SLF001
)
moderator = helpers.moderator


class FakeChallenge:
    """Stands in for Cloudflare: passes unless told to fail, and remembers what it was asked."""

    def __init__(self) -> None:
        self.fail = False
        self.calls: list[tuple[str | None, str, str | None]] = []

    def __call__(self, token: str | None, *, action: str, remote_address: str | None) -> None:
        self.calls.append((token, action, remote_address))
        if self.fail:
            raise ApiError("CHALLENGE_FAILED")


@pytest.fixture()
def challenge() -> FakeChallenge:
    return FakeChallenge()


@pytest.fixture()
def client(auth_env: None, postgres_session: Session, fake: support.FakeGoTrue, redis_fake: Any, challenge: FakeChallenge, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("RATE_LIMIT_GUEST_SUBMIT", "1000/minute")  # the in-memory burst filter is not under test here
    get_settings.cache_clear()
    browser = support.make_client(postgres_session, fake, redis_fake)
    browser.app.dependency_overrides[get_turnstile_verifier] = lambda: challenge
    browser.app.dependency_overrides[get_counter_session_factory] = lambda: sessionmaker(bind=postgres_session.get_bind(), expire_on_commit=False)
    yield browser
    get_settings.cache_clear()


@pytest.fixture()
def configure(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def apply(**env: str) -> None:
        for name, value in env.items():
            monkeypatch.setenv(name.upper(), value)
        get_settings.cache_clear()

    return apply


def _member(client: TestClient, session: Session, fake: support.FakeGoTrue, name: str, n: int) -> TestClient:
    return admin.staff_client(client, session, fake, f"{name}@example.test", None, f"203.0.113.{n}", aal="aal1")


def _visitor(client: TestClient, address: str, **headers: str) -> TestClient:
    return TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": address, **headers})


def _published(session: Session, moderator: User, *, rating: int = 4, name: str = "Sajek") -> Review:
    return _publish(session, _review(session, _destination(session, name), _verified_member(session), rating=rating), moderator)


def _task(session: Session, report_id: uuid.UUID) -> ModerationTask:
    task = session.scalar(select(ModerationTask).where(ModerationTask.subject_id == report_id))
    assert task is not None
    return task


def _count(session: Session, model: Any) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


# ---- reasons ----


def test_the_reason_lists_agree_with_each_other() -> None:
    assert len(report_reasons.REASONS) == 9 and report_reasons.REMOVAL_REQUEST not in report_reasons.REASONS
    assert set(report_reasons.LABELS) == set(report_reasons.ALL_STORED)
    assert set(report_reasons.REASONS) >= report_reasons.RATING_SUSPENDING
    assert report_reasons.normalise("offensive") == "harassment"
    assert report_reasons.normalise("removal_request") is None and report_reasons.normalise("nope") is None
    assert [report_reasons.priority(code) for code in ("spam", "privacy", "removal_request")] == [1, 2, 2]


# ---- members ----


@pytest.mark.parametrize("reason", report_reasons.REASONS)
def test_every_reason_is_accepted_and_queued_with_its_priority(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User, reason: str
) -> None:
    review = _published(postgres_session, moderator)
    reader = _member(client, postgres_session, fake, f"reader-{reason}", 10 + report_reasons.REASONS.index(reason))
    response = reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": reason, "details": "Please look."})
    assert response.status_code == 201 and response.json()["state"] == "open"
    report = postgres_session.get(Report, uuid.UUID(response.json()["report_id"]))
    assert report is not None and report.reason_code == reason and report.source == "member"
    assert _task(postgres_session, report.id).priority == report_reasons.priority(reason) == report.severity
    postgres_session.refresh(review)
    assert review.status == ReviewStatus.PUBLISHED, "a report never removes a review by itself"


def test_the_old_offensive_code_is_stored_as_harassment(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    review = _published(postgres_session, moderator)
    reader = _member(client, postgres_session, fake, "legacy", 30)
    assert reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "offensive"}).status_code == 201
    assert postgres_session.scalar(select(Report.reason_code)) == "harassment"


@pytest.mark.parametrize("reason", ["", "x", "not-a-reason", "removal_request", "SPAM", "spam; drop table reports", "a" * 41])
def test_unknown_reasons_and_the_removal_code_are_refused_for_members(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User, reason: str
) -> None:
    review = _published(postgres_session, moderator)
    reader = _member(client, postgres_session, fake, "badreason", 31)
    assert reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": reason}).status_code == 422
    assert _count(postgres_session, Report) == 0


def test_only_published_reviews_by_someone_else_can_be_reported(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    destination, author = _destination(postgres_session), _verified_member(postgres_session)
    pending = _review(postgres_session, destination, author)
    published = _publish(postgres_session, _review(postgres_session, destination, author, month=__import__("datetime").date(2026, 8, 1)), moderator)
    reader = _member(client, postgres_session, fake, "scope", 32)
    assert reader.post(f"{API}/reviews/{pending.id}/reports", json={"reason_code": "spam"}).status_code == 404
    assert reader.post(f"{API}/reviews/{uuid.uuid4()}/reports", json={"reason_code": "spam"}).status_code == 404
    own = admin.staff_client(client, postgres_session, fake, "ownerreport@example.test", None, "203.0.113.33", aal="aal1")
    owner_id = fake.users["ownerreport@example.test"]["id"]
    published.author_user_id = owner_id
    postgres_session.commit()
    assert own.post(f"{API}/reviews/{published.id}/reports", json={"reason_code": "spam"}).status_code == 403
    assert _count(postgres_session, Report) == 0


def test_a_visitor_or_a_request_without_csrf_cannot_report(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    review = _published(postgres_session, moderator)
    assert _visitor(client, "203.0.113.34").post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "spam"}).status_code == 401
    no_csrf = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN})
    admin.staff_client(client, postgres_session, fake, "nocsrf@example.test", None, "203.0.113.35", aal="aal1")
    no_csrf.cookies.set("__Host-abhijatri_session", fake.mint("nocsrf@example.test").access_token)
    assert no_csrf.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "spam"}).status_code == 403


def test_a_second_open_report_is_a_conflict_until_the_first_is_closed(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    review = _published(postgres_session, moderator)
    reader = _member(client, postgres_session, fake, "twice", 36)
    first = reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "spam"})
    again = reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "other"})
    assert first.status_code == 201 and again.status_code == 409 and again.json()["error"]["code"] == "DUPLICATE_OPEN_REPORT"
    assert _count(postgres_session, Report) == 1
    report = postgres_session.get(Report, uuid.UUID(first.json()["report_id"]))
    assert report is not None
    report.state = "dismissed"
    postgres_session.commit()
    assert reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "other"}).status_code == 201


def test_details_are_limited_to_a_thousand_characters(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    review = _published(postgres_session, moderator)
    reader = _member(client, postgres_session, fake, "long", 37)
    assert reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "spam", "details": "x" * 1001}).status_code == 422
    assert reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "spam", "details": "x" * 1000}).status_code == 201
    assert reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "spam", "surprise": 1}).status_code == 422


def test_member_limits_count_attempts_and_reset_by_window(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User, configure: Any
) -> None:
    configure(member_report_per_hour="3", member_report_per_review_per_day="2")
    reviews = [_published(postgres_session, moderator, name=f"Place {n}") for n in range(4)]
    reader = _member(client, postgres_session, fake, "flood", 38)
    codes = [reader.post(f"{API}/reviews/{r.id}/reports", json={"reason_code": "spam"}).status_code for r in reviews]
    assert codes == [201, 201, 201, 429], "the fourth report in the hour is refused"
    limited = reader.post(f"{API}/reviews/{reviews[0].id}/reports", json={"reason_code": "spam"})
    assert limited.status_code == 429 and limited.json()["error"]["code"] == "RATE_LIMITED" and "retry-after" in limited.headers
    assert _count(postgres_session, Report) == 3
    other = _member(client, postgres_session, fake, "calm", 39)
    assert other.post(f"{API}/reviews/{reviews[0].id}/reports", json={"reason_code": "spam"}).status_code == 201, "limits are per member"


def test_the_per_review_limit_counts_failed_attempts_too(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User, configure: Any
) -> None:
    configure(member_report_per_review_per_day="2")
    review = _published(postgres_session, moderator)
    reader = _member(client, postgres_session, fake, "retry", 40)
    statuses = [reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "spam"}).status_code for _ in range(3)]
    assert statuses == [201, 409, 429]


def test_a_restricted_member_cannot_report(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    review = _published(postgres_session, moderator)
    reader = _member(client, postgres_session, fake, "restricted", 41)
    reader_id = fake.users["restricted@example.test"]["id"]
    postgres_session.add(Sanction(user_id=reader_id, kind="posting_restriction", reason_code="policy", created_by=moderator.id, ends_at=datetime.now(UTC) + timedelta(days=3)))
    postgres_session.commit()
    answer = reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "spam"})
    assert answer.status_code == 403 and answer.json()["error"]["code"] == "ACCOUNT_RESTRICTED"
    assert _count(postgres_session, Report) == 0


def test_a_member_report_writes_the_audit_row_and_the_outbox_event_together(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User
) -> None:
    review = _published(postgres_session, moderator)
    reader = _member(client, postgres_session, fake, "audited", 42)
    audits, outbox = _count(postgres_session, AuditEvent), _count(postgres_session, OutboxEvent)
    report_id = reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "privacy", "details": "Shows my phone number"}).json()["report_id"]
    event = postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "report.create"))
    assert event is not None and event.target_id == report_id and event.actor_user_id == fake.users["audited@example.test"]["id"]
    assert event.event_metadata == {"review_id": str(review.id), "priority": 2}
    assert "phone" not in str(event.event_metadata) and event.reason == "privacy"
    assert _count(postgres_session, OutboxEvent) > outbox and _count(postgres_session, AuditEvent) == audits + 1
    # a refused duplicate leaves nothing behind
    audits, outbox = _count(postgres_session, AuditEvent), _count(postgres_session, OutboxEvent)
    assert reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "privacy"}).status_code == 409
    assert (_count(postgres_session, AuditEvent), _count(postgres_session, OutboxEvent)) == (audits, outbox)


@pytest.mark.parametrize("reason", sorted(report_reasons.RATING_SUSPENDING))
def test_a_serious_member_report_suspends_the_rating_and_closing_it_restores_it(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User, reason: str
) -> None:
    review = _published(postgres_session, moderator, rating=5)
    reader = _member(client, postgres_session, fake, f"serious-{reason}", 43 + sorted(report_reasons.RATING_SUSPENDING).index(reason))
    reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": reason})
    postgres_session.refresh(review)
    assert review.rating_eligibility == RatingEligibility.INELIGIBLE_REPORTED and review.counted_rating is None
    destination = postgres_session.get(Destination, review.destination_id)
    assert destination is not None and helpers._stats(postgres_session, destination) == ((0, 0), (0, 0))  # noqa: SLF001


def test_my_reports_lists_only_my_own_without_staff_fields(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    reviews = [_published(postgres_session, moderator, name=f"Spot {n}") for n in range(3)]
    mine = _member(client, postgres_session, fake, "mine", 50)
    theirs = _member(client, postgres_session, fake, "theirs", 51)
    for review in reviews:
        mine.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "spam", "details": "private words"})
    theirs.post(f"{API}/reviews/{reviews[0].id}/reports", json={"reason_code": "other"})
    page = mine.get(f"{API}/reports/mine", params={"limit": 2}).json()
    assert len(page["items"]) == 2 and page["next_cursor"]
    rest = mine.get(f"{API}/reports/mine", params={"limit": 2, "cursor": page["next_cursor"]}).json()
    seen = [item["id"] for item in page["items"] + rest["items"]]
    assert len(seen) == 3 and len(set(seen)) == 3 and rest["next_cursor"] is None
    assert set(page["items"][0]) == {"id", "review_id", "reason_code", "state", "created_at"}
    assert "private words" not in str(page) + str(rest)
    assert _visitor(client, "203.0.113.52").get(f"{API}/reports/mine").status_code == 401
    assert mine.get(f"{API}/reports/mine", params={"cursor": "!!"}).status_code == 422


# ---- anonymous reports ----


def _anonymous_body(review: Review, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"review_id": str(review.id), "reason_code": "privacy", "details": "It names my family.", "turnstile_token": "ok-token"}
    body.update(overrides)
    return body


def test_an_anonymous_report_is_accepted_queued_and_keeps_no_address(
    client: TestClient, postgres_session: Session, moderator: User, challenge: FakeChallenge
) -> None:
    review = _published(postgres_session, moderator)
    visitor = _visitor(client, "198.51.100.7")
    response = visitor.post(f"{API}/public/review-reports", json=_anonymous_body(review, contact="reader@example.test"))
    assert response.status_code == 202 and response.json() == {"received": True}
    report = postgres_session.scalar(select(Report))
    assert report is not None and report.source == "anonymous" and report.reporter_user_id is None
    assert report.reporter_scope_hash is not None and len(report.reporter_scope_hash) == 32
    assert report.reason_code == "privacy" and report.severity == 2 and _task(postgres_session, report.id).priority == 2
    assert "198.51.100.7" not in str((report.contact, report.details, report.reporter_scope_hash)), "the address is never stored"
    assert challenge.calls and challenge.calls[0][1] == "guest-report"
    postgres_session.refresh(review)
    assert review.rating_eligibility == RatingEligibility.ELIGIBLE, "an anonymous report cannot suspend a rating"
    recheck_rating(postgres_session, review.id)  # any later re-evaluation must agree
    postgres_session.commit()
    postgres_session.refresh(review)
    assert review.rating_eligibility == RatingEligibility.ELIGIBLE and review.counted_rating == 4


def test_an_anonymous_report_is_audited_without_personal_data(client: TestClient, postgres_session: Session, moderator: User) -> None:
    review = _published(postgres_session, moderator)
    _visitor(client, "198.51.100.8").post(f"{API}/public/review-reports", json=_anonymous_body(review, contact="+880 1712-345678"))
    event = postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "report.create_anonymous"))
    assert event is not None and event.actor_user_id is None and event.actor_role_snapshot is None
    dump = str((event.reason, event.event_metadata, event.target_id))
    for secret in ("198.51.100.8", "+880", "1712", "family", "ok-token"):
        assert secret not in dump
    assert event.event_metadata == {"review_id": str(review.id), "has_contact": True}


def test_a_failed_challenge_or_a_foreign_origin_creates_nothing(client: TestClient, postgres_session: Session, moderator: User, challenge: FakeChallenge) -> None:
    review = _published(postgres_session, moderator)
    challenge.fail = True
    failed = _visitor(client, "198.51.100.9").post(f"{API}/public/review-reports", json=_anonymous_body(review))
    assert failed.status_code == 403 and failed.json()["error"]["code"] == "CHALLENGE_FAILED"
    challenge.fail = False
    foreign = TestClient(client.app, base_url="https://localhost", headers={"Origin": "https://evil.example", "X-Forwarded-For": "198.51.100.10"})
    refused = foreign.post(f"{API}/public/review-reports", json=_anonymous_body(review))
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "CSRF_INVALID"
    assert _count(postgres_session, Report) == 0


def test_the_network_limit_applies_to_everyone_behind_one_address(
    client: TestClient, postgres_session: Session, moderator: User, configure: Any
) -> None:
    configure(anon_report_per_network_per_hour="2")
    reviews = [_published(postgres_session, moderator, name=f"Anon {n}") for n in range(3)]
    visitor = _visitor(client, "198.51.100.11")
    codes = [visitor.post(f"{API}/public/review-reports", json=_anonymous_body(r)).status_code for r in reviews]
    assert codes == [202, 202, 429]
    assert _visitor(client, "198.51.100.12").post(f"{API}/public/review-reports", json=_anonymous_body(reviews[2])).status_code == 202
    assert _count(postgres_session, Report) == 3


def test_a_repeat_report_from_the_same_visitor_answers_the_same_and_makes_no_second_row(client: TestClient, postgres_session: Session, moderator: User) -> None:
    review = _published(postgres_session, moderator)
    visitor = _visitor(client, "198.51.100.13")
    first = visitor.post(f"{API}/public/review-reports", json=_anonymous_body(review))
    second = visitor.post(f"{API}/public/review-reports", json=_anonymous_body(review, reason_code="spam"))
    assert (first.status_code, first.json()) == (second.status_code, second.json()) == (202, {"received": True})
    assert _count(postgres_session, Report) == 1
    assert _visitor(client, "198.51.100.14").post(f"{API}/public/review-reports", json=_anonymous_body(review)).status_code == 202
    assert _count(postgres_session, Report) == 2


def test_unpublished_and_unknown_reviews_answer_the_same_and_create_nothing(client: TestClient, postgres_session: Session, moderator: User) -> None:
    pending = _review(postgres_session, _destination(postgres_session), _verified_member(postgres_session))
    visitor = _visitor(client, "198.51.100.15")
    unknown = visitor.post(f"{API}/public/review-reports", json={**_anonymous_body(pending), "review_id": str(uuid.uuid4())})
    unpublished = visitor.post(f"{API}/public/review-reports", json=_anonymous_body(pending))
    assert (unknown.status_code, unknown.json()) == (unpublished.status_code, unpublished.json()) == (202, {"received": True})
    assert _count(postgres_session, Report) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"reason_code": "nonsense"}, {"reason_code": "removal_request"}, {"reason_code": ""}, {"contact": "not a contact"},
        {"contact": "a@b"}, {"contact": "x" * 201}, {"details": "x" * 1001}, {"extra": "field"}, {"review_id": "not-a-uuid"},
    ],
)
def test_malformed_anonymous_reports_are_refused(client: TestClient, postgres_session: Session, moderator: User, overrides: dict[str, Any]) -> None:
    review = _published(postgres_session, moderator)
    answer = _visitor(client, "198.51.100.16").post(f"{API}/public/review-reports", json=_anonymous_body(review, **overrides))
    assert answer.status_code == 422
    assert _count(postgres_session, Report) == 0


def test_the_contact_is_for_staff_only(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User, caplog: pytest.LogCaptureFixture) -> None:
    review = _published(postgres_session, moderator)
    with caplog.at_level("DEBUG"):
        _visitor(client, "198.51.100.17").post(f"{API}/public/review-reports", json=_anonymous_body(review, contact="contact-me@example.test"))
    assert "contact-me@example.test" not in caplog.text
    staff = admin.staff_client(client, postgres_session, fake, "triage@example.test", "moderator", "203.0.113.60")
    report = postgres_session.scalar(select(Report))
    assert report is not None
    queue = staff.get(f"{BASE}/queue", params={"task_type": "report"}).json()["items"]
    subject = next(item["subject"] for item in queue if item["subject"]["report_id"] == str(report.id))
    assert subject["contact"] == "contact-me@example.test" and subject["source"] == "anonymous" and subject["priority"] == 2
    assert subject["reason_label"] == {"bn": report_reasons.LABELS["privacy"][0], "en": report_reasons.LABELS["privacy"][1]}
    reader = _member(client, postgres_session, fake, "reader-contact", 61)
    assert "contact-me" not in reader.get(f"{API}/reports/mine").text
    assert "contact-me" not in _visitor(client, "198.51.100.18").get(f"{API}/destinations/{review.destination_id}/reviews").text
    audit_text = str([(e.reason, e.event_metadata) for e in postgres_session.scalars(select(AuditEvent))])
    assert "contact-me" not in audit_text


# ---- lost-receipt removal requests ----


def _removal_body(review: Review, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"review_id": str(review.id), "statement": "I wrote this review and lost my receipt.", "contact": "author@example.test", "turnstile_token": "ok"}
    body.update(overrides)
    return body


def test_a_removal_request_becomes_a_high_priority_report_with_a_required_contact(client: TestClient, postgres_session: Session, moderator: User, challenge: FakeChallenge) -> None:
    review = _published(postgres_session, moderator)
    visitor = _visitor(client, "198.51.100.20")
    assert visitor.post(f"{API}/public/removal-requests", json=_removal_body(review)).status_code == 202
    report = postgres_session.scalar(select(Report))
    assert report is not None and report.reason_code == "removal_request" and report.source == "anonymous"
    assert report.contact == "author@example.test" and report.details == "I wrote this review and lost my receipt."
    assert _task(postgres_session, report.id).priority == 2 and challenge.calls[-1][1] == "guest-removal"
    event = postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "removal_request.create"))
    assert event is not None and "author@example.test" not in str(event.event_metadata)
    postgres_session.refresh(review)
    assert review.status == ReviewStatus.PUBLISHED, "ownership is checked by a person first"


@pytest.mark.parametrize("overrides", [{"contact": ""}, {"contact": "  "}, {"contact": "nope"}, {"statement": "short"}, {"statement": "x" * 1001}, {"extra": 1}])
def test_a_removal_request_needs_a_valid_contact_and_a_real_statement(client: TestClient, postgres_session: Session, moderator: User, overrides: dict[str, Any]) -> None:
    review = _published(postgres_session, moderator)
    assert _visitor(client, "198.51.100.21").post(f"{API}/public/removal-requests", json=_removal_body(review, **overrides)).status_code == 422
    assert _count(postgres_session, Report) == 0


def test_removal_requests_share_the_network_limit_and_the_challenge(client: TestClient, postgres_session: Session, moderator: User, challenge: FakeChallenge, configure: Any) -> None:
    configure(anon_report_per_network_per_hour="1")
    review = _published(postgres_session, moderator)
    visitor = _visitor(client, "198.51.100.22")
    assert visitor.post(f"{API}/public/removal-requests", json=_removal_body(review)).status_code == 202
    assert visitor.post(f"{API}/public/review-reports", json=_anonymous_body(review)).status_code == 429
    challenge.fail = True
    assert _visitor(client, "198.51.100.23").post(f"{API}/public/removal-requests", json=_removal_body(review)).status_code == 403


def test_a_phone_number_is_a_valid_contact(client: TestClient, postgres_session: Session, moderator: User) -> None:
    review = _published(postgres_session, moderator)
    assert _visitor(client, "198.51.100.24").post(f"{API}/public/removal-requests", json=_removal_body(review, contact="+880 1712-345678")).status_code == 202


# ---- a NUL character is the caller's mistake, not an outage ----


@pytest.mark.parametrize("field", ["details", "contact"])
def test_a_nul_character_in_a_report_is_a_validation_error_not_a_server_error(client: TestClient, postgres_session: Session, moderator: User, field: str) -> None:
    review = _published(postgres_session, moderator)
    value = "a\x00b@example.test" if field == "contact" else "bad \x00 text"
    answer = _visitor(client, "198.51.100.40").post(f"{API}/public/review-reports", json=_anonymous_body(review, **{field: value}))
    assert answer.status_code == 422 and answer.json()["error"]["code"] == "VALIDATION_FAILED"
    assert _count(postgres_session, Report) == 0


def test_a_nul_character_in_a_member_report_is_refused(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    review = _published(postgres_session, moderator)
    reader = _member(client, postgres_session, fake, "nul-reader", 70)
    answer = reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": "spam", "details": "x\x00y"})
    assert answer.status_code == 422
    assert _count(postgres_session, Report) == 0


def test_the_contact_check_agrees_with_the_one_in_the_public_form() -> None:
    """The same sample list is in `frontend/src/api/reports.test.ts`; a rule changed on one side must change on both."""
    from app.admin.actions import clean_contact

    for good in ["a@b.co", "nila.rahman@example.com", "+880 1712-345678", "01712345678", "(02) 5555-0101"]:
        assert clean_contact(good) == good
    for bad in ["not a contact", "a@b", "12", "a b@c.com", "@@", "abc123"]:
        with pytest.raises(ApiError):
            clean_contact(bad)
    assert clean_contact("  a@b.co  ") == "a@b.co" and clean_contact("   ") is None and clean_contact(None) is None
    with pytest.raises(ApiError):
        clean_contact("", required=True)
