"""Health panel: version, environment, uptime, database, migrations, pool, Redis, roll-up, switches.

Every probe runs at request time (Dashboard doc 4).
"""

import os
import time
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import redis
from alembic.script import ScriptDirectory
from sqlalchemy import func, select, text

from app import visits
from app.db import engine
from app.models import VisitDailyStats
from app.ops import events
from app.ops.registry import Panel, PanelContext, PanelResult, register, stat, status

STARTED_AT = datetime.now(UTC)
MIGRATIONS = Path(__file__).resolve().parents[3] / "migrations"
COMMIT_VARIABLES = ("RENDER_GIT_COMMIT", "RAILWAY_GIT_COMMIT_SHA", "VERCEL_GIT_COMMIT_SHA", "GIT_COMMIT")


@lru_cache
def migration_head() -> str | None:
    return ScriptDirectory(str(MIGRATIONS)).get_current_head()


def commit() -> str:
    for name in COMMIT_VARIABLES:
        if value := os.environ.get(name):
            return value[:12]
    return "unknown"


@register
class HealthPanel(Panel):
    id = "health"
    title = {"bn": "সিস্টেমের অবস্থা", "en": "Health"}
    refresh_seconds = 30
    sources = ("postgres", "redis", "config")

    def collect(self, ctx: PanelContext) -> PanelResult:
        settings = ctx.settings
        result = PanelResult(blocks=[], fresh={"postgres": ctx.now, "config": ctx.now})
        uptime_hours = round((ctx.now - STARTED_AT).total_seconds() / 3600, 1)
        result.blocks += [
            status("version", {"bn": "সংস্করণ (কমিট)", "en": "Version (commit)"}, commit()),
            status("environment", {"bn": "পরিবেশ", "en": "Environment"}, settings.app_env),
            stat("uptime_hours", {"bn": "চালু (ঘণ্টা)", "en": "Uptime (hours)"}, uptime_hours),
        ]

        try:
            started = time.perf_counter()
            with ctx.sessions() as session:
                session.execute(text("SELECT 1"))
                latency = round((time.perf_counter() - started) * 1000, 1)
                revision = session.scalar(text("SELECT version_num FROM alembic_version LIMIT 1"))
                last_rollup = session.scalar(select(func.max(VisitDailyStats.day)))
            head = migration_head()
            result.blocks += [
                status("database", {"bn": "ডাটাবেস", "en": "Database"}, "ready"),
                stat(
                    "database_latency_ms",
                    {"bn": "ডাটাবেস ল্যাটেন্সি (ms)", "en": "Database latency (ms)"},
                    latency,
                    level="warn" if latency > 200 else "ok",
                ),
                status(
                    "migrations",
                    {"bn": "মাইগ্রেশন", "en": "Migrations"},
                    f"{revision or 'none'} (head {head})",
                    level="ok" if revision == head else "critical",
                ),
                status(
                    "last_rollup_day",
                    {"bn": "শেষ রোল-আপ দিন", "en": "Last roll-up day"},
                    last_rollup.isoformat() if last_rollup else "never",
                ),
            ]
        except Exception:  # noqa: BLE001  (a down database is a reading, not a crash)
            result.status = "degraded"
            result.fresh["postgres"] = None
            result.blocks.append(status("database", {"bn": "ডাটাবেস", "en": "Database"}, "down", level="critical"))

        pool = engine.pool
        checked_out = pool.checkedout() if hasattr(pool, "checkedout") else None
        result.blocks.append(
            stat(
                "pool_in_use",
                {"bn": "ব্যবহৃত সংযোগ", "en": "DB pool in use"},
                checked_out,
                limit=settings.db_pool_size + settings.db_max_overflow,
            )
        )

        if ctx.redis is None:
            result.status = "degraded"
            result.fresh["redis"] = None
            result.blocks.append(status("redis", {"bn": "Redis", "en": "Redis"}, "not configured", level="critical"))
        else:
            try:
                started = time.perf_counter()
                ctx.redis.ping()
                latency = round((time.perf_counter() - started) * 1000, 1)
                result.fresh["redis"] = ctx.now
                result.blocks += [
                    status("redis", {"bn": "Redis", "en": "Redis"}, "up"),
                    stat(
                        "redis_latency_ms",
                        {"bn": "Redis ল্যাটেন্সি (ms)", "en": "Redis latency (ms)"},
                        latency,
                        level="warn" if latency > 100 else "ok",
                    ),
                ]
            except redis.RedisError:
                result.status = "degraded"
                result.fresh["redis"] = None
                result.blocks.append(status("redis", {"bn": "Redis", "en": "Redis"}, "down", level="critical"))

        flushed = events.last_flush_at
        result.blocks += [
            status(
                "last_counter_flush",
                {"bn": "শেষ কাউন্টার ফ্লাশ", "en": "Last counter flush"},
                flushed.isoformat(timespec="seconds") if flushed else "not yet",
            ),
            stat(
                "visits_dropped",
                {"bn": "গোনা যায়নি এমন ভিজিট (এই প্রসেস)", "en": "Visits dropped (this process)"},
                visits.visits_dropped.value,
                level="warn" if visits.visits_dropped.value else "ok",
            ),
            status(
                "turnstile",
                {"bn": "Turnstile", "en": "Turnstile"},
                "enabled" if settings.turnstile_enabled else "disabled",
                level="ok" if settings.turnstile_enabled or not settings.is_production else "critical",
            ),
            status(
                "visit_counter",
                {"bn": "ভিজিট কাউন্টার", "en": "Visit counter"},
                "on" if settings.visit_counter_enabled else "off",
                level="ok" if settings.visit_counter_enabled else "warn",
            ),
        ]
        return result
