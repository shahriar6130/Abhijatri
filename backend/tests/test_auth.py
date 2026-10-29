"""Member authentication (Gantt R04, API.md 5.17) against a fake Auth provider.

Tokens are real HS256 JWTs, so signature, expiry, audience and claim handling are the production
code paths. Only the call out to Supabase Auth is replaced.
"""

import re
import time
import uuid
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from typing import Any

import fakeredis
import jwt
import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import visits
from app.abuse import get_counter_session_factory
from app.auth import csrf, tokens, validation
from app.auth.gotrue import GoTrueError, TokenPair, get_gotrue
from app.auth.sessions import Principal, require_recent_auth, staff_principal
from app.config import get_settings
from app.db import get_session
from app.destination_services import today_in_display_tz
from app.errors import ApiError
from app.limits import limiter
from app.main import create_app
from app.models import AuthSessionActivity, User, UserRole
from app.redis_client import get_redis

SECRET = "unit-test-jwt-secret-with-more-than-32-bytes"
ORIGIN = "http://localhost:5173"
PASSWORD = "Passw0rdTest99"


class FakeGoTrue:
    """Just enough of Supabase Auth: users, confirmation, sessions, TOTP."""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, Any]] = {}
        self.refresh_tokens: dict[str, str] = {}
        self.calls: list[str] = []
        self.sign_outs: list[str] = []
        self.verify_tokens: dict[str, tuple[str, str]] = {}  # token_hash -> (email, kind)
        self.factors: dict[str, list[dict[str, Any]]] = {}
        self.aal_for: dict[str, str] = {}

    # ---- helpers for tests ----
    def add_user(self, email: str, *, confirmed: bool = True, password: str = PASSWORD, name: str = "Rafi Test") -> uuid.UUID:
        user_id = uuid.uuid4()
        self.users[email] = {"id": user_id, "password": password, "confirmed": confirmed, "name": name}
        return user_id

    def mint(
        self, email: str, *, aal: str = "aal1", expires_in: int = 3600, session_id: uuid.UUID | None = None, auth_age: int = 0
    ) -> TokenPair:
        user = self.users[email]
        now = int(time.time())
        claims = {
            "sub": str(user["id"]),
            "aud": "authenticated",
            "email": email,
            "iat": now,
            "exp": now + expires_in,
            "session_id": str(session_id or uuid.uuid4()),
            "aal": aal,
            "amr": [{"method": "password", "timestamp": now - auth_age}],
            "user_metadata": {"display_name": user["name"]},
        }
        access = jwt.encode(claims, SECRET, algorithm="HS256")
        refresh = f"refresh-{uuid.uuid4().hex}"
        self.refresh_tokens[refresh] = email
        return TokenPair(access_token=access, refresh_token=refresh, expires_in=expires_in)

    # ---- the client interface ----
    def sign_up(self, email: str, password: str, display_name: str) -> None:
        self.calls.append("sign_up")
        if email not in self.users:  # an existing address is silently ignored, like Supabase with confirmations on
            self.add_user(email, confirmed=False, password=password, name=display_name)

    def verify_token_hash(self, token_hash: str, kind: str) -> TokenPair:
        self.calls.append(f"verify:{kind}")
        email, expected = self.verify_tokens.pop(token_hash, ("", ""))
        if not email or expected != kind:
            raise GoTrueError(403, "otp_expired")
        self.users[email]["confirmed"] = True
        return self.mint(email)

    def resend_confirmation(self, email: str) -> None:
        self.calls.append("resend")

    def sign_in(self, email: str, password: str) -> TokenPair:
        self.calls.append("sign_in")
        user = self.users.get(email)
        if user is None or user["password"] != password:
            raise GoTrueError(400, "invalid_credentials")
        if not user["confirmed"]:
            raise GoTrueError(400, "email_not_confirmed")
        return self.mint(email)

    def refresh(self, refresh_token: str) -> TokenPair:
        self.calls.append("refresh")
        email = self.refresh_tokens.pop(refresh_token, None)
        if email is None:
            raise GoTrueError(400, "refresh_token_not_found")
        return self.mint(email)

    def sign_out(self, access_token: str) -> None:
        self.calls.append("sign_out")
        self.sign_outs.append(access_token)

    def admin_generate_link(self, kind: str, email: str, password: str | None = None, data: dict[str, Any] | None = None) -> str:
        self.calls.append(f"generate:{kind}")
        user = self.users.get(email)
        if kind == "signup":
            if user is not None and user["confirmed"]:
                raise GoTrueError(422, "email_exists")
            if user is None:
                if password is None:
                    raise GoTrueError(404, "user_not_found")
                self.add_user(email, confirmed=False, password=password, name=(data or {}).get("display_name", "Member"))
        elif user is None:
            raise GoTrueError(404, "user_not_found")
        token = f"{kind}-{uuid.uuid4().hex}"
        self.verify_tokens[token] = (email, kind)
        return token

    def admin_create_confirmed_user(self, email: str, password: str, data: dict[str, Any]) -> None:
        self.calls.append("create_confirmed")
        if email in self.users:
            raise GoTrueError(422, "email_exists")
        self.add_user(email, confirmed=True, password=password, name=data.get("display_name", "Member"))

    def request_recovery(self, email: str) -> None:
        self.calls.append("recover")
        if email in self.users:
            self.verify_tokens[f"recovery-{email}"] = (email, "recovery")

    def update_password(self, access_token: str, new_password: str) -> None:
        self.calls.append("update_password")
        claims = tokens.verify_access_token(access_token)
        for user in self.users.values():
            if user["id"] == claims.user_id:
                if user["password"] == new_password:
                    raise GoTrueError(422, "same_password")  # what Supabase answers
                user["password"] = new_password

    def list_factors(self, access_token: str) -> list[dict[str, Any]]:
        claims = tokens.verify_access_token(access_token)
        return self.factors.get(str(claims.user_id), [])

    def mfa_enroll(self, access_token: str, friendly_name: str) -> dict[str, Any]:
        return {"id": "factor-12345678", "totp": {"secret": "JBSWY3DPEHPK3PXP", "uri": "otpauth://x", "qr_code": "<svg/>"}}

    def mfa_challenge(self, access_token: str, factor_id: str) -> str:
        return "challenge-1"

    def mfa_verify(self, access_token: str, factor_id: str, challenge_id: str, code: str) -> TokenPair:
        if code != "123456":
            raise GoTrueError(400, "mfa_verification_failed")
        claims = tokens.verify_access_token(access_token)
        email = next(e for e, u in self.users.items() if u["id"] == claims.user_id)
        return self.mint(email, aal="aal2", session_id=claims.session_id)


@pytest.fixture(autouse=True)
def _reset_limiter() -> None:
    limiter.reset()


@pytest.fixture()
def auth_env(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.setenv("SUPABASE_URL", "http://auth.test")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key-for-tests")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("CLIENT_ADDRESS_HEADER", "X-Forwarded-For")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", f"{ORIGIN},http://localhost:5175")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def fake() -> FakeGoTrue:
    return FakeGoTrue()


@pytest.fixture()
def redis_fake() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(server=fakeredis.FakeServer(), decode_responses=True)


@pytest.fixture()
def client(
    auth_env: None, postgres_session: Session, fake: FakeGoTrue, redis_fake: fakeredis.FakeRedis
) -> TestClient:
    return make_client(postgres_session, fake, redis_fake)


def make_client(postgres_session: Session, fake: FakeGoTrue, redis_fake: fakeredis.FakeRedis) -> TestClient:
    """An app wired to the test database, the fake Auth provider and fakeredis (shared by the staff tests)."""
    application = create_app()
    factory = sessionmaker(bind=postgres_session.get_bind(), expire_on_commit=False)

    def session_override() -> Generator[Session, None, None]:
        yield postgres_session

    application.dependency_overrides[get_session] = session_override
    application.dependency_overrides[get_counter_session_factory] = lambda: factory
    application.dependency_overrides[get_gotrue] = lambda: fake
    application.dependency_overrides[get_redis] = lambda: redis_fake

    @application.get("/_test/member")
    def member_route(principal: Principal = Depends(staff_principal("moderator", "superadmin"))) -> dict[str, str | None]:  # type: ignore[assignment]
        return {"role": principal.role}

    @application.get("/_test/superadmin")
    def superadmin_route(principal: Principal = Depends(staff_principal("superadmin"))) -> dict[str, str | None]:  # type: ignore[assignment]
        return {"role": principal.role}

    return TestClient(application, base_url="https://localhost", headers={"Origin": ORIGIN, "X-Forwarded-For": "203.0.113.5"})


def _login(client: TestClient, fake: FakeGoTrue, email: str = "rafi@example.com", **kwargs: Any) -> str:
    fake.add_user(email, **kwargs)
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return email


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.get("/api/v1/auth/csrf").json()["csrf_token"]}


def _cookie_headers(response: Any) -> list[str]:
    return response.headers.get_list("set-cookie")


# ---- configuration ----


def test_every_route_is_501_until_the_provider_is_configured(
    monkeypatch: pytest.MonkeyPatch, postgres_session: Session
) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    get_settings.cache_clear()
    try:
        response = TestClient(create_app()).post("/api/v1/auth/login", json={"email": "a@b.co", "password": PASSWORD})
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"
    finally:
        get_settings.cache_clear()


# ---- registration ----


@pytest.mark.integration
def test_register_answers_the_same_for_new_and_existing_addresses(client: TestClient, fake: FakeGoTrue) -> None:
    body = {"email": "New.User@Example.com", "password": PASSWORD, "display_name": "Nila"}
    first = client.post("/api/v1/auth/register", json=body)
    second = client.post("/api/v1/auth/register", json=body)
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json() == {"status": "verification_sent"}
    assert "new.user@example.com" in fake.users  # the address is normalised
    assert first.headers["cache-control"] == "no-store"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"email": "not-an-email", "password": PASSWORD, "display_name": "Nila"}, "email"),
        ({"email": "a@example.com", "password": "short1", "display_name": "Nila"}, "password"),
        ({"email": "a@example.com", "password": "onlyletterspassword", "display_name": "Nila"}, "password"),
        ({"email": "a@example.com", "password": PASSWORD, "display_name": "   "}, "display_name"),
    ],
)
def test_register_rejects_invalid_input_with_field_errors(client: TestClient, body: dict[str, str], field: str) -> None:
    response = client.post("/api/v1/auth/register", json=body)
    assert response.status_code == 422
    assert field in {item["field"] for item in response.json()["error"]["field_errors"]}


@pytest.mark.integration
@pytest.mark.parametrize("name", ["Admin", "admin", "Moderator", "Abhijatri Team", "4dm1n", "ADM IN".replace(" ", "")])
def test_register_refuses_reserved_and_look_alike_names(client: TestClient, name: str) -> None:
    response = client.post(
        "/api/v1/auth/register", json={"email": "a@example.com", "password": PASSWORD, "display_name": name}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "RESERVED_DISPLAY_NAME"


@pytest.mark.integration
def test_register_rejects_unknown_fields(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "a@example.com", "password": PASSWORD, "display_name": "Nila", "is_staff": True},
    )
    assert response.status_code == 422


@pytest.mark.integration
def test_register_is_limited_per_network(client: TestClient) -> None:
    codes = [
        client.post(
            "/api/v1/auth/register",
            json={"email": f"user{i}@example.com", "password": PASSWORD, "display_name": f"Nila {i}"},
        ).status_code
        for i in range(11)
    ]
    assert codes[:10] == [202] * 10
    assert codes[10] == 429


# ---- verification ----


@pytest.mark.integration
def test_verify_email_confirms_without_creating_a_session(client: TestClient, fake: FakeGoTrue) -> None:
    fake.add_user("v@example.com", confirmed=False)
    fake.verify_tokens["good-token-hash-1"] = ("v@example.com", "signup")
    response = client.post("/api/v1/auth/verify-email", json={"token_hash": "good-token-hash-1"})
    assert response.status_code == 200 and response.json() == {"status": "verified"}
    assert _cookie_headers(response) == []
    assert fake.sign_outs, "the session created by the link is revoked"
    assert fake.users["v@example.com"]["confirmed"] is True


@pytest.mark.integration
def test_verify_email_rejects_a_used_or_wrong_link(client: TestClient, fake: FakeGoTrue) -> None:
    response = client.post("/api/v1/auth/verify-email", json={"token_hash": "never-issued-token"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TOKEN_INVALID_OR_EXPIRED"


# ---- sign-in ----


@pytest.mark.integration
def test_login_sets_httponly_cookies_and_never_returns_a_token(
    client: TestClient, fake: FakeGoTrue, postgres_session: Session
) -> None:
    fake.add_user("rafi@example.com")
    response = client.post("/api/v1/auth/login", json={"email": "Rafi@Example.com ", "password": PASSWORD})
    assert response.status_code == 200
    body = response.json()
    assert body["authenticated"] is True and body["user"]["email"] == "rafi@example.com"
    assert body["role"] is None and body["aal"] == "aal1"
    assert "eyJ" not in response.text and "refresh-" not in response.text
    cookies = _cookie_headers(response)
    assert len(cookies) == 2
    for cookie in cookies:
        lowered = cookie.lower()
        assert lowered.startswith("__host-abhijatri_")
        assert "httponly" in lowered and "secure" in lowered and "path=/" in lowered and "domain=" not in lowered
        assert "samesite=lax" in lowered
    user = postgres_session.get(User, fake.users["rafi@example.com"]["id"])
    assert user is not None and user.email_verified_at is not None and user.display_name == "Rafi Test"
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.integration
def test_login_failures_look_alike_and_are_throttled(client: TestClient, fake: FakeGoTrue) -> None:
    fake.add_user("rafi@example.com")
    wrong_password = client.post("/api/v1/auth/login", json={"email": "rafi@example.com", "password": "wrongpass1234"})
    unknown_user = client.post("/api/v1/auth/login", json={"email": "ghost@example.com", "password": "wrongpass1234"})
    assert wrong_password.status_code == unknown_user.status_code == 401
    assert wrong_password.json()["error"]["code"] == unknown_user.json()["error"]["code"] == "INVALID_CREDENTIALS"
    assert wrong_password.json()["error"]["message"] == unknown_user.json()["error"]["message"]
    for _ in range(4):
        client.post("/api/v1/auth/login", json={"email": "rafi@example.com", "password": "wrongpass1234"})
    blocked = client.post("/api/v1/auth/login", json={"email": "rafi@example.com", "password": PASSWORD})
    assert blocked.status_code == 429 and "retry-after" in blocked.headers
    assert "sign_in" in fake.calls
    other = client.post("/api/v1/auth/login", json={"email": "someone@example.com", "password": "wrongpass1234"})
    assert other.status_code == 401, "one account's lockout does not block other emails"


@pytest.mark.integration
def test_unverified_email_is_reported_only_after_the_right_password(client: TestClient, fake: FakeGoTrue) -> None:
    fake.add_user("new@example.com", confirmed=False)
    right = client.post("/api/v1/auth/login", json={"email": "new@example.com", "password": PASSWORD})
    assert right.status_code == 403 and right.json()["error"]["code"] == "EMAIL_NOT_VERIFIED"
    wrong = client.post("/api/v1/auth/login", json={"email": "new@example.com", "password": "wrongpass1234"})
    assert wrong.status_code == 401


@pytest.mark.integration
def test_a_disabled_account_cannot_sign_in_or_use_a_session(
    client: TestClient, fake: FakeGoTrue, postgres_session: Session
) -> None:
    email = _login(client, fake)
    user = postgres_session.get(User, fake.users[email]["id"])
    assert user is not None
    user.status, user.disabled_at = "disabled", datetime.now(UTC)
    postgres_session.commit()
    assert client.get("/api/v1/auth/session").status_code == 403
    fresh = TestClient(client.app, base_url="https://localhost", headers={"Origin": ORIGIN, "X-Forwarded-For": "203.0.113.6"})
    denied = fresh.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert denied.status_code == 403 and denied.json()["error"]["code"] == "ACCOUNT_DISABLED"


# ---- session, refresh, CSRF, logout ----


@pytest.mark.integration
def test_session_is_anonymous_without_cookies_and_never_a_401(client: TestClient) -> None:
    response = client.get("/api/v1/auth/session")
    assert response.status_code == 200 and response.json() == {"authenticated": False}


@pytest.mark.integration
def test_session_refreshes_an_expired_access_token_once(client: TestClient, fake: FakeGoTrue) -> None:
    email = _login(client, fake)
    expired = fake.mint(email, expires_in=-60)
    client.cookies.set("__Host-abhijatri_session", expired.access_token)
    response = client.get("/api/v1/auth/session")
    assert response.status_code == 200 and response.json()["authenticated"] is True
    assert fake.calls.count("refresh") == 1
    assert any(c.startswith("__Host-abhijatri_session=") for c in _cookie_headers(response))


@pytest.mark.integration
def test_a_tampered_or_foreign_token_is_not_a_session(client: TestClient, fake: FakeGoTrue) -> None:
    fake.add_user("rafi@example.com")
    good = fake.mint("rafi@example.com").access_token
    for bad in (good[:-3] + "abc", jwt.encode({"sub": str(uuid.uuid4()), "aud": "authenticated", "exp": int(time.time()) + 600}, "another-secret-that-is-long-enough-xx", algorithm="HS256")):
        client.cookies.clear()
        client.cookies.set("__Host-abhijatri_session", bad)
        assert client.get("/api/v1/auth/session").json() == {"authenticated": False}


@pytest.mark.integration
def test_csrf_origin_and_logout(client: TestClient, fake: FakeGoTrue) -> None:
    _login(client, fake)
    without = client.post("/api/v1/auth/logout")
    assert without.status_code == 403 and without.json()["error"]["code"] == "CSRF_INVALID"
    forged = client.post("/api/v1/auth/logout", headers={**_csrf(client), "X-CSRF-Token": "x.y"})
    assert forged.status_code == 403
    foreign = client.post("/api/v1/auth/login", json={"email": "a@b.co", "password": PASSWORD}, headers={"Origin": "https://evil.example"})
    assert foreign.status_code == 403 and foreign.json()["error"]["code"] == "CSRF_INVALID"
    ok = client.post("/api/v1/auth/logout", headers=_csrf(client))
    assert ok.status_code == 204
    cleared = _cookie_headers(ok)
    assert cleared and all("max-age=0" in c.lower() for c in cleared)
    assert fake.sign_outs
    client.cookies.clear()
    assert client.get("/api/v1/auth/session").json() == {"authenticated": False}


@pytest.mark.integration
def test_a_csrf_token_belongs_to_one_session(client: TestClient, fake: FakeGoTrue) -> None:
    _login(client, fake)
    token = client.get("/api/v1/auth/csrf").json()["csrf_token"]
    assert csrf.verify(client.get("/api/v1/auth/session").json()["user"]["id"], token) is False  # bound to the session id
    other = TestClient(client.app, base_url="https://localhost", headers={"Origin": ORIGIN, "X-Forwarded-For": "203.0.113.9"})
    _login(other, fake, "second@example.com")
    assert other.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token}).status_code == 403


@pytest.mark.integration
def test_csrf_endpoint_needs_a_session(client: TestClient) -> None:
    assert client.get("/api/v1/auth/csrf").status_code == 401


# ---- password reset ----


@pytest.mark.integration
def test_reset_request_is_identical_for_known_and_unknown_addresses(client: TestClient, fake: FakeGoTrue) -> None:
    fake.add_user("rafi@example.com")
    known = client.post("/api/v1/auth/password-reset/request", json={"email": "rafi@example.com"})
    unknown = client.post("/api/v1/auth/password-reset/request", json={"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 202
    assert known.json() == unknown.json() == {"status": "reset_sent"}


@pytest.mark.integration
def test_reset_request_is_limited_per_address(client: TestClient) -> None:
    codes = [client.post("/api/v1/auth/password-reset/request", json={"email": "rafi@example.com"}).status_code for _ in range(4)]
    assert codes == [202, 202, 202, 429]


@pytest.mark.integration
def test_reset_confirm_checks_the_password_before_spending_the_link(client: TestClient, fake: FakeGoTrue) -> None:
    fake.add_user("rafi@example.com")
    fake.verify_tokens["reset-link-token-1"] = ("rafi@example.com", "recovery")
    weak = client.post("/api/v1/auth/password-reset/confirm", json={"token_hash": "reset-link-token-1", "new_password": "short"})
    assert weak.status_code == 422
    assert "reset-link-token-1" in fake.verify_tokens, "the link must survive a rejected password"
    done = client.post(
        "/api/v1/auth/password-reset/confirm", json={"token_hash": "reset-link-token-1", "new_password": "BrandNewPass123"}
    )
    assert done.status_code == 200 and done.json() == {"status": "password_changed"}
    assert fake.users["rafi@example.com"]["password"] == "BrandNewPass123"
    assert fake.sign_outs, "all sessions end after a reset"
    again = client.post(
        "/api/v1/auth/password-reset/confirm", json={"token_hash": "reset-link-token-1", "new_password": "AnotherPass123"}
    )
    assert again.status_code == 422 and again.json()["error"]["code"] == "TOKEN_INVALID_OR_EXPIRED"



@pytest.mark.integration
def test_reset_to_the_same_password_says_so(client: TestClient, fake: FakeGoTrue) -> None:
    fake.add_user("rafi@example.com")
    fake.verify_tokens["reset-link-token-2"] = ("rafi@example.com", "recovery")
    same = client.post("/api/v1/auth/password-reset/confirm", json={"token_hash": "reset-link-token-2", "new_password": PASSWORD})
    assert same.status_code == 422
    assert same.json()["error"]["field_errors"] == [{"field": "password", "code": "SAME_PASSWORD"}]


# ---- visits ----


@pytest.mark.integration
def test_a_member_is_counted_once_per_dhaka_day(client: TestClient, fake: FakeGoTrue, redis_fake: fakeredis.FakeRedis) -> None:
    _login(client, fake)
    client.get("/api/v1/auth/session")
    client.get("/api/v1/auth/session")
    counts = visits.read_day(redis_fake, today_in_display_tz())
    assert counts is not None and counts.member_new == 1 and counts.member_returning == 0


# ---- staff gates (Moderation spec 2.4 and 4) ----


@pytest.mark.integration
def test_staff_routes_hide_from_members_and_demand_totp(
    client: TestClient, fake: FakeGoTrue, postgres_session: Session
) -> None:
    assert client.get("/_test/member").status_code == 401
    email = _login(client, fake)
    assert client.get("/_test/member").status_code == 404, "a member is told the staff route does not exist"
    user_id = fake.users[email]["id"]
    postgres_session.add(UserRole(user_id=user_id, role="moderator"))
    postgres_session.commit()
    needs_mfa = client.get("/_test/member")
    assert needs_mfa.status_code == 403 and needs_mfa.json()["error"]["code"] == "MFA_REQUIRED"
    client.cookies.set("__Host-abhijatri_session", fake.mint(email, aal="aal2").access_token)
    assert client.get("/_test/member").json() == {"role": "moderator"}
    assert client.get("/_test/superadmin").status_code == 403, "a moderator is not a superadmin"


@pytest.mark.integration
def test_a_revoked_role_loses_access_even_with_a_valid_token(
    client: TestClient, fake: FakeGoTrue, postgres_session: Session
) -> None:
    email = _login(client, fake)
    user_id = fake.users[email]["id"]
    role = UserRole(user_id=user_id, role="moderator")
    postgres_session.add(role)
    postgres_session.commit()
    client.cookies.set("__Host-abhijatri_session", fake.mint(email, aal="aal2").access_token)
    assert client.get("/_test/member").status_code == 200
    role.revoked_at = datetime.now(UTC)
    postgres_session.commit()
    assert client.get("/_test/member").status_code == 404, "the role is read from the database on every request"


@pytest.mark.integration
def test_staff_writes_need_a_csrf_token(client: TestClient, fake: FakeGoTrue, postgres_session: Session) -> None:
    email = _login(client, fake)
    postgres_session.add(UserRole(user_id=fake.users[email]["id"], role="moderator"))
    postgres_session.commit()
    client.cookies.set("__Host-abhijatri_session", fake.mint(email, aal="aal2").access_token)
    application = client.app

    @application.post("/_test/write")  # type: ignore[attr-defined]
    def write(principal: Principal = Depends(staff_principal("moderator"))) -> dict[str, bool]:  # type: ignore[assignment]
        return {"ok": True}

    assert client.post("/_test/write").status_code == 403
    assert client.post("/_test/write", headers=_csrf(client)).status_code == 200


@pytest.mark.integration
def test_a_superadmin_session_ends_after_inactivity(
    client: TestClient, fake: FakeGoTrue, postgres_session: Session
) -> None:
    email = _login(client, fake)
    user_id = fake.users[email]["id"]
    postgres_session.add(UserRole(user_id=user_id, role="superadmin"))
    session_id = uuid.uuid4()
    client.cookies.set("__Host-abhijatri_session", fake.mint(email, aal="aal2", session_id=session_id).access_token)
    postgres_session.add(
        AuthSessionActivity(session_id=session_id, user_id=user_id, last_seen_at=datetime.now(UTC) - timedelta(hours=9))
    )
    postgres_session.commit()
    assert client.get("/api/v1/auth/session").json() == {"authenticated": False}
    assert postgres_session.scalar(select(AuthSessionActivity).where(AuthSessionActivity.session_id == session_id)) is not None


@pytest.mark.integration
def test_mfa_enroll_verify_and_reauth(client: TestClient, fake: FakeGoTrue) -> None:
    email = _login(client, fake)
    enrolled = client.post("/api/v1/auth/mfa/enroll", headers=_csrf(client))
    assert enrolled.status_code == 200 and enrolled.json()["factor_id"] == "factor-12345678"
    wrong = client.post("/api/v1/auth/mfa/verify", json={"factor_id": "factor-12345678", "code": "000000"}, headers=_csrf(client))
    assert wrong.status_code == 401
    verified = client.post("/api/v1/auth/mfa/verify", json={"factor_id": "factor-12345678", "code": "123456"}, headers=_csrf(client))
    assert verified.status_code == 200 and verified.json()["aal"] == "aal2"
    assert client.get("/api/v1/auth/session").json()["aal"] == "aal2"

    fake.factors[str(fake.users[email]["id"])] = [{"id": "factor-12345678", "factor_type": "totp", "status": "verified"}]
    no_code = client.post("/api/v1/auth/reauth", json={"password": PASSWORD}, headers=_csrf(client))
    assert no_code.status_code == 403 and no_code.json()["error"]["code"] == "MFA_REQUIRED"
    bad_password = client.post("/api/v1/auth/reauth", json={"password": "wrongpass1234", "code": "123456"}, headers=_csrf(client))
    assert bad_password.status_code == 401
    ok = client.post("/api/v1/auth/reauth", json={"password": PASSWORD, "code": "123456"}, headers=_csrf(client))
    assert ok.status_code == 200 and ok.json()["aal"] == "aal2"


# ---- units that need no database ----


def test_recent_authentication_window() -> None:
    claims = tokens.Claims(
        user_id=uuid.uuid4(), email="a@b.co", session_id=None, aal="aal2", amr=("password",),
        expires_at=datetime.now(UTC) + timedelta(hours=1), issued_at=datetime.now(UTC),
        auth_time=datetime.now(UTC) - timedelta(minutes=30), display_name=None,
    )
    stale = Principal(user=User(email="a@b.co", display_name="A"), claims=claims, role="superadmin")
    with pytest.raises(ApiError) as caught:
        require_recent_auth(stale)
    assert caught.value.code == "REAUTH_REQUIRED"
    fresh = Principal(user=stale.user, claims=claims.__class__(**{**claims.__dict__, "auth_time": datetime.now(UTC)}), role="superadmin")
    require_recent_auth(fresh)


def test_token_verification_rejects_expiry_audience_and_algorithm_confusion(auth_env: None) -> None:
    now = int(time.time())
    base = {"sub": str(uuid.uuid4()), "aud": "authenticated", "exp": now + 600, "email": "a@b.co"}
    assert tokens.verify_access_token(jwt.encode(base, SECRET, algorithm="HS256")).email == "a@b.co"
    with pytest.raises(tokens.InvalidToken):
        tokens.verify_access_token(jwt.encode({**base, "exp": now - tokens.CLOCK_SKEW_SECONDS - 5}, SECRET, algorithm="HS256"))
    with pytest.raises(tokens.InvalidToken):
        tokens.verify_access_token(jwt.encode({**base, "aud": "anon"}, SECRET, algorithm="HS256"))
    with pytest.raises(tokens.InvalidToken):
        tokens.verify_access_token(jwt.encode({**base, "sub": "not-a-uuid"}, SECRET, algorithm="HS256"))
    with pytest.raises(tokens.InvalidToken):
        tokens.verify_access_token(jwt.encode(base, SECRET, algorithm="HS512"))  # algorithm not on the allow-list
    unsigned = jwt.encode(base, "", algorithm="none")
    with pytest.raises(tokens.InvalidToken):
        tokens.verify_access_token(unsigned)


def test_validators() -> None:
    assert validation.password_problem("Passw0rdTest99") is None
    assert validation.password_problem("short1") == "TOO_SHORT"
    assert validation.password_problem("a" * 200) == "TOO_LONG"
    assert validation.password_problem("alllettersnodigit") == "WEAK"
    assert validation.is_reserved("Admin") and validation.is_reserved("m0derator") and validation.is_reserved("Abhijatri Team")
    assert not validation.is_reserved("Nila Rahman")
    assert re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", validation.normalize_email("  A@B.Co "))


@pytest.mark.integration
def test_skip_verification_creates_a_confirmed_account_without_email(
    client: TestClient, fake: FakeGoTrue, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTH_SKIP_EMAIL_VERIFICATION", "true")
    get_settings.cache_clear()
    body = {"email": "nila@example.com", "password": PASSWORD, "display_name": "Nila"}
    first = client.post("/api/v1/auth/register", json=body)
    again = client.post("/api/v1/auth/register", json=body)
    assert first.status_code == again.status_code == 202
    assert first.json() == again.json() == {"status": "registered"}, "an existing address looks the same"
    assert "sign_up" not in fake.calls and not any(c.startswith("generate:") for c in fake.calls), "no email is sent"
    assert client.post("/api/v1/auth/login", json={"email": "nila@example.com", "password": PASSWORD}).status_code == 200


# ---- account emails sent by this API (AUTH_EMAIL_DELIVERY=app) ----


@pytest.fixture()
def app_mail(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.auth import mail
    from app.notify.providers import RecordingProvider

    provider = RecordingProvider()
    monkeypatch.setenv("AUTH_EMAIL_DELIVERY", "app")
    monkeypatch.setenv("EMAIL_PROVIDER", "mailpit")
    get_settings.cache_clear()
    monkeypatch.setattr(mail, "get_provider", lambda: provider)
    return provider


@pytest.mark.integration
def test_app_mode_sends_the_verification_email_itself(client: TestClient, fake: FakeGoTrue, app_mail: Any) -> None:
    response = client.post("/api/v1/auth/register", json={"email": "nila@example.com", "password": PASSWORD, "display_name": "Nila"})
    assert response.status_code == 202
    assert "sign_up" not in fake.calls and "generate:signup" in fake.calls, "Auth only issues the token"
    sent = app_mail.sent
    assert len(sent) == 1 and sent[0].to == "nila@example.com" and "Confirm" in sent[0].subject
    link = re.search(r"https?://[^\s]+/verify-email\?token_hash=([^&\s]+)&type=signup", sent[0].text)
    assert link is not None and "Nila" in sent[0].text
    verified = client.post("/api/v1/auth/verify-email", json={"token_hash": link.group(1)})
    assert verified.status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "nila@example.com", "password": PASSWORD}).status_code == 200


@pytest.mark.integration
def test_app_mode_answers_the_same_for_existing_and_unknown_addresses(client: TestClient, fake: FakeGoTrue, app_mail: Any) -> None:
    fake.add_user("taken@example.com")  # confirmed
    taken = client.post("/api/v1/auth/register", json={"email": "taken@example.com", "password": PASSWORD, "display_name": "Taken"})
    assert taken.status_code == 202 and taken.json() == {"status": "verification_sent"}
    unknown_reset = client.post("/api/v1/auth/password-reset/request", json={"email": "ghost@example.com"})
    known_reset = client.post("/api/v1/auth/password-reset/request", json={"email": "taken@example.com"})
    assert unknown_reset.json() == known_reset.json() == {"status": "reset_sent"}
    assert [e.to for e in app_mail.sent] == ["taken@example.com"], "only the real account gets the reset email"
    assert "reset-password?token_hash=" in app_mail.sent[0].text


@pytest.mark.integration
def test_app_mode_resend_keeps_the_password(client: TestClient, fake: FakeGoTrue, app_mail: Any) -> None:
    client.post("/api/v1/auth/register", json={"email": "nila@example.com", "password": PASSWORD, "display_name": "Nila"})
    again = client.post("/api/v1/auth/resend-verification", json={"email": "nila@example.com"})
    assert again.status_code == 202 and len(app_mail.sent) == 2
    assert fake.users["nila@example.com"]["password"] == PASSWORD
    assert client.post("/api/v1/auth/resend-verification", json={"email": "ghost@example.com"}).status_code == 202
    assert len(app_mail.sent) == 2


@pytest.mark.integration
def test_app_mode_reset_link_changes_the_password(client: TestClient, fake: FakeGoTrue, app_mail: Any) -> None:
    fake.add_user("nila@example.com")
    client.post("/api/v1/auth/password-reset/request", json={"email": "nila@example.com"})
    token = re.search(r"token_hash=([^&\s]+)&type=recovery", app_mail.sent[0].text)
    assert token is not None
    done = client.post("/api/v1/auth/password-reset/confirm", json={"token_hash": token.group(1), "new_password": "BrandNewPass123"})
    assert done.status_code == 200 and fake.users["nila@example.com"]["password"] == "BrandNewPass123"
