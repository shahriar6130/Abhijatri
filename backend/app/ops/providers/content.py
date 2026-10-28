"""Content panel: published destinations, guide items, advisory freshness, contacts (Dashboard doc 4)."""

from collections import Counter

from sqlalchemy import func, select

from app.destination_services import advisory_state, today_in_display_tz
from app.models import (
    Destination,
    DestinationAdvisory,
    DestinationContact,
    DestinationGuideItem,
    DestinationStatus,
)
from app.ops.registry import Panel, PanelContext, PanelResult, register, stat


@register
class ContentPanel(Panel):
    id = "content"
    title = {"bn": "কনটেন্ট", "en": "Content"}
    refresh_seconds = 300
    sources = ("postgres",)

    def collect(self, ctx: PanelContext) -> PanelResult:
        today = today_in_display_tz(ctx.now)
        with ctx.sessions() as session:
            destinations = session.scalar(
                select(func.count()).where(Destination.status == DestinationStatus.PUBLISHED)
            )
            guide_items = session.scalar(
                select(func.count()).where(DestinationGuideItem.is_published.is_(True))
            )
            contacts = session.scalar(select(func.count()).select_from(DestinationContact))
            advisories = session.execute(
                select(
                    DestinationAdvisory.effective_on,
                    DestinationAdvisory.valid_until,
                    DestinationAdvisory.verified_on,
                ).where(DestinationAdvisory.is_published.is_(True))
            ).all()
        states = Counter(
            advisory_state(
                effective_on=effective_on,
                valid_until=valid_until,
                verified_on=verified_on,
                today=today,
                stale_after_days=ctx.settings.advisory_stale_after_days,
            )
            for effective_on, valid_until, verified_on in advisories
        )
        return PanelResult(
            fresh={"postgres": ctx.now},
            blocks=[
                stat("destinations_published", {"bn": "প্রকাশিত গন্তব্য", "en": "Published destinations"}, destinations),
                stat("guide_items", {"bn": "গাইড আইটেম", "en": "Guide items"}, guide_items),
                stat("advisories_current", {"bn": "চলতি সতর্কতা", "en": "Advisories current"}, states["CURRENT"]),
                stat(
                    "advisories_stale",
                    {"bn": "পুরনো সতর্কতা", "en": "Advisories stale"},
                    states["STALE"],
                    level="warn" if states["STALE"] else "ok",
                ),
                stat(
                    "advisories_expired",
                    {"bn": "মেয়াদোত্তীর্ণ সতর্কতা", "en": "Advisories expired"},
                    states["EXPIRED"],
                    level="warn" if states["EXPIRED"] else "ok",
                ),
                stat("contacts", {"bn": "যোগাযোগ", "en": "Contacts"}, contacts),
            ],
        )
