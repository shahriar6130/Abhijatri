"""Notification system v1.1 (Docs/Notification-Documentation.md): acceptance list (section 14) and
crash cases (section 8)."""

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import test_admin as admin
import test_auth as support
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.models import (
    Appeal,
    AuditEvent,
    ModerationTask,
    Notification,
    NotificationDelivery,
    NotificationDeliveryAttempt,
    NotificationDigest,
    NotificationPreference,
    NotificationProviderEvent,
    NotificationSuppression,
    OutboxEvent,
    User,
)
from app.notify import alerts, delivery, events, messages, registry, worker
from app.notify.providers import Email, RecordingProvider, SendAmbiguous, SendFailed

auth_env = support.auth_env
fake = support.fake
redis_fake = support.redis_fake
_reset_limiter = support._reset_limiter  # noqa: SLF001
pytestmark = pytest.mark.integration
BASE = "/api/v1/admin"


@pytest.fixture()
def client(auth_env: None, postgres_session: Session, fake: support.FakeGoTrue, redis_fake: Any) -> TestClient:
    return support.make_client(postgres_session, fake, redis_fake)


def factory(session: Session) -> sessionmaker[Session]:
    return sessionmaker(bind=session.get_bind(), expire_on_commit=False)


def _user(session: Session, email: str = "nila@example.com", *, verified: bool = True) -> User:
    user = User(email=email, display_name="Nila", email_verified_at=datetime.now(UTC) if verified else None)
    session.add(user)
    session.commit()
    return user


def _emit(session: Session, topic: str, payload: dict[str, Any], **kwargs: Any) -> None:
    events.emit(session, topic, uuid.uuid4(), payload, **kwargs)
    session.commit()


def _process(session: Session) -> int:
    sessions = factory(session)
    return sum(worker.process_event(sessions, event_id) for event_id in worker.claim_events(sessions))


def _rejected_notice(session: Session, user: User) -> Notification:
    """A critical member notice with a queued email (content.rejected)."""
    _emit(session, "review.state_changed", {"decision": "REJECT", "author_id": str(user.id), "destination_id": str(uuid.uuid4())})
    assert _process(session) == 1
    note = session.scalar(select(Notification).where(Notification.recipient_user_id == user.id))
    assert note is not None
    return note


class Provider:
    """A provider whose next answers are scripted: 'ok', 'temporary', 'permanent' or 'ambiguous'."""

    name = "scripted"

    def __init__(self, *answers: str) -> None:
        self.answers = list(answers)
        self.sent: list[Email] = []

    def send(self, email: Email) -> str:
        answer = self.answers.pop(0) if self.answers else "ok"
        if answer == "temporary":
            raise SendFailed("busy", code="http_503")
        if answer == "permanent":
            raise SendFailed("rejected", permanent=True, code="http_422")
        if answer == "ambiguous":
            raise SendAmbiguous("timeout")
        self.sent.append(email)
        return f"msg-{len(self.sent)}"


# ============================ events and the inbox (spec 4, 7.1, 7.2) ============================


def test_a_rolled_back_decision_leaves_no_event(postgres_session: Session) -> None:
    events.emit(postgres_session, "review.state_changed", uuid.uuid4(), {"decision": "PUBLISH"})
    postgres_session.rollback()
    assert postgres_session.scalar(select(OutboxEvent)) is None


def test_events_wait_for_a_stopped_worker_and_are_deduplicated(postgres_session: Session) -> None:
    user = _user(postgres_session)
    payload = {"decision": "PUBLISH", "author_id": str(user.id), "destination_id": str(uuid.uuid4())}
    assert events.emit(postgres_session, "review.state_changed", user.id, payload, dedupe_key="review:1:v2")
    assert not events.emit(postgres_session, "review.state_changed", user.id, payload, dedupe_key="review:1:v2"), "same key, same event"
    postgres_session.commit()
    event = postgres_session.scalar(select(OutboxEvent))
    assert event is not None and event.status == "pending" and event.recipient_policy == {"members": "named_in_payload"}
    assert _process(postgres_session) == 1, "processed whenever the worker runs again"
    note = postgres_session.scalar(select(Notification))
    assert note is not None and note.kind == "content.published" and note.template_key == "content.published"
    assert note.expires_at - note.created_at == timedelta(days=90)
    assert note.link is not None and note.link.startswith("/destinations/")


def test_two_workers_create_one_notification(postgres_session: Session) -> None:
    user = _user(postgres_session)
    _emit(postgres_session, "review.state_changed", {"decision": "REJECT", "author_id": str(user.id)})
    postgres_session.execute(update(OutboxEvent).values(status="processing"))
    postgres_session.commit()
    event_id = postgres_session.scalar(select(OutboxEvent.id))
    assert event_id is not None
    sessions = factory(postgres_session)
    threads = [threading.Thread(target=worker.process_event, args=(sessions, event_id)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    notes = postgres_session.scalars(select(Notification)).all()
    assert len(notes) == 1 and notes[0].expires_at - notes[0].created_at == timedelta(days=730), "critical: 24 months"
    assert len(postgres_session.scalars(select(NotificationDelivery)).all()) == 1


def test_a_failing_event_is_retried_then_dead_lettered(postgres_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _emit(postgres_session, "review.state_changed", {"decision": "PUBLISH"})
    monkeypatch.setattr(worker, "messages_for", lambda session, event: (_ for _ in ()).throw(RuntimeError("boom")))
    sessions = factory(postgres_session)
    for _ in range(worker.MAX_EVENT_ATTEMPTS):
        postgres_session.execute(update(OutboxEvent).values(available_at=datetime.now(UTC) - timedelta(seconds=1)))
        postgres_session.commit()
        for event_id in worker.claim_events(sessions):
            worker.process_event(sessions, event_id)
    postgres_session.expire_all()
    event = postgres_session.scalar(select(OutboxEvent))
    assert event is not None and event.status == "dead_letter" and event.last_error_code == "RuntimeError"


def test_inbox_pages_marks_read_archives_and_counts(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    nila = admin.staff_client(client, postgres_session, fake, "nila@example.com", None, "203.0.113.170", aal="aal1")
    user_id = fake.users["nila@example.com"]["id"]
    for decision in ("PUBLISH", "REJECT", "HIDE"):
        _emit(postgres_session, "review.state_changed", {"decision": decision, "author_id": str(user_id)})
        time.sleep(0.01)
    assert _process(postgres_session) == 3
    first = nila.get("/api/v1/notifications", params={"limit": 2}).json()
    assert len(first["items"]) == 2 and first["next_cursor"] and first["unread"] == 3
    rest = nila.get("/api/v1/notifications", params={"limit": 2, "cursor": first["next_cursor"]}).json()
    assert len(rest["items"]) == 1 and rest["next_cursor"] is None
    assert {i["kind"] for i in first["items"] + rest["items"]} == {"content.published", "content.rejected", "content.hidden"}
    target = first["items"][0]["id"]
    assert nila.patch(f"/api/v1/notifications/{target}", json={"archived": True}).json()["archived"] is True
    assert [i["id"] for i in nila.get("/api/v1/notifications", params={"archived": True}).json()["items"]] == [target]
    assert nila.get("/api/v1/notifications/unread-count").json() == {"unread": 2}
    assert nila.post("/api/v1/notifications/mark-all-read").json() == {"unread": 0}
    assert nila.patch(f"/api/v1/notifications/{target}", json={"priority": "low"}).status_code == 422, "nothing else can change"
    rafi = admin.staff_client(client, postgres_session, fake, "rafi@example.com", None, "203.0.113.171", aal="aal1")
    assert rafi.patch(f"/api/v1/notifications/{target}", json={"read": True}).status_code == 404
    assert client.get("/api/v1/notifications").status_code == 401
    assert nila.get("/api/v1/notifications", params={"cursor": "not-a-cursor"}).status_code == 422


# ============================ email delivery (spec 7.3, 7.4, 8) ============================


def test_retries_follow_the_schedule_then_fail_permanently(postgres_session: Session) -> None:
    user = _user(postgres_session)
    _rejected_notice(postgres_session, user)
    sessions = factory(postgres_session)
    provider = Provider(*["temporary"] * delivery.MAX_ATTEMPTS)
    gaps = []
    for _ in range(delivery.MAX_ATTEMPTS):
        before = datetime.now(UTC)
        delivery.send_due(sessions, provider)
        postgres_session.expire_all()
        row = postgres_session.scalar(select(NotificationDelivery))
        assert row is not None
        if row.status == "queued":
            gaps.append((row.next_attempt_at - before).total_seconds())
            postgres_session.execute(update(NotificationDelivery).values(next_attempt_at=datetime.now(UTC)))
            postgres_session.commit()
    assert row.status == "failed_permanently" and row.attempt_count == delivery.MAX_ATTEMPTS
    for gap, base in zip(gaps, delivery.RETRY_DELAYS, strict=True):
        assert base * 0.85 <= gap <= base * 1.15, "about 1 min, 5 min, 30 min, 2 h with jitter"
    attempts = postgres_session.scalars(select(NotificationDeliveryAttempt).order_by(NotificationDeliveryAttempt.attempt_number)).all()
    assert [a.attempt_number for a in attempts] == [1, 2, 3, 4, 5] and {a.outcome for a in attempts} == {"transient_failure"}


def test_a_permanent_rejection_is_not_retried(postgres_session: Session) -> None:
    _rejected_notice(postgres_session, _user(postgres_session))
    delivery.send_due(factory(postgres_session), Provider("permanent"))
    row = postgres_session.scalar(select(NotificationDelivery))
    assert row is not None and row.status == "failed_permanently" and row.last_error_code == "http_422"


def test_a_crash_after_the_provider_call_is_recorded_as_ambiguous(postgres_session: Session) -> None:
    _rejected_notice(postgres_session, _user(postgres_session))
    # The worker marked the row as sending, called the provider, then died before recording anything.
    postgres_session.execute(
        update(NotificationDelivery).values(status="sending", attempt_count=1, lease_until=datetime.now(UTC) - timedelta(seconds=1))
    )
    postgres_session.commit()
    provider = Provider()
    delivery.send_due(factory(postgres_session), provider)
    postgres_session.expire_all()
    row = postgres_session.scalar(select(NotificationDelivery))
    assert row is not None and row.status == "ambiguous" and provider.sent == [], "never resent blindly"
    attempt = postgres_session.scalar(select(NotificationDeliveryAttempt))
    assert attempt is not None and attempt.outcome == "ambiguous" and attempt.error_code == "worker_lost"


def test_the_current_verified_address_is_used_at_send_time(postgres_session: Session) -> None:
    user = _user(postgres_session, "old@example.com")
    _rejected_notice(postgres_session, user)
    user.email = "new@example.com"  # changed and verified before the send
    postgres_session.commit()
    provider = Provider()
    delivery.send_due(factory(postgres_session), provider)
    assert [m.to for m in provider.sent] == ["new@example.com"]
    unverified = _user(postgres_session, "unverified@example.com", verified=False)
    _rejected_notice(postgres_session, unverified)
    delivery.send_due(factory(postgres_session), provider)
    skipped = postgres_session.scalar(select(NotificationDelivery).where(NotificationDelivery.status == "skipped"))
    assert skipped is not None and skipped.last_error_code == "no_verified_address" and len(provider.sent) == 1
    assert postgres_session.scalar(select(Notification).where(Notification.recipient_user_id == unverified.id)), "the in-app notice stays"


def test_suppressed_addresses_are_skipped_and_suppressions_are_audited(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    boss = admin.staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.172")
    added = boss.post(f"{BASE}/notification-suppressions", json={"email": "Nila@Example.com ", "reason_code": "owner_request"})
    assert added.status_code == 201 and "nila" not in added.text.lower(), "the address itself is never returned"
    assert boss.post(f"{BASE}/notification-suppressions", json={"email": "nila@example.com", "reason_code": "again"}).status_code == 422
    _rejected_notice(postgres_session, _user(postgres_session, "nila@example.com"))
    provider = Provider()
    delivery.send_due(factory(postgres_session), provider)
    row = postgres_session.scalar(select(NotificationDelivery))
    assert provider.sent == [] and row is not None and row.status == "skipped" and row.last_error_code == "suppressed"
    removed = boss.request("DELETE", f"{BASE}/notification-suppressions/{added.json()['id']}", json={"removal_reason": "asked to receive mail again"})
    assert removed.status_code == 200 and removed.json()["removed_at"]
    actions = {e.action for e in postgres_session.scalars(select(AuditEvent))}
    assert {"notification.suppression_added", "notification.suppression_removed"} <= actions


def test_superadmins_retry_only_retryable_deliveries_and_it_is_audited(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    _rejected_notice(postgres_session, _user(postgres_session))
    delivery.send_due(factory(postgres_session), Provider("ambiguous"))
    row = postgres_session.scalar(select(NotificationDelivery))
    assert row is not None and row.status == "ambiguous"
    boss = admin.staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.173")
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.174")
    assert mod.get(f"{BASE}/notification-deliveries").status_code == 403, "superadmin only"
    listing = boss.get(f"{BASE}/notification-deliveries", params={"status": "ambiguous"}).json()
    assert listing["items"][0]["id"] == str(row.id) and "@" not in json.dumps(listing), "redacted"
    detail = boss.get(f"{BASE}/notification-deliveries/{row.id}").json()
    assert [a["outcome"] for a in detail["attempts"]] == ["ambiguous"]
    retried = boss.post(f"{BASE}/notification-deliveries/{row.id}/retry", json={"reason": "provider shows it was not sent"})
    assert retried.status_code == 200 and retried.json()["status"] == "queued"
    assert boss.post(f"{BASE}/notification-deliveries/{row.id}/retry", json={"reason": "again please"}).status_code == 422
    assert postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "notification.delivery_retried")) is not None
    outbox = boss.get(f"{BASE}/notification-outbox").json()
    assert outbox["counts"].get("processed", 0) >= 1


# ============================ preferences and the digest (spec 6.5, 7.8, 7.10) ============================


def test_preferences_choose_standard_email_but_never_delay_critical(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    nila = admin.staff_client(client, postgres_session, fake, "nila@example.com", None, "203.0.113.175", aal="aal1")
    user_id = fake.users["nila@example.com"]["id"]
    assert nila.get("/api/v1/notification-preferences").json()["standard_email_mode"] == "digest"
    bad = nila.put("/api/v1/notification-preferences", json={"standard_email_mode": "digest", "digest_timezone": "Mars/Base", "digest_local_time": "08:00"})
    assert bad.status_code == 422
    assert nila.put("/api/v1/notification-preferences", json={"standard_email_mode": "off", "digest_timezone": "Asia/Dhaka", "digest_local_time": "07:30"}).status_code == 200
    _emit(postgres_session, "review.state_changed", {"decision": "PUBLISH", "author_id": str(user_id)})
    _emit(postgres_session, "review.state_changed", {"decision": "REJECT", "author_id": str(user_id)})
    _process(postgres_session)
    modes = {n.kind: n.delivery_mode for n in postgres_session.scalars(select(Notification))}
    assert modes == {"content.published": "none", "content.rejected": "immediate"}, "off silences standard email only"
    nila.put("/api/v1/notification-preferences", json={"standard_email_mode": "immediate", "digest_timezone": "Asia/Dhaka", "digest_local_time": "07:30"})
    _emit(postgres_session, "review.state_changed", {"decision": "RESTORE", "author_id": str(user_id)})
    _process(postgres_session)
    restored = postgres_session.scalar(select(Notification).where(Notification.kind == "content.restored"))
    assert restored is not None and restored.delivery_mode == "immediate"


def test_the_digest_is_sent_once_at_the_local_time(postgres_session: Session) -> None:
    user = _user(postgres_session)
    postgres_session.add(NotificationPreference(recipient_user_id=user.id, standard_email_mode="digest", digest_timezone="Asia/Dhaka"))
    postgres_session.commit()
    for decision in ("PUBLISH", "RESTORE", "REJECT"):
        _emit(postgres_session, "review.state_changed", {"decision": decision, "author_id": str(user.id)})
    _process(postgres_session)
    sessions = factory(postgres_session)
    day = datetime.now(UTC).date() + timedelta(days=1)
    early = datetime(day.year, day.month, day.day, 1, 0, tzinfo=UTC)  # 07:00 in Dhaka
    assert delivery.build_digests(sessions, early) == 0, "not before 08:00 local time"
    on_time = early + timedelta(hours=2)
    assert delivery.build_digests(sessions, on_time) == 1
    assert delivery.build_digests(sessions, on_time + timedelta(minutes=5)) == 0, "one digest per recipient and day"
    provider = Provider()
    delivery.send_due(sessions, provider, now=on_time)
    digests = [m for m in provider.sent if "summary" in m.subject]
    assert len(digests) == 1 and "(2)" in digests[0].subject, "the critical rejection was emailed on its own, not batched"
    assert postgres_session.scalar(select(NotificationDigest)).status == "accepted"  # type: ignore[union-attr]
    assert "/account/notifications" in digests[0].text


# ============================ provider webhooks (spec 7.5, 9) ============================


SECRET = base64.b64encode(b"webhook-secret-for-tests-0123456789").decode()


def _svix(body: bytes, event_id: str, stamp: int | None = None) -> dict[str, str]:
    moment = str(stamp or int(time.time()))
    signature = base64.b64encode(hmac.new(base64.b64decode(SECRET), f"{event_id}.{moment}.".encode() + body, hashlib.sha256).digest()).decode()
    return {"svix-id": event_id, "svix-timestamp": moment, "svix-signature": f"v1,{signature}", "content-type": "application/json"}


def test_resend_webhooks_are_verified_and_deduplicated(client: TestClient, postgres_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.post("/api/v1/webhooks/notifications/resend", content=b"{}", headers={"content-type": "application/json"}).status_code == 404, "not configured"
    monkeypatch.setenv("RESEND_WEBHOOK_SECRET", f"whsec_{SECRET}")
    get_settings.cache_clear()
    _rejected_notice(postgres_session, _user(postgres_session))
    delivery.send_due(factory(postgres_session), Provider())
    row = postgres_session.scalar(select(NotificationDelivery))
    assert row is not None and row.provider_message_id == "msg-1"
    body = json.dumps({"type": "email.bounced", "created_at": "now", "data": {"email_id": "msg-1", "to": ["nila@example.com"]}}).encode()
    url = "/api/v1/webhooks/notifications/resend"
    assert client.post(url, content=body, headers=_svix(body, "evt_1")).json() == {"status": "processed"}
    assert client.post(url, content=body, headers=_svix(body, "evt_1")).json() == {"status": "duplicate"}
    postgres_session.expire_all()
    assert postgres_session.get(NotificationDelivery, row.id).status == "bounced"  # type: ignore[union-attr]
    assert postgres_session.scalar(select(NotificationSuppression)) is not None, "a hard bounce suppresses the address"
    stored = postgres_session.scalar(select(NotificationProviderEvent).where(NotificationProviderEvent.provider_event_id == "evt_1"))
    assert stored is not None and "nila" not in json.dumps(stored.redacted_payload), "no address is kept"
    forged = _svix(body, "evt_2")
    forged["svix-signature"] = "v1,AAAA"
    assert client.post(url, content=body, headers=forged).status_code == 403
    assert client.post(url, content=body, headers=_svix(body, "evt_3", int(time.time()) - 3600)).status_code == 403, "replay window"
    rejected = postgres_session.scalars(select(NotificationProviderEvent).where(NotificationProviderEvent.event_type == "signature_failure")).all()
    assert len(rejected) == 2


def test_brevo_webhooks_need_the_token(client: TestClient, postgres_session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BREVO_WEBHOOK_TOKEN", "brevo-token-for-tests")
    get_settings.cache_clear()
    _rejected_notice(postgres_session, _user(postgres_session))
    delivery.send_due(factory(postgres_session), Provider())
    body = json.dumps({"event": "delivered", "message-id": "<msg-1>", "ts_event": int(time.time())}).encode()
    url = "/api/v1/webhooks/notifications/brevo"
    assert client.post(url, content=body, headers={"content-type": "application/json"}).status_code == 403
    ok = client.post(url, content=body, headers={"content-type": "application/json", "authorization": "Bearer brevo-token-for-tests"})
    assert ok.json() == {"status": "processed"}
    assert postgres_session.scalar(select(NotificationDelivery.status)) == "delivered"
    assert client.post(url, content=b"x", headers={"content-type": "text/plain"}).status_code == 422


# ============================ recipients and roles (spec 5, 6.4) ============================


def _change_role(boss: TestClient, user_id: uuid.UUID, role: str | None) -> None:
    response = boss.post(f"{BASE}/staff/{user_id}/role", json={"role": role, "reason": "staffing change"})
    assert response.status_code == 200, response.text


def test_a_revoked_moderator_is_told_but_loses_staff_notices(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    boss = admin.staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.176")
    other_boss = admin.staff_client(client, postgres_session, fake, "boss2@example.com", "superadmin", "203.0.113.177")
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.178")
    mod_id = fake.users["mod@example.com"]["id"]
    _emit(postgres_session, "verification.submitted", {"applicant_id": None}, staff_roles=("moderator", "superadmin"))
    _process(postgres_session)
    assert [i["kind"] for i in mod.get("/api/v1/notifications").json()["items"]] == ["staff.verification_submitted"]
    _change_role(boss, mod_id, None)
    _process(postgres_session)
    items = mod.get("/api/v1/notifications").json()["items"]
    assert [i["kind"] for i in items] == ["staff.role_revoked"], "the revoked person is told; old staff notices are hidden"
    assert [i["kind"] for i in other_boss.get("/api/v1/notifications").json()["items"] if i["kind"] == "staff.role_changed"] == ["staff.role_changed"]
    assert all(i["kind"] != "staff.role_changed" for i in boss.get("/api/v1/notifications").json()["items"]), "the actor is not told about their own change"


def test_staff_captured_at_event_time_are_rechecked_before_delivery(postgres_session: Session, client: TestClient, fake: support.FakeGoTrue) -> None:
    admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.179")
    _emit(postgres_session, "verification.submitted", {}, staff_roles=("moderator",))
    event = postgres_session.scalar(select(OutboxEvent))
    assert event is not None and event.payload["staff_recipients"] == [str(fake.users["mod@example.com"]["id"])]
    assert event.recipient_policy["staff"] == "captured_at_event"
    from app.models import UserRole  # noqa: PLC0415

    postgres_session.execute(update(UserRole).values(revoked_at=datetime.now(UTC)))  # the role ends before the worker runs
    postgres_session.commit()
    assert _process(postgres_session) == 0


def test_assignment_notifies_assignee_and_previous_assignee(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    boss = admin.staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.180")
    one = admin.staff_client(client, postgres_session, fake, "one@example.com", "moderator", "203.0.113.181")
    two = admin.staff_client(client, postgres_session, fake, "two@example.com", "moderator", "203.0.113.182")
    task = admin._task_for(postgres_session, admin._pending_review(postgres_session))  # noqa: SLF001
    assert one.post(f"{BASE}/tasks/{task.id}/assign", json={"user_id": None}).status_code == 403, "superadmins assign"
    assert boss.post(f"{BASE}/tasks/{task.id}/assign", json={"user_id": str(fake.users["one@example.com"]["id"])}).status_code == 200
    assert boss.post(f"{BASE}/tasks/{task.id}/assign", json={"user_id": str(fake.users["two@example.com"]["id"])}).status_code == 200
    _process(postgres_session)
    assert [i["kind"] for i in one.get("/api/v1/notifications").json()["items"]] == ["moderation.task_unassigned", "moderation.task_assigned"]
    assert [i["kind"] for i in two.get("/api/v1/notifications").json()["items"]] == ["moderation.task_assigned"]
    stranger = admin.staff_client(client, postgres_session, fake, "member@example.com", None, "203.0.113.183", aal="aal1")
    assert boss.post(f"{BASE}/tasks/{task.id}/assign", json={"user_id": str(fake.users["member@example.com"]["id"])}).status_code == 422
    del stranger


# ============================ templates and rules (spec 7.6, 7.7) ============================


def test_template_versions_are_validated_activated_and_audited(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    boss = admin.staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.184")
    worker.sync_defaults(factory(postgres_session))
    url = f"{BASE}/notification-templates/appeal.received/versions"
    bad = boss.post(url, json={"channel": "in_app", "locale": "en", "title_template": "Appeal", "body_template": "Ref {reference} for {email}"})
    assert bad.status_code == 422 and bad.json()["error"]["field_errors"][0]["code"] == "UNKNOWN_VARIABLE"
    sneaky = boss.post(url, json={"channel": "in_app", "locale": "en", "title_template": "x", "body_template": "{reference.__class__}"})
    assert sneaky.status_code == 422
    draft = boss.post(url, json={"channel": "in_app", "locale": "en", "title_template": "We got your appeal", "body_template": "Reference {reference}, decide by {deadline}."})
    assert draft.status_code == 201 and draft.json()["version"] == 2 and draft.json()["status"] == "draft"
    activated = boss.post(f"{url}/2/activate", json={"channel": "in_app", "locale": "en"})
    assert activated.status_code == 200 and activated.json()["status"] == "active"
    versions = {(v["version"], v["status"]) for v in boss.get(url).json()["items"] if v["locale"] == "en"}
    assert versions == {(1, "retired"), (2, "active")}
    assert boss.post(f"{url}/1/activate", json={"channel": "in_app", "locale": "en"}).status_code == 422, "a retired version stays retired"

    user = _user(postgres_session, "appellant@example.com")
    appeal_id = uuid.uuid4()
    _emit(postgres_session, "appeal.received", {"appellant_id": str(user.id), "appeal_id": str(appeal_id), "deadline_at": "2026-11-30T17:59:59+00:00"})
    _process(postgres_session)
    note = postgres_session.scalar(select(Notification).where(Notification.recipient_user_id == user.id))
    assert note is not None and note.title_en == "We got your appeal" and note.template_version == 2
    assert note.body_en == f"Reference {str(appeal_id)[:8]}, decide by 2026-11-30." and note.appeal_id == appeal_id
    actions = {e.action for e in postgres_session.scalars(select(AuditEvent))}
    assert {"notification.template_drafted", "notification.template_activated"} <= actions
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.185")
    assert mod.get(f"{BASE}/notification-templates").status_code == 403


def test_a_rule_can_turn_email_off_but_not_invent_recipients(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    boss = admin.staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.186")
    changed = boss.patch(f"{BASE}/notification-rules/content.rejected", json={"email": False})
    assert changed.status_code == 200 and changed.json()["email"] is False
    assert boss.patch(f"{BASE}/notification-rules/made.up", json={"email": False}).status_code == 404
    _rejected_notice(postgres_session, _user(postgres_session))
    assert postgres_session.scalar(select(NotificationDelivery)) is None
    assert postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "notification.rule_changed")) is not None


def test_the_catalogue_is_consistent() -> None:
    assert {r.resolver for r in registry.RULES} <= set(registry.RESOLVERS)
    for rule in registry.RULES:
        template = registry.TEMPLATES[rule.template_key]
        for text in (template.title_bn, template.title_en, template.body_bn, template.body_en):
            assert messages.template_variables(text) <= set(template.variables), rule.template_key
    spec_member_events = {
        "verification.submitted", "verification.clarification_requested", "verification.approved", "verification.rejected",
        "content.published", "content.hidden", "content.rejected", "content.taken_down", "content.restored", "account.suspended",
        "account.suspension_lifted", "account.removed", "appeal.submitted", "appeal.received", "appeal.decided", "security.account_action_required",
        "moderation.task_assigned", "moderation.task_unassigned", "moderation.task_lease_expiring", "moderation.queue_overdue",
        "moderation.escalated", "moderation.appeal_assigned", "moderation.security_anomaly", "staff.role_granted", "staff.role_revoked",
        "moderation.emergency_takedown", "moderation.escalation_required", "notification.delivery_failure_threshold_reached",
        "notification.outbox_backlog_threshold_reached", "notification.provider_webhook_anomaly",
    }
    assert spec_member_events <= {r.template_key for r in registry.RULES}, "every catalogued event of spec 3 has a rule"


# ============================ alerts (spec 8, 11) ============================


def test_scanners_alert_once_per_window(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    boss = admin.staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.187")
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.188")
    task = admin._task_for(postgres_session, admin._pending_review(postgres_session))  # noqa: SLF001
    admin._claim(mod, task)  # noqa: SLF001
    postgres_session.execute(update(ModerationTask).values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=30), created_at=datetime.now(UTC) - timedelta(days=2)))
    postgres_session.commit()
    for index in range(get_settings().notify_failure_alert_per_hour):
        _rejected_notice(postgres_session, _user(postgres_session, f"failing{index}@example.com"))
    postgres_session.execute(update(NotificationDelivery).values(status="failed_permanently", updated_at=datetime.now(UTC)))
    postgres_session.commit()
    sessions = factory(postgres_session)
    first = alerts.scan(sessions)
    second = alerts.scan(sessions)
    assert first["lease_expiring"] == 1 and first["queue_overdue"] == 1 and first["delivery_failures"] == 1
    assert second == dict.fromkeys(second, 0), "one alert per window"
    _process(postgres_session)
    kinds = [i["kind"] for i in mod.get("/api/v1/notifications").json()["items"]]
    assert "moderation.task_lease_expiring" in kinds and "moderation.queue_overdue" in kinds
    boss_kinds = [i["kind"] for i in boss.get("/api/v1/notifications").json()["items"]]
    assert boss_kinds.count("notification.delivery_failure_threshold_reached") == 1


def test_repeated_denials_alert_superadmins(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    boss = admin.staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.189")
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.190")
    task = admin._task_for(postgres_session, admin._pending_review(postgres_session))  # noqa: SLF001
    for _ in range(alerts.DENIAL_THRESHOLD + 1):
        assert mod.post(f"{BASE}/tasks/{task.id}/assign", json={"user_id": None}).status_code == 403
    _process(postgres_session)
    kinds = [i["kind"] for i in boss.get("/api/v1/notifications").json()["items"]]
    assert kinds.count("moderation.security_anomaly") == 1


# ============================ retention, security notice, logs (spec 6.2, 10) ============================


def test_expired_notifications_linked_to_an_open_appeal_are_kept(postgres_session: Session) -> None:
    from app.jobs import retention  # noqa: PLC0415
    from app.models import VerificationCase  # noqa: PLC0415

    user = _user(postgres_session)
    case = VerificationCase(applicant_user_id=user.id, state="rejected")
    postgres_session.add(case)
    postgres_session.flush()
    appeal = Appeal(appellant_user_id=user.id, verification_case_id=case.id, reason="please look again", state="received", deadline_at=datetime.now(UTC) + timedelta(days=30))
    event = OutboxEvent(topic="x", aggregate_id=uuid.uuid4(), payload={}, status="processed")
    postgres_session.add_all([appeal, event])
    postgres_session.flush()
    past = datetime.now(UTC) - timedelta(days=1)
    common = {"event_id": event.id, "recipient_user_id": user.id, "title_bn": "t", "title_en": "t", "body_bn": "b", "body_en": "b", "expires_at": past}
    postgres_session.add(Notification(kind="kept", template_key="kept", appeal_id=appeal.id, **common))
    postgres_session.add(Notification(kind="gone", template_key="gone", **common))
    postgres_session.add(Notification(kind="fresh", template_key="fresh", **{**common, "expires_at": datetime.now(UTC) + timedelta(days=1)}))
    postgres_session.commit()
    sessions = factory(postgres_session)
    assert retention.purge_notifications(sessions, datetime.now(UTC)) == 1
    assert {n.kind for n in postgres_session.scalars(select(Notification))} == {"kept", "fresh"}
    postgres_session.execute(update(Appeal).values(state="upheld"))
    postgres_session.commit()
    assert retention.purge_notifications(sessions, datetime.now(UTC)) == 1, "deleted once the appeal is closed"
    old = OutboxEvent(topic="x", aggregate_id=uuid.uuid4(), payload={}, status="processed", created_at=datetime.now(UTC) - timedelta(days=31))
    postgres_session.add(old)
    postgres_session.commit()
    assert retention.purge_outbox(sessions, datetime.now(UTC)) == 1, "processed events go after 30 days unless still referenced"


def test_a_password_change_sends_a_security_notice(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    user_id = admin._make_user(postgres_session, fake, "nila@example.com")  # noqa: SLF001
    fake.verify_tokens["recovery-hash"] = ("nila@example.com", "recovery")
    browser = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.191"})
    changed = browser.post("/api/v1/auth/password-reset/confirm", json={"token_hash": "recovery-hash", "new_password": "An0therStrongPass"})
    assert changed.status_code == 200, changed.text
    _process(postgres_session)
    note = postgres_session.scalar(select(Notification).where(Notification.recipient_user_id == user_id))
    assert note is not None and note.kind == "security.account_action_required" and note.priority == "critical"


def test_logs_never_contain_addresses_or_bodies(postgres_session: Session, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    _rejected_notice(postgres_session, _user(postgres_session, "private.person@example.com"))
    delivery.send_due(factory(postgres_session), Provider("temporary"))
    delivery.send_due(factory(postgres_session), RecordingProvider(fail_with=SendAmbiguous))
    assert "private.person" not in caplog.text and "did not meet the policy" not in caplog.text
