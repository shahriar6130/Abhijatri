"""Thin server-side client for Supabase Auth (GoTrue).

Only this module knows GoTrue's URLs and error shapes. Passwords, tokens and raw responses are
never logged. A GoTrue failure that is not the visitor's fault becomes ``GoTrueUnavailable``
(a 503), never a pass.
"""

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class GoTrueError(Exception):
    """GoTrue answered with an error. ``code`` is GoTrue's own error code (e.g. ``invalid_credentials``)."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(f"{status} {code}")
        self.status = status
        self.code = code


class GoTrueUnavailable(Exception):
    """GoTrue could not be reached or answered with a server error."""


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str
    expires_in: int


def _pair(body: dict[str, Any]) -> TokenPair:
    return TokenPair(
        access_token=str(body["access_token"]),
        refresh_token=str(body["refresh_token"]),
        expires_in=int(body.get("expires_in", 3600)),
    )


class GoTrueClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    # ---- plumbing ----

    def _call(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, str] | None = None,
        bearer: str | None = None,
        service: bool = False,
    ) -> dict[str, Any]:
        settings = get_settings()
        if not settings.auth_configured:
            raise GoTrueUnavailable("not configured")
        key = (settings.supabase_service_role_key if service else settings.supabase_anon_key) or ""
        headers = {"apikey": key, "Authorization": f"Bearer {bearer or key}"}
        try:
            with httpx.Client(
                base_url=f"{settings.supabase_url}/auth/v1",
                timeout=settings.supabase_timeout_seconds,
                transport=self._transport,
            ) as client:
                response = client.request(method, path, json=json, params=params, headers=headers)
        except httpx.HTTPError as error:
            logger.warning("auth provider unreachable: %s", type(error).__name__)
            raise GoTrueUnavailable(type(error).__name__) from error
        if response.status_code >= 500:
            logger.warning("auth provider error %s on %s", response.status_code, path.split("?")[0])
            raise GoTrueUnavailable(str(response.status_code))
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        if not isinstance(body, dict):
            body = {}
        if response.status_code >= 400:
            code = str(body.get("error_code") or body.get("code") or body.get("error") or "unknown")
            raise GoTrueError(response.status_code, code)
        return body

    # ---- identity ----

    def sign_up(self, email: str, password: str, display_name: str) -> None:
        """With confirmations on, GoTrue answers the same for new and existing addresses."""
        self._call(
            "POST",
            "/signup",
            json={"email": email, "password": password, "data": {"display_name": display_name}},
        )

    def verify_token_hash(self, token_hash: str, kind: str) -> TokenPair:
        return _pair(self._call("POST", "/verify", json={"token_hash": token_hash, "type": kind}))

    def resend_confirmation(self, email: str) -> None:
        self._call("POST", "/resend", json={"type": "signup", "email": email})

    def sign_in(self, email: str, password: str) -> TokenPair:
        return _pair(
            self._call("POST", "/token", params={"grant_type": "password"}, json={"email": email, "password": password})
        )

    def refresh(self, refresh_token: str) -> TokenPair:
        return _pair(
            self._call("POST", "/token", params={"grant_type": "refresh_token"}, json={"refresh_token": refresh_token})
        )

    def sign_out(self, access_token: str) -> None:
        self._call("POST", "/logout", params={"scope": "global"}, bearer=access_token)

    def request_recovery(self, email: str) -> None:
        self._call("POST", "/recover", json={"email": email})

    def update_password(self, access_token: str, new_password: str) -> None:
        self._call("PUT", "/user", json={"password": new_password}, bearer=access_token)

    # ---- MFA (TOTP) ----

    def mfa_enroll(self, access_token: str, friendly_name: str) -> dict[str, Any]:
        return self._call(
            "POST",
            "/factors",
            json={"factor_type": "totp", "friendly_name": friendly_name, "issuer": "Abhijatri"},
            bearer=access_token,
        )

    def mfa_challenge(self, access_token: str, factor_id: str) -> str:
        return str(self._call("POST", f"/factors/{factor_id}/challenge", bearer=access_token)["id"])

    def mfa_verify(self, access_token: str, factor_id: str, challenge_id: str, code: str) -> TokenPair:
        return _pair(
            self._call(
                "POST",
                f"/factors/{factor_id}/verify",
                json={"challenge_id": challenge_id, "code": code},
                bearer=access_token,
            )
        )

    def list_factors(self, access_token: str) -> list[dict[str, Any]]:
        user = self._call("GET", "/user", bearer=access_token)
        factors = user.get("factors") or []
        return [f for f in factors if isinstance(f, dict)]

    # ---- admin (service role, server side only) ----

    def admin_sign_out_user(self, access_token: str) -> None:
        self._call("POST", "/logout", params={"scope": "global"}, bearer=access_token)

    def admin_generate_link(self, kind: str, email: str, password: str | None = None, data: dict[str, Any] | None = None) -> str:
        """Ask Auth for a one-time `token_hash` WITHOUT Auth sending any email (we send it ourselves).

        ``kind`` is ``signup`` (creates the unconfirmed account when ``password`` is given, or re-issues the
        link for an existing unconfirmed one) or ``recovery``. Raises ``GoTrueError`` with ``email_exists``
        for a confirmed account and ``user_not_found`` for an unknown address.
        """
        body: dict[str, Any] = {"type": kind, "email": email}
        if password is not None:
            body["password"] = password
        if data:
            body["data"] = data
        answer = self._call("POST", "/admin/generate_link", json=body, service=True)
        token = answer.get("hashed_token") or (answer.get("properties") or {}).get("hashed_token")
        if not token:
            raise GoTrueUnavailable("no token in generate_link answer")
        return str(token)

    def admin_create_confirmed_user(self, email: str, password: str, data: dict[str, Any]) -> None:
        """Create an account whose email is already confirmed (AUTH_SKIP_EMAIL_VERIFICATION, development only).

        Raises ``GoTrueError`` with ``email_exists`` when the address is taken.
        """
        body = {"email": email, "password": password, "email_confirm": True, "user_metadata": data}
        self._call("POST", "/admin/users", json=body, service=True)

    def admin_ban_user(self, user_id: str, hours: int | None) -> None:
        duration = "none" if hours is None else f"{hours}h"
        self._call("PUT", f"/admin/users/{user_id}", json={"ban_duration": duration}, service=True)


def get_gotrue() -> GoTrueClient:
    """Dependency so tests substitute a fake."""
    return GoTrueClient()
