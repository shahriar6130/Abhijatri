"""Moderation task queue with claim leases, and member reports (Moderation-Dashboard-Specification 5 and 6.3; Gantt R10, R11).

- ``moderation_tasks``: queue ownership and lease state, separate from content lifecycle. One open task per
  subject. Existing pending reviews get a task so nothing is missing from the queue.
- ``reports``: a member's report on a review; one open report per reporter and review.
- ``moderation_actions`` gains ``task_id`` and ``request_id`` so a decision can be traced to its task and request.

Revision ID: 0012_tasks_reports
Revises: 0011_audit_idempotency
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0012_tasks_reports"
down_revision: str | None = "0011_audit_idempotency"
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
        "moderation_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("task_type", sa.String(30), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="open"),
        sa.Column("required_role", sa.String(20), nullable=False, server_default="moderator"),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("assigned_to", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("claimed_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('open', 'done', 'cancelled')", name="ck_moderation_tasks_status"),
        sa.CheckConstraint("required_role IN ('moderator', 'superadmin')", name="ck_moderation_tasks_role"),
        sa.CheckConstraint(
            "task_type IN ('review_moderation', 'report', 'verification', 'appeal', 'enforcement')",
            name="ck_moderation_tasks_type",
        ),
    )
    op.create_index(
        "uq_moderation_tasks_open_subject",
        "moderation_tasks",
        ["task_type", "subject_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index("ix_moderation_tasks_queue", "moderation_tasks", ["status", "priority", "created_at"])

    op.create_table(
        "reports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("review_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reporter_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reason_code", sa.String(40), nullable=False),
        sa.Column("details", sa.String(1000)),
        sa.Column("state", sa.String(12), nullable=False, server_default="open"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("resolved_at", sa.DateTime(timezone=True)),
        sa.Column("resolution_note", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("state IN ('open', 'in_review', 'actioned', 'dismissed')", name="ck_reports_state"),
    )
    op.create_index(
        "uq_reports_one_open_per_reporter",
        "reports",
        ["reporter_user_id", "review_id"],
        unique=True,
        postgresql_where=sa.text("state IN ('open', 'in_review')"),
    )
    op.create_index("ix_reports_review", "reports", ["review_id"])

    op.add_column("moderation_actions", sa.Column("task_id", postgresql.UUID(as_uuid=True)))
    op.add_column("moderation_actions", sa.Column("request_id", sa.String(64)))

    # Reviews already waiting for a moderator appear in the queue.
    op.execute(
        """
        INSERT INTO moderation_tasks (id, task_type, subject_id, created_at, updated_at)
        SELECT gen_random_uuid(), 'review_moderation', id, created_at, now()
        FROM reviews WHERE status IN ('PENDING', 'UNDER_REVIEW')
        """
    )

    for table in ("moderation_tasks", "reports"):
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(REVOKE_SUPABASE_ROLES)


def downgrade() -> None:
    op.drop_column("moderation_actions", "request_id")
    op.drop_column("moderation_actions", "task_id")
    op.drop_table("reports")
    op.drop_table("moderation_tasks")
