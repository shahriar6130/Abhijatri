"""Visitors panel (System-Monitoring-Dashboard 4; definitions owned by Guest-Identity-and-Visits 4.1, 5).

Today is read live from Redis; finished days from ``visit_daily_stats``. Range totals are
visitor-days, not distinct people. A day with no data is a gap (``null``), never a zero (R5).
"""

from datetime import UTC, datetime, timedelta

import redis
from sqlalchemy import func, select

from app import visits
from app.destination_services import today_in_display_tz
from app.models import VisitDailyStats
from app.ops.registry import Panel, PanelContext, PanelResult, register, series, stat, status
from app.visits import DayCounts, metrics

LABELS = {
    "guest": {"bn": "অতিথি", "en": "Guest"},
    "verified": {"bn": "ভেরিফায়েড", "en": "Verified"},
    "new_guest": {"bn": "নতুন অতিথি", "en": "New Guest"},
    "new_verified": {"bn": "নতুন ভেরিফায়েড", "en": "New Verified"},
    "total_visits": {"bn": "মোট ভিজিট (A)", "en": "Total visits (A)"},
    "new_visits": {"bn": "নতুন ভিজিট (B)", "en": "New visits (B)"},
    "old_visits": {"bn": "পুরনো ভিজিট (A − B)", "en": "Old visits (A − B)"},
}


def _counts(row: VisitDailyStats) -> DayCounts | None:
    if row.guest_new is None:
        return None  # legacy day: only a total is known
    return DayCounts(
        guest_new=row.guest_new,
        guest_returning=row.guest_returning or 0,
        member_new=row.member_new or 0,
        member_returning=row.member_returning or 0,
    )


@register
class VisitorsPanel(Panel):
    id = "visitors"
    title = {"bn": "ভিজিটর", "en": "Visitors"}
    refresh_seconds = 30
    sources = ("redis", "postgres")

    def collect(self, ctx: PanelContext) -> PanelResult:
        today = today_in_display_tz(ctx.now)
        first = today - timedelta(days=ctx.days - 1)
        result = PanelResult(blocks=[])

        live: DayCounts | None = None
        redis_ok = ctx.redis is not None
        if ctx.redis is not None:
            try:
                live = visits.read_day(ctx.redis, today) or DayCounts()
                result.fresh["redis"] = ctx.now
            except redis.RedisError:
                redis_ok = False
        if not redis_ok:
            result.status = "degraded"
            result.fresh["redis"] = None

        with ctx.sessions() as session:
            stored = visits.stored_days(session, first, today - timedelta(days=1))
            all_time_new, legacy = session.execute(
                select(
                    func.coalesce(func.sum(VisitDailyStats.guest_new), 0),
                    func.coalesce(func.sum(VisitDailyStats.guest_total_legacy), 0),
                )
            ).one()
            last_rollup = session.scalar(select(func.max(VisitDailyStats.rolled_up_at)))
        result.fresh["postgres"] = last_rollup or datetime.now(UTC)

        today_metrics = metrics(live) if live is not None else None
        for name, label in LABELS.items():
            value = getattr(today_metrics, name) if today_metrics else None
            result.blocks.append(stat(f"today_{name}", {"bn": f"আজ: {label['bn']}", "en": f"Today: {label['en']}"}, value))

        range_total = live if live is not None else DayCounts()
        new_points: list[tuple[str, int | None]] = []
        returning_points: list[tuple[str, int | None]] = []
        total_points: list[tuple[str, int | None]] = []
        for offset in range(ctx.days):
            day = first + timedelta(days=offset)
            day_label = day.isoformat()
            if day == today:
                counts = live
                legacy_total = None
            else:
                row = stored.get(day)
                counts = _counts(row) if row else None
                legacy_total = row.guest_total_legacy if row else None
                if counts is not None:
                    range_total = range_total + counts
            if counts is not None:
                m = metrics(counts)
                new_points.append((day_label, m.new_visits))
                returning_points.append((day_label, m.old_visits))
                total_points.append((day_label, m.total_visits))
            else:
                new_points.append((day_label, None))
                returning_points.append((day_label, None))
                total_points.append((day_label, legacy_total))

        range_metrics = metrics(range_total)
        span = {"bn": f"{ctx.days} দিন", "en": f"{ctx.days} days"}
        for name in ("total_visits", "new_visits", "old_visits", "guest", "verified"):
            label = LABELS[name]
            result.blocks.append(
                stat(
                    f"range_{name}",
                    {"bn": f"{span['bn']}: {label['bn']}", "en": f"{span['en']}: {label['en']}"},
                    getattr(range_metrics, name),
                )
            )
        result.blocks.append(
            stat(
                "all_time_guests",
                {"bn": "সর্বমোট অতিথি", "en": "All-time guests"},
                int(all_time_new or 0) + int(legacy or 0) + (live.guest_new if live else 0),
                hint={"bn": "নতুন অতিথির যোগফল ও পুরনো মোট", "en": "Sum of new guests plus the legacy totals"},
            )
        )
        result.blocks.append(series("new_by_day", {"bn": "নতুন ভিজিট / দিন", "en": "New visits per day"}, new_points))
        result.blocks.append(
            series("returning_by_day", {"bn": "পুরনো ভিজিট / দিন", "en": "Returning visits per day"}, returning_points)
        )
        result.blocks.append(series("total_by_day", {"bn": "মোট ভিজিট / দিন", "en": "Total visits per day"}, total_points))
        result.blocks.append(
            status(
                "member_sign_in",
                {"bn": "সদস্য সাইন-ইন", "en": "Member sign-in"},
                "not built",
                level="warn",
            )
        )
        result.notes.extend(
            [
                {
                    "bn": "ভিজিট মানে একজন ভিজিটর একদিনে একবার; একই দিনে অতিথি ও সদস্য হলে দুটোতেই গোনা হয়।",
                    "en": "A visit is one visitor per day; a guest who signs in the same day is counted in both.",
                },
                {
                    "bn": "সময়সীমার মোট সংখ্যা ভিজিটর-দিন, আলাদা মানুষ নয়।",
                    "en": "Range totals are visitor-days, not distinct people.",
                },
                {
                    "bn": "Verified সংখ্যা ০ থাকবে যতক্ষণ সদস্য সাইন-ইন (R04) তৈরি না হয়।",
                    "en": "Verified stays 0 until member sign-in (R04) is built.",
                },
            ]
        )
        return result
