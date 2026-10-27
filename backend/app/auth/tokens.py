"""Verification of Supabase access tokens (JWTs).

Local and hosted projects sign with either a shared secret (HS256) or an asymmetric key published
at a JWKS URL (ES256/RS256). Both are supported; the token header chooses. Expiry, audience and
signature are always checked. A token proves identity only; permissions come from the database.
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any

import jwt
from jwt import PyJWKClient

from app.config import get_settings

logger = logging.getLogger(__name__)

AUDIENCE = "authenticated"
# Small allowance for clock drift between this server and Supabase Auth. A larger difference means
# the server clock or time zone is wrong and must be fixed there, not hidden here.
CLOCK_SKEW_SECONDS = 30
ASYMMETRIC = ("ES256", "RS256", "EdDSA")


class InvalidToken(Exception):
    pass


@dataclass(frozen=True)
class Claims:
    user_id: uuid.UUID
    email: str
    session_id: uuid.UUID | None
    aal: str
    amr: tuple[str, ...]
    expires_at: datetime
    issued_at: datetime
    display_name: str | None
    auth_time: datetime  # latest password or TOTP check: stays put when the access token is refreshed
    user_metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def mfa_verified(self) -> bool:
        return self.aal == "aal2"


@lru_cache
def _jwks_client(url: str) -> PyJWKClient:
    return PyJWKClient(url, cache_keys=True, lifespan=600, timeout=5)


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def verify_access_token(token: str) -> Claims:
    settings = get_settings()
    try:
        algorithm = str(jwt.get_unverified_header(token).get("alg", ""))
        if algorithm == "HS256" and settings.supabase_jwt_secret:
            key: Any = settings.supabase_jwt_secret
        elif algorithm in ASYMMETRIC and settings.supabase_jwks_url:
            key = _jwks_client(settings.supabase_jwks_url).get_signing_key_from_jwt(token).key
        else:
            raise InvalidToken("unsupported algorithm")
        payload = jwt.decode(
            token,
            key,
            algorithms=[algorithm],
            audience=AUDIENCE,
            options={"require": ["exp", "sub", "aud"]},
            leeway=CLOCK_SKEW_SECONDS,
        )
    except InvalidToken:
        raise
    except (jwt.PyJWTError, jwt.PyJWKClientError, ValueError) as error:
        raise InvalidToken(type(error).__name__) from error

    user_id = _uuid(payload.get("sub"))
    if user_id is None:
        raise InvalidToken("subject")
    metadata = payload.get("user_metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    entries = [item for item in payload.get("amr", []) if isinstance(item, dict) and item.get("method")]
    amr = tuple(str(item["method"]) for item in entries)
    issued_at = datetime.fromtimestamp(int(payload.get("iat", payload["exp"])), tz=UTC)
    checks = [
        datetime.fromtimestamp(int(item["timestamp"]), tz=UTC)
        for item in entries
        if item.get("method") in ("password", "totp") and isinstance(item.get("timestamp"), int | float)
    ]
    name = metadata.get("display_name")
    return Claims(
        user_id=user_id,
        email=str(payload.get("email") or "").lower(),
        session_id=_uuid(payload.get("session_id")),
        aal=str(payload.get("aal") or "aal1"),
        amr=amr,
        expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=UTC),
        issued_at=issued_at,
        auth_time=max(checks) if checks else issued_at,
        display_name=str(name) if isinstance(name, str) and name.strip() else None,
        user_metadata=metadata,
    )
