"""R11 moderation actions (Review.md 5.4; Moderation spec 11.1, P-00, P-03, P-06): hide pending a decision, a
takedown that keeps the rating, reopen, the Rejected and Hidden lists, the 30-day purge, and the reason catalogue."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import test_admin as admin
import test_auth as support
import test_cases as cases_tests
import test_rating_exclusion as helpers
from conftest import backdate_decisions
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app import reasons
from app.errors import ApiError
from app.jobs import retention
from app.models import (
    Appeal,
    AuditEvent,
    Destination,
    DestinationRatingStats,
    EnforcementCase,
    ModerationActionRecord,
    ModerationDecision,
    ModerationTask,
    Notification,
    OutboxEvent,
    RatingEligibility,
    Report,
    Review,
    ReviewCategory,
    ReviewMedia,
    ReviewRevision,
    ReviewStatus,
    RevisionStatus,
    User,
)
from app.rating_integrity import reconcile
from app.services import moderate_review, set_hidden_rating_kept, withdraw_review

auth_env = support.auth_env
fake = support.fake
redis_fake = support.redis_fake
pytestmark = pytest.mark.integration
BASE = "/api/v1/admin"
API = "/api/v1"

_destination, _verified_member, _review, _publish, _user, _stats = (
    helpers._destination, helpers._verified_member, helpers._review, helpers._publish, helpers._user, helpers._stats,  # noqa: SLF001
)
moderator = helpers.moderator


class FakeMediaStorage:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, keys: list[str], bucket: str = "") -> None:
        self.deleted += keys


@pytest.fixture()
def client(auth_env: None, postgres_session: Session, fake: support.FakeGoTrue, redis_fake: Any) -> TestClient:
    return support.make_client(postgres_session, fake, redis_fake)


def _staff(client: TestClient, session: Session, fake: support.FakeGoTrue, role: str, n: int) -> TestClient:
    return admin.staff_client(client, session, fake, f"{role}-act{n}@example.test", role, f"203.0.113.{140 + n}")


def _reported(client: TestClient, session: Session, fake: support.FakeGoTrue, moderator: User, n: int, *, reason: str = "privacy", rating: int = 5) -> tuple[Review, Report, TestClient, ModerationTask, dict[str, Any]]:
    review = _publish(session, _review(session, _destination(session, f"Place {n}"), _verified_member(session), rating=rating), moderator)
    reader = admin.staff_client(client, session, fake, f"reader-act{n}@example.test", None, f"203.0.113.{170 + n}", aal="aal1")
    report_id = reader.post(f"{API}/reviews/{review.id}/reports", json={"reason_code": reason}).json()["report_id"]
    staff = _staff(client, session, fake, "moderator", n)
    report = session.get(Report, uuid.UUID(report_id))
    assert report is not None
    task = session.scalar(select(ModerationTask).where(ModerationTask.subject_id == report.id))
    assert task is not None
    return review, report, staff, task, admin._claim(staff, task)  # noqa: SLF001


def _hide(staff: TestClient, report: Report, task: ModerationTask, lease: dict[str, Any], **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "expected_version": report.version, "reason_code": "privacy-pending", "counts_toward_rating": False,
        "task_id": str(task.id), "lease_token": lease["lease_token"],
    }
    body.update(overrides)
    return staff.post(f"{BASE}/reports/{report.id}/hide-pending", json=body)


def _count_actions(session: Session, action: str) -> int:
    return int(session.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == action)) or 0)


# ---- hide pending a decision ----


def test_a_moderator_hides_a_reported_review_until_a_decision_is_recorded(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    review, report, staff, task, lease = _reported(client, session, fake, moderator, 1)
    started = report.version
    done = _hide(staff, report, task, lease)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["state"] == "in_review" and body["version"] == started + 1 and body["review_status"] == "HIDDEN"
    session.expire_all()
    stored = session.get(Review, review.id)
    assert stored is not None and stored.status == ReviewStatus.HIDDEN
    case = session.get(EnforcementCase, uuid.UUID(body["case_id"]))
    assert case is not None and case.kind == "takedown" and case.state == "taken_down" and case.counts_toward_rating is False
    assert _count_actions(session, "report.hide_pending") == 1 and _count_actions(session, "enforcement.opened") == 1
    audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "report.hide_pending"))
    assert audit is not None and audit.reason == "privacy-pending" and audit.event_metadata["case_id"] == body["case_id"]
    topics = {event.topic for event in session.scalars(select(OutboxEvent))}
    assert {"review.state_changed", "enforcement.opened"} <= topics
    assert session.get(ModerationTask, task.id).status == "open", "the report stays open until a recorded decision"  # type: ignore[union-attr]


def test_the_author_is_told_when_their_review_is_hidden(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    from app.notify import worker

    session = postgres_session
    review, report, staff, task, lease = _reported(client, session, fake, moderator, 2)
    assert _hide(staff, report, task, lease).status_code == 200
    worker.run_once(cases_tests.factory(session), cases_tests.RecordingProvider())
    session.expire_all()
    kinds = {n.kind for n in session.scalars(select(Notification).where(Notification.recipient_user_id == review.author_user_id))}
    assert kinds & {"content.hidden", "content.taken_down"}, kinds


@pytest.mark.parametrize("keep", [False, True])
def test_the_moderator_chooses_whether_the_rating_stays(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User, keep: bool) -> None:
    session = postgres_session
    review, report, staff, task, lease = _reported(client, session, fake, moderator, 3 + int(keep), rating=5)
    destination = session.get(Destination, review.destination_id)
    # The privacy report already took the rating out (R08); the moderator's choice below decides whether it returns.
    assert destination is not None and _stats(session, destination) == ((0, 0), (0, 0))
    assert _hide(staff, report, task, lease, counts_toward_rating=keep).status_code == 200
    session.expire_all()
    stored = session.get(Review, review.id)
    assert stored is not None
    if keep:
        assert stored.counted_rating == 5 and stored.rating_eligibility == RatingEligibility.ELIGIBLE
        assert _stats(session, destination) == ((5, 1), (0, 0))
    else:
        assert stored.counted_rating is None and stored.rating_eligibility == RatingEligibility.INELIGIBLE_REPORTED
        assert _stats(session, destination) == ((0, 0), (0, 0))
    assert reconcile(session).clean
    public = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.99"})
    feed = public.get(f"{API}/destinations/{destination.id}/reviews").json()["items"]
    assert str(review.id) not in {item["id"] for item in feed}, "a hidden review is never shown, whatever its rating does"


def test_hide_pending_refuses_the_unauthorised_the_stale_and_the_already_hidden(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    review, report, staff, task, lease = _reported(client, session, fake, moderator, 5)
    member = admin.staff_client(client, session, fake, "curious@example.test", None, "203.0.113.150", aal="aal1")
    assert _hide(member, report, task, lease).status_code == 404
    anonymous = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.151"})
    assert _hide(anonymous, report, task, lease).status_code == 401
    assert _hide(staff, report, task, {"lease_token": str(uuid.uuid4())}).status_code == 409, "a lease that is not yours"
    assert _hide(staff, report, task, lease, expected_version=99).status_code == 409
    assert _hide(staff, report, task, lease, reason_code="spam").status_code == 422, "a reject reason is not a hide reason"
    assert _hide(staff, report, task, lease, reason_code="made-up").status_code == 422
    assert _hide(staff, report, task, lease, surprise=1).status_code == 422
    session.expire_all()
    stored = session.get(Review, review.id)
    assert stored is not None and stored.status == ReviewStatus.PUBLISHED
    assert _hide(staff, report, task, lease).status_code == 200
    again = _hide(staff, report, task, lease, expected_version=report.version)  # the live report is now at its new version
    assert again.status_code == 422 and again.json()["error"]["code"] == "TRANSITION_NOT_ALLOWED"


def test_a_moderator_cannot_hide_their_own_review_this_way(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    review, report, staff, task, lease = _reported(client, session, fake, moderator, 6)
    review.author_user_id = fake.users["moderator-act6@example.test"]["id"]
    session.commit()
    answer = _hide(staff, report, task, lease)
    assert answer.status_code == 403 and answer.json()["error"]["code"] == "SELF_MODERATION_FORBIDDEN"


def test_a_failure_while_hiding_leaves_no_half_state(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User, monkeypatch: pytest.MonkeyPatch) -> None:
    session = postgres_session
    review, report, staff, task, lease = _reported(client, session, fake, moderator, 7, reason="spam")
    started = report.version
    from app.admin import actions as actions_module

    original = actions_module.audit.record

    def failing(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("action") == "report.hide_pending":
            raise RuntimeError("audit store is down")
        return original(*args, **kwargs)

    monkeypatch.setattr(actions_module.audit, "record", failing)
    with pytest.raises(RuntimeError):
        _hide(staff, report, task, lease)
    session.rollback()
    session.expire_all()
    stored = session.get(Review, review.id)
    assert stored is not None and stored.status == ReviewStatus.PUBLISHED and stored.counted_rating == 5
    assert session.scalar(select(func.count()).select_from(EnforcementCase)) == 0
    assert session.get(Report, report.id).version == started  # type: ignore[union-attr]
    assert _count_actions(session, "enforcement.opened") == 0 and _count_actions(session, "report.hide_pending") == 0


def test_restoring_after_a_hide_pending_counts_the_rating_again(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    review, report, staff, task, lease = _reported(client, session, fake, moderator, 8, reason="spam")
    body = _hide(staff, report, task, lease).json()
    session.expire_all()
    hidden = session.get(Review, review.id)
    assert hidden is not None
    restored = staff.post(
        f"{BASE}/submissions/{review.id}/moderation-actions",
        json=admin._decision(task, lease["lease_token"], hidden, decision="RESTORE"),  # noqa: SLF001
    )
    assert restored.status_code == 200 and restored.json()["status"] == "PUBLISHED" and restored.json()["counted_rating"] == 5
    destination = session.get(Destination, review.destination_id)
    assert destination is not None and _stats(session, destination) == ((5, 1), (0, 0))
    assert body["state"] == "in_review"


# ---- P-00: a takedown that keeps the rating ----


def _hidden_review(session: Session, moderator: User, *, keep: bool, rating: int = 4, author: User | None = None) -> Review:
    review = _publish(session, _review(session, _destination(session, f"Kept {uuid.uuid4().hex[:6]}"), author or _verified_member(session), rating=rating), moderator)
    moderate_review(
        session, review_id=review.id, actor_user_id=moderator.id, expected_version=review.version, decision=ModerationDecision.HIDE,
        reason_code="privacy-pending", note=None, keep_rating=keep,
    )
    session.commit()
    session.refresh(review)
    return review


def _dest(session: Session, review: Review) -> Any:
    return session.get(Destination, review.destination_id)


def test_a_kept_rating_stays_in_the_totals_while_the_review_is_hidden(postgres_session: Session, moderator: User) -> None:
    review = _hidden_review(postgres_session, moderator, keep=True)
    assert review.status == ReviewStatus.HIDDEN and review.counted_rating == 4 and review.rating_eligibility == RatingEligibility.ELIGIBLE
    assert _stats(postgres_session, _dest(postgres_session, review)) == ((4, 1), (0, 0))
    assert reconcile(postgres_session).clean


def test_a_plain_hide_removes_the_rating_by_default(postgres_session: Session, moderator: User) -> None:
    review = _hidden_review(postgres_session, moderator, keep=False)
    assert review.counted_rating is None and review.rating_eligibility == RatingEligibility.INELIGIBLE_REPORTED
    assert _stats(postgres_session, _dest(postgres_session, review)) == ((0, 0), (0, 0))


def test_changing_the_flag_later_moves_the_totals(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    review = _hidden_review(session, moderator, keep=True)
    destination = _dest(session, review)
    set_hidden_rating_kept(session, review.id, False)
    session.commit()
    session.refresh(review)
    assert review.counted_rating is None and _stats(session, destination) == ((0, 0), (0, 0)) and reconcile(session).clean
    version = review.version
    set_hidden_rating_kept(session, review.id, False)  # no change: no version bump
    session.commit()
    session.refresh(review)
    assert review.version == version
    set_hidden_rating_kept(session, review.id, True)
    session.commit()
    session.refresh(review)
    assert review.counted_rating == 4 and review.rating_eligibility == RatingEligibility.ELIGIBLE
    assert _stats(session, destination) == ((4, 1), (0, 0)) and reconcile(session).clean


def test_a_kept_rating_is_still_subject_to_the_eligibility_rules(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    review = _hidden_review(session, moderator, keep=False)
    review.conflict_declared = True
    session.commit()
    set_hidden_rating_kept(session, review.id, True)
    session.commit()
    session.refresh(review)
    assert review.counted_rating is None and review.rating_eligibility == RatingEligibility.INELIGIBLE_CONFLICT
    assert _stats(session, _dest(session, review)) == ((0, 0), (0, 0))


def test_a_kept_guest_rating_stays_in_guest_feedback(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    destination = _destination(session, "Guest kept")
    guest = _publish(session, _review(session, destination, None, rating=3), moderator)
    moderate_review(session, review_id=guest.id, actor_user_id=moderator.id, expected_version=guest.version, decision=ModerationDecision.HIDE, reason_code="privacy-pending", note=None, keep_rating=True)
    session.commit()
    assert _stats(session, destination) == ((0, 0), (3, 1)) and reconcile(session).clean


def test_withdrawing_a_kept_review_uncounts_it_once(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    review = _hidden_review(session, moderator, keep=True)
    withdraw_review(session, review.id, review.version)
    session.commit()
    withdraw_review(session, review.id, review.version)  # a retry changes nothing
    session.commit()
    assert _stats(session, _dest(session, review)) == ((0, 0), (0, 0)) and reconcile(session).clean


def test_reconciliation_finds_a_kept_rating_missing_from_the_totals(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    review = _hidden_review(session, moderator, keep=True)
    row = session.get(DestinationRatingStats, review.destination_id)
    assert row is not None
    row.community_rating_sum, row.community_rating_count = 0, 0
    session.commit()
    found = reconcile(session)
    assert [d.kind for d in found.drifts] == ["community"] and found.drifts[0].expected == (4, 1)
    reconcile(session, repair=True, actor=None)
    session.commit()
    assert reconcile(session).clean


def test_a_takedown_opened_over_http_keeps_the_rating_only_when_asked(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    boss = _staff(client, session, fake, "superadmin", 20)
    kept = _publish(session, _review(session, _destination(session, "HTTP kept"), _verified_member(session), rating=5), moderator)
    dropped = _publish(session, _review(session, _destination(session, "HTTP dropped"), _verified_member(session), rating=5), moderator)
    a = boss.post(f"{BASE}/enforcement-cases", json={"review_id": str(kept.id), "reason_code": "privacy-pending", "counts_toward_rating": True})
    b = boss.post(f"{BASE}/enforcement-cases", json={"review_id": str(dropped.id), "reason_code": "privacy-pending"})
    assert a.status_code == 201 and b.status_code == 201
    assert _stats(session, _dest(session, kept)) == ((5, 1), (0, 0)), "kept on request"
    assert _stats(session, _dest(session, dropped)) == ((0, 0), (0, 0)), "removed by default"
    case = a.json()
    changed = boss.post(f"{BASE}/enforcement-cases/{case['case_id']}/actions", json={"action": "remove", "expected_version": case["version"], "reason_code": "policy-violation", "counts_toward_rating": False})
    assert changed.status_code == 200 and changed.json()["counts_toward_rating"] is False
    assert _stats(session, _dest(session, kept)) == ((0, 0), (0, 0)), "changing the flag moved the totals"
    assert reconcile(session).clean


@settings(max_examples=30, suppress_health_check=[HealthCheck.function_scoped_fixture], deadline=None)
@given(steps=st.lists(st.tuples(st.integers(0, 1), st.sampled_from(["publish", "hide_keep", "hide_drop", "keep_on", "keep_off", "restore", "withdraw"])), min_size=1, max_size=25))
def test_random_takedowns_keep_the_totals_equal_to_a_full_recompute(postgres_session: Session, steps: list[tuple[int, str]]) -> None:
    session = postgres_session
    destination, staff = _destination(session), _user(session, "Moderator")
    reviews = [
        _review(session, destination, _verified_member(session), rating=5, categories={ReviewCategory.FOOD: 5}),  # noqa: SLF001
        _review(session, destination, None, rating=2, categories={ReviewCategory.FOOD: 2}),  # noqa: SLF001
    ]
    for index, step in steps:
        review = session.get(Review, reviews[index].id)
        assert review is not None
        session.refresh(review)

        def decide(decision: ModerationDecision, keep: bool = False, review: Review = review) -> None:
            moderate_review(session, review_id=review.id, actor_user_id=staff.id, expected_version=review.version, decision=decision, reason_code="PROP", note=None, keep_rating=keep)

        if step == "publish" and review.status == ReviewStatus.PENDING:
            decide(ModerationDecision.PUBLISH)
        elif step in ("hide_keep", "hide_drop") and review.status == ReviewStatus.PUBLISHED:
            decide(ModerationDecision.HIDE, keep=step == "hide_keep")
        elif step in ("keep_on", "keep_off") and review.status == ReviewStatus.HIDDEN:
            set_hidden_rating_kept(session, review.id, step == "keep_on")
        elif step == "restore" and review.status == ReviewStatus.HIDDEN:
            decide(ModerationDecision.RESTORE)
        elif step == "withdraw" and review.status not in {ReviewStatus.WITHDRAWN, ReviewStatus.DELETED}:
            withdraw_review(session, review.id, review.version)
        session.commit()
        result = reconcile(session)
        assert result.clean, [(d.kind, d.key, d.stored, d.expected) for d in result.drifts]


def test_restore_racing_a_flag_change_ends_consistent(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    review = _hidden_review(session, moderator, keep=True)
    engine = create_engine(session.get_bind().url.render_as_string(hide_password=False), pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = threading.Barrier(2)

    def restore() -> None:
        with factory() as worker:
            barrier.wait()
            current = worker.get(Review, review.id)
            assert current is not None
            moderate_review(worker, review_id=review.id, actor_user_id=moderator.id, expected_version=current.version, decision=ModerationDecision.RESTORE, reason_code="hidden-in-error", note=None)
            worker.commit()

    def flip() -> None:
        with factory() as worker:
            barrier.wait()
            set_hidden_rating_kept(worker, review.id, False)
            worker.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(restore), pool.submit(flip)]
        outcomes = []
        for future in futures:
            try:
                future.result()
                outcomes.append("ok")
            except Exception as error:  # noqa: BLE001 - a stale version is an acceptable loser
                outcomes.append(type(error).__name__)
    engine.dispose()
    session.expire_all()
    assert "ok" in outcomes
    assert reconcile(session).clean, "whatever the order, the totals match the rows"


# ---- reopen ----


def _rejected(session: Session, moderator: User, *, days_ago: int = 1, author: User | None = None) -> Review:
    review = _review(session, _destination(session, f"Rej {uuid.uuid4().hex[:6]}"), author or _verified_member(session))
    moderate_review(session, review_id=review.id, actor_user_id=moderator.id, expected_version=review.version, decision=ModerationDecision.REJECT, reason_code="spam", note=None)
    session.commit()
    backdate_decisions(session, datetime.now(UTC) - timedelta(days=days_ago), review_id=review.id)
    session.commit()
    session.refresh(review)
    return review


def _reopen(boss: TestClient, review: Review, **overrides: Any) -> Any:
    body: dict[str, Any] = {"expected_version": review.version, "reason_code": "rejected-in-error"}
    body.update(overrides)
    return boss.post(f"{BASE}/reviews/{review.id}/reopen", json=body)


@pytest.mark.parametrize("days", [1, 29])
def test_a_superadmin_reopens_a_rejected_review_inside_the_window(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User, days: int) -> None:
    session = postgres_session
    review = _rejected(session, moderator, days_ago=days)
    boss = _staff(client, session, fake, "superadmin", 21)
    before = review.version
    answer = _reopen(boss, review)
    assert answer.status_code == 200 and answer.json()["status"] == "PENDING" and answer.json()["version"] == before + 1
    session.expire_all()
    stored = session.get(Review, review.id)
    assert stored is not None and stored.status == ReviewStatus.PENDING and stored.rating_eligibility == RatingEligibility.NOT_EVALUATED
    revision = session.get(ReviewRevision, stored.current_revision_id)
    assert revision is not None and revision.status == RevisionStatus.PENDING
    task = session.scalar(select(ModerationTask).where(ModerationTask.subject_id == review.id, ModerationTask.status == "open"))
    assert task is not None and task.priority == 1, "back in the queue, ahead of ordinary reviews"
    record = session.scalar(select(ModerationActionRecord).where(ModerationActionRecord.decision == ModerationDecision.REOPEN))
    assert record is not None and record.previous_status == ReviewStatus.REJECTED and record.new_status == ReviewStatus.PENDING
    audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "review.reopen"))
    assert audit is not None and audit.reason == "rejected-in-error" and audit.actor_role_snapshot == "superadmin"
    event = session.scalar(select(OutboxEvent).where(OutboxEvent.topic == "review.state_changed").order_by(OutboxEvent.created_at.desc()))
    assert event is not None and event.payload["decision"] == "REOPEN"


def test_the_window_closes_after_thirty_days(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    review = _rejected(postgres_session, moderator, days_ago=31)
    boss = _staff(client, postgres_session, fake, "superadmin", 22)
    answer = _reopen(boss, review)
    assert answer.status_code == 409 and answer.json()["error"]["code"] == "REOPEN_WINDOW_CLOSED"
    postgres_session.expire_all()
    assert postgres_session.get(Review, review.id).status == ReviewStatus.REJECTED  # type: ignore[union-attr]


def test_a_purged_review_cannot_be_reopened(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    review = _rejected(postgres_session, moderator, days_ago=2)
    review.purged_at = datetime.now(UTC)
    postgres_session.commit()
    boss = _staff(client, postgres_session, fake, "superadmin", 23)
    assert _reopen(boss, review).json()["error"]["code"] == "REOPEN_WINDOW_CLOSED"


def test_only_a_superadmin_can_reopen_and_a_refusal_is_audited(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    review = _rejected(postgres_session, moderator)
    mod = _staff(client, postgres_session, fake, "moderator", 24)
    assert _reopen(mod, review).status_code == 403
    denied = postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "denied.role"))
    assert denied is not None and denied.actor_role_snapshot == "moderator" and denied.reason == "needs superadmin"
    assert denied.target_id == "POST /api/v1/admin/reviews/{review_id}/reopen" or denied.target_id.startswith("POST /api/v1/admin/reviews/")
    member = admin.staff_client(client, postgres_session, fake, "plain-act@example.test", None, "203.0.113.160", aal="aal1")
    assert _reopen(member, review).status_code == 404
    anonymous = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.161"})
    assert _reopen(anonymous, review).status_code == 401
    postgres_session.expire_all()
    assert postgres_session.get(Review, review.id).status == ReviewStatus.REJECTED  # type: ignore[union-attr]


def test_reopen_validates_state_version_reason_and_input(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    review = _rejected(session, moderator)
    boss = _staff(client, session, fake, "superadmin", 25)
    assert _reopen(boss, review, expected_version=99).status_code == 409
    assert _reopen(boss, review, reason_code="spam").status_code == 422, "a reject reason is not a reopen reason"
    assert _reopen(boss, review, extra=1).status_code == 422
    published = _publish(session, _review(session, _destination(session, "Not rejected"), _verified_member(session)), moderator)
    wrong_state = _reopen(boss, published)
    assert wrong_state.status_code == 422 and wrong_state.json()["error"]["code"] == "TRANSITION_NOT_ALLOWED"
    assert _reopen(boss, review).status_code == 200
    again = _reopen(boss, review, expected_version=review.version)  # the live object holds the new version
    assert again.status_code == 422, "a reopened review is no longer rejected"


def test_a_moderator_cannot_reopen_their_own_rejected_review(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    review = _rejected(session, moderator)
    boss = _staff(client, session, fake, "superadmin", 26)
    review.author_user_id = fake.users["superadmin-act26@example.test"]["id"]
    session.commit()
    assert _reopen(boss, review).json()["error"]["code"] == "SELF_MODERATION_FORBIDDEN"


# ---- Rejected and Hidden lists ----


def test_the_lists_show_the_recovery_window_and_page_without_repeats(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    rejected = [_rejected(session, moderator, days_ago=n + 1) for n in range(5)]
    hidden = _hidden_review(session, moderator, keep=False)
    staff = _staff(client, session, fake, "moderator", 27)
    seen: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(4):
        params: dict[str, Any] = {"status": "REJECTED", "limit": 2}
        if cursor:
            params["after"] = cursor
        page = staff.get(f"{BASE}/reviews", params=params).json()
        seen += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert [item["review_id"] for item in seen] == [str(r.id) for r in rejected], "newest decision first, each exactly once"
    first = seen[0]
    assert first["status"] == "REJECTED" and first["reason_code"] == "spam" and first["purged"] is False and first["title"] == "Clean and calm"
    decided = datetime.fromisoformat(first["decided_at"])
    assert datetime.fromisoformat(first["recoverable_until"]) - decided == timedelta(days=30)
    listing = staff.get(f"{BASE}/reviews", params={"status": "HIDDEN"}).json()["items"]
    assert [item["review_id"] for item in listing] == [str(hidden.id)] and listing[0]["recoverable_until"] is None


def test_a_purged_review_shows_no_text_and_no_deadline(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    review = _rejected(postgres_session, moderator, days_ago=40)
    review.purged_at = datetime.now(UTC)
    postgres_session.commit()
    staff = _staff(client, postgres_session, fake, "moderator", 28)
    item = staff.get(f"{BASE}/reviews", params={"status": "REJECTED"}).json()["items"][0]
    assert item["title"] == "[removed]" and item["purged"] is True and item["recoverable_until"] is None


@pytest.mark.parametrize("params", [{}, {"status": "PUBLISHED"}, {"status": "rejected"}, {"status": "REJECTED", "limit": 0}, {"status": "REJECTED", "limit": 101}])
def test_list_parameters_are_validated(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, params: dict[str, Any]) -> None:
    staff = _staff(client, postgres_session, fake, "moderator", 29)
    assert staff.get(f"{BASE}/reviews", params=params).status_code == 422
    assert staff.get(f"{BASE}/reviews", params={"status": "REJECTED", "after": "!!"}).json()["error"]["code"] == "INVALID_CURSOR"


def test_the_lists_are_for_staff_only(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    anonymous = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.162"})
    assert anonymous.get(f"{BASE}/reviews", params={"status": "HIDDEN"}).status_code == 401
    member = admin.staff_client(client, postgres_session, fake, "plain-list@example.test", None, "203.0.113.163", aal="aal1")
    assert member.get(f"{BASE}/reviews", params={"status": "HIDDEN"}).status_code == 404


# ---- the 30-day purge ----


def _media(session: Session, review: Review, author: User) -> list[str]:
    keys = [f"quarantine/{uuid.uuid4()}", f"processed/{uuid.uuid4()}"]
    session.add(
        ReviewMedia(
            review_id=review.id, uploader_id=author.id, kind="image", state="rejected", content_type="image/jpeg",
            quarantine_key=keys[0], processed_key=keys[1], alt_text="a view", ownership_declared=True,
        )
    )
    session.commit()
    return keys


def test_retention_redacts_a_rejected_review_after_thirty_days(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    author = _verified_member(session)
    review = _rejected(session, moderator, days_ago=31, author=author)
    keys = _media(session, review, author)
    storage = FakeMediaStorage()
    factory = cases_tests.factory(session)
    assert retention.purge_rejected_reviews(factory, storage, datetime.now(UTC)) == 1  # type: ignore[arg-type]
    session.expire_all()
    stored = session.get(Review, review.id)
    assert stored is not None and stored.purged_at is not None and stored.status == ReviewStatus.REJECTED
    revision = session.get(ReviewRevision, stored.current_revision_id)
    assert revision is not None and (revision.title, revision.body) == ("[removed]", "[removed]")
    assert sorted(storage.deleted) == sorted(keys)
    assert session.scalar(select(ReviewMedia.state)) == "removed"
    event = session.scalar(select(AuditEvent).where(AuditEvent.action == "review.purged"))
    assert event is not None and event.actor_user_id is None and event.target_id == str(review.id)
    assert retention.purge_rejected_reviews(factory, storage, datetime.now(UTC)) == 0, "a second run does nothing"  # type: ignore[arg-type]
    assert _count_actions(session, "review.purged") == 1


def test_a_review_rejected_twenty_nine_days_ago_is_kept(postgres_session: Session, moderator: User) -> None:
    review = _rejected(postgres_session, moderator, days_ago=29)
    assert retention.purge_rejected_reviews(cases_tests.factory(postgres_session), FakeMediaStorage(), datetime.now(UTC)) == 0  # type: ignore[arg-type]
    postgres_session.expire_all()
    assert postgres_session.get(Review, review.id).purged_at is None  # type: ignore[union-attr]


def test_an_open_appeal_blocks_the_purge_until_it_is_decided(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    author = _verified_member(session)
    review = _rejected(session, moderator, days_ago=45, author=author)
    action = session.scalar(select(ModerationActionRecord).where(ModerationActionRecord.review_id == review.id))
    assert action is not None
    appeal = Appeal(appellant_user_id=author.id, moderation_action_id=action.id, state="in_review", reason="Please look again at this review.", deadline_at=datetime.now(UTC) + timedelta(days=1), original_decider_id=moderator.id)
    session.add(appeal)
    session.commit()
    factory = cases_tests.factory(session)
    assert retention.purge_rejected_reviews(factory, FakeMediaStorage(), datetime.now(UTC)) == 0  # type: ignore[arg-type]
    appeal.state = "upheld"
    session.commit()
    assert retention.purge_rejected_reviews(factory, FakeMediaStorage(), datetime.now(UTC)) == 1  # type: ignore[arg-type]


def test_a_reopened_review_is_never_purged(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    review = _rejected(session, moderator, days_ago=29)
    assert _reopen(_staff(client, session, fake, "superadmin", 30), review).status_code == 200
    backdate_decisions(session, datetime.now(UTC) - timedelta(days=60), review_id=review.id)
    session.commit()
    assert retention.purge_rejected_reviews(cases_tests.factory(session), FakeMediaStorage(), datetime.now(UTC)) == 0  # type: ignore[arg-type]


def test_a_review_another_run_is_working_on_is_skipped(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    review = _rejected(session, moderator, days_ago=40)
    engine = create_engine(session.get_bind().url.render_as_string(hide_password=False))
    holder = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        holder.execute(select(Review).where(Review.id == review.id).with_for_update())  # another run holds the row
        assert retention.purge_rejected_reviews(cases_tests.factory(session), FakeMediaStorage(), datetime.now(UTC)) == 0  # type: ignore[arg-type]
    finally:
        holder.rollback()
        holder.close()
        engine.dispose()
    assert retention.purge_rejected_reviews(cases_tests.factory(session), FakeMediaStorage(), datetime.now(UTC)) == 1  # type: ignore[arg-type]


def test_purged_text_never_reaches_an_api_response(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    author = _user(session, "Author")
    member = admin.staff_client(client, session, fake, "author-purge@example.test", None, "203.0.113.164", aal="aal1")
    author_id = fake.users["author-purge@example.test"]["id"]
    owner = session.get(User, author_id)
    assert owner is not None
    review = _rejected(session, moderator, days_ago=40, author=owner)
    retention.purge_rejected_reviews(cases_tests.factory(session), FakeMediaStorage(), datetime.now(UTC))  # type: ignore[arg-type]
    mine = member.get(f"{API}/reviews/{review.id}")
    assert mine.status_code == 200 and "Clean and calm" not in mine.text and "[removed]" in mine.text
    listing = member.get(f"{API}/reviews/mine").text
    assert "Clean and calm" not in listing
    staff = _staff(client, session, fake, "moderator", 31)
    assert "Clean and calm" not in staff.get(f"{BASE}/reviews", params={"status": "REJECTED"}).text
    del author


# ---- the reason catalogue ----


def test_the_catalogue_is_served_to_staff_with_both_languages(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    anonymous = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.165"})
    assert anonymous.get(f"{BASE}/reason-codes").status_code == 401
    member = admin.staff_client(client, postgres_session, fake, "plain-rc@example.test", None, "203.0.113.166", aal="aal1")
    assert member.get(f"{BASE}/reason-codes").status_code == 404
    groups = _staff(client, postgres_session, fake, "moderator", 32).get(f"{BASE}/reason-codes").json()["groups"]
    assert {"publish", "reject", "hide", "restore", "request_changes", "reopen", "report_resolution", "enforcement"} <= set(groups)
    for name, group in groups.items():
        assert isinstance(group["strict"], bool) and group["reasons"], name
        for reason in group["reasons"]:
            assert reason["code"] and reason["bn"].strip() and reason["en"].strip(), (name, reason)
    assert groups["enforcement"]["strict"] is False and groups["reject"]["strict"] is True


def test_every_strict_group_refuses_codes_from_another_group() -> None:
    for group, (strict, items) in reasons.GROUPS.items():
        if not strict:
            assert reasons.is_valid(group, "anything the moderator writes")
            continue
        own = {item.code for item in items}
        assert all(reasons.is_valid(group, code) for code in own)
        foreign = {item.code for g, (_, other) in reasons.GROUPS.items() if g != group for item in other} - own
        assert not any(reasons.is_valid(group, code) for code in foreign), group
        assert not reasons.is_valid(group, "made-up") and not reasons.is_valid(group, "")
    assert set(reasons.DECISION_GROUP) == {"PUBLISH", "REJECT", "HIDE", "RESTORE", "REQUEST_CHANGES", "REOPEN"}


def test_decision_routes_apply_the_catalogue(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    review, report, staff, task, lease = _reported(client, session, fake, moderator, 9)
    bad = staff.post(f"{BASE}/reports/{report.id}/transition", json={"to": "dismissed", "expected_version": report.version, "reason_code": "spam", "task_id": str(task.id), "lease_token": lease["lease_token"]})
    assert bad.status_code == 422 and bad.json()["error"]["field_errors"] == [{"field": "reason_code", "code": "INVALID_VALUE"}]
    good = staff.post(f"{BASE}/reports/{report.id}/transition", json={"to": "dismissed", "expected_version": report.version, "reason_code": "report-dismissed", "task_id": str(task.id), "lease_token": lease["lease_token"]})
    assert good.status_code == 200
    fresh, fresh_report, mod2, task2, lease2 = _reported(client, session, fake, moderator, 10)
    wrong = mod2.post(f"{BASE}/submissions/{fresh.id}/moderation-actions", json=admin._decision(task2, lease2["lease_token"], fresh, decision="HIDE", reason_code="meets-policy"))  # noqa: SLF001
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "VALIDATION_FAILED"
    right = mod2.post(f"{BASE}/submissions/{fresh.id}/moderation-actions", json=admin._decision(task2, lease2["lease_token"], fresh, decision="HIDE", reason_code="policy-violation"))  # noqa: SLF001
    assert right.status_code == 200
    del fresh_report


def test_old_free_text_reasons_still_render_in_the_lists(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User) -> None:
    session = postgres_session
    review = _review(session, _destination(session, "Legacy"), _verified_member(session))
    moderate_review(session, review_id=review.id, actor_user_id=moderator.id, expected_version=review.version, decision=ModerationDecision.REJECT, reason_code="some old free text", note=None)
    session.commit()
    staff = _staff(client, session, fake, "moderator", 33)
    assert staff.get(f"{BASE}/reviews", params={"status": "REJECTED"}).json()["items"][0]["reason_code"] == "some old free text"


def test_the_service_refuses_an_unknown_decision_group() -> None:
    from app.admin import actions

    with pytest.raises(ApiError):
        actions.require_reason("reject", "nope")
    actions.require_reason("enforcement", "free text is fine here")
    assert date.today().year >= 2026


def test_the_staff_app_built_in_reason_lists_match_the_servers_catalogue() -> None:
    """The staff screens fall back to their own lists when the catalogue cannot be loaded. Those lists are the codes
    the server accepts, so a change on either side that is not made on the other fails here (Moderation spec P-06)."""
    import re
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "staff" / "src" / "logic.ts").read_text(encoding="utf-8")
    block = source[source.index("export const REASONS") : source.index("export const DECISION_LABEL")]
    found: dict[str, set[str]] = {}
    for decision, body in re.findall(r"^  ([A-Z_]+): \[(.*?)\],$", block, flags=re.DOTALL | re.MULTILINE):
        found[decision] = set(re.findall(r"code: '([^']+)'", body))
    assert set(found) == set(reasons.DECISION_GROUP) - {"REOPEN"}, found.keys()
    for decision, codes in found.items():
        assert codes == set(reasons.codes(reasons.DECISION_GROUP[decision])), decision
    reopen = source[source.index("export const REOPEN_REASONS") : source.index("/** The reasons the server accepts for a group")]
    assert set(re.findall(r"code: '([^']+)'", reopen)) == set(reasons.codes("reopen"))
    resolutions = source[source.index("export const REPORT_RESOLUTIONS") : source.index("/** Whole seconds until")]
    assert set(re.findall(r"code: '([^']+)'", resolutions)) <= set(reasons.codes("report_resolution"))
    labels = source[source.index("export const REPORT_REASONS") : source.index("/** Why a rejected review can come back")]
    from app import report_reasons

    assert set(re.findall(r"\n  (\w+): \{ bn:", labels)) == set(report_reasons.ALL_STORED) | {"offensive"}
