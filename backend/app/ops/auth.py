"""Phase 1 access to the ops API: one bearer token (System-Monitoring-Dashboard 3.1).

- ``OPS_DASHBOARD_TOKEN`` unset: every ``/ops`` route is 404, as if it did not exist.
- Only the ``Authorization: Bearer`` header is read; never a URL, cookie or log.
- Constant-time compare. A wrong or missing token is 401 and counts one durable failure per
  network; after ``OPS_AUTH_FAILURES_PER_NETWORK_PER_HOUR`` failures the network gets 429.
"""

import hmac

from fastapi import Header, Request

from app import abuse
from app.abuse import CounterSessions
from app.client_address import network_digest
from app.config import get_settings
from app.errors import ApiError
from app.ops import events


def _failure_rule() -> abuse.Rule:
    return abuse.Rule(
        "ops_auth_fail:network:1h", abuse.HOUR, get_settings().ops_auth_failures_per_network_per_hour
    )


def require_ops_token(
    request: Request,
    sessions: CounterSessions,
    authorization: str | None = Header(default=None),
) -> None:
    expected = get_settings().ops_dashboard_token
    if not expected:
        raise ApiError("NOT_FOUND")
    network = network_digest(request)
    rule = _failure_rule()
    wait = abuse.peek(sessions, rule, network)
    if wait is not None:
        raise ApiError("RATE_LIMITED", headers={"Retry-After": str(wait)})
    scheme, _, presented = (authorization or "").partition(" ")
    if scheme.lower() == "bearer" and hmac.compare_digest(
        presented.strip().encode("utf-8"), expected.encode("utf-8")
    ):
        return
    events.count("ops.auth_failed")
    _, wait = abuse.hit(sessions, rule, network)
    if wait is not None:
        raise ApiError("RATE_LIMITED", headers={"Retry-After": str(wait)})
    raise ApiError("AUTH_REQUIRED", headers={"WWW-Authenticate": "Bearer"})
