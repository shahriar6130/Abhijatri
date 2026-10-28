"""Shared outbox contract, in-app notifications and email delivery history (Moderation-Dashboard-Specification 6.7, 11).

- ``outbox_events`` gains status, lease, retry and error columns so one relay serves moderation and
  notifications. Rows that were already processed are marked ``done``.
- ``notifications``: one row per (event, recipient, kind), never duplicated.
- ``delivery_attempts``: every email attempt; an accepted-then-crashed send is ``ambiguous``.

Revision ID: 0014_outbox_notifications
Revises: 0013_cases_appeals
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0014_outbox_notifications"
down_revision: str | None = "0013_cases_appeals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REVOKE_SUPABASE_ROLES = """
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA public FROM %I', r);
    END IF;
  END LOOP;
END $$;
"""
UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("schema_version", sa.SmallInteger(), nullable=False, server_default="1"))
    op.add_column("outbox_events", sa.Column("status", sa.String(12), nullable=False, server_default="pending"))
    op.add_column("outbox_events", sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"))
    op.add_column("outbox_events", sa.Column("lease_until", TS))
    op.add_column("outbox_events", sa.Column("available_at", TS, nullable=False, server_default=sa.func.now()))
    op.add_column("outbox_events", sa.Column("last_error", sa.String(300)))
    op.create_check_constraint("ck_outbox_events_status", "outbox_events", "status IN ('pending', 'processing', 'done', 'failed')")
    op.execute("UPDATE outbox_events SET status = 'done' WHERE processed_at IS NOT NULL")
    op.create_index("ix_outbox_events_relay", "outbox_events", ["status", "available_at"])

    op.create_table(
        "notifications",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("event_id", UUID, sa.ForeignKey("outbox_events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recipient_user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(60), nullable=False),
        sa.Column("critical", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("title_bn", sa.String(160), nullable=False),
        sa.Column("title_en", sa.String(160), nullable=False),
        sa.Column("body_bn", sa.String(600), nullable=False),
        sa.Column("body_en", sa.String(600), nullable=False),
        sa.Column("link", sa.String(300)),
        sa.Column("appeal_id", UUID),
        sa.Column("email_status", sa.String(10), nullable=False, server_default="none"),
        sa.Column("email_attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("read_at", TS),
        sa.UniqueConstraint("event_id", "recipient_user_id", "kind", name="uq_notifications_identity"),
        sa.CheckConstraint(
            "email_status IN ('none', 'pending', 'sent', 'failed', 'ambiguous', 'digest')", name="ck_notifications_email_status"
        ),
    )
    op.create_index("ix_notifications_recipient_created", "notifications", ["recipient_user_id", "created_at"])

    op.create_table(
        "delivery_attempts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("notification_id", UUID, sa.ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False, server_default="email"),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("provider_message_id", sa.String(120)),
        sa.Column("error", sa.String(300)),
        sa.Column("attempted_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('sent', 'failed', 'ambiguous')", name="ck_delivery_attempts_status"),
    )
    op.create_index("ix_delivery_attempts_notification_id", "delivery_attempts", ["notification_id"])

    for table in ("notifications", "delivery_attempts"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(REVOKE_SUPABASE_ROLES)


def downgrade() -> None:
    op.drop_table("delivery_attempts")
    op.drop_table("notifications")
    op.drop_index("ix_outbox_events_relay", table_name="outbox_events")
    op.drop_constraint("ck_outbox_events_status", "outbox_events", type_="check")
    for column in ("last_error", "available_at", "lease_until", "attempts", "status", "schema_version"):
        op.drop_column("outbox_events", column)
