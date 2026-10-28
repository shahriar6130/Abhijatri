"""Operations API under ``/api/v1/ops`` (System-Monitoring-Dashboard 5). Read-only except the roll-up.

Every route needs the ops credential, answers ``no-store`` (the app default) and returns
aggregates only (R4).
"""

import logging
from datetime import UTC, datetime
from typing import Annotated, Any

import redis
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app import visits
from app.abuse import CounterSessions
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.limits import limiter
from app.ops.auth import require_ops_token
from app.ops.registry import PanelContext, collect, collect_all, get_panel, panels
from app.redis_client import RedisDep

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/ops", tags=["ops"], dependencies=[Depends(require_ops_token)])

OPS_RATE = "60/minute"
DAY_CHOICES = (7, 30, 90)


def _days(days: int = Query(default=30)) -> int:
    """The dashboard's 7/30/90-day selector; anything else is a 422."""
    if days not in DAY_CHOICES:
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "days", "code": "INVALID_VALUE"}])
    return days


Days = Annotated[int, Depends(_days)]


def _context(sessions: CounterSessions, redis_client: RedisDep, days: int) -> PanelContext:
    return PanelContext(
        sessions=sessions, redis=redis_client, settings=get_settings(), days=days, now=datetime.now(UTC)
    )


def _catch_up(session: Session, redis_client: redis.Redis | None) -> None:
    """Opening the dashboard rolls up any missing finished day (Guest doc 4.5). Best effort."""
    if redis_client is None:
        return
    try:
        visits.rollup(session, redis_client)
    except Exception:  # noqa: BLE001  (a failed catch-up must not block the dashboard)
        session.rollback()
        logger.warning("visit roll-up on dashboard open failed; the nightly job will retry")


@router.get("/panels")
@limiter.limit(OPS_RATE)
def list_panels(request: Request) -> dict[str, Any]:
    return {"panels": [panel.catalogue_entry() for panel in panels()]}


@router.get("/panels/{panel_id}")
@limiter.limit(OPS_RATE)
def get_one_panel(
    request: Request,
    panel_id: str,
    sessions: CounterSessions,
    redis_client: RedisDep,
    days: Days,
) -> dict[str, Any]:
    panel = get_panel(panel_id)
    if panel is None:
        raise ApiError("NOT_FOUND")
    return collect(panel, _context(sessions, redis_client, days))


@router.get("/overview")
@limiter.limit(OPS_RATE)
def overview(
    request: Request,
    sessions: CounterSessions,
    redis_client: RedisDep,
    days: Days,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    _catch_up(session, redis_client)
    ctx = _context(sessions, redis_client, days)
    return {"generated_at": ctx.now.isoformat().replace("+00:00", "Z"), "days": days, "panels": collect_all(ctx)}


@router.post("/jobs/visit-rollup")
@limiter.limit(OPS_RATE)
def visit_rollup(
    request: Request,
    redis_client: RedisDep,
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    """Idempotent; called nightly by GitHub Actions and by the dashboard's "Run roll-up" button."""
    if redis_client is None:
        raise ApiError("SERVICE_UNAVAILABLE")
    try:
        days = visits.rollup(session, redis_client)
    except redis.RedisError:
        session.rollback()
        raise ApiError("SERVICE_UNAVAILABLE")
    return {"rolled_up": [day.isoformat() for day in days]}
