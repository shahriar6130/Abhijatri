"""Panel registry for the System Monitoring Dashboard (System-Monitoring-Dashboard 6.1 and 6.2).

A feature appears on the dashboard by adding one provider module under ``app/ops/providers`` with
a ``@register``-ed ``Panel`` subclass. The core never changes. Each panel runs on its own with a
time budget; one that raises or is too slow is shown as ``unavailable`` and the others still load.
"""

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar, Literal

import redis
from sqlalchemy.orm import Session

from app.config import Settings

logger = logging.getLogger(__name__)

BUDGET_SECONDS = 2.0
Level = Literal["ok", "warn", "critical"]
Localized = dict[str, str]
Block = dict[str, Any]


@dataclass
class PanelContext:
    sessions: Callable[[], Session]
    redis: redis.Redis | None
    settings: Settings
    days: int
    now: datetime


@dataclass
class PanelResult:
    blocks: list[Block]
    status: Literal["ok", "degraded"] = "ok"
    # Each source this panel read and when its data was current (R5).
    fresh: dict[str, datetime | None] = field(default_factory=dict)
    notes: list[Localized] = field(default_factory=list)


class Panel:
    id: ClassVar[str]
    version: ClassVar[int] = 1
    title: ClassVar[Localized]
    permission: ClassVar[str] = "ops.read"
    refresh_seconds: ClassVar[int] = 60
    sources: ClassVar[tuple[str, ...]]
    owner: ClassVar[str] = "backend"

    def collect(self, ctx: PanelContext) -> PanelResult:
        raise NotImplementedError

    @classmethod
    def catalogue_entry(cls) -> dict[str, Any]:
        return {
            "id": cls.id,
            "title": cls.title,
            "version": cls.version,
            "refresh_seconds": cls.refresh_seconds,
            "permission": cls.permission,
            "sources": list(cls.sources),
            "owner": cls.owner,
        }


_PANELS: dict[str, type[Panel]] = {}


def register[P: type[Panel]](panel: P) -> P:
    if panel.id in _PANELS and _PANELS[panel.id] is not panel:
        raise ValueError(f"duplicate panel id {panel.id!r}")
    _PANELS[panel.id] = panel
    return panel


def panels() -> list[type[Panel]]:
    from app.ops import providers  # noqa: F401  (importing registers every provider)

    return list(_PANELS.values())


def get_panel(panel_id: str) -> type[Panel] | None:
    return {panel.id: panel for panel in panels()}.get(panel_id)


# Panels run here under their budget; the overview fans out on a separate pool so waiting on a
# panel never takes a worker the panel itself needs.
_executor = ThreadPoolExecutor(max_workers=16, thread_name_prefix="ops-panel")
_fan_out = ThreadPoolExecutor(max_workers=8, thread_name_prefix="ops-overview")


def _iso(moment: datetime | None) -> str | None:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z") if moment else None


def _envelope(panel: type[Panel], status: str, generated_at: datetime) -> dict[str, Any]:
    return {
        "id": panel.id,
        "version": panel.version,
        "title": panel.title,
        "status": status,
        "generated_at": _iso(generated_at),
        "refresh_seconds": panel.refresh_seconds,
    }


def collect(panel: type[Panel], ctx: PanelContext, *, budget: float = BUDGET_SECONDS) -> dict[str, Any]:
    future = _executor.submit(panel().collect, ctx)
    try:
        result = future.result(timeout=budget)
    except FutureTimeout:
        logger.warning("ops panel %s exceeded its %.1fs budget", panel.id, budget)
        return {**_envelope(panel, "unavailable", datetime.now(UTC)), "sources": [], "blocks": [], "notes": []}
    except Exception:
        logger.exception("ops panel %s failed", panel.id)
        return {**_envelope(panel, "unavailable", datetime.now(UTC)), "sources": [], "blocks": [], "notes": []}
    return {
        **_envelope(panel, result.status, datetime.now(UTC)),
        "sources": [{"name": name, "fresh_at": _iso(fresh)} for name, fresh in result.fresh.items()],
        "blocks": result.blocks,
        "notes": result.notes,
    }


def collect_all(ctx: PanelContext) -> list[dict[str, Any]]:
    """Run every panel concurrently; each keeps its own budget and failure."""
    futures = [_fan_out.submit(collect, panel, ctx) for panel in panels()]
    return [future.result() for future in futures]


# ---- block builders (the four types of section 6.2) ----


def stat(
    key: str,
    label: Localized,
    value: int | float | None,
    *,
    limit: int | None = None,
    level: Level = "ok",
    hint: Localized | None = None,
) -> Block:
    block: Block = {"type": "stat", "key": key, "label": label, "value": value, "level": level}
    if limit is not None:
        block["limit"] = limit
    if hint is not None:
        block["hint"] = hint
    return block


def series(key: str, label: Localized, points: list[tuple[str, int | None]]) -> Block:
    return {
        "type": "series",
        "key": key,
        "label": label,
        "points": [{"date": day, "value": value} for day, value in points],
    }


def table(key: str, label: Localized, columns: list[str], rows: list[list[Any]]) -> Block:
    return {"type": "table", "key": key, "label": label, "columns": columns, "rows": rows}


def status(key: str, label: Localized, value: str, *, level: Level = "ok") -> Block:
    return {"type": "status", "key": key, "label": label, "value": value, "level": level}


def ratio_level(value: int, limit: int, warn_ratio: float = 0.8) -> Level:
    if value >= limit:
        return "critical"
    if value >= limit * warn_ratio:
        return "warn"
    return "ok"
