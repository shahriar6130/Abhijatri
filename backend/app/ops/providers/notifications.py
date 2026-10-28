"""Notifications panel: outbox and email health read straight from PostgreSQL (Notification spec 11).

This dashboard is deployed and authenticated separately from the API's notification worker, so it
keeps showing a stuck outbox or failing email even when the notification system cannot report on
itself. Counts only: no address, subject or body.
"""

from datetime import timedelta

from sqlalchemy import func, select

from app.models import NotificationDelivery, NotificationProviderEvent, OutboxEvent
from app.ops.registry import Panel, PanelContext, PanelResult, register, stat, table

BACKLOG_WARN_MINUTES = 10


@register
class NotificationsPanel(Panel):
    id = "notifications"
    title = {"bn": "বিজ্ঞপ্তি", "en": "Notifications"}
    refresh_seconds = 60
    sources = ("postgres",)

    def collect(self, ctx: PanelContext) -> PanelResult:
        hour_ago = ctx.now - timedelta(hours=1)
        with ctx.sessions() as session:
            waiting = OutboxEvent.status.in_(("pending", "retry", "processing"))
            backlog = int(session.scalar(select(func.count()).select_from(OutboxEvent).where(waiting)) or 0)
            oldest = session.scalar(select(func.min(OutboxEvent.created_at)).where(waiting))
            dead = int(session.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.status == "dead_letter")) or 0)
            by_status = session.execute(
                select(NotificationDelivery.status, func.count()).where(NotificationDelivery.updated_at >= ctx.now - timedelta(days=1)).group_by(NotificationDelivery.status)
            ).all()
            failing_hour = int(
                session.scalar(
                    select(func.count()).select_from(NotificationDelivery).where(
                        NotificationDelivery.status.in_(("failed_permanently", "ambiguous", "bounced")), NotificationDelivery.updated_at >= hour_ago
                    )
                ) or 0
            )
            rejected_callbacks = int(
                session.scalar(
                    select(func.count()).select_from(NotificationProviderEvent).where(
                        NotificationProviderEvent.event_type == "signature_failure", NotificationProviderEvent.received_at >= hour_ago
                    )
                ) or 0
            )
        age_minutes = int((ctx.now - oldest).total_seconds() // 60) if oldest else 0
        return PanelResult(
            fresh={"postgres": ctx.now},
            blocks=[
                stat("outbox_backlog", {"bn": "অপেক্ষমাণ ঘটনা", "en": "Events waiting"}, backlog, level="warn" if backlog and age_minutes >= BACKLOG_WARN_MINUTES else "ok"),
                stat(
                    "oldest_waiting_minutes", {"bn": "সবচেয়ে পুরোনো (মিনিট)", "en": "Oldest waiting (minutes)"}, age_minutes,
                    level="critical" if age_minutes >= 3 * BACKLOG_WARN_MINUTES else ("warn" if age_minutes >= BACKLOG_WARN_MINUTES else "ok"),
                ),
                stat("dead_letter", {"bn": "ব্যর্থ ঘটনা", "en": "Dead-lettered events"}, dead, level="warn" if dead else "ok"),
                stat("email_failing_hour", {"bn": "গত ঘণ্টায় ব্যর্থ/অস্পষ্ট ইমেইল", "en": "Failed or unclear emails (last hour)"}, failing_hour, level="warn" if failing_hour >= 5 else "ok"),
                stat("webhook_rejections_hour", {"bn": "প্রত্যাখ্যাত কলব্যাক (ঘণ্টা)", "en": "Rejected provider callbacks (hour)"}, rejected_callbacks, level="warn" if rejected_callbacks >= 5 else "ok"),
                table(
                    "deliveries_last_day",
                    {"bn": "গত ২৪ ঘণ্টার ইমেইল", "en": "Emails in the last 24 hours"},
                    ["status", "count"],
                    [[status, int(count)] for status, count in sorted(by_status)],
                ),
            ],
        )
