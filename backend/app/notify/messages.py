"""Turn one outbox event into the notifications it causes (Notification spec 3 to 6).

The catalogue in ``registry.py`` decides which rules apply. Recipients come only from the allowlisted
resolvers; staff captured at event time are re-checked against their current role here, so a person
who lost the role is not told restricted case details. Texts come from the active template version
(``notification_templates``) or the version-1 text in code, filled only with allowlisted variables
taken from the event's own facts, never from the current state of the case.
"""

import string
import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import NotificationRule, NotificationTemplate, OutboxEvent, User, UserRole
from app.notify import registry
from app.notify.registry import Rule

OUTCOME = {
    "upheld": ("মূল সিদ্ধান্ত বহাল", "the original decision stands"),
    "overturned": ("মূল সিদ্ধান্ত বাতিল করা হয়েছে", "the original decision was reversed"),
}
ROLE_NAMES = {"moderator": ("মডারেটর", "moderator"), "superadmin": ("সুপারঅ্যাডমিন", "superadmin"), "none": ("কোনোটি নয়", "none")}


@dataclass(frozen=True)
class Message:
    recipient: uuid.UUID
    kind: str
    priority: str
    audience: str
    email: bool
    template_version: int
    title_bn: str
    title_en: str
    body_bn: str
    body_en: str
    link: str | None = None
    appeal_id: uuid.UUID | None = None

    @property
    def critical(self) -> bool:
        return self.priority == "critical"


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _fact(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _applies(rule: Rule, payload: dict[str, Any]) -> bool:
    return all(_fact(payload.get(key)) in allowed for key, allowed in rule.when)


def _active_staff(session: Session, ids: list[uuid.UUID], role: str | None) -> set[uuid.UUID]:
    if not ids:
        return set()
    statement = select(UserRole.user_id).where(UserRole.user_id.in_(ids), UserRole.revoked_at.is_(None))
    if role:
        statement = statement.where(UserRole.role == role)
    return set(session.scalars(statement))


def recipients(session: Session, rule: Rule, payload: dict[str, Any]) -> list[uuid.UUID]:
    """The allowlisted recipient policies. Staff notices go only to people who hold a staff role now."""
    if rule.resolver == "payload_user":
        user_id = _uuid(payload.get(rule.source))
        if user_id is None or session.get(User, user_id) is None:
            return []
        if rule.audience == "staff" and not _active_staff(session, [user_id], rule.role):
            return []
        return [user_id]
    if rule.resolver == "captured_staff":
        captured = [i for i in (_uuid(v) for v in payload.get(rule.source) or []) if i]
        current = _active_staff(session, captured, rule.role)
        return [i for i in captured if i in current]
    return []


def _variables(payload: dict[str, Any], locale: int) -> dict[str, str]:
    reference = payload.get("reference") or payload.get("appeal_id") or ""
    outcome = OUTCOME.get(str(payload.get("outcome")), ("", ""))[locale]
    role = ROLE_NAMES.get(str(payload.get("role")), ("", ""))[locale]
    return {
        "reference": str(reference)[:8],
        "deadline": str(payload.get("deadline_at") or "")[:10],
        "question": str(payload.get("question") or "")[:300],
        "count": str(payload.get("count") or ""),
        "outcome": outcome,
        "role": role,
    }


class _Only(dict[str, str]):
    """Unknown placeholders render as nothing instead of failing or leaking anything."""

    def __missing__(self, key: str) -> str:
        return ""


def render(text: str, variables: dict[str, str], allowed: tuple[str, ...]) -> str:
    safe = _Only({k: v for k, v in variables.items() if k in allowed})
    return string.Formatter().vformat(text, (), safe)


def template_variables(text: str) -> set[str]:
    """Placeholder names used in a template text; attribute or index access is not allowed."""
    names: set[str] = set()
    for _, name, spec, conversion in string.Formatter().parse(text):
        if name is None:
            continue
        if not name.isidentifier() or spec or conversion:
            raise ValueError(f"placeholder {{{name}}} is not allowed")
        names.add(name)
    return names


def _link(rule: Rule, payload: dict[str, Any]) -> str | None:
    if rule.route is None:
        return None
    if "{destination_id}" in rule.route:
        destination = _uuid(payload.get("destination_id"))
        return rule.route.format(destination_id=destination) if destination else "/account/notifications"
    return rule.route


def _texts(session: Session, key: str) -> tuple[int, dict[str, tuple[str, str]]]:
    """(version, {locale: (title, body)}) from the active in-app templates, or version 1 from code."""
    default = registry.TEMPLATES[key]
    texts = {"bn": (default.title_bn, default.body_bn), "en": (default.title_en, default.body_en)}
    version = 1
    for row in session.scalars(
        select(NotificationTemplate).where(
            NotificationTemplate.template_key == key, NotificationTemplate.channel == "in_app", NotificationTemplate.status == "active"
        )
    ):
        texts[row.locale] = (row.title_template or texts[row.locale][0], row.body_template)
        version = max(version, row.version)
    return version, texts


def messages_for(session: Session, event: OutboxEvent) -> list[Message]:
    payload = event.payload or {}
    overrides = {row.template_key: row for row in session.scalars(select(NotificationRule))}
    out: list[Message] = []
    for rule in registry.rules_for(event.topic):
        if not _applies(rule, payload):
            continue
        override = overrides.get(rule.template_key)
        if override is not None and not override.enabled:
            continue
        people = recipients(session, rule, payload)
        if not people:
            continue
        allowed = registry.TEMPLATES[rule.template_key].variables
        version, texts = _texts(session, rule.template_key)
        bn, en = _variables(payload, 0), _variables(payload, 1)
        for person in people:
            out.append(
                Message(
                    recipient=person,
                    kind=rule.template_key,
                    priority=override.priority if override else rule.priority,
                    audience=rule.audience,
                    email=override.email if override else rule.email,
                    template_version=version,
                    title_bn=render(texts["bn"][0], bn, allowed)[:160],
                    title_en=render(texts["en"][0], en, allowed)[:160],
                    body_bn=render(texts["bn"][1], bn, allowed)[:600],
                    body_en=render(texts["en"][1], en, allowed)[:600],
                    link=_link(rule, payload),
                    appeal_id=_uuid(payload.get(rule.appeal_field)) if rule.appeal_field else None,
                )
            )
    return out
