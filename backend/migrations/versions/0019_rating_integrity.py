"""R08 rating integrity: ``INELIGIBLE_INVALID`` for a review that cannot be counted as it stands.

- ``rating_eligibility`` gains INELIGIBLE_INVALID: the visit month is in the future or the structured
  fields are incomplete (Review.md 6.1). Nothing else changes in the schema; reconciliation results and
  verification revocations are recorded in ``audit_events``.

Downgrade: PostgreSQL cannot drop an enum value, so the value stays in the type and rows that use it
are moved to INELIGIBLE_REMOVED (the nearest value that older code understands).

Revision ID: 0019_rating_integrity
Revises: 0018_review_crud
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0019_rating_integrity"
down_revision: str | None = "0018_review_crud"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # A new enum value cannot be used in the transaction that adds it, so it is committed on its own.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE rating_eligibility ADD VALUE IF NOT EXISTS 'INELIGIBLE_INVALID'")


def downgrade() -> None:
    op.execute("UPDATE reviews SET rating_eligibility = 'INELIGIBLE_REMOVED' WHERE rating_eligibility = 'INELIGIBLE_INVALID'")
