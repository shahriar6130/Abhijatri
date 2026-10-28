"""Synchronizer CSRF tokens bound to the session (Platform Foundation 16.2, Security 4.2).

A token is ``<nonce>.<mac>`` where the MAC covers the session id and the nonce under the HMAC
keyring. It is fetched from ``GET /auth/csrf`` and sent as ``X-CSRF-Token`` on every cookie-
authenticated write. Rotating the session invalidates it. The Origin check is only a second layer.
"""

import base64
import hmac
import secrets

from fastapi import Request

from app import crypto
from app.config import get_settings
from app.errors import ApiError

CSRF_LABEL = "abhijatri:csrf:v1"
HEADER = "X-CSRF-Token"


def _mac(binding: str, nonce: str) -> str:
    raw = crypto.digest(CSRF_LABEL, crypto.current_key_id(), f"{binding}:{nonce}")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def issue(binding: str) -> str:
    nonce = secrets.token_urlsafe(16)
    return f"{nonce}.{_mac(binding, nonce)}"


def verify(binding: str, token: str | None) -> bool:
    if not token or "." not in token:
        return False
    nonce, _, mac = token.partition(".")
    return hmac.compare_digest(mac, _mac(binding, nonce))


def require_valid(request: Request, binding: str) -> None:
    if not verify(binding, request.headers.get(HEADER)):
        raise ApiError("CSRF_INVALID")


def check_origin(request: Request) -> None:
    """Browsers always send Origin on cross-site writes; a foreign one is refused outright."""
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in get_settings().cors_origins:
        raise ApiError("CSRF_INVALID")
