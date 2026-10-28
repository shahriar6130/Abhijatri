"""Append-only audit events and decision idempotency keys (Moderation-Dashboard-Specification 6.6 and 8.2).

- ``audit_events``: privileged actions, state transitions and role changes. A trigger refuses UPDATE and
  DELETE, so even the application role cannot rewrite history. The table is not partitioned, so ``id`` is
  a global lookup key. There is no foreign key to ``users``: the log must outlive an account.
- ``idempotency_keys``: the stored result of a retried decision, scoped by actor and operation.

Revision ID: 0011_audit_idempotency
Revises: 0010_auth_roles
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0011_audit_idempotency"
down_revision: str | None = "0010_auth_roles"
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


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("actor_role_snapshot", sa.String(20)),
        sa.Column("action", sa.String(80), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("request_id", sa.String(64)),
        sa.Column("reason", sa.String(500)),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_target", "audit_events", ["target_type", "target_id"])
    op.create_index("ix_audit_events_actor", "audit_events", ["actor_user_id"])
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_events_are_append_only() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_change BEFORE UPDATE OR DELETE ON audit_events "
        "FOR EACH ROW EXECUTE FUNCTION audit_events_are_append_only()"
    )
    op.execute(
        "CREATE TRIGGER audit_events_no_truncate BEFORE TRUNCATE ON audit_events "
        "FOR EACH STATEMENT EXECUTE FUNCTION audit_events_are_append_only()"
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("operation", sa.String(80), primary_key=True),
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("fingerprint", sa.CHAR(64), nullable=False),
        sa.Column("status_code", sa.SmallInteger(), nullable=False),
        sa.Column("response", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    for table in ("audit_events", "idempotency_keys"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(REVOKE_SUPABASE_ROLES)


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events")
    op.execute("DROP TRIGGER IF EXISTS audit_events_no_change ON audit_events")
    op.drop_table("audit_events")
    op.execute("DROP FUNCTION IF EXISTS audit_events_are_append_only()")
