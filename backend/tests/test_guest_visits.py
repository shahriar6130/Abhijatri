"""Visit counting (Guest-Identity-and-Visits 4, 5 and 8): Redis day counters, nothing about who."""

import uuid
from collections.abc import Generator
from datetime import UTC, date, datetime, timedelta

import fakeredis
import pytest
import redis
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session, sessionmaker

from app import visits
from app.abuse import get_counter_session_factory
from app.config import get_settings
from app.db import get_session
from app.limits import limiter
from app.main import create_app
from app.models import User, VisitDailyStats
from app.redis_client import get_redis
from app.visits import DayCounts, metrics

# 20:30 UTC on 19 Oct is already 20 Oct in Dhaka (UTC+6).
NOW = datetime(2026, 10, 19, 20, 30, tzinfo=UTC)
TODAY = date(2026, 10, 20)


@pytest.fixture(autouse=True)
def _reset_limiter() -> None:
    limiter.reset()


@pytest.fixture()
def fake() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)


class BrokenRedis:
    """Every command fails as if Upstash were unreachable."""

    def __getattr__(self, _name: str):
        def fail(*_args, **_kwargs):
            raise redis.ConnectionError("down")

        return fail


# ---- the counter primitive (no database) ----


def test_a_visit_increments_one_field_with_an_eight_day_ttl(fake: fakeredis.FakeRedis) -> None:
    assert visits.record_visit(fake, "guest", new=True, day=TODAY)
    assert visits.record_visit(fake, "guest", new=False, day=TODAY)
    assert visits.record_visit(fake, "guest", new=False, day=TODAY)
    name = f"abj:{get_settings().app_env}:visits:2026-10-20"
    assert fake.hgetall(name) == {"guest_new": "1", "guest_returning": "2"}
    assert 0 < fake.ttl(name) <= 8 * 86400


def test_keys_and_values_identify_nobody(fake: fakeredis.FakeRedis) -> None:
    visits.record_visit(fake, "guest", new=True, day=TODAY)
    for name in fake.keys("*"):
        assert name.startswith("abj:")
        assert set(fake.hgetall(name)) <= set(visits.FIELDS)
        assert all(value.isdigit() for value in fake.hgetall(name).values())


def test_redis_down_counts_a_drop_and_never_raises() -> None:
    before = visits.visits_dropped.value
    assert visits.record_visit(BrokenRedis(), "guest", new=True, day=TODAY) is False  # type: ignore[arg-type]
    assert visits.record_visit(None, "guest", new=True, day=TODAY) is False
    assert visits.visits_dropped.value == before + 2


@given(
    st.lists(
        st.tuples(st.integers(0, 4), st.sampled_from(["guest", "member"]), st.booleans()), max_size=60
    )
)
def test_old_visits_always_equal_a_minus_b(sequence: list[tuple[int, str, bool]]) -> None:
    client = fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)
    for offset, kind, new in sequence:
        visits.record_visit(client, kind, new=new, day=TODAY - timedelta(days=offset))  # type: ignore[arg-type]
    total = DayCounts()
    for offset in range(5):
        counts = visits.read_day(client, TODAY - timedelta(days=offset)) or DayCounts()
        day = metrics(counts)
        assert day.old_visits == day.total_visits - day.new_visits
        assert day.old_visits == counts.guest_returning + counts.member_returning
        total = total + counts
    assert metrics(total).total_visits == len(sequence)
    assert metrics(total).new_visits == sum(1 for _, _, new in sequence if new)


# ---- POST /guest-visits ----


def _client(redis_client: object, postgres_session: Session | None = None) -> TestClient:
    application = create_app()
    application.dependency_overrides[get_redis] = lambda: redis_client
    if postgres_session is None:
        application.dependency_overrides[get_session] = lambda: None
    else:
        factory = sessionmaker(bind=postgres_session.get_bind(), expire_on_commit=False)
        application.dependency_overrides[get_counter_session_factory] = lambda: factory
    return TestClient(application)


@pytest.mark.parametrize(
    "body",
    [
        {"first_visit": True, "name": "Sadia"},
        {"first_visit": True, "guest_scope_secret": "x" * 43},
        {"first_visit": True, "guest_tag": "1C669-J0TDY"},
        {"first_visit": False, "device_id": "abc"},
    ],
)
def test_only_the_first_visit_flag_is_accepted(body: dict[str, object], fake: fakeredis.FakeRedis) -> None:
    response = _client(fake).post("/api/v1/guest-visits", json=body)
    assert response.status_code == 422
    assert {e["code"] for e in response.json()["error"]["field_errors"]} == {"UNKNOWN_FIELD"}


def test_the_flag_is_required(fake: fakeredis.FakeRedis) -> None:
    assert _client(fake).post("/api/v1/guest-visits", json={}).status_code == 422


def test_the_stats_route_is_gone(fake: fakeredis.FakeRedis) -> None:
    assert _client(fake).get("/api/v1/guest-visits/stats").status_code in {404, 405}


@pytest.fixture()
def http(postgres_session: Session, monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("RATE_LIMIT_GUEST_VISIT", "1000/minute")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.mark.integration
def test_a_visit_is_204_no_store_and_lands_in_todays_hash(
    http: None, postgres_session: Session, fake: fakeredis.FakeRedis
) -> None:
    client = _client(fake, postgres_session)
    first = client.post("/api/v1/guest-visits", json={"first_visit": True})
    assert first.status_code == 204
    assert first.content == b""
    assert first.headers["cache-control"] == "no-store"
    client.post("/api/v1/guest-visits", json={"first_visit": False})
    today = visits.read_day(fake, visits.today_in_display_tz())
    assert today == DayCounts(guest_new=1, guest_returning=1)


@pytest.mark.integration
def test_redis_down_still_answers_204(http: None, postgres_session: Session) -> None:
    before = visits.visits_dropped.value
    response = _client(BrokenRedis(), postgres_session).post("/api/v1/guest-visits", json={"first_visit": True})
    assert response.status_code == 204
    assert visits.visits_dropped.value == before + 1


@pytest.mark.integration
def test_the_kill_switch_counts_nothing(
    http: None, postgres_session: Session, fake: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VISIT_COUNTER_ENABLED", "false")
    get_settings.cache_clear()
    assert _client(fake, postgres_session).post("/api/v1/guest-visits", json={"first_visit": True}).status_code == 204
    assert fake.keys("*") == []


@pytest.mark.integration
def test_guest_visits_are_rate_limited_per_network(
    http: None, postgres_session: Session, fake: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GUEST_VISITS_PER_NETWORK_PER_HOUR", "2")
    get_settings.cache_clear()
    client = _client(fake, postgres_session)
    codes = [client.post("/api/v1/guest-visits", json={"first_visit": False}).status_code for _ in range(3)]
    assert codes == [204, 204, 429]


# ---- roll-up to visit_daily_stats ----


@pytest.mark.integration
def test_daily_stats_table_has_only_numbers(postgres_session: Session) -> None:
    columns = {c["name"] for c in inspect(postgres_session.get_bind()).get_columns("visit_daily_stats")}
    assert columns == {
        "day",
        "guest_new",
        "guest_returning",
        "member_new",
        "member_returning",
        "guest_total_legacy",
        "rolled_up_at",
    }


@pytest.mark.integration
def test_rollup_copies_finished_days_and_is_idempotent(
    postgres_session: Session, fake: fakeredis.FakeRedis
) -> None:
    yesterday = TODAY - timedelta(days=1)
    visits.record_visit(fake, "guest", new=True, day=yesterday)
    visits.record_visit(fake, "guest", new=False, day=yesterday)
    visits.record_visit(fake, "guest", new=True, day=TODAY)  # today stays live in Redis

    assert visits.rollup(postgres_session, fake, now=NOW) == [yesterday]
    assert visits.rollup(postgres_session, fake, now=NOW) == [yesterday]
    rows = postgres_session.scalars(select(VisitDailyStats)).all()
    assert [(r.day, r.guest_new, r.guest_returning, r.member_new) for r in rows] == [(yesterday, 1, 1, 0)]


@pytest.mark.integration
def test_a_missing_hash_never_zeroes_an_existing_row(postgres_session: Session, fake: fakeredis.FakeRedis) -> None:
    day = TODAY - timedelta(days=2)
    postgres_session.add(VisitDailyStats(day=day, guest_new=5, guest_returning=7, member_new=0, member_returning=0))
    postgres_session.commit()
    assert visits.rollup(postgres_session, fake, now=NOW) == []
    row = postgres_session.get(VisitDailyStats, day)
    assert (row.guest_new, row.guest_returning) == (5, 7)


@pytest.mark.integration
def test_the_lock_stops_a_second_concurrent_run(postgres_session: Session, fake: fakeredis.FakeRedis) -> None:
    yesterday = TODAY - timedelta(days=1)
    visits.record_visit(fake, "guest", new=True, day=yesterday)
    fake.set(visits.rollup_lock_key(yesterday), "1", nx=True, ex=300)  # another run holds it
    assert visits.rollup(postgres_session, fake, now=NOW) == []
    assert postgres_session.get(VisitDailyStats, yesterday) is None


@pytest.mark.integration
def test_member_visit_is_counted_once_per_day_and_new_only_once(postgres_session: Session) -> None:
    member = User(email=f"m-{uuid.uuid4()}@example.test", display_name="Member")
    postgres_session.add(member)
    postgres_session.commit()
    assert visits.record_member_visit(postgres_session, member.id, TODAY) is True
    assert visits.record_member_visit(postgres_session, member.id, TODAY) is None
    assert visits.record_member_visit(postgres_session, member.id, TODAY + timedelta(days=1)) is False
    postgres_session.commit()
    postgres_session.refresh(member)
    assert (member.first_visit_on, member.last_visit_on) == (TODAY, TODAY + timedelta(days=1))
