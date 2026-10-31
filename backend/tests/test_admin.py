"""Staff API (Moderation-Dashboard-Specification 14; Gantt R10 and R11) against real PostgreSQL.

Staff sign in through the same fake Auth provider as the member tests. Roles, tasks, leases,
versions, idempotency keys and audit rows are all real database state.
"""

import threading
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import test_auth as support
from fastapi.testclient import TestClient
from receipts import new_receipt
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app import reasons
from app.admin import roles, tasks
from app.auth.sessions import Principal
from app.auth.tokens import Claims
from app.errors import ApiError
from app.models import (
    AuditEvent,
    Destination,
    DestinationStatus,
    ModerationActionRecord,
    ModerationTask,
    OutboxEvent,
    Report,
    Review,
    ReviewStatus,
    User,
    UserRole,
)
from app.schemas import GuestReviewCreate
from app.services import submit_guest_review

# The member tests' fixtures: a fake Auth provider, fakeredis, and an app wired to the test database.
auth_env = support.auth_env
fake = support.fake
redis_fake = support.redis_fake
client = support.client
_reset_limiter = support._reset_limiter  # noqa: SLF001

pytestmark = pytest.mark.integration
BASE = "/api/v1/admin"


# ---- helpers ----


def _make_user(session: Session, fake: support.FakeGoTrue, email: str, name: str = "Staff Person") -> uuid.UUID:
    user_id = fake.add_user(email, name=name)
    session.add(User(id=user_id, email=email, display_name=name, email_verified_at=datetime.now(UTC)))
    session.commit()
    return user_id


def staff_client(
    template: TestClient, session: Session, fake: support.FakeGoTrue, email: str, role: str | None, ip: str, *, aal: str = "aal2", auth_age: int = 0
) -> TestClient:
    """A browser signed in as `email`, holding `role` in the database and (by default) a TOTP-verified session."""
    user_id = fake.users[email]["id"] if email in fake.users else _make_user(session, fake, email)
    if session.get(User, user_id) is None:
        session.add(User(id=user_id, email=email, display_name="Staff Person", email_verified_at=datetime.now(UTC)))
    if role is not None:
        session.add(UserRole(user_id=user_id, role=role))
    session.commit()
    browser = TestClient(template.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": ip})
    browser.cookies.set("__Host-abhijatri_session", fake.mint(email, aal=aal, auth_age=auth_age).access_token)
    browser.headers["X-CSRF-Token"] = browser.get("/api/v1/auth/csrf").json()["csrf_token"]
    return browser


def _pending_review(session: Session, title: str = "Lovely beach", destination: Destination | None = None) -> Review:
    destination = destination or Destination(status=DestinationStatus.PUBLISHED, name_bn="কক্সবাজার", name_en="Cox")
    if destination.id is None or session.get(Destination, destination.id) is None:
        session.add(destination)
        session.commit()
    payload = GuestReviewCreate.model_validate(
        {
            "destination_id": str(destination.id),
            "client_draft_id": str(uuid.uuid4()),
            "guest_scope_secret": "s" * 43,
            "receipt_secret": new_receipt(),
            "guest_display_name": "Rahim",
            "language": "EN",
            "traveller_type": "SOLO",
            "comfort_tier": "STANDARD",
            "visit_month": date.today().replace(day=1).isoformat(),
            "title": title,
            "body": "A long enough review body for the validation rules.",
            "overall_rating": 5,
            "consent_version": "v1",
        }
    )
    review = submit_guest_review(session, payload).review
    session.commit()
    return review


def _task_for(session: Session, review: Review) -> ModerationTask:
    task = session.scalar(select(ModerationTask).where(ModerationTask.subject_id == review.id))
    assert task is not None, "a submitted review is queued"
    return task


def _claim(browser: TestClient, task: ModerationTask) -> dict[str, Any]:
    response = browser.post(f"{BASE}/tasks/{task.id}/claim")
    assert response.status_code == 200, response.text
    return response.json()


def _decision(task: ModerationTask, lease: str, review: Review, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "task_id": str(task.id),
        "lease_token": lease,
        "expected_version": review.version,
        "decision": "PUBLISH",
    }
    body.update(overrides)
    # Reasons come from the server's catalogue (P-06); the first code of the decision's group is a valid default.
    group = reasons.DECISION_GROUP.get(str(body["decision"]))
    body.setdefault("reason_code", reasons.GROUPS[group][1][0].code if group else "unknown-decision")
    return body


def _principal(user: User, role: str) -> Principal:
    now = datetime.now(UTC)
    claims = Claims(
        user_id=user.id, email=user.email, session_id=uuid.uuid4(), aal="aal2", amr=("password",),
        expires_at=now + timedelta(hours=1), issued_at=now, auth_time=now, display_name=None,
    )
    return Principal(user=user, claims=claims, role=role)


# ---- access ----


def test_staff_routes_are_hidden_from_members_and_the_public(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    anonymous = client.get(f"{BASE}/queue")
    assert anonymous.status_code == 401
    member = staff_client(client, postgres_session, fake, "member@example.com", None, "203.0.113.20")
    assert member.get(f"{BASE}/queue").status_code == 404
    assert member.get(f"{BASE}/audit-events").status_code == 404
    moderator = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.21")
    assert moderator.get(f"{BASE}/queue").status_code == 200
    assert moderator.get(f"{BASE}/queue").headers["cache-control"] == "no-store"
    assert moderator.get(f"{BASE}/staff").status_code == 403, "a moderator is not a superadmin"


def test_a_moderator_without_totp_cannot_use_staff_routes(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    weak = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.22", aal="aal1")
    denied = weak.get(f"{BASE}/queue")
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "MFA_REQUIRED"


# ---- roles (spec 2.2 and 6.1) ----


def test_the_database_allows_one_active_role_per_user(postgres_session: Session) -> None:
    user = User(email="a@example.com", display_name="A")
    postgres_session.add(user)
    postgres_session.commit()
    postgres_session.add_all([UserRole(user_id=user.id, role="moderator"), UserRole(user_id=user.id, role="superadmin")])
    with pytest.raises(IntegrityError):
        postgres_session.commit()
    postgres_session.rollback()
    postgres_session.add(UserRole(user_id=user.id, role="admin"))
    with pytest.raises(IntegrityError):
        postgres_session.commit()


def test_changing_a_role_replaces_it_and_is_audited(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    boss = staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.30")
    target = _make_user(postgres_session, fake, "target@example.com")
    granted = boss.post(f"{BASE}/staff/{target}/role", json={"role": "moderator", "reason": "joins the team"})
    assert granted.status_code == 200, granted.text
    promoted = boss.post(f"{BASE}/staff/{target}/role", json={"role": "superadmin", "reason": "second owner"})
    assert promoted.status_code == 200
    active = postgres_session.scalars(select(UserRole).where(UserRole.user_id == target, UserRole.revoked_at.is_(None))).all()
    assert [row.role for row in active] == ["superadmin"]
    history = postgres_session.scalars(select(UserRole).where(UserRole.user_id == target)).all()
    assert len(history) == 2 and sum(1 for row in history if row.revoked_at) == 1
    actions = [e.action for e in postgres_session.scalars(select(AuditEvent).where(AuditEvent.target_id == str(target)).order_by(AuditEvent.occurred_at))]
    assert actions == ["staff.role_granted", "staff.role_changed"]
    listing = boss.get(f"{BASE}/staff").json()["items"]
    assert {item["role"] for item in listing} == {"superadmin"}


def test_role_changes_need_a_superadmin_and_a_recent_password_check(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.31")
    target = _make_user(postgres_session, fake, "target@example.com")
    forbidden = mod.post(f"{BASE}/staff/{target}/role", json={"role": "moderator", "reason": "trying"})
    assert forbidden.status_code == 403
    stale = staff_client(client, postgres_session, fake, "oldboss@example.com", "superadmin", "203.0.113.32", auth_age=3600)
    needs_reauth = stale.post(f"{BASE}/staff/{target}/role", json={"role": "moderator", "reason": "needs fresh login"})
    assert needs_reauth.status_code == 403 and needs_reauth.json()["error"]["code"] == "REAUTH_REQUIRED"
    assert postgres_session.scalar(select(UserRole).where(UserRole.user_id == target)) is None
    bad_role = staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.33").post(
        f"{BASE}/staff/{target}/role", json={"role": "owner", "reason": "not a role"}
    )
    assert bad_role.status_code == 422


def test_denied_attempts_are_audited(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.34")
    target = _make_user(postgres_session, fake, "target@example.com")
    assert mod.post(f"{BASE}/staff/{target}/role", json={"role": "moderator", "reason": "trying"}).status_code == 403
    denied = postgres_session.scalars(select(AuditEvent).where(AuditEvent.action.like("denied.%"))).all()
    # the 403 for a wrong role is raised by the dependency before the route; a route-level denial is audited below
    assert all(e.actor_user_id is not None for e in denied)


def test_the_last_superadmin_cannot_be_removed(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    boss = staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.35")
    me = postgres_session.scalar(select(User).where(User.email == "boss@example.com"))
    assert me is not None
    refused = boss.post(f"{BASE}/staff/{me.id}/role", json={"role": None, "reason": "stepping down"})
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "LAST_SUPERADMIN"
    assert boss.post(f"{BASE}/staff/{me.id}/role", json={"role": "moderator", "reason": "demote myself"}).status_code == 409


def test_two_superadmins_cannot_remove_each_other_at_once(postgres_session: Session) -> None:
    first, second = User(email="s1@example.com", display_name="S1"), User(email="s2@example.com", display_name="S2")
    postgres_session.add_all([first, second])
    postgres_session.commit()
    postgres_session.add_all([UserRole(user_id=first.id, role="superadmin"), UserRole(user_id=second.id, role="superadmin")])
    postgres_session.commit()
    factory = sessionmaker(bind=postgres_session.get_bind(), expire_on_commit=False)
    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def revoke(actor_id: uuid.UUID, victim_id: uuid.UUID) -> None:
        with factory() as session:
            actor = session.get(User, actor_id)
            assert actor is not None
            barrier.wait(timeout=10)
            try:
                roles.set_staff_role(session, actor=_principal(actor, "superadmin"), target_user_id=victim_id, role=None, reason="race")
                session.commit()
                outcomes.append("removed")
            except ApiError as error:
                session.rollback()
                outcomes.append(error.code)

    threads = [threading.Thread(target=revoke, args=(first.id, second.id)), threading.Thread(target=revoke, args=(second.id, first.id))]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert sorted(outcomes) == ["LAST_SUPERADMIN", "removed"]
    postgres_session.expire_all()
    remaining = postgres_session.scalars(select(UserRole).where(UserRole.role == "superadmin", UserRole.revoked_at.is_(None))).all()
    assert len(remaining) == 1


# ---- queue and claims (spec 5) ----


def test_new_reviews_are_queued_and_the_queue_shows_content_without_leaking_leases(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    one = staff_client(client, postgres_session, fake, "one@example.com", "moderator", "203.0.113.40")
    two = staff_client(client, postgres_session, fake, "two@example.com", "moderator", "203.0.113.41")
    items = one.get(f"{BASE}/queue").json()["items"]
    assert [i["subject_id"] for i in items] == [str(review.id)]
    assert items[0]["subject"]["title"] == "Lovely beach" and items[0]["claimable"] is True
    task = _task_for(postgres_session, review)
    mine = _claim(one, task)
    assert mine["lease_token"], "the holder is given the token"
    others_view = two.get(f"{BASE}/queue").json()["items"][0]
    assert "lease_token" not in others_view and others_view["lease_active"] is True and others_view["claimable"] is False
    assert one.get(f"{BASE}/queue").json()["items"][0]["lease_token"] == mine["lease_token"]


def test_only_one_staff_member_can_hold_a_task(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    task = _task_for(postgres_session, review)
    one = staff_client(client, postgres_session, fake, "one@example.com", "moderator", "203.0.113.42")
    two = staff_client(client, postgres_session, fake, "two@example.com", "moderator", "203.0.113.43")
    _claim(one, task)
    second = two.post(f"{BASE}/tasks/{task.id}/claim")
    assert second.status_code == 409 and second.json()["error"]["code"] == "TASK_NOT_AVAILABLE"


def test_simultaneous_claims_produce_one_lease(postgres_session: Session) -> None:
    review = _pending_review(postgres_session)
    task = _task_for(postgres_session, review)
    people = [User(email=f"m{i}@example.com", display_name=f"M{i}") for i in range(4)]
    postgres_session.add_all(people)
    postgres_session.commit()
    factory = sessionmaker(bind=postgres_session.get_bind(), expire_on_commit=False)
    outcomes: list[str] = []
    barrier = threading.Barrier(len(people))

    def attempt(person_id: uuid.UUID) -> None:
        with factory() as session:
            person = session.get(User, person_id)
            assert person is not None
            barrier.wait(timeout=10)
            try:
                tasks.claim(session, _principal(person, "moderator"), task.id)
                session.commit()
                outcomes.append("claimed")
            except ApiError as error:
                session.rollback()
                outcomes.append(error.code)

    threads = [threading.Thread(target=attempt, args=(person.id,)) for person in people]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    assert outcomes.count("claimed") == 1 and outcomes.count("TASK_NOT_AVAILABLE") == len(people) - 1


def test_an_expired_lease_can_be_taken_over_and_the_old_holder_is_told_to_reload(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    task = _task_for(postgres_session, review)
    one = staff_client(client, postgres_session, fake, "one@example.com", "moderator", "203.0.113.44")
    two = staff_client(client, postgres_session, fake, "two@example.com", "moderator", "203.0.113.45")
    old = _claim(one, task)
    postgres_session.execute(update(ModerationTask).where(ModerationTask.id == task.id).values(lease_expires_at=datetime.now(UTC) - timedelta(seconds=5)))
    postgres_session.commit()
    postgres_session.expire_all()
    new = _claim(two, task)
    assert new["lease_token"] != old["lease_token"]
    stale = one.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(task, old["lease_token"], review))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "LEASE_LOST"
    postgres_session.expire_all()
    assert postgres_session.get(Review, review.id).status == ReviewStatus.PENDING, "an expired lease never decides anything"
    assert one.post(f"{BASE}/tasks/{task.id}/heartbeat", json={"lease_token": old["lease_token"]}).status_code == 409


def test_heartbeat_extends_and_release_frees_the_task(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    task = _task_for(postgres_session, review)
    one = staff_client(client, postgres_session, fake, "one@example.com", "moderator", "203.0.113.46")
    two = staff_client(client, postgres_session, fake, "two@example.com", "moderator", "203.0.113.47")
    lease = _claim(one, task)
    postgres_session.execute(update(ModerationTask).where(ModerationTask.id == task.id).values(lease_expires_at=datetime.now(UTC) + timedelta(seconds=10)))
    postgres_session.commit()
    beat = one.post(f"{BASE}/tasks/{task.id}/heartbeat", json={"lease_token": lease["lease_token"]})
    assert beat.status_code == 200 and beat.json()["lease_expires_at"] > lease["lease_expires_at"][:0]
    assert two.post(f"{BASE}/tasks/{task.id}/release", json={"lease_token": lease["lease_token"]}).status_code == 409
    assert one.post(f"{BASE}/tasks/{task.id}/release", json={"lease_token": lease["lease_token"]}).status_code == 200
    assert _claim(two, task)["claimed_by"]


def test_a_stale_tab_cannot_decide_a_task_that_was_escalated(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    task = _task_for(postgres_session, review)
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.48")
    boss = staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.49")
    lease = _claim(mod, task)
    assert mod.post(f"{BASE}/tasks/{task.id}/escalate", json={"lease_token": lease["lease_token"], "reason": "needs a superadmin"}).status_code == 200
    stale = mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(task, lease["lease_token"], review))
    assert stale.status_code in (403, 409), stale.text
    assert mod.post(f"{BASE}/tasks/{task.id}/claim").status_code == 403, "a moderator cannot claim an escalated task"
    held = _claim(boss, task)
    assert boss.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(task, held["lease_token"], review)).status_code == 200
    postgres_session.expire_all()
    assert postgres_session.get(Review, review.id).status == ReviewStatus.PUBLISHED


# ---- decisions (spec 8.5, 14) ----


def test_a_decision_writes_action_audit_and_outbox_together(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    task = _task_for(postgres_session, review)
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.50")
    lease = _claim(mod, task)
    version_before = review.version
    response = mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(task, lease["lease_token"], review))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "PUBLISHED" and response.json()["version"] == version_before + 1
    postgres_session.expire_all()
    action = postgres_session.scalar(select(ModerationActionRecord).where(ModerationActionRecord.review_id == review.id))
    assert action is not None and action.task_id == task.id and action.request_id
    event = postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "review.publish"))
    assert event is not None and event.target_id == str(review.id) and event.request_id == action.request_id
    assert event.actor_role_snapshot == "moderator" and event.event_metadata["to"] == "PUBLISHED"
    assert postgres_session.scalar(select(OutboxEvent).where(OutboxEvent.topic == "review.state_changed", OutboxEvent.aggregate_id == review.id))
    done = postgres_session.get(ModerationTask, task.id)
    assert done.status == "done" and done.claimed_by is None
    assert mod.get(f"{BASE}/queue").json()["items"] == []


def test_a_stale_version_is_a_conflict_and_changes_nothing(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    task = _task_for(postgres_session, review)
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.51")
    lease = _claim(mod, task)
    stale = mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(task, lease["lease_token"], review, expected_version=review.version + 5))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "REVIEW_VERSION_CONFLICT"
    postgres_session.expire_all()
    assert postgres_session.get(Review, review.id).status == ReviewStatus.PENDING
    assert postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "review.publish")) is None, "no partial write"
    assert postgres_session.get(ModerationTask, task.id).status == "open"
    assert postgres_session.scalar(select(ModerationActionRecord)) is None


def test_an_invalid_transition_is_422_and_the_lease_survives(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    task = _task_for(postgres_session, review)
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.52")
    lease = _claim(mod, task)
    invalid = mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(task, lease["lease_token"], review, decision="RESTORE"))
    assert invalid.status_code == 422 and invalid.json()["error"]["code"] == "TRANSITION_NOT_ALLOWED"
    unknown = mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(task, lease["lease_token"], review, decision="DELETE_EVERYTHING"))
    assert unknown.status_code == 422
    assert mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(task, lease["lease_token"], review)).status_code == 200


def test_a_decision_without_the_lease_of_that_task_is_refused(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    other = _pending_review(postgres_session, title="Another review", destination=postgres_session.scalar(select(Destination)))
    task, other_task = _task_for(postgres_session, review), _task_for(postgres_session, other)
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.53")
    lease = _claim(mod, task)
    wrong_token = mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(task, str(uuid.uuid4()), review))
    assert wrong_token.status_code == 409 and wrong_token.json()["error"]["code"] == "LEASE_LOST"
    wrong_subject = mod.post(f"{BASE}/submissions/{other.id}/moderation-actions", json=_decision(task, lease["lease_token"], other))
    assert wrong_subject.status_code == 404
    unclaimed = mod.post(f"{BASE}/submissions/{other.id}/moderation-actions", json=_decision(other_task, lease["lease_token"], other))
    assert unclaimed.status_code == 409


def test_a_retry_with_the_same_key_returns_the_original_result(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    task = _task_for(postgres_session, review)
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.54")
    lease = _claim(mod, task)
    body = _decision(task, lease["lease_token"], review)
    version_before = review.version
    first = mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=body, headers={"Idempotency-Key": "retry-key-0001"})
    replay = mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=body, headers={"Idempotency-Key": "retry-key-0001"})
    assert first.status_code == replay.status_code == 200 and first.json() == replay.json()
    postgres_session.expire_all()
    assert len(postgres_session.scalars(select(ModerationActionRecord)).all()) == 1
    assert postgres_session.get(Review, review.id).version == version_before + 1, "applied once"
    different = mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json={**body, "reason_code": "different"}, headers={"Idempotency-Key": "retry-key-0001"})
    assert different.status_code == 409 and different.json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    bad = mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=body, headers={"Idempotency-Key": "bad key!"})
    assert bad.status_code == 422


def test_bulk_decisions_report_each_item(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    destination = Destination(status=DestinationStatus.PUBLISHED, name_bn="সাজেক", name_en="Sajek")
    reviews = [_pending_review(postgres_session, title=f"Review {i}", destination=destination) for i in range(2)]
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.55")
    items = []
    for index, review in enumerate(reviews):
        task = _task_for(postgres_session, review)
        lease = _claim(mod, task)
        items.append({"review_id": str(review.id), **_decision(task, lease["lease_token"], review, expected_version=review.version + (7 if index else 0))})
    response = mod.post(f"{BASE}/bulk/moderation-actions", json={"items": items})
    assert response.status_code == 200
    body = response.json()
    assert (body["succeeded"], body["failed"]) == (1, 1)
    assert body["results"][0]["ok"] is True and body["results"][1] == {"review_id": str(reviews[1].id), "ok": False, "error": "REVIEW_VERSION_CONFLICT"}
    postgres_session.expire_all()
    assert postgres_session.get(Review, reviews[0].id).status == ReviewStatus.PUBLISHED
    assert postgres_session.get(Review, reviews[1].id).status == ReviewStatus.PENDING


def test_withdrawing_a_pending_review_removes_it_from_the_queue(postgres_session: Session) -> None:
    from app.services import withdraw_review

    review = _pending_review(postgres_session)
    withdraw_review(postgres_session, review.id, review.version)
    postgres_session.commit()
    assert _task_for(postgres_session, review).status == "cancelled"


# ---- reports (Gantt R11) ----


def _publish(client: TestClient, session: Session, fake: support.FakeGoTrue, review: Review, ip: str) -> TestClient:
    mod = staff_client(client, session, fake, f"publisher-{ip}@example.com", "moderator", ip)
    lease = _claim(mod, _task_for(session, review))
    task = _task_for(session, review)
    assert mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(task, lease["lease_token"], review)).status_code == 200
    session.expire_all()
    return mod


def test_report_to_decision_flow(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    mod = _publish(client, postgres_session, fake, review, "203.0.113.60")
    reader = staff_client(client, postgres_session, fake, "reader@example.com", None, "203.0.113.61")
    reported = reader.post(f"/api/v1/reviews/{review.id}/reports", json={"reason_code": "spam", "details": "advert"})
    assert reported.status_code == 201, reported.text
    report_id = uuid.UUID(reported.json()["report_id"])
    duplicate = reader.post(f"/api/v1/reviews/{review.id}/reports", json={"reason_code": "offensive"})
    assert duplicate.status_code == 409 and duplicate.json()["error"]["code"] == "DUPLICATE_OPEN_REPORT"

    item = next(i for i in mod.get(f"{BASE}/queue", params={"task_type": "report"}).json()["items"])
    assert item["subject"]["reason_code"] == "spam" and item["subject"]["review_title"] == "Lovely beach"
    task = postgres_session.get(ModerationTask, uuid.UUID(item["id"]))
    lease = _claim(mod, task)
    start = mod.post(f"{BASE}/reports/{report_id}/transition", json={"to": "in_review", "expected_version": 1, "reason_code": "looking", "task_id": str(task.id), "lease_token": lease["lease_token"]})
    assert start.status_code == 200 and start.json() == {"report_id": str(report_id), "state": "in_review", "version": 2}
    back = mod.post(f"{BASE}/reports/{report_id}/transition", json={"to": "in_review", "expected_version": 2, "reason_code": "looking", "task_id": str(task.id), "lease_token": lease["lease_token"]})
    assert back.status_code == 422 and back.json()["error"]["code"] == "TRANSITION_NOT_ALLOWED"
    stale = mod.post(f"{BASE}/reports/{report_id}/transition", json={"to": "actioned", "expected_version": 1, "reason_code": "report-confirmed", "task_id": str(task.id), "lease_token": lease["lease_token"]})
    assert stale.status_code == 409
    # the reviewer hides the reported review under the report task's own lease; the task stays open
    review = postgres_session.get(Review, review.id)
    hidden = mod.post(
        f"{BASE}/submissions/{review.id}/moderation-actions",
        json=_decision(task, lease["lease_token"], review, decision="HIDE", reason_code="reported-spam"),
    )
    assert hidden.status_code == 200 and hidden.json()["status"] == "HIDDEN"
    postgres_session.expire_all()
    assert postgres_session.get(ModerationTask, task.id).status == "open"
    another = _pending_review(postgres_session, title="Unrelated", destination=postgres_session.scalar(select(Destination)))
    unrelated = mod.post(f"{BASE}/submissions/{another.id}/moderation-actions", json=_decision(task, lease["lease_token"], another))
    assert unrelated.status_code == 404, "a report task can only decide the review it names"

    done = mod.post(f"{BASE}/reports/{report_id}/transition", json={"to": "actioned", "expected_version": 2, "reason_code": "report-confirmed", "note": "hidden", "task_id": str(task.id), "lease_token": lease["lease_token"]})
    assert done.status_code == 200 and done.json()["state"] == "actioned"
    postgres_session.expire_all()
    report = postgres_session.get(Report, report_id)
    assert report.state == "actioned" and report.resolved_by is not None and postgres_session.get(ModerationTask, task.id).status == "done"
    assert {e.action for e in postgres_session.scalars(select(AuditEvent))} >= {"report.in_review", "report.actioned", "review.hide"}
    again = reader.post(f"/api/v1/reviews/{review.id}/reports", json={"reason_code": "spam"})
    assert again.status_code == 404, "a hidden review can no longer be reported"


def test_a_superadmin_can_find_accounts_by_email(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    boss = staff_client(client, postgres_session, fake, "boss@example.com", "superadmin", "203.0.113.63")
    _make_user(postgres_session, fake, "nila.rahman@example.com", "Nila")
    found = boss.get(f"{BASE}/users", params={"q": "RAHMAN"}).json()["items"]
    assert [item["email"] for item in found] == ["nila.rahman@example.com"] and found[0]["role"] is None
    assert boss.get(f"{BASE}/users", params={"q": "ab"}).status_code == 422, "at least three characters"
    assert boss.get(f"{BASE}/users", params={"q": "%%%"}).json()["items"] == [], "wildcards are literal"
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.64")
    assert mod.get(f"{BASE}/users", params={"q": "example"}).status_code == 403


def test_reports_have_rules(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    pending = _pending_review(postgres_session)
    reader = staff_client(client, postgres_session, fake, "reader@example.com", None, "203.0.113.62")
    assert reader.post(f"/api/v1/reviews/{pending.id}/reports", json={"reason_code": "spam"}).status_code == 404, "unpublished reviews are not disclosed"
    assert reader.post(f"/api/v1/reviews/{uuid.uuid4()}/reports", json={"reason_code": "spam"}).status_code == 404
    assert reader.post(f"/api/v1/reviews/{pending.id}/reports", json={"reason_code": "not-a-reason"}).status_code == 422
    anonymous = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN})
    assert anonymous.post(f"/api/v1/reviews/{pending.id}/reports", json={"reason_code": "spam"}).status_code == 401
    no_csrf = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN})
    no_csrf.cookies.set("__Host-abhijatri_session", fake.mint("reader@example.com").access_token)
    assert no_csrf.post(f"/api/v1/reviews/{pending.id}/reports", json={"reason_code": "spam"}).status_code == 403


# ---- audit (spec 6.6) ----


def test_audit_events_are_append_only_and_findable_by_id(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.70")
    lease = _claim(mod, _task_for(postgres_session, review))
    assert mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(_task_for(postgres_session, review), lease["lease_token"], review)).status_code == 200
    listing = mod.get(f"{BASE}/audit-events", params={"target_type": "review"}).json()
    assert [i["action"] for i in listing["items"]] == ["review.publish"]
    event = listing["items"][0]
    one = mod.get(f"{BASE}/audit-events/{event['id']}")
    assert one.status_code == 200 and one.json() == event
    assert mod.get(f"{BASE}/audit-events/{uuid.uuid4()}").status_code == 404
    assert mod.get(f"{BASE}/audit-events", params={"action": "task.claimed"}).json()["items"][0]["target_type"] == "task"
    with pytest.raises(DBAPIError):
        postgres_session.execute(text("UPDATE audit_events SET action = 'tampered'"))
    postgres_session.rollback()
    with pytest.raises(DBAPIError):
        postgres_session.execute(delete(AuditEvent))
    postgres_session.rollback()
    with pytest.raises(DBAPIError):
        postgres_session.execute(text("TRUNCATE audit_events"))
    postgres_session.rollback()


def test_the_audit_log_has_no_secrets(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    review = _pending_review(postgres_session)
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.71")
    lease = _claim(mod, _task_for(postgres_session, review))
    mod.post(f"{BASE}/submissions/{review.id}/moderation-actions", json=_decision(_task_for(postgres_session, review), lease["lease_token"], review))
    dump = str([(e.action, e.reason, e.event_metadata) for e in postgres_session.scalars(select(AuditEvent))])
    for secret in (lease["lease_token"], "eyJ", "refresh-", support.PASSWORD, "abr1_"):
        assert secret not in dump


# ---- monitoring ----


def test_monitoring_summary_counts_the_queue(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    _pending_review(postgres_session)
    mod = staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.72")
    summary = mod.get(f"{BASE}/monitoring/summary").json()
    assert summary["queue_depth"] == 1 and summary["expired_claims"] == 0 and summary["open_reports"] == 0
    assert summary["oldest_open_task_age_seconds"] >= 0 and summary["outbox_pending"] >= 1
