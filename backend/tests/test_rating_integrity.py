"""R08: verification revoked for abuse, nightly reconciliation with audited repair, and the semester
evidence figures (Review.md 6.3, 6.4), plus the access rules of the three staff routes and the ops route."""

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import test_admin as admin
import test_auth as support
import test_ops as ops
import test_rating_exclusion as helpers
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app import rating_integrity
from app.auth.sessions import Principal
from app.errors import ApiError
from app.jobs import reconcile_ratings
from app.models import (
    AuditEvent,
    Destination,
    DestinationCategoryStats,
    DestinationRatingStats,
    ModerationDecision,
    OutboxEvent,
    RatingAudience,
    RatingEligibility,
    Review,
    ReviewCategory,
    ReviewStatus,
    User,
    UserRole,
    Verification,
    VerificationCase,
)
from app.rating_integrity import reconcile, revoke_verification_for_abuse, run_reconciliation
from app.services import moderate_review

auth_env = support.auth_env
fake = support.fake
redis_fake = support.redis_fake
ops_fake = ops.fake
ops_token = ops.token
pytestmark = pytest.mark.integration
BASE = "/api/v1/admin"

_destination = helpers._destination  # noqa: SLF001
_verified_member = helpers._verified_member  # noqa: SLF001
_review = helpers._review  # noqa: SLF001
_publish = helpers._publish  # noqa: SLF001
_stats = helpers._stats  # noqa: SLF001
_user = helpers._user  # noqa: SLF001
moderator = helpers.moderator


def _actor(session: Session) -> Principal:
    return admin._principal(_user(session, "Moderator Two"), "moderator")  # noqa: SLF001


# ---- verification revoked for abuse ----


def test_revoking_verification_uncounts_every_rating_of_that_member_only(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    first, second = _destination(session, "Sajek"), _destination(session, "Sylhet")
    abuser, bystander = _verified_member(session), _verified_member(session)
    mine_a = _publish(session, _review(session, first, abuser, rating=5, categories={ReviewCategory.FOOD: 5}), moderator)
    mine_b = _publish(session, _review(session, second, abuser, rating=4), moderator)
    other = _publish(session, _review(session, first, bystander, rating=3, categories={ReviewCategory.FOOD: 3}), moderator)
    assert _stats(session, first) == ((8, 2), (0, 0))

    result = revoke_verification_for_abuse(session, _actor(session), user_id=abuser.id, reason_code="REVIEW_FARMING", request_id="r1")
    session.commit()

    assert result["reviews_uncounted"] == 2
    assert _stats(session, first) == ((3, 1), (0, 0)) and _stats(session, second) == ((0, 0), (0, 0))
    for review in (mine_a, mine_b, other):
        session.refresh(review)
    assert mine_a.status == mine_b.status == ReviewStatus.PUBLISHED, "the reviews stay public"
    assert mine_a.rating_eligibility == mine_b.rating_eligibility == RatingEligibility.INELIGIBLE_UNVERIFIED
    assert mine_a.counted_rating is None and mine_b.counted_rating is None
    assert other.rating_eligibility == RatingEligibility.ELIGIBLE and other.counted_rating == 3
    category = session.get(DestinationCategoryStats, (first.id, ReviewCategory.FOOD, RatingAudience.COMMUNITY))
    assert category is not None and (category.rating_sum, category.rating_count) == (3, 1)
    record = session.scalar(select(Verification).where(Verification.user_id == abuser.id))
    assert record is not None and record.revoked_at is not None and record.revocation_reason == "REVIEW_FARMING"
    audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "verification.revoke_for_abuse"))
    assert audit is not None and audit.target_id == str(abuser.id) and audit.event_metadata["reviews_uncounted"] == 2
    event = session.scalar(select(OutboxEvent).where(OutboxEvent.topic == "verification.state_changed"))
    assert event is not None and event.payload["state"] == "revoked" and event.payload["applicant_id"] == str(abuser.id)
    assert reconcile(session).clean


def test_a_member_whose_verification_was_revoked_no_longer_counts_on_new_reviews(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    destination, member = _destination(session), _verified_member(session)
    revoke_verification_for_abuse(session, _actor(session), user_id=member.id, reason_code="ABUSE", request_id=None)
    session.commit()
    review = _publish(session, _review(session, destination, member), moderator)
    assert review.rating_eligibility == RatingEligibility.INELIGIBLE_UNVERIFIED
    assert _stats(session, destination) == ((0, 0), (0, 0))


def test_revoking_twice_or_without_a_record_is_not_found_and_your_own_is_forbidden(postgres_session: Session) -> None:
    session = postgres_session
    member, actor = _verified_member(session), _actor(session)
    revoke_verification_for_abuse(session, actor, user_id=member.id, reason_code="ABUSE", request_id=None)
    session.commit()
    with pytest.raises(ApiError) as repeated:
        revoke_verification_for_abuse(session, actor, user_id=member.id, reason_code="ABUSE", request_id=None)
    assert repeated.value.code == "NOT_FOUND"
    with pytest.raises(ApiError) as own:
        revoke_verification_for_abuse(session, actor, user_id=actor.user.id, reason_code="ABUSE", request_id=None)
    assert own.value.code == "FORBIDDEN"


def test_revocation_racing_a_publish_of_the_same_author_ends_consistent(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    destination, member = _destination(session), _verified_member(session)
    published = _publish(session, _review(session, destination, member, rating=5), moderator)
    pending = _review(session, destination, member, rating=4, month=date(2026, 8, 1))
    actor_id = _user(session, "Moderator Two").id
    engine = create_engine(session.get_bind().url.render_as_string(hide_password=False), pool_pre_ping=True)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    barrier = threading.Barrier(2)

    def revoke() -> str:
        with factory() as worker:
            actor = admin._principal(worker.get(User, actor_id), "moderator")  # noqa: SLF001
            barrier.wait()
            revoke_verification_for_abuse(worker, actor, user_id=member.id, reason_code="ABUSE", request_id=None)
            worker.commit()
        return "revoked"

    def publish() -> str:
        with factory() as worker:
            barrier.wait()
            moderate_review(
                worker, review_id=pending.id, actor_user_id=moderator.id, expected_version=pending.version,
                decision=ModerationDecision.PUBLISH, reason_code="OK", note=None,
            )
            worker.commit()
        return "published"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda job: job(), [revoke, publish]))
    engine.dispose()
    assert outcomes == ["published", "revoked"]
    session.expire_all()
    assert reconcile(session).clean, "whichever order they ran in, the totals match the review rows"
    session.refresh(published)
    assert published.counted_rating is None, "the earlier published rating is uncounted either way"
    # If the publish ran first the new review was uncounted by the revocation; if the revocation ran first
    # the new review was evaluated against an already revoked record. Both end with nothing counted.
    assert _stats(session, destination) == ((0, 0), (0, 0))


def test_a_failure_midway_leaves_nothing_half_applied(postgres_session: Session, moderator: User, monkeypatch: pytest.MonkeyPatch) -> None:
    session = postgres_session
    destination, member = _destination(session), _verified_member(session)
    _publish(session, _review(session, destination, member), moderator)
    _publish(session, _review(session, destination, member, month=date(2026, 8, 1)), moderator)
    calls = {"n": 0}
    original = rating_integrity.recheck_rating

    def flaky(sess: Session, review_id: uuid.UUID) -> Review:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return original(sess, review_id)

    monkeypatch.setattr(rating_integrity, "recheck_rating", flaky)
    with pytest.raises(RuntimeError):
        revoke_verification_for_abuse(session, _actor(session), user_id=member.id, reason_code="ABUSE", request_id=None)
    session.rollback()
    assert _stats(session, destination) == ((10, 2), (0, 0)), "nothing half-applied"
    assert session.scalar(select(Verification.revoked_at).where(Verification.user_id == member.id)) is None
    assert reconcile(session).clean


# ---- reconciliation ----


def _seeded(session: Session, moderator: User, name: str = "Sajek") -> Destination:
    destination = _destination(session, name)
    _publish(session, _review(session, destination, _verified_member(session), rating=5, categories={ReviewCategory.FOOD: 5}), moderator)
    _publish(session, _review(session, destination, _verified_member(session), rating=3), moderator)
    _publish(session, _review(session, destination, None, rating=4, categories={ReviewCategory.FOOD: 4}), moderator)
    return destination


def test_a_consistent_database_reconciles_clean(postgres_session: Session, moderator: User) -> None:
    _seeded(postgres_session, moderator)
    result = reconcile(postgres_session)
    assert result.clean and result.destinations_checked == 1 and result.repaired == 0


def test_drift_is_detected_without_writing_and_repair_fixes_it_with_an_audit_event(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    destination = _seeded(session, moderator)
    stats = session.get(DestinationRatingStats, destination.id)
    assert stats is not None
    stats.community_rating_sum += 7
    stats.guest_rating_count += 1
    session.add(
        DestinationCategoryStats(
            destination_id=destination.id, category=ReviewCategory.TRANSPORT, audience=RatingAudience.GUEST, rating_sum=9, rating_count=2
        )
    )
    session.commit()

    found = reconcile(session)
    assert sorted((drift.kind, drift.key) for drift in found.drifts) == [
        ("category", "GUEST:TRANSPORT"), ("community", "community"), ("guest", "guest"),
    ]
    session.expire_all()
    stats = session.get(DestinationRatingStats, destination.id)
    assert stats is not None and (stats.community_rating_sum, stats.guest_rating_count) == (15, 2), "detect-only never changes a total"
    assert session.scalar(select(AuditEvent).where(AuditEvent.action == "ratings.reconcile_repair")) is None

    version = stats.version
    fixed = reconcile(session, repair=True, actor=_actor(session))
    session.commit()
    assert fixed.repaired == 1
    session.expire_all()
    assert reconcile(session).clean
    repaired = session.get(DestinationRatingStats, destination.id)
    assert repaired is not None and repaired.version == version + 1
    audit = session.scalar(select(AuditEvent).where(AuditEvent.action == "ratings.reconcile_repair"))
    assert audit is not None and audit.target_id == str(destination.id)
    assert audit.event_metadata["before"]["community"] == [15, 2] and audit.event_metadata["after"]["community"] == [8, 2]


def test_a_destination_with_counted_reviews_but_no_totals_row_is_repaired(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    destination = _seeded(session, moderator)
    session.query(DestinationCategoryStats).delete()
    session.query(DestinationRatingStats).delete()
    session.commit()
    assert not reconcile(session).clean
    reconcile(session, repair=True, actor=None)
    session.commit()
    assert reconcile(session).clean
    assert _stats(session, destination) == ((8, 2), (4, 1))


def test_a_review_row_that_disagrees_with_itself_is_reported_but_not_repaired(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    destination = _seeded(session, moderator)
    review = session.scalar(select(Review).where(Review.destination_id == destination.id, Review.author_user_id.is_not(None)))
    assert review is not None
    review.status = ReviewStatus.DELETED  # deleted, yet still carrying a counted rating
    session.commit()
    assert any(drift.kind == "review" and not drift.repairable for drift in reconcile(session).drifts)
    repaired = reconcile(session, repair=True, actor=None)
    session.commit()
    assert any(drift.kind == "review" for drift in reconcile(session).drifts), "a human decides what a corrupt review row means"
    assert repaired.repaired == 1, "the totals were still rebuilt from the rows that count"


def test_reconciling_one_destination_ignores_the_others(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    clean, broken = _seeded(session, moderator, "Sajek"), _seeded(session, moderator, "Sylhet")
    broken_stats = session.get(DestinationRatingStats, broken.id)
    assert broken_stats is not None
    broken_stats.guest_rating_sum += 1
    session.commit()
    assert reconcile(session, destination_id=clean.id).clean
    assert not reconcile(session, destination_id=broken.id).clean


def test_a_run_is_audited_and_drift_raises_one_alert_a_day(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    destination = _seeded(session, moderator)
    superadmin = _user(session, "Super")
    session.add(UserRole(user_id=superadmin.id, role="superadmin"))
    stats = session.get(DestinationRatingStats, destination.id)
    assert stats is not None
    stats.guest_rating_sum += 1
    session.commit()
    run_reconciliation(session, repair=False, actor=None)
    run_reconciliation(session, repair=False, actor=None)
    session.commit()
    alerts = session.scalars(select(OutboxEvent).where(OutboxEvent.topic == "ratings.drift_detected")).all()
    assert len(alerts) == 1 and alerts[0].payload["count"] == 1 and alerts[0].payload["staff_recipients"] == [str(superadmin.id)]
    runs = session.scalars(select(AuditEvent).where(AuditEvent.action == "ratings.reconcile_run")).all()
    assert len(runs) == 2 and runs[0].event_metadata["drifts"] == 1


def test_the_nightly_job_detects_then_repairs(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    destination = _seeded(session, moderator)
    stats = session.get(DestinationRatingStats, destination.id)
    assert stats is not None
    stats.community_rating_count += 1
    session.commit()
    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    detected = reconcile_ratings.run(factory)
    assert len(detected.drifts) == 1 and detected.repaired == 0
    repaired = reconcile_ratings.run(factory, repair=True)
    assert repaired.repaired == 1
    session.expire_all()
    assert reconcile(session).clean


# ---- semester evidence ----


def test_evidence_reports_members_turnaround_and_the_mode_of_each_destination(postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    seeded, ranked = _destination(session, "Seeded"), _destination(session, "Ranked")
    for _ in range(5):
        _publish(session, _review(session, ranked, _verified_member(session), rating=4), moderator)
    _publish(session, _review(session, seeded, _verified_member(session), rating=4), moderator)
    revoke_verification_for_abuse(session, _actor(session), user_id=_verified_member(session).id, reason_code="ABUSE", request_id=None)
    now = datetime.now(UTC)
    for hours in (2, 10):
        applicant = _user(session)
        session.add(VerificationCase(applicant_user_id=applicant.id, state="approved", created_at=now - timedelta(hours=hours), decided_at=now))
    session.commit()

    evidence = rating_integrity.rating_evidence(session)
    assert evidence["threshold"] == 5
    assert evidence["verified_members"] == {"active": 6, "ever_approved": 7}
    assert evidence["verification_turnaround_hours"] == {"decisions": 2, "median": 6.0, "maximum": 10.0}
    modes = {row["name_en"]: (row["eligible_reviews"], row["mode"]) for row in evidence["destinations"]}
    assert modes == {"Ranked": (5, "top_rated"), "Seeded": (1, "seeded")}


def test_evidence_with_no_data_is_empty_not_an_error(postgres_session: Session) -> None:
    evidence = rating_integrity.rating_evidence(postgres_session)
    assert evidence["verification_turnaround_hours"] == {"decisions": 0, "median": None, "maximum": None}
    assert evidence["destinations"] == [] and evidence["verified_members"] == {"active": 0, "ever_approved": 0}


# ---- the routes ----


@pytest.fixture()
def client(auth_env: None, postgres_session: Session, fake: support.FakeGoTrue, redis_fake: Any) -> TestClient:
    return support.make_client(postgres_session, fake, redis_fake)


def _anonymous(client: TestClient) -> TestClient:
    return TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.90"})


ROUTES: list[tuple[str, str, Any]] = [
    ("POST", f"{BASE}/members/{uuid.uuid4()}/verification/revoke", {"reason_code": "ABUSE"}),
    ("POST", f"{BASE}/ratings/reconcile", {"repair": False}),
    ("GET", f"{BASE}/rating-evidence", None),
]


@pytest.mark.parametrize(("method", "path", "body"), ROUTES)
def test_the_routes_are_closed_to_the_public_and_to_members(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, method: str, path: str, body: Any
) -> None:
    anonymous = _anonymous(client).request(method, path, json=body)
    assert anonymous.status_code == 401 and anonymous.json()["error"]["code"] == "AUTH_REQUIRED"
    member = admin.staff_client(client, postgres_session, fake, f"member-{uuid.uuid4().hex[:6]}@example.test", None, "203.0.113.91", aal="aal1")
    assert member.request(method, path, json=body).status_code == 404, "a member is not told the route exists"


def test_a_moderator_can_revoke_and_read_evidence_but_not_reconcile(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User
) -> None:
    session = postgres_session
    destination, member = _destination(session), _verified_member(session)
    _publish(session, _review(session, destination, member), moderator)
    staff = admin.staff_client(client, session, fake, "mod-r08@example.test", "moderator", "203.0.113.92")
    assert staff.post(f"{BASE}/ratings/reconcile", json={"repair": False}).status_code == 403
    assert staff.get(f"{BASE}/rating-evidence").status_code == 200

    done = staff.post(f"{BASE}/members/{member.id}/verification/revoke", json={"reason_code": "ABUSE"})
    assert done.status_code == 200 and done.json()["reviews_uncounted"] == 1
    assert _stats(session, destination) == ((0, 0), (0, 0))
    again = staff.post(f"{BASE}/members/{member.id}/verification/revoke", json={"reason_code": "ABUSE"})
    assert again.status_code == 404, "a repeat has nothing left to revoke"
    assert staff.post(f"{BASE}/members/{member.id}/verification/revoke", json={}).status_code == 422
    own = session.scalar(select(User).where(User.email == "mod-r08@example.test"))
    assert own is not None
    _verify_row = Verification(user_id=own.id, verification_type="VERIFIED_MEMBER", status="APPROVED", method="TEST_FIXTURE")
    session.add(_verify_row)
    session.commit()
    assert staff.post(f"{BASE}/members/{own.id}/verification/revoke", json={"reason_code": "ABUSE"}).status_code == 403
    session.expire_all()
    assert session.scalars(select(AuditEvent).where(AuditEvent.action == "denied.verification.revoke")).all(), "the refused attempt was audited"
    assert session.scalar(select(Verification.revoked_at).where(Verification.user_id == own.id)) is None


def test_revoking_requires_the_csrf_token_and_a_totp_session(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    session = postgres_session
    member = _verified_member(session)
    staff = admin.staff_client(client, session, fake, "mod-csrf@example.test", "moderator", "203.0.113.93")
    path = f"{BASE}/members/{member.id}/verification/revoke"
    token = staff.headers.pop("X-CSRF-Token")
    assert staff.post(path, json={"reason_code": "ABUSE"}).status_code == 403
    staff.headers["X-CSRF-Token"] = token
    no_totp = admin.staff_client(client, session, fake, "mod-aal1@example.test", "moderator", "203.0.113.94", aal="aal1")
    assert no_totp.post(path, json={"reason_code": "ABUSE"}).status_code in (401, 403)
    assert session.scalar(select(Verification.revoked_at).where(Verification.user_id == member.id)) is None


def test_a_superadmin_can_reconcile_and_repair_over_http(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, moderator: User
) -> None:
    session = postgres_session
    destination = _seeded(session, moderator)
    stats = session.get(DestinationRatingStats, destination.id)
    assert stats is not None
    stats.community_rating_sum += 2
    session.commit()
    boss = admin.staff_client(client, session, fake, "boss-r08@example.test", "superadmin", "203.0.113.95")
    found = boss.post(f"{BASE}/ratings/reconcile", json={"repair": False}).json()
    assert found["repaired"] == 0 and [d["kind"] for d in found["drifts"]] == ["community"]
    assert found["drifts"][0]["stored"] == [10, 2] and found["drifts"][0]["expected"] == [8, 2]
    assert boss.post(f"{BASE}/ratings/reconcile", json={"repair": True}).json()["repaired"] == 1
    assert boss.post(f"{BASE}/ratings/reconcile", json={"repair": False}).json()["drifts"] == []
    assert boss.post(f"{BASE}/ratings/reconcile", json={"repair": False, "extra": 1}).status_code == 422


def test_the_ops_route_detects_without_repairing(ops_token: None, ops_fake: Any, postgres_session: Session, moderator: User) -> None:
    session = postgres_session
    destination = _seeded(session, moderator)
    stats = session.get(DestinationRatingStats, destination.id)
    assert stats is not None
    stats.guest_rating_sum += 3
    session.commit()
    ops_client = ops._app(ops_fake, session)  # noqa: SLF001
    answer = ops_client.post("/api/v1/ops/jobs/rating-reconciliation", headers=ops.AUTH)
    assert answer.status_code == 200 and answer.json() == {"destinations_checked": 1, "drifts": 1, "clean": False}
    session.expire_all()
    again = session.get(DestinationRatingStats, destination.id)
    assert again is not None and again.guest_rating_sum == 7, "the nightly route never repairs"
    assert ops_client.post("/api/v1/ops/jobs/rating-reconciliation").status_code == 401
