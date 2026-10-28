"""Notification system v1.1 (Docs/Notification-Documentation.md section 7).

The shared outbox gains the spec's event fields; notifications gain priority, audience, template,
delivery mode, archive and per-row expiry; email state moves to deliveries with an append-only attempt
history. New: provider events, versioned templates, rules, preferences, suppressions and digests.
Existing rows are carried over; the old ``delivery_attempts`` table is copied and dropped.

Revision ID: 0017_notification_system
Revises: 0016_review_media
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0017_notification_system"
down_revision: str | None = "0016_review_media"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB()
TS = sa.DateTime(timezone=True)
NEW_TABLES = (
    "notification_digests",
    "notification_deliveries",
    "notification_delivery_attempts",
    "notification_provider_events",
    "notification_templates",
    "notification_rules",
    "notification_preferences",
    "notification_suppressions",
)

REVOKE_SUPABASE_ROLES = """
DO $$
DECLARE r text; t text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      FOREACH t IN ARRAY ARRAY[{tables}] LOOP
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I', t, r);
      END LOOP;
    END IF;
  END LOOP;
END $$;
"""


def _fk(table: str, ondelete: str) -> sa.ForeignKey:
    return sa.ForeignKey(f"{table}.id", ondelete=ondelete)


def upgrade() -> None:
    # ---- outbox (spec 7.1) ----
    op.add_column("outbox_events", sa.Column("dedupe_key", sa.String(200)))
    op.add_column("outbox_events", sa.Column("aggregate_type", sa.String(40)))
    op.add_column("outbox_events", sa.Column("aggregate_version", sa.BigInteger()))
    op.add_column("outbox_events", sa.Column("recipient_policy", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column("outbox_events", sa.Column("occurred_at", TS, nullable=False, server_default=sa.func.now()))
    op.add_column("outbox_events", sa.Column("lease_owner", sa.String(80)))
    op.add_column("outbox_events", sa.Column("last_error_code", sa.String(60)))
    op.drop_constraint("ck_outbox_events_status", "outbox_events", type_="check")  # 0014's done/failed states
    op.execute("UPDATE outbox_events SET dedupe_key = 'legacy:' || id::text, occurred_at = created_at")
    op.execute("UPDATE outbox_events SET status = 'processed' WHERE status = 'done'")
    op.execute("UPDATE outbox_events SET status = 'dead_letter' WHERE status = 'failed'")
    op.alter_column("outbox_events", "dedupe_key", nullable=False)
    op.create_unique_constraint("uq_outbox_events_dedupe_key", "outbox_events", ["dedupe_key"])
    op.create_check_constraint(
        "ck_outbox_events_status", "outbox_events", "status IN ('pending', 'processing', 'processed', 'retry', 'dead_letter')"
    )

    # ---- digests first: notifications point at them ----
    op.create_table(
        "notification_digests",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("recipient_user_id", UUID, _fk("users", "CASCADE"), nullable=False),
        sa.Column("window_date", sa.Date(), nullable=False),
        sa.Column("scheduled_for", TS, nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="queued"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("recipient_user_id", "window_date", name="uq_notification_digests_window"),
        sa.CheckConstraint("status IN ('queued', 'sending', 'accepted', 'failed', 'ambiguous')", name="ck_notification_digests_status"),
    )

    # ---- notifications (spec 7.2) ----
    op.add_column("notifications", sa.Column("priority", sa.String(8), nullable=False, server_default="normal"))
    op.add_column("notifications", sa.Column("audience", sa.String(8), nullable=False, server_default="member"))
    op.add_column("notifications", sa.Column("template_key", sa.String(80)))
    op.add_column("notifications", sa.Column("template_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("notifications", sa.Column("delivery_mode", sa.String(10), nullable=False, server_default="none"))
    op.add_column("notifications", sa.Column("digest_id", UUID, _fk("notification_digests", "SET NULL")))
    op.add_column("notifications", sa.Column("archived_at", TS))
    op.add_column("notifications", sa.Column("expires_at", TS))
    op.execute(
        """
        UPDATE notifications SET
          priority = CASE WHEN critical THEN 'critical' ELSE 'normal' END,
          audience = CASE WHEN kind LIKE 'staff.%' THEN 'staff' ELSE 'member' END,
          template_key = kind,
          expires_at = created_at + CASE WHEN critical THEN interval '730 days' ELSE interval '90 days' END,
          delivery_mode = CASE
            WHEN email_status IN ('pending', 'sent', 'failed', 'ambiguous') THEN 'immediate'
            WHEN email_status = 'digest' THEN 'digest'
            ELSE 'none' END
        """
    )
    op.alter_column("notifications", "template_key", nullable=False)
    op.alter_column("notifications", "expires_at", nullable=False)
    op.create_check_constraint("ck_notifications_priority", "notifications", "priority IN ('critical', 'high', 'normal', 'low')")
    op.create_check_constraint("ck_notifications_audience", "notifications", "audience IN ('member', 'staff')")
    op.create_check_constraint("ck_notifications_delivery_mode", "notifications", "delivery_mode IN ('immediate', 'digest', 'none')")
    op.create_index("ix_notifications_expires_at", "notifications", ["expires_at"])
    op.create_index("ix_notifications_digest_queue", "notifications", ["delivery_mode", "digest_id"])

    # ---- deliveries and attempts (spec 7.3, 7.4) ----
    op.create_table(
        "notification_deliveries",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("notification_id", UUID, _fk("notifications", "CASCADE")),
        sa.Column("digest_id", UUID, _fk("notification_digests", "CASCADE")),
        sa.Column("channel", sa.String(10), nullable=False, server_default="email"),
        sa.Column("destination_ref", sa.String(64)),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("next_attempt_at", TS),
        sa.Column("lease_until", TS),
        sa.Column("provider", sa.String(20)),
        sa.Column("provider_message_id", sa.String(200)),
        sa.Column("last_error_code", sa.String(60)),
        sa.Column("last_error_summary", sa.String(300)),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('queued', 'sending', 'accepted', 'delivered', 'bounced', 'failed_permanently', 'skipped', 'ambiguous')",
            name="ck_notification_deliveries_status",
        ),
        sa.CheckConstraint("num_nonnulls(notification_id, digest_id) = 1", name="ck_notification_deliveries_subject"),
        sa.UniqueConstraint("notification_id", "channel", name="uq_notification_deliveries_notification"),
        sa.UniqueConstraint("digest_id", "channel", name="uq_notification_deliveries_digest"),
    )
    op.create_index("ix_notification_deliveries_due", "notification_deliveries", ["status", "next_attempt_at"])
    op.create_index("ix_notification_deliveries_message", "notification_deliveries", ["provider_message_id"])
    op.create_table(
        "notification_delivery_attempts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("delivery_id", UUID, _fk("notification_deliveries", "CASCADE"), nullable=False),
        sa.Column("attempt_number", sa.SmallInteger(), nullable=False),
        sa.Column("started_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", TS),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("provider_message_id", sa.String(200)),
        sa.Column("error_class", sa.String(40)),
        sa.Column("error_code", sa.String(60)),
        sa.Column("redacted_error_summary", sa.String(300)),
        sa.UniqueConstraint("delivery_id", "attempt_number", name="uq_notification_delivery_attempts_number"),
        sa.CheckConstraint(
            "outcome IN ('accepted', 'transient_failure', 'permanent_failure', 'ambiguous', 'skipped')",
            name="ck_notification_delivery_attempts_outcome",
        ),
    )
    # Carry the email state of existing notifications over, then their attempt history.
    op.execute(
        """
        INSERT INTO notification_deliveries (id, notification_id, channel, status, attempt_count, created_at, updated_at)
        SELECT gen_random_uuid(), id, 'email',
          CASE email_status WHEN 'pending' THEN 'queued' WHEN 'sent' THEN 'accepted'
                            WHEN 'failed' THEN 'failed_permanently' ELSE 'ambiguous' END,
          email_attempts, created_at, now()
        FROM notifications WHERE email_status IN ('pending', 'sent', 'failed', 'ambiguous')
        """
    )
    op.execute(
        """
        INSERT INTO notification_delivery_attempts
          (id, delivery_id, attempt_number, started_at, finished_at, outcome, provider_message_id, error_class, redacted_error_summary)
        SELECT gen_random_uuid(), d.id,
          row_number() OVER (PARTITION BY a.notification_id ORDER BY a.attempted_at),
          a.attempted_at, a.attempted_at,
          CASE a.status WHEN 'sent' THEN 'accepted' WHEN 'ambiguous' THEN 'ambiguous' ELSE 'transient_failure' END,
          a.provider_message_id, CASE WHEN a.status = 'failed' THEN 'legacy' END, left(a.error, 300)
        FROM delivery_attempts a JOIN notification_deliveries d ON d.notification_id = a.notification_id
        """
    )
    op.drop_table("delivery_attempts")
    op.drop_constraint("ck_notifications_email_status", "notifications", type_="check")
    op.drop_column("notifications", "email_status")
    op.drop_column("notifications", "email_attempts")
    op.drop_column("notifications", "critical")

    # ---- provider events, templates, rules, preferences, suppressions (spec 7.5 to 7.9) ----
    op.create_table(
        "notification_provider_events",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("provider_event_id", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("delivery_id", UUID, _fk("notification_deliveries", "SET NULL")),
        sa.Column("received_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", TS),
        sa.Column("redacted_payload", JSONB),
        sa.UniqueConstraint("provider", "provider_event_id", name="uq_notification_provider_events"),
    )
    op.create_table(
        "notification_templates",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("template_key", sa.String(80), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("locale", sa.String(5), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("subject_template", sa.String(200)),
        sa.Column("title_template", sa.String(160)),
        sa.Column("body_template", sa.String(600), nullable=False),
        sa.Column("variable_schema", JSONB, nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="draft"),
        sa.Column("created_by", UUID, _fk("users", "SET NULL")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("activated_at", TS),
        sa.UniqueConstraint("template_key", "channel", "locale", "version", name="uq_notification_templates_version"),
        sa.CheckConstraint("channel IN ('in_app', 'email')", name="ck_notification_templates_channel"),
        sa.CheckConstraint("locale IN ('bn', 'en')", name="ck_notification_templates_locale"),
        sa.CheckConstraint("status IN ('draft', 'active', 'retired')", name="ck_notification_templates_status"),
    )
    op.create_index(
        "uq_notification_templates_active", "notification_templates", ["template_key", "channel", "locale"],
        unique=True, postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "notification_rules",
        sa.Column("template_key", sa.String(80), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("priority", sa.String(8), nullable=False),
        sa.Column("email", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("priority IN ('critical', 'high', 'normal', 'low')", name="ck_notification_rules_priority"),
    )
    op.create_table(
        "notification_preferences",
        sa.Column("recipient_user_id", UUID, _fk("users", "CASCADE"), primary_key=True),
        sa.Column("standard_email_mode", sa.String(10), nullable=False, server_default="digest"),
        sa.Column("digest_timezone", sa.String(64), nullable=False, server_default="Asia/Dhaka"),
        sa.Column("digest_local_time", sa.Time(), nullable=False, server_default="08:00"),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("standard_email_mode IN ('immediate', 'digest', 'off')", name="ck_notification_preferences_mode"),
    )
    op.create_table(
        "notification_suppressions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("destination_hmac", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False, server_default="email"),
        sa.Column("reason_code", sa.String(60), nullable=False),
        sa.Column("created_by", UUID, _fk("users", "SET NULL")),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("removed_by", UUID, _fk("users", "SET NULL")),
        sa.Column("removed_at", TS),
        sa.Column("removal_reason", sa.String(300)),
    )
    op.create_index(
        "uq_notification_suppressions_active", "notification_suppressions", ["destination_hmac", "channel"],
        unique=True, postgresql_where=sa.text("removed_at IS NULL"),
    )

    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(REVOKE_SUPABASE_ROLES.format(tables=", ".join(f"'{t}'" for t in NEW_TABLES)))


def downgrade() -> None:
    """Back to the 0014 shape. Email state is folded back into the notification row; the attempt
    history is copied back as far as the old table can hold it. Templates, rules, preferences,
    suppressions, digests and provider events have no older home and are dropped."""
    op.add_column("notifications", sa.Column("critical", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("notifications", sa.Column("email_status", sa.String(10), nullable=False, server_default="none"))
    op.add_column("notifications", sa.Column("email_attempts", sa.SmallInteger(), nullable=False, server_default="0"))
    op.execute(
        """
        UPDATE notifications n SET
          critical = (n.priority = 'critical'),
          email_status = CASE
            WHEN n.delivery_mode = 'digest' THEN 'digest'
            WHEN x.status IS NULL THEN 'none'
            WHEN x.status IN ('accepted', 'delivered') THEN 'sent'
            WHEN x.status IN ('queued', 'sending') THEN 'pending'
            WHEN x.status = 'ambiguous' THEN 'ambiguous'
            ELSE 'failed' END,
          email_attempts = COALESCE(x.attempt_count, 0)
        FROM (
          SELECT n2.id, d.status, d.attempt_count
          FROM notifications n2 LEFT JOIN notification_deliveries d ON d.notification_id = n2.id
        ) x
        WHERE n.id = x.id
        """
    )
    op.create_check_constraint(
        "ck_notifications_email_status", "notifications", "email_status IN ('none', 'pending', 'sent', 'failed', 'ambiguous', 'digest')"
    )
    op.create_table(
        "delivery_attempts",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("notification_id", UUID, _fk("notifications", "CASCADE"), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False, server_default="email"),
        sa.Column("provider", sa.String(20), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("provider_message_id", sa.String(120)),
        sa.Column("error", sa.String(300)),
        sa.Column("attempted_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('sent', 'failed', 'ambiguous')", name="ck_delivery_attempts_status"),
    )
    op.create_index("ix_delivery_attempts_notification_id", "delivery_attempts", ["notification_id"])
    op.execute(
        """
        INSERT INTO delivery_attempts (id, notification_id, channel, provider, status, provider_message_id, error, attempted_at)
        SELECT a.id, d.notification_id, 'email', COALESCE(d.provider, 'unknown'),
          CASE a.outcome WHEN 'accepted' THEN 'sent' WHEN 'ambiguous' THEN 'ambiguous' ELSE 'failed' END,
          left(a.provider_message_id, 120), a.redacted_error_summary, a.started_at
        FROM notification_delivery_attempts a JOIN notification_deliveries d ON d.id = a.delivery_id
        WHERE d.notification_id IS NOT NULL AND a.outcome <> 'skipped'
        """
    )
    op.execute("ALTER TABLE public.delivery_attempts ENABLE ROW LEVEL SECURITY")

    for table in ("notification_provider_events", "notification_delivery_attempts", "notification_deliveries"):
        op.drop_table(table)
    op.drop_index("ix_notifications_digest_queue", table_name="notifications")
    op.drop_index("ix_notifications_expires_at", table_name="notifications")
    for name in ("ck_notifications_priority", "ck_notifications_audience", "ck_notifications_delivery_mode"):
        op.drop_constraint(name, "notifications", type_="check")
    for column in ("priority", "audience", "template_key", "template_version", "delivery_mode", "digest_id", "archived_at", "expires_at"):
        op.drop_column("notifications", column)
    for table in ("notification_digests", "notification_templates", "notification_rules", "notification_preferences", "notification_suppressions"):
        op.drop_table(table)

    op.drop_constraint("ck_outbox_events_status", "outbox_events", type_="check")
    op.execute("UPDATE outbox_events SET status = 'done' WHERE status = 'processed'")
    op.execute("UPDATE outbox_events SET status = 'failed' WHERE status = 'dead_letter'")
    op.execute("UPDATE outbox_events SET status = 'pending' WHERE status = 'retry'")
    op.create_check_constraint("ck_outbox_events_status", "outbox_events", "status IN ('pending', 'processing', 'done', 'failed')")
    op.drop_constraint("uq_outbox_events_dedupe_key", "outbox_events", type_="unique")
    for column in ("dedupe_key", "aggregate_type", "aggregate_version", "recipient_policy", "occurred_at", "lease_owner", "last_error_code"):
        op.drop_column("outbox_events", column)
