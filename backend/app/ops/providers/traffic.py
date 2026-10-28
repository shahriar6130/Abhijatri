"""Traffic panel: today's requests by status class, 429s, challenge failures, 5xx by route template,
and visits Redis did not accept (Dashboard doc 4, 6.3). Values are up to METRICS_FLUSH_SECONDS old
in Redis; this process's not-yet-flushed counts are added so a single instance is exact.
"""

from datetime import timedelta

import redis

from app import visits
from app.destination_services import today_in_display_tz
from app.ops import events
from app.ops.registry import Panel, PanelContext, PanelResult, register, stat, table


@register
class TrafficPanel(Panel):
    id = "traffic"
    title = {"bn": "ট্রাফিক", "en": "Traffic"}
    refresh_seconds = 60
    sources = ("redis",)

    def collect(self, ctx: PanelContext) -> PanelResult:
        today = today_in_display_tz(ctx.now)
        result = PanelResult(blocks=[])
        counts: dict[str, int] | None = None
        if ctx.redis is not None:
            try:
                counts = events.read_day(ctx.redis, today)
                result.fresh["redis"] = events.last_flush_at or ctx.now - timedelta(
                    seconds=ctx.settings.metrics_flush_seconds
                )
            except redis.RedisError:
                counts = None
        if counts is None:
            result.status = "degraded"
            result.fresh["redis"] = None
        else:
            for name, amount in events.pending().items():
                counts[name] = counts.get(name, 0) + amount

        def value(name: str) -> int | None:
            return None if counts is None else counts.get(name, 0)

        five_hundreds = value("http.5xx")
        result.blocks.extend(
            [
                stat("http_2xx", {"bn": "সফল (2xx)", "en": "Success (2xx)"}, value("http.2xx")),
                stat("http_4xx", {"bn": "ক্লায়েন্ট ত্রুটি (4xx)", "en": "Client errors (4xx)"}, value("http.4xx")),
                stat(
                    "http_5xx",
                    {"bn": "সার্ভার ত্রুটি (5xx)", "en": "Server errors (5xx)"},
                    five_hundreds,
                    level="critical" if five_hundreds else "ok",
                ),
                stat("http_429", {"bn": "রেট লিমিট (429)", "en": "Rate limited (429)"}, value("http.429")),
                stat(
                    "challenge_failed",
                    {"bn": "Turnstile ব্যর্থ", "en": "CHALLENGE_FAILED"},
                    value("challenge_failed"),
                ),
                stat(
                    "visits_dropped",
                    {"bn": "গোনা যায়নি এমন ভিজিট", "en": "Visits dropped"},
                    max(value("visits.dropped") or 0, visits.visits_dropped.value),
                    level="warn" if visits.visits_dropped.value or value("visits.dropped") else "ok",
                    hint={"bn": "Redis বন্ধ থাকায় বাদ পড়া ভিজিট", "en": "Visits lost while Redis was down"},
                ),
                stat("ops_auth_failed", {"bn": "ড্যাশবোর্ড টোকেন ব্যর্থ", "en": "Ops token failures"}, value("ops.auth_failed")),
            ]
        )
        routes = sorted(
            (
                (name[len(events.ROUTE_5XX_PREFIX) :], amount)
                for name, amount in (counts or {}).items()
                if name.startswith(events.ROUTE_5XX_PREFIX)
            ),
            key=lambda item: -item[1],
        )[:10]
        result.blocks.append(
            table(
                "top_5xx_routes",
                {"bn": "সবচেয়ে বেশি 5xx রুট", "en": "Top routes by 5xx"},
                ["route", "count"],
                [[route, amount] for route, amount in routes],
            )
        )
        return result
