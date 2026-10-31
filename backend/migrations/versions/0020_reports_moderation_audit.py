"""R11 reports, moderation actions and audit log.

- ``reports``: the nine reasons of Review.md 5.4 (``offensive`` becomes ``harassment``) plus ``removal_request``;
  anonymous reports (``source``, ``reporter_scope_hash``, ``contact``, ``severity``), reporter columns guarded by
  ``ck_reports_source``; one open anonymous report per scope and review.
- ``moderation_decision`` gains REOPEN (a rejected review goes back to the queue within 30 days).
- ``reviews.purged_at`` marks a rejected review whose text retention redacted (Moderation spec P-03).
- ``moderation_actions`` becomes append-only like ``audit_events`` (Review.md 5.4).
- ``audit_events`` gets the indexes the filtered search uses.

Downgrade: the enum value REOPEN stays (PostgreSQL cannot drop it); rows that use it cannot exist after the
downgrade because the code that writes it is gone. ``harassment`` is mapped back to ``offensive`` and anonymous
reports are deleted, since the old schema has no place for them.

Revision ID: 0020_reports_mod_audit
Revises: 0019_rating_integrity
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0020_reports_mod_audit"
down_revision: str | None = "0019_rating_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REASONS = (
    "'spam', 'harassment', 'false_information', 'privacy', 'impersonation', 'safety_misinformation', "
    "'copyright', 'conflict_of_interest', 'other', 'removal_request'"
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE moderation_decision ADD VALUE IF NOT EXISTS 'REOPEN'")

    # reports
    op.alter_column("reports", "reporter_user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.add_column("reports", sa.Column("source", sa.String(10), nullable=False, server_default="member"))
    op.add_column("reports", sa.Column("reporter_scope_hash", sa.LargeBinary(32)))
    op.add_column("reports", sa.Column("contact", sa.String(200)))
    op.add_column("reports", sa.Column("severity", sa.SmallInteger(), nullable=False, server_default="1"))
    op.execute("UPDATE reports SET reason_code = 'harassment' WHERE reason_code = 'offensive'")
    op.execute("UPDATE reports SET severity = 2 WHERE reason_code IN ('privacy', 'safety_misinformation', 'impersonation', 'copyright', 'harassment')")
    op.create_check_constraint("ck_reports_reason", "reports", f"reason_code IN ({REASONS})")
    op.create_check_constraint(
        "ck_reports_source",
        "reports",
        "(source = 'member' AND reporter_user_id IS NOT NULL AND reporter_scope_hash IS NULL) OR "
        "(source = 'anonymous' AND reporter_user_id IS NULL AND reporter_scope_hash IS NOT NULL)",
    )
    op.create_index(
        "uq_reports_one_open_per_scope",
        "reports",
        ["reporter_scope_hash", "review_id"],
        unique=True,
        postgresql_where=sa.text("reporter_scope_hash IS NOT NULL AND state IN ('open', 'in_review')"),
    )

    # reviews
    op.add_column("reviews", sa.Column("purged_at", sa.DateTime(timezone=True)))
    op.create_index(
        "ix_reviews_purge_candidates",
        "reviews",
        ["updated_at"],
        postgresql_where=sa.text("status = 'REJECTED' AND purged_at IS NULL"),
    )

    # audit search
    op.create_index("ix_audit_events_action_time", "audit_events", ["action", "occurred_at"])
    op.create_index("ix_audit_events_request", "audit_events", ["request_id"])

    # moderation history is append-only
    op.execute(
        "CREATE OR REPLACE FUNCTION moderation_actions_are_append_only() RETURNS trigger SET search_path = '' AS $$ "
        "BEGIN RAISE EXCEPTION 'moderation_actions is append-only'; END; $$ LANGUAGE plpgsql"
    )
    op.execute(
        "CREATE TRIGGER moderation_actions_no_change BEFORE UPDATE OR DELETE ON moderation_actions "
        "FOR EACH ROW EXECUTE FUNCTION moderation_actions_are_append_only()"
    )
    op.execute(
        "CREATE TRIGGER moderation_actions_no_truncate BEFORE TRUNCATE ON moderation_actions "
        "FOR EACH STATEMENT EXECUTE FUNCTION moderation_actions_are_append_only()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS moderation_actions_no_truncate ON moderation_actions")
    op.execute("DROP TRIGGER IF EXISTS moderation_actions_no_change ON moderation_actions")
    op.execute("DROP FUNCTION IF EXISTS moderation_actions_are_append_only()")
    op.drop_index("ix_audit_events_request", table_name="audit_events")
    op.drop_index("ix_audit_events_action_time", table_name="audit_events")
    op.drop_index("ix_reviews_purge_candidates", table_name="reviews")
    op.drop_column("reviews", "purged_at")
    op.drop_index("uq_reports_one_open_per_scope", table_name="reports")
    op.drop_constraint("ck_reports_source", "reports", type_="check")
    op.drop_constraint("ck_reports_reason", "reports", type_="check")
    op.execute("DELETE FROM reports WHERE source = 'anonymous'")
    op.execute("UPDATE reports SET reason_code = 'offensive' WHERE reason_code = 'harassment'")
    op.execute("UPDATE reports SET reason_code = 'other' WHERE reason_code NOT IN ('spam', 'offensive', 'false_information', 'privacy', 'conflict_of_interest', 'other')")
    op.drop_column("reports", "severity")
    op.drop_column("reports", "contact")
    op.drop_column("reports", "reporter_scope_hash")
    op.drop_column("reports", "source")
    op.alter_column("reports", "reporter_user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
