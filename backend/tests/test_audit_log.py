"""R11 audit log (Moderation spec 6.6, 12.6; Review.md 5.4): immutability, search and paging, the action
catalogue, and the capped, audited CSV export."""

import csv
import io
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import test_admin as admin
import test_auth as support
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.admin import audit as audit_module
from app.audit_actions import AUDIT_ACTIONS, FAMILIES, FIXED, is_known
from app.models import AuditEvent, ModerationActionRecord, ModerationDecision, ReviewStatus

auth_env = support.auth_env
fake = support.fake
redis_fake = support.redis_fake
pytestmark = pytest.mark.integration
BASE = "/api/v1/admin"


@pytest.fixture()
def client(auth_env: None, postgres_session: Session, fake: support.FakeGoTrue, redis_fake: Any) -> TestClient:
    return support.make_client(postgres_session, fake, redis_fake)


def _event(session: Session, when: datetime, **overrides: Any) -> AuditEvent:
    values: dict[str, Any] = {
        "occurred_at": when, "actor_user_id": None, "actor_role_snapshot": None, "action": "task.claimed",
        "target_type": "task", "target_id": str(uuid.uuid4()), "request_id": None, "reason": None, "event_metadata": {},
    }
    values.update(overrides)
    event = AuditEvent(**values)
    session.add(event)
    return event


def _staff(client: TestClient, session: Session, fake: support.FakeGoTrue, role: str, n: int) -> TestClient:
    return admin.staff_client(client, session, fake, f"{role}-{n}@example.test", role, f"203.0.113.{120 + n}")


# ---- immutability (Review.md 5.4: history cannot be updated or deleted) ----


def test_the_decision_history_is_append_only_like_the_audit_log(postgres_session: Session) -> None:
    review = admin._pending_review(postgres_session)  # noqa: SLF001
    moderator = admin._make_user(postgres_session, support.FakeGoTrue(), "history@example.test")  # noqa: SLF001
    action = ModerationActionRecord(
        review_id=review.id, actor_user_id=moderator, decision=ModerationDecision.PUBLISH,
        previous_status=ReviewStatus.PENDING, new_status=ReviewStatus.PUBLISHED, reason_code="meets-policy",
    )
    postgres_session.add(action)
    postgres_session.commit()
    for statement in (
        update(ModerationActionRecord).values(reason_code="tampered"),
        delete(ModerationActionRecord),
        text("TRUNCATE moderation_actions CASCADE"),
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            postgres_session.execute(statement)
        postgres_session.rollback()
    assert postgres_session.scalar(select(ModerationActionRecord.reason_code)) == "meets-policy"


def test_audit_events_refuse_update_delete_and_truncate(postgres_session: Session) -> None:
    _event(postgres_session, datetime.now(UTC))
    postgres_session.commit()
    for statement in (update(AuditEvent).values(action="x"), delete(AuditEvent), text("TRUNCATE audit_events")):
        with pytest.raises(DBAPIError, match="append-only"):
            postgres_session.execute(statement)
        postgres_session.rollback()


# ---- the action catalogue ----


def test_every_action_family_is_listed_and_denials_are_always_known() -> None:
    assert FIXED <= AUDIT_ACTIONS
    for prefix, suffixes in FAMILIES.items():
        assert {f"{prefix}.{suffix}" for suffix in suffixes} <= AUDIT_ACTIONS
    assert is_known("denied.report.transition") and is_known("report.create")
    assert not is_known("report.made_up") and not is_known("denied.")


def test_an_unlisted_action_fails_in_the_suite_and_only_warns_in_production(postgres_session: Session, caplog: pytest.LogCaptureFixture) -> None:
    actor = None
    with pytest.raises(AssertionError, match="not listed"):
        audit_module.record(postgres_session, actor=actor, action="made.up", target_type="x", target_id="1")
    audit_module.STRICT = False
    try:
        with caplog.at_level("WARNING"):
            audit_module.record(postgres_session, actor=actor, action="made.up", target_type="x", target_id="1")
        assert "made.up" in caplog.text
    finally:
        audit_module.STRICT = True
    postgres_session.rollback()


def test_the_catalogue_endpoint_lists_actions_for_staff_only(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    anonymous = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.90"})
    assert anonymous.get(f"{BASE}/audit-events/actions").status_code == 401
    member = admin.staff_client(client, postgres_session, fake, "plain@example.test", None, "203.0.113.91", aal="aal1")
    assert member.get(f"{BASE}/audit-events/actions").status_code == 404
    moderator = _staff(client, postgres_session, fake, "moderator", 1)
    answer = moderator.get(f"{BASE}/audit-events/actions").json()
    assert answer["denied_prefix"] == "denied." and answer["actions"] == sorted(AUDIT_ACTIONS)
    assert "report.create" in answer["actions"] and "audit.exported" in answer["actions"]


# ---- search and paging ----


def test_paging_never_skips_or_repeats_rows_that_share_a_timestamp(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    same = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    same_rows = [_event(postgres_session, same, target_id=f"t{n}") for n in range(120)]
    older = _event(postgres_session, same - timedelta(minutes=1), target_id="older")
    postgres_session.commit()
    ids = {str(row.id) for row in same_rows}
    moderator = _staff(client, postgres_session, fake, "moderator", 2)
    seen: list[str] = []
    cursor: str | None = None
    for _ in range(10):
        params: dict[str, Any] = {"limit": 50, "target_type": "task"}
        if cursor:
            params["cursor"] = cursor
        page = moderator.get(f"{BASE}/audit-events", params=params).json()
        seen += [item["id"] for item in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 121 and len(set(seen)) == 121, "every row exactly once"
    assert set(seen) == ids | {str(older.id)}
    assert seen[-1] == str(older.id), "newest first, so the older row is last"


def test_each_filter_alone_and_combined(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    actor, other = uuid.uuid4(), uuid.uuid4()
    now = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
    _event(postgres_session, now, action="report.create", target_type="review", target_id="r1", actor_user_id=actor, actor_role_snapshot="moderator", request_id="req-1")
    _event(postgres_session, now - timedelta(seconds=1), action="report.dismissed", target_type="report", target_id="p1", actor_user_id=other, actor_role_snapshot="superadmin", request_id="req-2")
    _event(postgres_session, now - timedelta(seconds=2), action="report.create", target_type="review", target_id="r2", actor_user_id=other, actor_role_snapshot="superadmin", request_id="req-3")
    postgres_session.commit()
    moderator = _staff(client, postgres_session, fake, "moderator", 3)

    def ids(**params: Any) -> list[str]:
        return [item["target_id"] for item in moderator.get(f"{BASE}/audit-events", params=params).json()["items"]]

    assert ids(action="report.create") == ["r1", "r2"]
    assert ids(target_type="report") == ["p1"]
    assert ids(target_id="r2") == ["r2"]
    assert ids(actor_user_id=str(actor)) == ["r1"]
    assert ids(actor_role="superadmin") == ["p1", "r2"]
    assert ids(request_id="req-3") == ["r2"]
    assert ids(action="report.create", actor_role="superadmin") == ["r2"]
    assert ids(action="report.create", target_type="report") == []
    assert moderator.get(f"{BASE}/audit-events", params={"actor_role": "root"}).status_code == 422


def test_date_range_includes_from_and_excludes_to(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    t0 = datetime(2026, 10, 3, 10, 0, tzinfo=UTC)
    for n, name in enumerate(("a", "b", "c")):
        _event(postgres_session, t0 + timedelta(seconds=n), target_id=name)
    postgres_session.commit()
    moderator = _staff(client, postgres_session, fake, "moderator", 4)

    def ids(**params: Any) -> list[str]:
        response = moderator.get(f"{BASE}/audit-events", params=params)
        assert response.status_code == 200, response.text
        return [item["target_id"] for item in response.json()["items"]]

    assert ids(**{"from": (t0 + timedelta(seconds=1)).isoformat()}) == ["c", "b"]
    assert ids(to=(t0 + timedelta(seconds=2)).isoformat()) == ["b", "a"]
    assert ids(**{"from": (t0 + timedelta(seconds=1)).isoformat(), "to": (t0 + timedelta(seconds=2)).isoformat()}) == ["b"]
    inverted = moderator.get(f"{BASE}/audit-events", params={"from": t0.isoformat(), "to": t0.isoformat()})
    assert inverted.status_code == 422 and inverted.json()["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_limit_must_be_between_one_and_one_hundred(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, limit: int) -> None:
    moderator = _staff(client, postgres_session, fake, "moderator", 5)
    assert moderator.get(f"{BASE}/audit-events", params={"limit": limit}).status_code == 422
    assert moderator.get(f"{BASE}/audit-events", params={"limit": 1}).status_code == 200
    assert moderator.get(f"{BASE}/audit-events", params={"limit": 100}).status_code == 200


@pytest.mark.parametrize("cursor", ["garbage", "", "MjAyNi0xMC0wMVQxMjowMDowMHxub3QtYS11dWlk", "bm8tYmFy", "MjAyNi0xMC0wMVQxMjowMDowMHw="])
def test_a_bad_cursor_is_refused(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, cursor: str) -> None:
    moderator = _staff(client, postgres_session, fake, "moderator", 6)
    response = moderator.get(f"{BASE}/audit-events", params={"cursor": cursor} if cursor else {"cursor": "!!"})
    assert response.status_code == 422 and response.json()["error"]["code"] == "INVALID_CURSOR"


def test_the_older_before_parameter_still_works(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    t0 = datetime(2026, 10, 4, 8, 0, tzinfo=UTC)
    for n in range(3):
        _event(postgres_session, t0 + timedelta(minutes=n), target_id=f"e{n}")
    postgres_session.commit()
    moderator = _staff(client, postgres_session, fake, "moderator", 7)
    items = moderator.get(f"{BASE}/audit-events", params={"before": (t0 + timedelta(minutes=2)).isoformat()}).json()["items"]
    assert [item["target_id"] for item in items] == ["e1", "e0"]


def test_one_event_by_id_and_unknown_ids(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    event = _event(postgres_session, datetime.now(UTC), target_id="one")
    postgres_session.commit()
    moderator = _staff(client, postgres_session, fake, "moderator", 8)
    assert moderator.get(f"{BASE}/audit-events/{event.id}").json()["target_id"] == "one"
    assert moderator.get(f"{BASE}/audit-events/{uuid.uuid4()}").status_code == 404


def test_the_log_is_for_staff_only(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    anonymous = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.92"})
    assert anonymous.get(f"{BASE}/audit-events").status_code == 401
    member = admin.staff_client(client, postgres_session, fake, "reader@example.test", None, "203.0.113.93", aal="aal1")
    assert member.get(f"{BASE}/audit-events").status_code == 404


# ---- export ----


def _rows(response: Any) -> list[dict[str, str]]:
    return list(csv.DictReader(io.StringIO(response.text)))


def test_a_superadmin_exports_csv_and_the_export_is_itself_audited(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    now = datetime(2026, 10, 5, 7, 0, tzinfo=UTC)
    _event(postgres_session, now, action="report.create", target_type="review", target_id="r1", reason="spam")
    _event(postgres_session, now - timedelta(seconds=1), action="report.dismissed", target_type="report", target_id="p1")
    postgres_session.commit()
    boss = _staff(client, postgres_session, fake, "superadmin", 9)
    response = boss.get(f"{BASE}/audit-events/export", params={"action": "report.create"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv") and "attachment" in response.headers["content-disposition"]
    assert response.headers["x-row-count"] == "1" and response.headers["x-truncated"] == "false"
    rows = _rows(response)
    assert [row["target_id"] for row in rows] == ["r1"] and rows[0]["reason"] == "spam"
    assert list(rows[0]) == ["id", "occurred_at", "actor_user_id", "actor_role", "action", "target_type", "target_id", "request_id", "reason", "metadata"]
    postgres_session.expire_all()
    logged = postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "audit.exported"))
    assert logged is not None and logged.actor_role_snapshot == "superadmin"
    assert logged.event_metadata == {"filters": {"action": "report.create"}, "rows": 1, "truncated": False}


def test_an_export_stops_at_the_cap_and_says_so(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audit_module, "EXPORT_LIMIT", 5)
    base = datetime(2026, 10, 6, 7, 0, tzinfo=UTC)
    for n in range(8):
        _event(postgres_session, base + timedelta(seconds=n), action="task.released")
    postgres_session.commit()
    boss = _staff(client, postgres_session, fake, "superadmin", 10)
    response = boss.get(f"{BASE}/audit-events/export", params={"action": "task.released"})
    assert response.headers["x-row-count"] == "5" and response.headers["x-truncated"] == "true" and len(_rows(response)) == 5


@pytest.mark.parametrize("payload", ["=HYPERLINK(\"http://evil\",\"x\")", "+SUM(1)", "-2+3", "@cmd", "\tTAB"])
def test_export_cells_cannot_run_as_spreadsheet_formulas(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, payload: str) -> None:
    _event(postgres_session, datetime(2026, 10, 7, tzinfo=UTC), action="task.assigned", reason=payload, target_id=payload)
    postgres_session.commit()
    boss = _staff(client, postgres_session, fake, "superadmin", 11)
    row = _rows(boss.get(f"{BASE}/audit-events/export", params={"action": "task.assigned"}))[0]
    assert row["reason"] == "'" + payload and row["target_id"] == "'" + payload


def test_a_moderator_cannot_export_and_the_attempt_is_audited(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    moderator = _staff(client, postgres_session, fake, "moderator", 12)
    assert moderator.get(f"{BASE}/audit-events/export").status_code == 403
    anonymous = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.94"})
    assert anonymous.get(f"{BASE}/audit-events/export").status_code == 401
    member = admin.staff_client(client, postgres_session, fake, "nobody@example.test", None, "203.0.113.95", aal="aal1")
    assert member.get(f"{BASE}/audit-events/export").status_code == 404
    assert postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "audit.exported")) is None


def test_an_export_with_inverted_dates_is_refused_and_not_audited(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    boss = _staff(client, postgres_session, fake, "superadmin", 13)
    now = datetime(2026, 10, 8, tzinfo=UTC).isoformat()
    assert boss.get(f"{BASE}/audit-events/export", params={"from": now, "to": now}).status_code == 422
    assert postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "audit.exported")) is None


# ---- completeness: no state-changing route can ship without a decision about its audit trail ----

# route -> the audit action(s) it writes, or None with the reason it writes none. A new write route that is not
# listed here fails the test below, so the author has to decide how it is audited.
AUDITED: dict[str, tuple[str, ...] | str] = {
    "POST /api/v1/admin/appeals/{appeal_id}/decision": ("appeal.upheld", "appeal.overturned"),
    "POST /api/v1/admin/bulk/moderation-actions": ("review.publish",),
    "POST /api/v1/admin/enforcement-cases": ("enforcement.opened",),
    "POST /api/v1/admin/enforcement-cases/{case_id}/actions": ("enforcement.remove", "enforcement.restore", "enforcement.close"),
    "POST /api/v1/admin/media/{media_id}/decision": ("media.approve", "media.reject"),
    "POST /api/v1/admin/members/{user_id}/verification/revoke": ("verification.revoke_for_abuse",),
    "POST /api/v1/admin/notification-deliveries/{delivery_id}/retry": ("notification.delivery_retried",),
    "PATCH /api/v1/admin/notification-rules/{template_key}": ("notification.rule_changed",),
    "POST /api/v1/admin/notification-suppressions": ("notification.suppression_added",),
    "DELETE /api/v1/admin/notification-suppressions/{suppression_id}": ("notification.suppression_removed",),
    "POST /api/v1/admin/notification-templates/{template_key}/versions": ("notification.template_drafted",),
    "POST /api/v1/admin/notification-templates/{template_key}/versions/{version}/activate": ("notification.template_activated",),
    "POST /api/v1/admin/ratings/reconcile": ("ratings.reconcile_run", "ratings.reconcile_repair"),
    "POST /api/v1/admin/reports/{report_id}/hide-pending": ("report.hide_pending",),
    "POST /api/v1/admin/reports/{report_id}/transition": ("report.in_review", "report.actioned", "report.dismissed"),
    "POST /api/v1/admin/reviews/{review_id}/reopen": ("review.reopen",),
    "POST /api/v1/admin/staff/{user_id}/role": ("staff.role_changed", "staff.role_granted", "staff.role_revoked"),
    "POST /api/v1/admin/submissions/{review_id}/conflict": ("review.conflict_set",),
    "POST /api/v1/admin/submissions/{review_id}/media/{media_id}/url": "a signed link to look at a file; the view is not a change",
    "POST /api/v1/admin/submissions/{review_id}/moderation-actions": ("review.publish", "review.reject", "review.hide", "review.restore", "review.request_changes"),
    "POST /api/v1/admin/tasks/{task_id}/assign": ("task.assigned",),
    "POST /api/v1/admin/tasks/{task_id}/claim": ("task.claimed",),
    "POST /api/v1/admin/tasks/{task_id}/escalate": ("task.escalated",),
    "POST /api/v1/admin/tasks/{task_id}/heartbeat": "lease renewal every minute would bury the log; the claim and release are audited",
    "POST /api/v1/admin/tasks/{task_id}/release": ("task.released",),
    "POST /api/v1/admin/verification-cases/{case_id}/evidence/{evidence_id}/url": ("evidence.viewed",),
    "POST /api/v1/admin/verification-cases/{case_id}/transition": ("verification.approved", "verification.rejected", "verification.escalated"),
    "POST /api/v1/ops/jobs/rating-reconciliation": ("ratings.reconcile_run",),
    "POST /api/v1/ops/jobs/retention": ("review.purged", "retention.contact_erased", "retention.evidence_purged"),
    "POST /api/v1/ops/jobs/visit-rollup": "copies visitor counters; no person or content changes",
    "POST /api/v1/public/removal-requests": ("removal_request.create",),
    "POST /api/v1/public/review-reports": ("report.create_anonymous",),
    "POST /api/v1/reviews/{review_id}/reports": ("report.create",),
}


def test_every_state_changing_staff_and_report_route_has_a_stated_audit_trail() -> None:
    from app.main import create_app

    found = {
        f"{method.upper()} {path}"
        for path, operations in create_app().openapi()["paths"].items()
        for method in operations
        if method.upper() in ("POST", "PUT", "PATCH", "DELETE")
        and (path.startswith(("/api/v1/admin", "/api/v1/ops", "/api/v1/public")) or path == "/api/v1/reviews/{review_id}/reports")
    }
    assert found == set(AUDITED), f"unlisted: {sorted(found - set(AUDITED))}, stale: {sorted(set(AUDITED) - found)}"
    for route, actions in AUDITED.items():
        if isinstance(actions, str):
            assert len(actions) > 20, f"{route}: say why no audit row is written"
        else:
            assert all(is_known(action) for action in actions), (route, [a for a in actions if not is_known(a)])


def test_every_listed_action_is_written_somewhere_in_the_code() -> None:
    from pathlib import Path

    source = "\n".join(path.read_text(encoding="utf-8") for path in Path("app").rglob("*.py"))
    families = {f"{prefix}.{suffix}" for prefix, suffixes in FAMILIES.items() for suffix in suffixes}
    for action in sorted(FIXED):
        assert f'"{action}"' in source or action in families, f"{action} is listed but nothing writes it"
    for prefix in FAMILIES:
        assert f'f"{prefix}.' in source or any(f'"{prefix}.' in source for _ in [0]), prefix


# ---- no secrets in the audit rows the new actions write ----


def test_the_new_actions_never_write_secrets_or_personal_data(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    import test_rating_exclusion as helpers

    from app.models import ReviewStatus  # noqa: F401

    session = postgres_session
    moderator = helpers._user(session, "Moderator")  # noqa: SLF001
    review = helpers._publish(session, helpers._review(session, helpers._destination(session, "Audit PII"), helpers._verified_member(session)), moderator)  # noqa: SLF001
    reader = admin.staff_client(client, session, fake, "pii-reader@example.test", None, "203.0.113.240", aal="aal1")
    reader.post(f"/api/v1/reviews/{review.id}/reports", json={"reason_code": "privacy", "details": "my phone is 01712345678 and my email is pii@example.test"})
    dump = str([(e.reason, e.event_metadata, e.target_id, e.request_id) for e in session.scalars(select(AuditEvent))])
    for secret in ("01712345678", "pii@example.test", "pii-reader@example.test", "csrf", "eyJ", "abr1_"):
        assert secret not in dump
