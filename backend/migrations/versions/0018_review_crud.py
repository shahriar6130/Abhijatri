"""R07 review CRUD: request-changes decision, superseded revisions, member history index, guest appeals.

- ``moderation_decision`` gains REQUEST_CHANGES so CHANGES_REQUESTED is reachable (Review.md 5.1, 5.2).
- ``revision_status`` gains SUPERSEDED for a revision replaced by an edit of the unpublished review.
- ``ix_reviews_member_history`` serves ``GET /reviews/mine`` (Review.md 9.3, "Member history").
- ``appeals.appellant_user_id`` becomes nullable for a guest appeal filed with a receipt (Review.md 4.2),
  guarded by ``ck_appeals_guest_target``; ``appeals.reason`` grows to the 2000 characters of API.md 5.6.

Revision ID: 0018_review_crud
Revises: 0017_notification_system
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0018_review_crud"
down_revision: str | None = "0017_notification_system"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A new enum value cannot be used in the transaction that adds it, so each is committed on its own.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE moderation_decision ADD VALUE IF NOT EXISTS 'REQUEST_CHANGES'")
        op.execute("ALTER TYPE revision_status ADD VALUE IF NOT EXISTS 'SUPERSEDED'")

    op.create_index(
        "ix_reviews_member_history",
        "reviews",
        ["author_user_id", sa.text("created_at DESC"), sa.text("id DESC")],
        postgresql_where=sa.text("author_user_id IS NOT NULL"),
    )

    op.alter_column("appeals", "appellant_user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)
    op.alter_column("appeals", "reason", existing_type=sa.String(1000), type_=sa.String(2000), existing_nullable=False)
    op.create_check_constraint(
        "ck_appeals_guest_target", "appeals", "appellant_user_id IS NOT NULL OR moderation_action_id IS NOT NULL"
    )


def downgrade() -> None:
    # Postgres cannot drop enum values; REQUEST_CHANGES and SUPERSEDED stay defined but unused.
    op.drop_constraint("ck_appeals_guest_target", "appeals", type_="check")
    op.execute("DELETE FROM appeals WHERE appellant_user_id IS NULL")
    op.execute("UPDATE appeals SET reason = left(reason, 1000)")
    op.alter_column("appeals", "reason", existing_type=sa.String(2000), type_=sa.String(1000), existing_nullable=False)
    op.alter_column("appeals", "appellant_user_id", existing_type=postgresql.UUID(as_uuid=True), nullable=False)
    op.drop_index("ix_reviews_member_history", table_name="reviews")
