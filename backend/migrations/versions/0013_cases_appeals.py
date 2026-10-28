"""Verification cases and evidence, enforcement cases, sanctions and appeals (Moderation-Dashboard-Specification 6.2 to 6.5).

Revision ID: 0013_cases_appeals
Revises: 0012_tasks_reports
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0013_cases_appeals"
down_revision: str | None = "0012_tasks_reports"
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
TABLES = ("verification_cases", "verification_evidence", "enforcement_cases", "sanctions", "appeals")


def _fk(table: str, ondelete: str) -> sa.ForeignKey:
    return sa.ForeignKey(f"{table}.id", ondelete=ondelete)


def upgrade() -> None:
    op.create_table(
        "verification_cases",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("applicant_user_id", UUID, _fk("users", "CASCADE"), nullable=False),
        sa.Column("statement", sa.String(1000)),
        sa.Column("state", sa.String(24), nullable=False, server_default="submitted"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("decided_by", UUID, _fk("users", "SET NULL")),
        sa.Column("decided_at", TS),
        sa.Column("decision_reason", sa.String(60)),
        sa.Column("decision_note", sa.String(500)),
        sa.Column("purge_after", TS),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "state IN ('submitted', 'in_review', 'needs_clarification', 'approved', 'rejected', 'escalated', 'withdrawn')",
            name="ck_verification_cases_state",
        ),
    )
    op.create_index(
        "uq_verification_cases_one_open", "verification_cases", ["applicant_user_id"], unique=True,
        postgresql_where=sa.text("state IN ('submitted', 'in_review', 'needs_clarification', 'escalated')"),
    )

    op.create_table(
        "verification_evidence",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("case_id", UUID, _fk("verification_cases", "CASCADE"), nullable=False),
        sa.Column("object_key", sa.String(300), nullable=False, unique=True),
        sa.Column("content_type", sa.String(80), nullable=False),
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
        sa.Column("uploaded_by", UUID, _fk("users", "CASCADE"), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", TS),
        sa.CheckConstraint("status IN ('pending', 'uploaded', 'deleted')", name="ck_verification_evidence_status"),
    )
    op.create_index("ix_verification_evidence_case_id", "verification_evidence", ["case_id"])

    op.create_table(
        "enforcement_cases",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("review_id", UUID, _fk("reviews", "CASCADE")),
        sa.Column("subject_user_id", UUID, _fk("users", "CASCADE")),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("emergency", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("counts_toward_rating", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("follow_up_due_at", TS),
        sa.Column("opened_by", UUID, _fk("users", "RESTRICT"), nullable=False),
        sa.Column("reason_code", sa.String(60), nullable=False),
        sa.Column("note", sa.String(500)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("closed_at", TS),
        sa.CheckConstraint("kind IN ('takedown', 'account')", name="ck_enforcement_cases_kind"),
        sa.CheckConstraint("state IN ('taken_down', 'removed', 'restored', 'open', 'closed')", name="ck_enforcement_cases_state"),
        sa.CheckConstraint("num_nonnulls(review_id, subject_user_id) = 1", name="ck_enforcement_cases_one_subject"),
    )

    op.create_table(
        "sanctions",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("user_id", UUID, _fk("users", "CASCADE"), nullable=False),
        sa.Column("enforcement_case_id", UUID, _fk("enforcement_cases", "SET NULL")),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("scope", sa.String(60), nullable=False, server_default="reviews"),
        sa.Column("state", sa.String(10), nullable=False, server_default="active"),
        sa.Column("starts_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("ends_at", TS),
        sa.Column("review_on", sa.Date()),
        sa.Column("reason_code", sa.String(60), nullable=False),
        sa.Column("created_by", UUID, _fk("users", "RESTRICT"), nullable=False),
        sa.Column("reversed_by", UUID, _fk("users", "SET NULL")),
        sa.Column("reversed_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('warning', 'posting_restriction', 'suspension')", name="ck_sanctions_kind"),
        sa.CheckConstraint("state IN ('active', 'expired', 'reversed')", name="ck_sanctions_state"),
        sa.CheckConstraint("ends_at IS NOT NULL OR review_on IS NOT NULL", name="ck_sanctions_has_end"),
    )
    op.create_index("ix_sanctions_user_active", "sanctions", ["user_id"], postgresql_where=sa.text("state = 'active'"))

    op.create_table(
        "appeals",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("appellant_user_id", UUID, _fk("users", "CASCADE"), nullable=False),
        sa.Column("moderation_action_id", UUID, _fk("moderation_actions", "CASCADE")),
        sa.Column("enforcement_case_id", UUID, _fk("enforcement_cases", "CASCADE")),
        sa.Column("verification_case_id", UUID, _fk("verification_cases", "CASCADE")),
        sa.Column("state", sa.String(12), nullable=False, server_default="received"),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("original_decider_id", UUID),
        sa.Column("submitted_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("deadline_at", TS, nullable=False),
        sa.Column("decided_by", UUID, _fk("users", "SET NULL")),
        sa.Column("decided_at", TS),
        sa.Column("decision_note", sa.String(500)),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("state IN ('received', 'in_review', 'upheld', 'overturned', 'withdrawn')", name="ck_appeals_state"),
        sa.CheckConstraint("num_nonnulls(moderation_action_id, enforcement_case_id, verification_case_id) = 1", name="ck_appeals_one_target"),
    )
    for column in ("moderation_action_id", "enforcement_case_id", "verification_case_id"):
        op.create_index(
            f"uq_appeals_{column.split('_')[0]}", "appeals", [column], unique=True,
            postgresql_where=sa.text(f"{column} IS NOT NULL AND state <> 'withdrawn'"),
        )

    for table in TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(REVOKE_SUPABASE_ROLES)


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
