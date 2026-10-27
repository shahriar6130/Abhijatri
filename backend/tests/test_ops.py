"""System Monitoring Dashboard API (System-Monitoring-Dashboard 11)."""

import json
import re
import time
from collections.abc import Generator
from datetime import timedelta

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app import visits
from app.abuse import get_counter_session_factory
from app.config import get_settings
from app.db import get_session
from app.destination_services import today_in_display_tz
from app.limits import limiter
from app.main import create_app
from app.models import Destination, DestinationStatus
from app.ops import events, registry
from app.ops.registry import Panel, PanelContext, PanelResult
from app.redis_client import get_redis

TOKEN = "ops-test-token-" + "x" * 40
BLOCK_TYPES = {"stat", "series", "table", "status"}
IDENTIFIER_PATTERNS = [
    re.compile(r"\b[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}\b"),  # guest tag
    re.compile(r"abr1_"),  # receipt
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),  # email
    re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b"),  # IPv4
    re.compile(r"[A-Za-z0-9_-]{43,}"),  # scope-secret length
]


@pytest.fixture(autouse=True)
def _reset_limiter() -> None:
    limiter.reset()


@pytest.fixture()
def fake() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)


def _app(fake: fakeredis.FakeRedis, postgres_session: Session | None = None) -> TestClient:
    application = create_app()
    application.dependency_overrides[get_redis] = lambda: fake
    if postgres_session is not None:
        factory = sessionmaker(bind=postgres_session.get_bind(), expire_on_commit=False)

        def session_override() -> Generator[Session, None, None]:
            yield postgres_session

        application.dependency_overrides[get_session] = session_override
        application.dependency_overrides[get_counter_session_factory] = lambda: factory
    return TestClient(application)


@pytest.fixture()
def token(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("OPS_DASHBOARD_TOKEN", TOKEN)
    monkeypatch.setenv("CLIENT_ADDRESS_HEADER", "X-Forwarded-For")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


AUTH = {"Authorization": f"Bearer {TOKEN}"}
ROUTES = [
    ("GET", "/api/v1/ops/panels"),
    ("GET", "/api/v1/ops/panels/visitors"),
    ("GET", "/api/v1/ops/overview"),
    ("POST", "/api/v1/ops/jobs/visit-rollup"),
]


# ---- access ----


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_route_is_404_while_the_token_is_unset(
    method: str, path: str, fake: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPS_DASHBOARD_TOKEN", raising=False)
    get_settings.cache_clear()
    response = _app(fake).request(method, path, headers=AUTH)
    assert response.status_code == 404
    get_settings.cache_clear()


@pytest.mark.integration
def test_wrong_token_is_401_then_429_and_never_logged(
    token: None, postgres_session: Session, fake: fakeredis.FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    client = _app(fake, postgres_session)
    headers = {"Authorization": "Bearer wrong-token-value", "X-Forwarded-For": "203.0.113.9"}
    codes = [client.get("/api/v1/ops/panels", headers=headers).status_code for _ in range(11)]
    assert codes == [401] * 10 + [429]
    assert client.get("/api/v1/ops/panels", headers={"X-Forwarded-For": "203.0.113.9"}).status_code == 429
    other = {**AUTH, "X-Forwarded-For": "203.0.113.10"}
    assert client.get("/api/v1/ops/panels", headers=other).status_code == 200
    assert "wrong-token-value" not in caplog.text and TOKEN not in caplog.text


@pytest.mark.integration
def test_token_in_the_url_is_not_accepted(token: None, postgres_session: Session, fake: fakeredis.FakeRedis) -> None:
    client = _app(fake, postgres_session)
    assert client.get(f"/api/v1/ops/panels?token={TOKEN}").status_code == 401


# ---- panels ----


def _assert_panel_shape(panel: dict) -> None:
    assert {"id", "version", "status", "generated_at", "sources", "blocks", "title"} <= set(panel)
    assert panel["status"] in {"ok", "degraded", "unavailable"}
    for source in panel["sources"]:
        assert set(source) == {"name", "fresh_at"}
    for block in panel["blocks"]:
        assert block["type"] in BLOCK_TYPES
        assert {"key", "label"} <= set(block)
        assert set(block["label"]) == {"bn", "en"}
        if "level" in block:
            assert block["level"] in {"ok", "warn", "critical"}
        if block["type"] == "series":
            assert all(set(point) == {"date", "value"} for point in block["points"])


@pytest.mark.integration
def test_overview_returns_every_panel_in_the_shared_shape_without_identifiers(
    token: None, postgres_session: Session, fake: fakeredis.FakeRedis
) -> None:
    postgres_session.add(Destination(status=DestinationStatus.PUBLISHED, name_bn="সাজেক", name_en="Sajek"))
    postgres_session.commit()
    visits.record_visit(fake, "guest", new=True)
    visits.record_visit(fake, "guest", new=False)
    response = _app(fake, postgres_session).get("/api/v1/ops/overview?days=7", headers=AUTH)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert {panel["id"] for panel in body["panels"]} == {"visitors", "content", "reviews", "traffic", "health", "members"}
    for panel in body["panels"]:
        _assert_panel_shape(panel)
        assert panel["status"] != "unavailable", panel
    text = json.dumps(body, ensure_ascii=False)
    for pattern in IDENTIFIER_PATTERNS:
        assert not pattern.search(text), pattern.pattern

    visitors = next(p for p in body["panels"] if p["id"] == "visitors")
    values = {block["key"]: block.get("value") for block in visitors["blocks"]}
    assert values["today_guest"] == 2
    assert values["today_new_guest"] == 1
    assert values["today_total_visits"] - values["today_new_visits"] == values["today_old_visits"] == 1
    assert values["today_verified"] == 0


@pytest.mark.integration
def test_missing_past_days_are_gaps_not_zeros(token: None, postgres_session: Session, fake: fakeredis.FakeRedis) -> None:
    body = _app(fake, postgres_session).get("/api/v1/ops/panels/visitors?days=7", headers=AUTH).json()
    series = next(b for b in body["blocks"] if b["key"] == "new_by_day")
    assert len(series["points"]) == 7
    assert [p["value"] for p in series["points"][:-1]] == [None] * 6
    assert series["points"][-1]["value"] == 0  # today is live and known


@pytest.mark.integration
def test_redis_down_makes_visitors_degraded_with_nulls(
    token: None, postgres_session: Session, fake: fakeredis.FakeRedis
) -> None:
    client = _app(fake, postgres_session)
    client.app.dependency_overrides[get_redis] = lambda: None  # type: ignore[attr-defined]
    body = client.get("/api/v1/ops/panels/visitors", headers=AUTH).json()
    assert body["status"] == "degraded"
    assert next(b for b in body["blocks"] if b["key"] == "today_guest")["value"] is None


@pytest.mark.integration
def test_unknown_panel_and_days_outside_the_selector(token: None, postgres_session: Session, fake: fakeredis.FakeRedis) -> None:
    client = _app(fake, postgres_session)
    assert client.get("/api/v1/ops/panels/nope", headers=AUTH).status_code == 404
    assert client.get("/api/v1/ops/overview?days=14", headers=AUTH).status_code == 422


@pytest.mark.integration
def test_rollup_route_is_idempotent(token: None, postgres_session: Session, fake: fakeredis.FakeRedis) -> None:
    yesterday = today_in_display_tz() - timedelta(days=1)
    visits.record_visit(fake, "guest", new=True, day=yesterday)
    client = _app(fake, postgres_session)
    first = client.post("/api/v1/ops/jobs/visit-rollup", headers=AUTH).json()
    second = client.post("/api/v1/ops/jobs/visit-rollup", headers=AUTH).json()
    assert first == second == {"rolled_up": [yesterday.isoformat()]}


# ---- registry isolation (no database) ----


class _Raises(Panel):
    id = "test-raises"
    title = {"bn": "x", "en": "x"}
    sources = ("config",)

    def collect(self, ctx: PanelContext) -> PanelResult:
        raise RuntimeError("boom")


class _Slow(Panel):
    id = "test-slow"
    title = {"bn": "x", "en": "x"}
    sources = ("config",)

    def collect(self, ctx: PanelContext) -> PanelResult:
        time.sleep(1)
        return PanelResult(blocks=[])


class _Fine(Panel):
    id = "test-fine"
    title = {"bn": "x", "en": "x"}
    sources = ("config",)

    def collect(self, ctx: PanelContext) -> PanelResult:
        return PanelResult(blocks=[registry.stat("one", {"bn": "১", "en": "1"}, 1)])


def test_one_failing_or_slow_provider_leaves_the_others_ok() -> None:
    from datetime import UTC, datetime

    ctx = PanelContext(sessions=lambda: None, redis=None, settings=get_settings(), days=7, now=datetime.now(UTC))  # type: ignore[arg-type, return-value]
    assert registry.collect(_Raises, ctx)["status"] == "unavailable"
    assert registry.collect(_Slow, ctx, budget=0.1)["status"] == "unavailable"
    fine = registry.collect(_Fine, ctx)
    assert fine["status"] == "ok"
    _assert_panel_shape(fine)


def test_every_registered_panel_declares_its_catalogue_fields() -> None:
    ids = [panel.id for panel in registry.panels()]
    assert len(ids) == len(set(ids))
    for panel in registry.panels():
        entry = panel.catalogue_entry()
        assert entry["title"].keys() == {"bn", "en"}
        assert entry["sources"]


# ---- event counters ----


def test_unknown_event_names_are_rejected() -> None:
    with pytest.raises(events.UnknownEvent):
        events.count("user@example.com")
    with pytest.raises(events.UnknownEvent):
        events.count("route_5xx:no-leading-slash")
    events.count("route_5xx:/api/v1/reviews/{review_id}/withdraw")


def test_events_flush_in_one_hash_and_survive_a_redis_failure(fake: fakeredis.FakeRedis) -> None:
    events.flush(fakeredis.FakeRedis(server=fakeredis.FakeServer()))  # discard earlier tests' counts
    day = today_in_display_tz()
    events.count("http.2xx")
    events.count("http.2xx")
    assert events.flush(None) is False  # no Redis: counts are kept
    assert events.pending()["http.2xx"] == 2
    assert events.flush(fake, day=day) is True
    assert events.read_day(fake, day)["http.2xx"] == 2
    assert events.pending() == {}
    assert 0 < fake.ttl(events.events_key(day)) <= 8 * 86400


def test_the_middleware_counts_status_classes(fake: fakeredis.FakeRedis) -> None:
    events.flush(fakeredis.FakeRedis(server=fakeredis.FakeServer()))
    client = _app(fake)
    client.get("/api/v1/health")
    client.get("/api/v1/does-not-exist")
    counted = events.pending()
    assert counted.get("http.2xx", 0) >= 1
    assert counted.get("http.4xx", 0) >= 1


def test_a_5xx_is_counted_by_route_template_never_by_raw_path(fake: fakeredis.FakeRedis) -> None:
    events.flush(fakeredis.FakeRedis(server=fakeredis.FakeServer()))
    application = create_app()

    @application.get("/boom/{item_id}")
    def boom(item_id: str) -> None:
        raise RuntimeError("boom")

    TestClient(application, raise_server_exceptions=False).get("/boom/secret-id-123")
    counted = events.pending()
    assert counted.get("http.5xx", 0) >= 1
    assert counted.get("route_5xx:/boom/{item_id}", 0) == 1
    assert not any("secret-id-123" in name for name in counted)


# ---- headers, limits and CORS ----


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_the_disabled_api_still_sends_no_store(
    method: str, path: str, fake: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPS_DASHBOARD_TOKEN", raising=False)
    get_settings.cache_clear()
    response = _app(fake).request(method, path, headers=AUTH)
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    get_settings.cache_clear()


def test_the_ops_origin_passes_the_preflight_with_the_authorization_header(
    fake: fakeredis.FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    ops_origin = "https://abhijatri-ops-44afee.vercel.app"
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", f"http://localhost:5173,{ops_origin}")
    get_settings.cache_clear()
    try:
        client = _app(fake)
        preflight = client.options(
            "/api/v1/ops/overview",
            headers={
                "Origin": ops_origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert preflight.status_code == 200
        assert preflight.headers["access-control-allow-origin"] == ops_origin
        assert "authorization" in preflight.headers["access-control-allow-headers"].lower()
        assert preflight.headers["access-control-allow-credentials"] == "true"  # cookie sessions (R04)

        stranger = client.options(
            "/api/v1/ops/overview",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "authorization",
            },
        )
        assert "access-control-allow-origin" not in stranger.headers
    finally:
        get_settings.cache_clear()


@pytest.mark.integration
def test_more_than_60_requests_a_minute_are_rate_limited(
    token: None, postgres_session: Session, fake: fakeredis.FakeRedis
) -> None:
    client = _app(fake, postgres_session)
    headers = {**AUTH, "X-Forwarded-For": "203.0.113.50"}
    codes = [client.get("/api/v1/ops/panels", headers=headers).status_code for _ in range(61)]
    assert codes[:60] == [200] * 60
    assert codes[60] == 429


@pytest.mark.integration
def test_error_responses_are_never_cached(token: None, postgres_session: Session, fake: fakeredis.FakeRedis) -> None:
    client = _app(fake, postgres_session)
    headers = {"Authorization": "Bearer nope", "X-Forwarded-For": "203.0.113.77"}
    responses = [client.get("/api/v1/ops/panels", headers=headers) for _ in range(11)]
    assert [r.status_code for r in responses] == [401] * 10 + [429]
    assert all(r.headers["cache-control"] == "no-store" for r in responses)


# ---- panel contents on real data ----


@pytest.mark.integration
def test_content_and_traffic_panels_show_real_counts(
    token: None, postgres_session: Session, fake: fakeredis.FakeRedis
) -> None:
    postgres_session.add(Destination(status=DestinationStatus.PUBLISHED, name_bn="কক্সবাজার", name_en="Cox"))
    postgres_session.add(Destination(status=DestinationStatus.PUBLISHED, name_bn="সাজেক", name_en="Sajek"))
    postgres_session.commit()
    events.flush(fakeredis.FakeRedis(server=fakeredis.FakeServer()))
    events.count("http.2xx", 3)
    events.count("http.4xx", 2)
    events.flush(fake)
    client = _app(fake, postgres_session)

    def values(panel_id: str) -> dict:
        body = client.get(f"/api/v1/ops/panels/{panel_id}?days=7", headers=AUTH).json()
        return {block["key"]: block.get("value") for block in body["blocks"]}

    assert values("content")["destinations_published"] == 2
    traffic = values("traffic")
    assert traffic["http_2xx"] >= 3
    assert traffic["http_4xx"] >= 2


@pytest.mark.integration
def test_health_panel_reports_database_and_redis_state(
    token: None, postgres_session: Session, fake: fakeredis.FakeRedis
) -> None:
    body = _app(fake, postgres_session).get("/api/v1/ops/panels/health", headers=AUTH).json()
    assert body["status"] in {"ok", "degraded"}
    keys = {block["key"] for block in body["blocks"]}
    assert keys, "the health panel must show something"
    text = json.dumps(body, ensure_ascii=False)
    assert TOKEN not in text
    assert get_settings().database_url.split("@")[-1] not in text  # no connection details
