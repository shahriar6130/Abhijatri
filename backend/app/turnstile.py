"""Server-side Cloudflare Turnstile validation (Platform Foundation 14.1).

A token is accepted only when Cloudflare reports success, the hostname is the expected one and
the action matches the endpoint. Cloudflare itself enforces single use and the 300 second
lifetime. Each verification carries an ``idempotency_key`` so a network retry of the siteverify
call cannot consume the token twice.

Failing to reach Cloudflare is *our* problem, not the visitor's: it returns 503, never a
challenge failure, and never lets the request through.
"""

import logging
import uuid
from collections.abc import Callable
from typing import Annotated, Protocol

import httpx
from fastapi import Depends

from app.config import get_settings
from app.errors import ApiError

logger = logging.getLogger(__name__)

ACTION_GUEST_REVIEW = "guest-review"
ACTION_GUEST_REPORT = "guest-report"
ACTION_GUEST_REMOVAL = "guest-removal"
ACTION_AUTH_REGISTER = "auth-register"
ACTION_AUTH_RESET = "auth-reset"


class Verifier(Protocol):
    def __call__(self, token: str | None, *, action: str, remote_address: str | None) -> None: ...


def verify_with_cloudflare(
    token: str | None,
    *,
    action: str,
    remote_address: str | None,
    transport: httpx.BaseTransport | None = None,
) -> None:
    settings = get_settings()
    if not settings.turnstile_enabled:
        return  # development and test only; production configuration requires it
    if not token:
        raise ApiError("CHALLENGE_FAILED")
    form = {
        "secret": settings.turnstile_secret or "",
        "response": token,
        "idempotency_key": str(uuid.uuid4()),
    }
    if remote_address:
        form["remoteip"] = remote_address

    result: dict[str, object] | None = None
    with httpx.Client(timeout=settings.turnstile_timeout_seconds, transport=transport) as client:
        for attempt in (1, 2):  # one retry with the same idempotency_key
            try:
                response = client.post(settings.turnstile_verify_url, data=form)
                response.raise_for_status()
                parsed = response.json()
                if not isinstance(parsed, dict):
                    raise ValueError("siteverify returned a non-object")
                result = parsed
                break
            except (httpx.HTTPError, ValueError) as error:
                logger.warning("turnstile siteverify attempt %d failed: %s", attempt, type(error).__name__)
    if result is None:
        raise ApiError("SERVICE_UNAVAILABLE", headers={"Retry-After": "5"})

    if (
        result.get("success") is not True
        or result.get("hostname") != settings.turnstile_hostname
        or result.get("action") != action
    ):
        raise ApiError("CHALLENGE_FAILED")


def get_turnstile_verifier() -> Verifier:
    """Dependency so tests and staging can substitute the verifier."""
    return verify_with_cloudflare


TurnstileDep = Annotated[Callable[..., None], Depends(get_turnstile_verifier)]
