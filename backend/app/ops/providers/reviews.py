"""Reviews panel: status counts, Guest pending ceilings with the 80 % warning, Guest writes switch.

Thresholds follow PF 14.3 through the same settings ``abuse.check_pending_ceilings`` enforces.
"""

from sqlalchemy import func, select

from app.abuse import PENDING_STATUSES
from app.models import Review, ReviewStatus
from app.ops.registry import (
    Panel,
    PanelContext,
    PanelResult,
    ratio_level,
    register,
    stat,
    status,
    table,
)


@register
class ReviewsPanel(Panel):
    id = "reviews"
    title = {"bn": "রিভিউ", "en": "Reviews"}
    refresh_seconds = 60
    sources = ("postgres", "config")

    def collect(self, ctx: PanelContext) -> PanelResult:
        settings = ctx.settings
        guest_pending = (Review.author_user_id.is_(None), Review.status.in_(PENDING_STATUSES))
        with ctx.sessions() as session:
            by_status = dict(session.execute(select(Review.status, func.count()).group_by(Review.status)).all())
            pending_total = int(session.scalar(select(func.count()).where(*guest_pending)) or 0)
            per_destination = (
                select(func.count().label("pending"))
                .where(*guest_pending)
                .group_by(Review.destination_id)
                .subquery()
            )
            busiest = int(session.scalar(select(func.max(per_destination.c.pending))) or 0)
            guest_published, community_published = session.execute(
                select(
                    func.count().filter(Review.author_user_id.is_(None)),
                    func.count().filter(Review.author_user_id.is_not(None)),
                ).where(Review.status == ReviewStatus.PUBLISHED)
            ).one()
        ratio = settings.guest_pending_alert_ratio
        paused = settings.guest_writes_paused
        return PanelResult(
            fresh={"postgres": ctx.now, "config": ctx.now},
            blocks=[
                stat(
                    "pending_total",
                    {"bn": "অপেক্ষমাণ অতিথি রিভিউ (মোট)", "en": "Guest pending (total)"},
                    pending_total,
                    limit=settings.guest_pending_total,
                    level=ratio_level(pending_total, settings.guest_pending_total, ratio),
                ),
                stat(
                    "pending_busiest_destination",
                    {"bn": "অপেক্ষমাণ (সবচেয়ে বেশি গন্তব্য)", "en": "Guest pending (busiest destination)"},
                    busiest,
                    limit=settings.guest_pending_per_destination,
                    level=ratio_level(busiest, settings.guest_pending_per_destination, ratio),
                ),
                stat("guest_feedback_published", {"bn": "প্রকাশিত অতিথি মতামত", "en": "Guest Feedback published"}, guest_published),
                stat(
                    "community_published",
                    {"bn": "প্রকাশিত কমিউনিটি রিভিউ", "en": "Community reviews published"},
                    community_published,
                ),
                status(
                    "guest_writes",
                    {"bn": "অতিথি জমা", "en": "Guest writes"},
                    "paused" if paused else "open",
                    level="critical" if paused else "ok",
                ),
                table(
                    "by_status",
                    {"bn": "অবস্থা অনুযায়ী", "en": "By status"},
                    ["status", "count"],
                    [[state.value, int(by_status.get(state, 0))] for state in ReviewStatus],
                ),
            ],
        )
