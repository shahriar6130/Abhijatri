"""R11 restrictions and sanction expiry (Moderation spec 6.4, P-01), the access matrix of the new routes, and the
audit of refused staff requests (Moderation spec 9, 14.7)."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import test_admin as admin
import test_auth as support
import test_ops as ops
import test_rating_exclusion as helpers
import test_review_crud as crud
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.admin import cases
from app.jobs import retention
from app.models import (
    AuditEvent,
    Destination,
    OutboxEvent,
    Review,
    ReviewRevision,
    Sanction,
    User,
    UserRole,
)
from app.notify.alerts import DENIAL_THRESHOLD

auth_env = support.auth_env
fake = support.fake
redis_fake = support.redis_fake
ops_fake = ops.fake
ops_token = ops.token
pytestmark = pytest.mark.integration
BASE = "/api/v1/admin"
API = "/api/v1"
moderator = helpers.moderator


@pytest.fixture()
def client(auth_env: None, postgres_session: Session, fake: support.FakeGoTrue, redis_fake: Any) -> TestClient:
    return support.make_client(postgres_session, fake, redis_fake)


def _member(client: TestClient, session: Session, fake: support.FakeGoTrue, name: str, n: int) -> tuple[TestClient, uuid.UUID]:
    browser = admin.staff_client(client, session, fake, f"{name}@example.test", None, f"203.0.113.{180 + n}", aal="aal1")
    return browser, fake.users[f"{name}@example.test"]["id"]


def _sanction(session: Session, user_id: uuid.UUID, kind: str, *, ends: timedelta | None, creator: User, review_on: Any = None) -> Sanction:
    row = Sanction(
        user_id=user_id, kind=kind, reason_code="policy-violation", created_by=creator.id,
        ends_at=None if ends is None else datetime.now(UTC) + ends, review_on=review_on,
    )
    session.add(row)
    session.commit()
    if kind == "suspension":
        cases._set_account_state(session, user_id)  # noqa: SLF001
        session.commit()
    return row


def _own_review(client: TestClient, session: Session, member: TestClient, destination: Destination) -> str:
    return crud._member_review(member, destination)  # noqa: SLF001


# ---- a restriction stops posting (F5) ----


def test_a_restricted_member_cannot_post_edit_attach_or_report_but_can_still_withdraw_appeal_and_read(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User
) -> None:
    session = postgres_session
    destination = crud._destination(session)  # noqa: SLF001
    member, member_id = _member(client, session, fake, "restricted-flow", 1)
    review_id = _own_review(client, session, member, destination)
    other = _publish_for(session, moderator)
    _sanction(session, member_id, "posting_restriction", ends=timedelta(days=3), creator=moderator)

    blocked: list[tuple[str, int]] = []
    blocked.append(("create", member.post(f"{API}/reviews/member", json=crud._body(destination, visit_month=crud._month(2))).status_code))  # noqa: SLF001
    blocked.append(("edit", member.patch(f"{API}/reviews/{review_id}/pending", json={"expected_version": 1, "title": "A new title"}).status_code))
    blocked.append(("media", member.post(f"{API}/reviews/{review_id}/media-intents", json={"content_type": "image/jpeg", "size_bytes": 1000, "alt_text": "a view", "ownership_declared": True}).status_code))
    blocked.append(("report", member.post(f"{API}/reviews/{other.id}/reports", json={"reason_code": "spam"}).status_code))
    assert blocked == [("create", 403), ("edit", 403), ("media", 403), ("report", 403)]
    for response in (
        member.post(f"{API}/reviews/member", json=crud._body(destination, visit_month=crud._month(3))),  # noqa: SLF001
        member.patch(f"{API}/reviews/{review_id}/pending", json={"expected_version": 1, "title": "Another title"}),
    ):
        assert response.json()["error"]["code"] == "ACCOUNT_RESTRICTED"

    assert member.get(f"{API}/reviews/mine").status_code == 200, "reading is never blocked"
    assert member.get(f"{API}/reviews/{review_id}").status_code == 200
    withdrawn = member.post(f"{API}/reviews/{review_id}/withdraw", json={"expected_version": 1})
    assert withdrawn.status_code == 200 and withdrawn.json()["status"] == "WITHDRAWN", "a restricted member can still withdraw"
    assert member.get(f"{API}/appeals/mine").status_code == 200, "and still reach the appeal screens"
    assert session.scalar(select(ReviewRevision.id).where(ReviewRevision.title == "A new title")) is None


def _publish_for(session: Session, staff: User) -> Review:
    return helpers._publish(session, helpers._review(session, helpers._destination(session, f"P-{uuid.uuid4().hex[:5]}"), helpers._verified_member(session)), staff)  # noqa: SLF001


def test_a_warning_blocks_nothing(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    member, member_id = _member(client, session, fake, "warned", 2)
    _sanction(session, member_id, "warning", ends=timedelta(days=3), creator=moderator)
    assert member.post(f"{API}/reviews/member", json=crud._body(crud._destination(session))).status_code == 201  # noqa: SLF001


def test_a_suspended_account_is_refused_everywhere(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    member, member_id = _member(client, session, fake, "suspended", 3)
    _sanction(session, member_id, "suspension", ends=timedelta(days=3), creator=moderator)
    for response in (member.get(f"{API}/reviews/mine"), member.post(f"{API}/reviews/member", json=crud._body(crud._destination(session)))):  # noqa: SLF001
        assert response.status_code == 403 and response.json()["error"]["code"] == "ACCOUNT_DISABLED"


def test_a_restriction_created_through_the_staff_api_takes_effect_at_once(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    member, member_id = _member(client, session, fake, "via-api", 4)
    staff = admin.staff_client(client, session, fake, "mod-restrict@example.test", "moderator", "203.0.113.190")
    later = (datetime.now(UTC) + timedelta(days=2)).isoformat()
    made = staff.post(f"{BASE}/enforcement-cases", json={"user_id": str(member_id), "reason_code": "policy-violation", "sanction": {"kind": "posting_restriction", "ends_at": later}})
    assert made.status_code == 201
    assert member.post(f"{API}/reviews/member", json=crud._body(crud._destination(session))).json()["error"]["code"] == "ACCOUNT_RESTRICTED"  # noqa: SLF001


# ---- expiry no longer depends on the job (F6, P-01) ----


def test_an_expired_restriction_stops_blocking_without_the_job_and_is_ended_and_audited(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User
) -> None:
    session = postgres_session
    member, member_id = _member(client, session, fake, "expired-restriction", 5)
    sanction = _sanction(session, member_id, "posting_restriction", ends=timedelta(days=1), creator=moderator)
    session.execute(update(Sanction).where(Sanction.id == sanction.id).values(ends_at=datetime.now(UTC) - timedelta(minutes=1)))
    session.commit()
    assert member.post(f"{API}/reviews/member", json=crud._body(crud._destination(session))).status_code == 201  # noqa: SLF001
    session.expire_all()
    ended = session.get(Sanction, sanction.id)
    assert ended is not None and ended.state == "expired" and ended.reversed_at is not None and ended.reversed_by is None
    event = session.scalar(select(AuditEvent).where(AuditEvent.action == "sanction.expired"))
    assert event is not None and event.actor_user_id is None and event.target_id == str(member_id)
    assert session.scalar(select(OutboxEvent).where(OutboxEvent.topic == "sanction.ended")) is not None, "the member is told it ended"


def test_an_expired_suspension_re_enables_the_account_on_the_next_request(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    member, member_id = _member(client, session, fake, "expired-suspension", 6)
    sanction = _sanction(session, member_id, "suspension", ends=timedelta(days=1), creator=moderator)
    assert member.get(f"{API}/reviews/mine").status_code == 403
    session.execute(update(Sanction).where(Sanction.id == sanction.id).values(ends_at=datetime.now(UTC) - timedelta(seconds=5)))
    session.commit()
    assert member.get(f"{API}/reviews/mine").status_code == 200, "the suspension ended by itself; no job ran"
    session.expire_all()
    user = session.get(User, member_id)
    assert user is not None and user.status == "active" and user.disabled_at is None
    assert session.get(Sanction, sanction.id).state == "expired"  # type: ignore[union-attr]
    assert len(session.scalars(select(AuditEvent).where(AuditEvent.action == "sanction.expired")).all()) == 1


def test_a_sanction_with_only_a_review_date_stays_in_force(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    member, member_id = _member(client, session, fake, "review-date-only", 7)
    _sanction(session, member_id, "posting_restriction", ends=None, creator=moderator, review_on=datetime.now(UTC).date() - timedelta(days=30))
    assert member.post(f"{API}/reviews/member", json=crud._body(crud._destination(session))).json()["error"]["code"] == "ACCOUNT_RESTRICTED"  # noqa: SLF001


def test_a_reversed_sanction_does_not_block(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    member, member_id = _member(client, session, fake, "reversed", 8)
    sanction = _sanction(session, member_id, "posting_restriction", ends=timedelta(days=2), creator=moderator)
    sanction.state = "reversed"
    session.commit()
    assert member.post(f"{API}/reviews/member", json=crud._body(crud._destination(session))).status_code == 201  # noqa: SLF001


def test_the_daily_job_still_sweeps_what_no_request_met(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    _, member_id = _member(client, session, fake, "swept", 9)
    sanction = _sanction(session, member_id, "suspension", ends=timedelta(days=1), creator=moderator)
    session.execute(update(Sanction).where(Sanction.id == sanction.id).values(ends_at=datetime.now(UTC) - timedelta(minutes=2)))
    session.commit()
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    assert retention.expire_sanctions(factory, datetime.now(UTC)) == 1  # type: ignore[arg-type]
    session.expire_all()
    assert session.get(User, member_id).status == "active"  # type: ignore[union-attr]


def test_expiry_by_a_request_and_by_the_job_at_once_happens_exactly_once(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    user = helpers._user(session, "Racer")  # noqa: SLF001
    sanction = _sanction(session, user.id, "suspension", ends=timedelta(days=1), creator=moderator)
    session.execute(update(Sanction).where(Sanction.id == sanction.id).values(ends_at=datetime.now(UTC) - timedelta(minutes=1)))
    session.commit()
    engine = create_engine(session.get_bind().url.render_as_string(hide_password=False), pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = threading.Barrier(2)

    def expire() -> int:
        with factory() as worker:
            barrier.wait()
            count = cases.expire_due_sanctions(worker, user.id)
            worker.commit()
            return count

    with ThreadPoolExecutor(max_workers=2) as pool:
        totals = sorted(pool.map(lambda job: job(), [expire, expire]))
    engine.dispose()
    assert sum(totals) == 1, totals
    session.expire_all()
    assert len(session.scalars(select(AuditEvent).where(AuditEvent.action == "sanction.expired")).all()) == 1
    assert session.get(User, user.id).status == "active"  # type: ignore[union-attr]


# ---- the retention route ----


def test_the_retention_route_needs_the_token_and_is_idempotent(ops_token: None, ops_fake: Any, postgres_session: Session) -> None:
    api = ops._app(ops_fake, postgres_session)  # noqa: SLF001
    assert api.post("/api/v1/ops/jobs/retention").status_code == 401
    first = api.post("/api/v1/ops/jobs/retention", headers=ops.AUTH)
    second = api.post("/api/v1/ops/jobs/retention", headers=ops.AUTH)
    assert first.status_code == second.status_code == 200
    assert {"sanctions_expired", "rejected_reviews", "report_contacts"} <= set(first.json())
    assert first.json() == second.json() == {key: 0 for key in first.json()}


# ---- refused staff requests are audited (Moderation spec 9, 14.7) ----


def test_a_wrong_role_request_is_audited_with_the_route_and_what_was_needed(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    mod = admin.staff_client(client, postgres_session, fake, "wrong-role@example.test", "moderator", "203.0.113.191")
    assert mod.post(f"{BASE}/ratings/reconcile", json={"repair": False}).status_code == 403
    event = postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "denied.role"))
    assert event is not None and event.actor_role_snapshot == "moderator" and event.reason == "needs superadmin"
    assert event.target_id == "POST /api/v1/admin/ratings/reconcile" and event.event_metadata["required"] == ["superadmin"]
    assert event.actor_user_id == fake.users["wrong-role@example.test"]["id"]


def test_a_stranger_probing_staff_routes_leaves_no_trace_in_the_log(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    member, _ = _member(client, postgres_session, fake, "stranger", 10)
    for _ in range(3):
        assert member.get(f"{BASE}/audit-events").status_code == 404
    anonymous = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.192"})
    assert anonymous.get(f"{BASE}/audit-events").status_code == 401
    assert postgres_session.scalar(select(AuditEvent).where(AuditEvent.action.like("denied.%"))) is None


def test_repeated_denials_raise_the_security_alert_once(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    session = postgres_session
    boss = admin.staff_client(client, session, fake, "watcher@example.test", "superadmin", "203.0.113.193")
    mod = admin.staff_client(client, session, fake, "prober@example.test", "moderator", "203.0.113.194")
    for _ in range(DENIAL_THRESHOLD + 2):
        assert mod.get(f"{BASE}/audit-events/export").status_code == 403
    alerts = session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "moderation.security_anomaly")).all()
    assert len(alerts) == 1, "one alert per hour, not one per denial"
    assert alerts[0].payload["staff_recipients"] == [str(fake.users["watcher@example.test"]["id"])]
    del boss


# ---- the access matrix of the new staff routes ----


def _caller(client: TestClient, session: Session, fake: support.FakeGoTrue, kind: str, n: int) -> TestClient:
    email = f"{kind}-matrix{n}@example.test"
    if kind == "anonymous":
        return TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": f"203.0.113.{200 + n}"})
    if kind == "member":
        return admin.staff_client(client, session, fake, email, None, f"203.0.113.{200 + n}", aal="aal1")
    if kind == "moderator_without_totp":
        return admin.staff_client(client, session, fake, email, "moderator", f"203.0.113.{200 + n}", aal="aal1")
    browser = admin.staff_client(client, session, fake, email, "superadmin" if kind in ("superadmin", "revoked_superadmin") else "moderator", f"203.0.113.{200 + n}")
    user_id = fake.users[email]["id"]
    if kind == "revoked_moderator" or kind == "revoked_superadmin":
        session.execute(update(UserRole).where(UserRole.user_id == user_id).values(revoked_at=datetime.now(UTC)))
        session.commit()
    if kind == "disabled_moderator":
        session.execute(update(User).where(User.id == user_id).values(status="disabled"))
        session.commit()
    return browser


MISSING = uuid.uuid4()
# (method, path, body, who is allowed in)
STAFF_ROUTES: list[tuple[str, str, Any, str]] = [
    ("GET", f"{BASE}/reason-codes", None, "staff"),
    ("GET", f"{BASE}/reviews?status=HIDDEN", None, "staff"),
    ("GET", f"{BASE}/audit-events", None, "staff"),
    ("GET", f"{BASE}/audit-events/actions", None, "staff"),
    ("POST", f"{BASE}/reports/{MISSING}/hide-pending", {"expected_version": 1, "reason_code": "privacy-pending", "task_id": str(MISSING), "lease_token": str(MISSING)}, "staff"),
    ("POST", f"{BASE}/reviews/{MISSING}/reopen", {"expected_version": 1, "reason_code": "rejected-in-error"}, "superadmin"),
    ("GET", f"{BASE}/audit-events/export", None, "superadmin"),
]


@pytest.mark.parametrize(("method", "path", "body", "allowed"), STAFF_ROUTES)
def test_every_caller_gets_the_right_answer_on_each_new_staff_route(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, method: str, path: str, body: Any, allowed: str
) -> None:
    session = postgres_session
    results: dict[str, tuple[int, str | None]] = {}
    for n, kind in enumerate(("anonymous", "member", "moderator_without_totp", "revoked_moderator", "disabled_moderator", "moderator", "superadmin", "revoked_superadmin")):
        caller = _caller(client, session, fake, kind, n)
        response = caller.request(method, path, json=body)
        code = response.json().get("error", {}).get("code") if response.headers.get("content-type", "").startswith("application/json") else None
        results[kind] = (response.status_code, code)
    assert results["anonymous"] == (401, "AUTH_REQUIRED")
    assert results["member"][0] == 404, "a member is not told the route exists"
    assert results["revoked_moderator"][0] == 404 and results["revoked_superadmin"][0] == 404, "a revoked role stops working on the next request"
    assert results["disabled_moderator"] == (403, "ACCOUNT_DISABLED")
    assert results["moderator_without_totp"] == (403, "MFA_REQUIRED") or allowed == "superadmin" and results["moderator_without_totp"][0] == 403
    if allowed == "staff":
        assert results["moderator"][0] in (200, 404) and results["superadmin"][0] in (200, 404), results  # 404 = the record named does not exist
        assert results["moderator"][1] != "FORBIDDEN"
    else:
        assert results["moderator"] == (403, "FORBIDDEN")
        assert results["superadmin"][0] in (200, 404), results


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", f"{BASE}/reports/{MISSING}/hide-pending", {"expected_version": 1, "reason_code": "privacy-pending", "task_id": str(MISSING), "lease_token": str(MISSING)}),
        ("POST", f"{BASE}/reviews/{MISSING}/reopen", {"expected_version": 1, "reason_code": "rejected-in-error"}),
    ],
)
def test_staff_writes_need_the_csrf_token_and_a_trusted_origin(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, method: str, path: str, body: Any) -> None:
    boss = admin.staff_client(client, postgres_session, fake, "csrf-matrix@example.test", "superadmin", "203.0.113.230")
    token = boss.headers.pop("X-CSRF-Token")
    assert boss.request(method, path, json=body).status_code == 403
    boss.headers["X-CSRF-Token"] = token
    boss.headers["Origin"] = "https://evil.example"
    assert boss.request(method, path, json=body).status_code == 403
    boss.headers["Origin"] = support.ORIGIN
    assert boss.request(method, path, json=body).status_code == 404, "with both proofs the request reaches the route (the review does not exist)"


@pytest.mark.parametrize("payload", ["' OR 1=1 --", "x" * 5000, "<script>alert(1)</script>", "\u0000", "../../etc/passwd"])
def test_hostile_input_is_refused_or_harmless_and_never_leaks_internals(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, payload: str) -> None:
    boss = admin.staff_client(client, postgres_session, fake, "hostile@example.test", "superadmin", "203.0.113.231")
    responses = [
        boss.post(f"{BASE}/reviews/{MISSING}/reopen", json={"expected_version": 1, "reason_code": payload}),
        boss.get(f"{BASE}/audit-events", params={"action": payload}),
        boss.get(f"{BASE}/audit-events", params={"request_id": payload}),
        boss.get(f"{BASE}/reviews", params={"status": payload}),
    ]
    for response in responses:
        assert response.status_code in (200, 404, 422), response.text[:200]
        text = response.text.lower()
        for leak in ("traceback", "psycopg", "sqlalchemy", "select ", "syntax error"):
            assert leak not in text
    assert postgres_session.scalar(select(AuditEvent.id).where(AuditEvent.action == "tampered")) is None
