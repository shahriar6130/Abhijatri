"""Pin the search_path of the audit trigger function (Supabase security advisor 0011).

A function without a fixed search_path can be made to resolve names through a schema an attacker
controls. This one only raises, but it is pinned so the advisor stays clean.

Revision ID: 0015_pin_function_search_path
Revises: 0014_outbox_notifications
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0015_pin_function_search_path"
down_revision: str | None = "0014_outbox_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER FUNCTION public.audit_events_are_append_only() SET search_path = ''")


def downgrade() -> None:
    op.execute("ALTER FUNCTION public.audit_events_are_append_only() RESET search_path")
