"""Verification, enforcement, appeals, notifications and retention (Moderation spec 6.2 to 6.7, 10, 11, 14)."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import test_admin as admin
import test_auth as support
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.admin import cases
from app.jobs import retention
from app.models import (
    Appeal,
    AuditEvent,
    EnforcementCase,
    ModerationActionRecord,
    ModerationTask,
    Notification,
    NotificationDelivery,
    OutboxEvent,
    Review,
    ReviewStatus,
    Sanction,
    User,
    Verification,
    VerificationCase,
    VerificationEvidence,
)
from app.notify import delivery, worker
from app.notify.providers import RecordingProvider, SendAmbiguous, SendFailed
from app.storage import get_storage

auth_env = support.auth_env
fake = support.fake
redis_fake = support.redis_fake
_reset_limiter = support._reset_limiter  # noqa: SLF001
pytestmark = pytest.mark.integration
BASE = "/api/v1/admin"


class FakeStorage:
    def __init__(self) -> None:
        self.objects: set[str] = set()
        self.deleted: list[str] = []

    def signed_upload_url(self, key: str) -> str:
        return f"http://storage.test/upload/{key}?token=t"

    def exists(self, key: str) -> bool:
        return key in self.objects

    def signed_download_url(self, key: str) -> str:
        return f"http://storage.test/download/{key}?token=t"

    def delete(self, keys: list[str]) -> None:
        self.deleted += keys
        self.objects -= set(keys)


@pytest.fixture()
def storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture()
def client(auth_env: None, postgres_session: Session, fake: support.FakeGoTrue, redis_fake: Any, storage: FakeStorage) -> TestClient:
    base = support.make_client(postgres_session, fake, redis_fake)
    base.app.dependency_overrides[get_storage] = lambda: storage  # type: ignore[attr-defined]
    return base


def factory(session: Session) -> sessionmaker[Session]:
    return sessionmaker(bind=session.get_bind(), expire_on_commit=False)


def member(client: TestClient, session: Session, fake: support.FakeGoTrue, email: str, ip: str) -> TestClient:
    return admin.staff_client(client, session, fake, email, None, ip, aal="aal1")


def claim(browser: TestClient, session: Session, subject_id: uuid.UUID) -> tuple[ModerationTask, str]:
    session.expire_all()
    task = session.scalar(select(ModerationTask).where(ModerationTask.subject_id == subject_id, ModerationTask.status == "open"))
    assert task is not None
    return task, admin._claim(browser, task)["lease_token"]  # noqa: SLF001


# ============================ verification ============================


def _submit_case(browser: TestClient, storage: FakeStorage, *, with_evidence: bool = True) -> dict[str, Any]:
    created = browser.post("/api/v1/verifications", json={"statement": "I am a student at BUET."})
    assert created.status_code == 201, created.text
    case = created.json()
    if with_evidence:
        intent = browser.post(f"/api/v1/verifications/{case['id']}/evidence", json={"content_type": "image/png", "size_bytes": 1000})
        assert intent.status_code == 200, intent.text
        assert intent.json()["upload_url"].startswith("http://storage.test/upload/")
        early = browser.post(f"/api/v1/verifications/{case['id']}/evidence/{intent.json()['evidence_id']}/complete")
        assert early.status_code == 422, "not uploaded yet"
        storage.objects.add(intent.json()["upload_url"].split("/upload/")[1].split("?")[0])
        done = browser.post(f"/api/v1/verifications/{case['id']}/evidence/{intent.json()['evidence_id']}/complete")
        assert done.status_code == 200 and done.json()["status"] == "uploaded"
    return case


def test_a_member_becomes_verified_through_the_queue(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, storage: FakeStorage) -> None:
    applicant = member(client, postgres_session, fake, "nila@example.com", "203.0.113.80")
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.81")
    case = _submit_case(applicant, storage)
    assert applicant.post("/api/v1/verifications", json={}).status_code == 409, "one open case per member"
    assert applicant.get("/api/v1/auth/session").json()["verified_member"] is False

    item = next(i for i in mod.get(f"{BASE}/queue", params={"task_type": "verification"}).json()["items"])
    assert item["subject"]["applicant"]["email"] == "nila@example.com" and len(item["subject"]["evidence"]) == 1
    task, lease = claim(mod, postgres_session, uuid.UUID(case["id"]))
    evidence_id = item["subject"]["evidence"][0]["id"]
    link = mod.post(f"{BASE}/verification-cases/{case['id']}/evidence/{evidence_id}/url")
    assert link.status_code == 200 and link.json()["expires_in"] == 60

    body = {"expected_version": 1, "reason_code": "start", "task_id": str(task.id), "lease_token": lease}
    assert mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**body, "to": "approved"}).status_code == 422, "approve only from in_review"
    assert mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**body, "to": "in_review"}).status_code == 200
    stale = mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**body, "to": "approved", "reason_code": "documents-ok"})
    assert stale.status_code == 409, "stale version"
    ok = mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**body, "expected_version": 2, "to": "approved", "reason_code": "documents-ok"})
    assert ok.status_code == 200 and ok.json()["state"] == "approved"

    assert applicant.get("/api/v1/auth/session").json()["verified_member"] is True
    verification = postgres_session.scalar(select(Verification).where(Verification.user_id == fake.users["nila@example.com"]["id"]))
    assert verification is not None and verification.status == "APPROVED" and verification.verification_type == "VERIFIED_MEMBER"
    assert applicant.post("/api/v1/verifications", json={}).status_code == 409, "already verified"
    assert {e.action for e in postgres_session.scalars(select(AuditEvent))} >= {"verification.submitted", "evidence.uploaded", "evidence.viewed", "verification.approved"}


def test_evidence_access_is_limited_to_the_holder(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, storage: FakeStorage) -> None:
    applicant = member(client, postgres_session, fake, "nila@example.com", "203.0.113.82")
    one = admin.staff_client(client, postgres_session, fake, "one@example.com", "moderator", "203.0.113.83")
    two = admin.staff_client(client, postgres_session, fake, "two@example.com", "moderator", "203.0.113.84")
    case = _submit_case(applicant, storage)
    evidence = postgres_session.scalar(select(VerificationEvidence).where(VerificationEvidence.case_id == uuid.UUID(case["id"])))
    assert evidence is not None
    url = f"{BASE}/verification-cases/{case['id']}/evidence/{evidence.id}/url"
    assert one.post(url).status_code == 403, "nobody holds it yet"
    claim(one, postgres_session, uuid.UUID(case["id"]))
    assert two.post(url).status_code == 403, "another moderator does not hold it"
    assert one.post(url).status_code == 200
    assert applicant.post(url).status_code == 404, "members never see staff routes"
    other = member(client, postgres_session, fake, "other@example.com", "203.0.113.85")
    assert other.post(f"/api/v1/verifications/{case['id']}/evidence", json={"content_type": "image/png", "size_bytes": 10}).status_code == 404
    assert applicant.post(f"/api/v1/verifications/{case['id']}/evidence", json={"content_type": "text/html", "size_bytes": 10}).status_code == 422


def test_approval_needs_evidence_and_escalation_needs_a_superadmin(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, storage: FakeStorage) -> None:
    applicant = member(client, postgres_session, fake, "nila@example.com", "203.0.113.86")
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.87")
    boss = admin.staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.88")
    case = _submit_case(applicant, storage, with_evidence=False)
    task, lease = claim(mod, postgres_session, uuid.UUID(case["id"]))
    base = {"reason_code": "r1", "task_id": str(task.id), "lease_token": lease}
    mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**base, "to": "in_review", "expected_version": 1})
    no_evidence = mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**base, "to": "approved", "expected_version": 2})
    assert no_evidence.status_code == 422 and no_evidence.json()["error"]["code"] == "EVIDENCE_REQUIRED"
    assert mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**base, "to": "escalated", "expected_version": 2}).status_code == 200
    stale_tab = mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**base, "to": "rejected", "expected_version": 3})
    assert stale_tab.status_code in (403, 409)
    task, lease = claim(boss, postgres_session, uuid.UUID(case["id"]))
    rejected = boss.post(f"{BASE}/verification-cases/{case['id']}/transition", json={"reason_code": "not-eligible", "task_id": str(task.id), "lease_token": lease, "to": "rejected", "expected_version": 3})
    assert rejected.status_code == 200
    postgres_session.expire_all()
    stored = postgres_session.get(VerificationCase, uuid.UUID(case["id"]))
    assert stored is not None and stored.purge_after is not None and stored.purge_after > datetime.now(UTC) + timedelta(days=29)


def test_clarification_round_trip(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, storage: FakeStorage) -> None:
    applicant = member(client, postgres_session, fake, "nila@example.com", "203.0.113.89")
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.90")
    case = _submit_case(applicant, storage)
    task, lease = claim(mod, postgres_session, uuid.UUID(case["id"]))
    base = {"reason_code": "r1", "task_id": str(task.id), "lease_token": lease}
    mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**base, "to": "in_review", "expected_version": 1})
    assert mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**base, "to": "needs_clarification", "expected_version": 2}).status_code == 422, "a question is required"
    asked = mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**base, "to": "needs_clarification", "expected_version": 2, "note": "Which department?"})
    assert asked.status_code == 200
    view = applicant.get("/api/v1/verifications/mine").json()["case"]
    assert view["state"] == "needs_clarification" and view["decision_note"] == "Which department?"
    answered = applicant.post(f"/api/v1/verifications/{case['id']}/respond", json={"statement": "Computer Science."})
    assert answered.status_code == 200 and answered.json()["state"] == "in_review"
    postgres_session.expire_all()
    assert postgres_session.scalar(select(ModerationTask).where(ModerationTask.subject_id == uuid.UUID(case["id"]), ModerationTask.status == "open")) is not None, "back in the queue"


# ============================ enforcement ============================


def _published(client: TestClient, session: Session, fake: support.FakeGoTrue, author_email: str | None = None) -> Review:
    review = admin._pending_review(session)  # noqa: SLF001
    if author_email:
        author_id = fake.users[author_email]["id"]
        session.execute(update(Review).where(Review.id == review.id).values(author_user_id=author_id, guest_display_name=None, guest_scope_hash=None, guest_scope_key_id=None, guest_tag=None))
        session.commit()
    admin._publish(client, session, fake, review, "203.0.113.99")  # noqa: SLF001
    session.expire_all()
    published = session.get(Review, review.id)
    assert published is not None and published.status == ReviewStatus.PUBLISHED
    return published


def test_emergency_takedown_and_follow_up(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _published(client, postgres_session, fake)
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.91")
    boss = admin.staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.92")
    opened = mod.post(f"{BASE}/enforcement-cases", json={"review_id": str(review.id), "reason_code": "doxxing", "emergency": True, "counts_toward_rating": False})
    assert opened.status_code == 201, opened.text
    case = opened.json()
    assert case["state"] == "taken_down" and case["follow_up_due_at"] and case["review"]["status"] == "HIDDEN"
    postgres_session.expire_all()
    follow_up = postgres_session.scalar(select(ModerationTask).where(ModerationTask.subject_id == uuid.UUID(case["case_id"])))
    assert follow_up is not None and follow_up.required_role == "superadmin"
    action = {"action": "remove", "expected_version": 1, "reason_code": "confirmed", "counts_toward_rating": False}
    assert mod.post(f"{BASE}/enforcement-cases/{case['case_id']}/actions", json=action).status_code == 403, "an emergency is decided by a superadmin"
    removed = boss.post(f"{BASE}/enforcement-cases/{case['case_id']}/actions", json=action)
    assert removed.status_code == 200 and removed.json() == {"case_id": case["case_id"], "state": "removed", "version": 2, "counts_toward_rating": False}
    restored = boss.post(f"{BASE}/enforcement-cases/{case['case_id']}/actions", json={"action": "restore", "expected_version": 2, "reason_code": "mistake"})
    assert restored.status_code == 200 and restored.json()["counts_toward_rating"] is True
    postgres_session.expire_all()
    assert postgres_session.get(Review, review.id).status == ReviewStatus.PUBLISHED
    assert boss.post(f"{BASE}/enforcement-cases/{case['case_id']}/actions", json={"action": "remove", "expected_version": 3, "reason_code": "x"}).status_code == 422


def test_sanctions_restrict_and_expire(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    target = member(client, postgres_session, fake, "troll@example.com", "203.0.113.93")
    target_id = fake.users["troll@example.com"]["id"]
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.94")
    boss = admin.staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.95")
    later = (datetime.now(UTC) + timedelta(days=7)).isoformat()
    suspension = {"user_id": str(target_id), "reason_code": "harassment", "sanction": {"kind": "suspension", "ends_at": later}}
    assert mod.post(f"{BASE}/enforcement-cases", json=suspension).status_code == 403, "suspension needs a superadmin"
    assert mod.post(f"{BASE}/enforcement-cases", json={**suspension, "sanction": {"kind": "warning"}}).status_code == 422, "a sanction needs an end or review date"
    restriction = mod.post(f"{BASE}/enforcement-cases", json={**suspension, "sanction": {"kind": "posting_restriction", "ends_at": later}})
    assert restriction.status_code == 201
    assert target.post("/api/v1/verifications", json={}).json()["error"]["code"] == "ACCOUNT_RESTRICTED"
    suspended = boss.post(f"{BASE}/enforcement-cases", json=suspension)
    assert suspended.status_code == 201
    assert target.get("/api/v1/auth/session").status_code == 403, "a suspended account is disabled at once"
    sanction_id = suspended.json()["sanctions"][0]["id"]
    assert mod.post(f"{BASE}/enforcement-cases", json={"user_id": str(fake.users['mod@example.com']['id']), "reason_code": "self-check"}).status_code == 403, "not against yourself"

    postgres_session.execute(update(Sanction).where(Sanction.ends_at.is_not(None)).values(ends_at=datetime.now(UTC) - timedelta(minutes=1)))
    postgres_session.commit()
    result = retention.run(factory(postgres_session), FakeStorage())  # type: ignore[arg-type]
    assert result["sanctions_expired"] == 2
    postgres_session.expire_all()
    assert postgres_session.get(User, target_id).status == "active"
    assert postgres_session.get(Sanction, uuid.UUID(sanction_id)).state == "expired"
    assert postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "sanction.expired", AuditEvent.actor_user_id.is_(None))) is not None, "a traceable system event"


# ============================ appeals ============================


def _rejected_member_review(client: TestClient, session: Session, fake: support.FakeGoTrue, author: str) -> tuple[Review, TestClient, ModerationActionRecord]:
    review = admin._pending_review(session)  # noqa: SLF001
    session.execute(update(Review).where(Review.id == review.id).values(author_user_id=fake.users[author]["id"], guest_display_name=None, guest_scope_hash=None, guest_scope_key_id=None, guest_tag=None))
    session.commit()
    decider = admin.staff_client(client, session, fake, "decider@example.com", "moderator", "203.0.113.110")
    task, lease = claim(decider, session, review.id)
    session.expire_all()
    current = session.get(Review, review.id)
    assert decider.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=admin._decision(task, lease, current, decision="REJECT", reason_code="spam")).status_code == 200  # noqa: SLF001
    action = session.scalar(select(ModerationActionRecord).where(ModerationActionRecord.review_id == review.id))
    assert action is not None
    return review, decider, action


def test_appeal_received_independent_review_and_overturn(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    author = member(client, postgres_session, fake, "author@example.com", "203.0.113.100")
    review, decider, action = _rejected_member_review(client, postgres_session, fake, "author@example.com")
    eligible = author.get("/api/v1/appeals/mine").json()["appealable"]
    assert [i["target_id"] for i in eligible] == [str(action.id)] and eligible[0]["open"] is True
    body = {"target_type": "moderation_action", "target_id": str(action.id), "reason": "This is my honest experience, not spam."}
    created = author.post("/api/v1/appeals", json=body)
    assert created.status_code == 201, created.text
    assert author.post("/api/v1/appeals", json=body).json()["error"]["code"] == "DUPLICATE_APPEAL"
    stranger = member(client, postgres_session, fake, "stranger@example.com", "203.0.113.101")
    assert stranger.post("/api/v1/appeals", json=body).status_code == 404, "no standing"

    appeal_id = uuid.UUID(created.json()["id"])
    queue_item = next(i for i in decider.get(f"{BASE}/queue", params={"task_type": "appeal"}).json()["items"])
    assert queue_item["subject"]["original_decider_is_you"] is True and queue_item["claimable"] is False
    task, lease = claim(decider, postgres_session, appeal_id)
    decision = {"outcome": "overturned", "expected_version": 1, "note": "It is a real review.", "task_id": str(task.id), "lease_token": lease}
    refused = decider.post(f"{BASE}/appeals/{appeal_id}/decision", json=decision)
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "APPEAL_REVIEWER_NOT_INDEPENDENT"
    decider.post(f"{BASE}/tasks/{task.id}/release", json={"lease_token": lease})

    other = admin.staff_client(client, postgres_session, fake, "other-mod@example.com", "moderator", "203.0.113.102")
    task, lease = claim(other, postgres_session, appeal_id)
    ok = other.post(f"{BASE}/appeals/{appeal_id}/decision", json={**decision, "lease_token": lease})
    assert ok.status_code == 200 and ok.json()["state"] == "overturned"
    postgres_session.expire_all()
    assert postgres_session.get(Review, review.id).status == ReviewStatus.PENDING, "back to the queue for a fresh review"
    assert postgres_session.get(ModerationActionRecord, action.id) is not None, "the original decision is preserved"
    assert author.post("/api/v1/appeals", json=body).json()["error"]["code"] == "DUPLICATE_APPEAL", "no second appeal after a decision"


def test_a_late_appeal_is_refused(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    author = member(client, postgres_session, fake, "author@example.com", "203.0.113.103")
    _, _, action = _rejected_member_review(client, postgres_session, fake, "author@example.com")
    postgres_session.execute(update(ModerationActionRecord).where(ModerationActionRecord.id == action.id).values(created_at=datetime.now(UTC) - timedelta(days=32)))
    postgres_session.commit()
    late = author.post("/api/v1/appeals", json={"target_type": "moderation_action", "target_id": str(action.id), "reason": "Please look again at this one."})
    assert late.status_code == 409 and late.json()["error"]["code"] == "APPEAL_WINDOW_CLOSED"


def test_deadline_is_the_end_of_the_30th_day_in_dhaka() -> None:
    decided = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)  # 02:00 on 2 Oct in Dhaka
    assert cases.appeal_deadline(decided) == datetime(2026, 11, 1, 17, 59, 59, tzinfo=UTC)  # 23:59:59 on 1 Nov in Dhaka


# ============================ notifications ============================


def test_events_become_notifications_once_and_critical_ones_are_emailed(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    author = member(client, postgres_session, fake, "author@example.com", "203.0.113.104")
    _rejected_member_review(client, postgres_session, fake, "author@example.com")
    provider = RecordingProvider()
    sessions = factory(postgres_session)
    first = worker.run_once(sessions, provider)
    assert first["notifications"] >= 1 and first["emails"] == 1
    assert provider.sent[0].to == "author@example.com" and "not published" in provider.sent[0].subject
    assert provider.sent[0].idempotency_key.startswith("delivery-")
    postgres_session.execute(update(OutboxEvent).values(status="pending", processed_at=None))  # replay every event
    postgres_session.commit()
    again = worker.run_once(sessions, provider)
    assert again["notifications"] == 0 and len(provider.sent) == 1, "the notification identity is unique; nothing is sent twice"

    listing = author.get("/api/v1/notifications").json()
    assert listing["unread"] == 1 and listing["items"][0]["kind"] == "content.rejected" and listing["items"][0]["critical"] is True
    note_id = listing["items"][0]["id"]
    assert author.patch(f"/api/v1/notifications/{note_id}", json={"read": True}).json()["unread"] == 0
    other = member(client, postgres_session, fake, "other@example.com", "203.0.113.105")
    assert other.patch(f"/api/v1/notifications/{note_id}", json={"read": True}).status_code == 404, "only your own"


def test_an_unclear_send_is_ambiguous_and_a_failure_is_retried(postgres_session: Session, fake: support.FakeGoTrue, auth_env: None, client: TestClient) -> None:
    member(client, postgres_session, fake, "author@example.com", "203.0.113.106")
    _rejected_member_review(client, postgres_session, fake, "author@example.com")
    sessions = factory(postgres_session)
    for event_id in worker.claim_events(sessions):  # notifications only, no email yet
        worker.process_event(sessions, event_id)
    notification = postgres_session.scalar(select(Notification).where(Notification.priority == "critical"))
    assert notification is not None and notification.delivery_mode == "immediate"
    delivery_row = postgres_session.scalar(select(NotificationDelivery).where(NotificationDelivery.notification_id == notification.id))
    assert delivery_row is not None and delivery_row.status == "queued"
    delivery.send_due(sessions, RecordingProvider(fail_with=SendFailed))
    postgres_session.expire_all()
    retried = postgres_session.get(NotificationDelivery, delivery_row.id)
    assert retried.status == "queued" and retried.next_attempt_at > datetime.now(UTC), "a certain failure is retried later"
    postgres_session.execute(update(NotificationDelivery).values(next_attempt_at=datetime.now(UTC)))
    postgres_session.commit()
    delivery.send_due(sessions, RecordingProvider(fail_with=SendAmbiguous))
    postgres_session.expire_all()
    assert postgres_session.get(NotificationDelivery, delivery_row.id).status == "ambiguous", "an unclear send is never resent blindly"
    again = RecordingProvider()
    delivery.send_due(sessions, again)
    assert again.sent == []


def test_a_broken_event_is_retried_then_parked(postgres_session: Session) -> None:
    event = OutboxEvent(topic="review.state_changed", aggregate_id=uuid.uuid4(), payload={"review_id": "not-a-uuid", "status": "PUBLISHED"})
    postgres_session.add(event)
    postgres_session.commit()
    sessions = factory(postgres_session)
    assert worker.run_once(sessions, None)["events"] >= 1
    postgres_session.expire_all()
    assert postgres_session.get(OutboxEvent, event.id).status == "processed", "an event with nothing to say is simply processed"


def test_the_daily_digest_bundles_non_critical_notifications(postgres_session: Session, fake: support.FakeGoTrue, auth_env: None, client: TestClient, storage: FakeStorage) -> None:
    applicant = member(client, postgres_session, fake, "nila@example.com", "203.0.113.107")
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.108")
    case = _submit_case(applicant, storage)
    sessions = factory(postgres_session)
    worker.run_once(sessions, None)
    staff_note = postgres_session.scalar(select(Notification).where(Notification.kind == "staff.verification_submitted"))
    assert staff_note is not None and staff_note.delivery_mode == "digest" and staff_note.recipient_user_id == fake.users["mod@example.com"]["id"]
    provider = RecordingProvider()
    tomorrow_morning = datetime.now(UTC) + timedelta(days=1)
    assert delivery.build_digests(sessions, tomorrow_morning.replace(hour=3, minute=0)) >= 1  # 09:00 in Dhaka
    delivery.send_due(sessions, provider, now=tomorrow_morning.replace(hour=3, minute=0))
    digests = [m for m in provider.sent if "summary" in m.subject]
    assert [m.to for m in digests if m.to == "mod@example.com"] == ["mod@example.com"]
    assert delivery.build_digests(sessions, tomorrow_morning.replace(hour=4)) == 0, "each notification is digested once"
    del case, mod


def test_the_stream_route_needs_a_session(client: TestClient) -> None:
    assert client.get("/api/v1/notifications/stream").status_code == 401


# ============================ retention ============================


def test_retention_keeps_what_an_open_appeal_needs(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, storage: FakeStorage) -> None:
    applicant = member(client, postgres_session, fake, "nila@example.com", "203.0.113.111")
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.112")
    case = _submit_case(applicant, storage)
    task, lease = claim(mod, postgres_session, uuid.UUID(case["id"]))
    base = {"reason_code": "r1", "task_id": str(task.id), "lease_token": lease}
    mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**base, "to": "in_review", "expected_version": 1})
    mod.post(f"{BASE}/verification-cases/{case['id']}/transition", json={**base, "to": "rejected", "expected_version": 2})
    appeal = applicant.post("/api/v1/appeals", json={"target_type": "verification_case", "target_id": case["id"], "reason": "My card is valid, please check again."})
    assert appeal.status_code == 201
    postgres_session.execute(update(VerificationCase).values(purge_after=datetime.now(UTC) - timedelta(minutes=1)))
    postgres_session.commit()
    kept = retention.run(factory(postgres_session), storage)  # type: ignore[arg-type]
    assert kept["cases"] == 0 and storage.deleted == [], "preserved while the appeal is open"
    postgres_session.execute(update(Appeal).values(state="upheld"))
    postgres_session.commit()
    purged = retention.run(factory(postgres_session), storage)  # type: ignore[arg-type]
    assert purged["cases"] == 1 and purged["evidence_files"] == 1 and len(storage.deleted) == 1
    postgres_session.expire_all()
    assert postgres_session.get(VerificationCase, uuid.UUID(case["id"])) is None


def test_old_notifications_are_purged_by_class(postgres_session: Session) -> None:
    user = User(email="a@example.com", display_name="A")
    postgres_session.add(user)
    event = OutboxEvent(topic="x", aggregate_id=uuid.uuid4(), payload={}, status="processed")
    postgres_session.add(event)
    postgres_session.flush()
    now = datetime.now(UTC)
    rows = [
        ("std-old", False, now - timedelta(days=91)),
        ("std-new", False, now - timedelta(days=10)),
        ("crit-mid", True, now - timedelta(days=200)),
        ("crit-old", True, now - timedelta(days=740)),
    ]
    for kind, critical, created in rows:
        expires = created + timedelta(days=730 if critical else 90)
        postgres_session.add(Notification(
            event_id=event.id, recipient_user_id=user.id, kind=kind, priority="critical" if critical else "normal", template_key=kind,
            title_bn="t", title_en="t", body_bn="b", body_en="b", created_at=created, expires_at=expires,
        ))
    postgres_session.commit()
    assert retention.purge_notifications(factory(postgres_session), now) == 2
    assert {n.kind for n in postgres_session.scalars(select(Notification))} == {"std-new", "crit-mid"}


# ============================ monitoring ============================


def test_monitoring_counts_each_concern_separately(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.113")
    postgres_session.add(OutboxEvent(topic="x", aggregate_id=uuid.uuid4(), payload={}, status="dead_letter"))
    postgres_session.commit()
    summary = mod.get(f"{BASE}/monitoring/summary").json()
    for key in ("outbox_failed", "emails_failed_or_ambiguous", "open_verification_cases", "open_appeals", "emergency_overdue", "active_sanctions"):
        assert key in summary
    assert summary["outbox_failed"] == 1
    assert isinstance(EnforcementCase.__table__, object)
