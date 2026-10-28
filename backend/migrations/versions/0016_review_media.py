"""Photos and videos on member reviews (Review.md 8, amendment A4 without transcoding).

Revision ID: 0016_review_media
Revises: 0015_pin_function_search_path
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0016_review_media"
down_revision: str | None = "0015_pin_function_search_path"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = postgresql.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)

REVOKE_SUPABASE_ROLES = """
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['anon', 'authenticated'] LOOP
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('REVOKE ALL ON TABLE public.review_media FROM %I', r);
    END IF;
  END LOOP;
END $$;
"""


def upgrade() -> None:
    op.create_table(
        "review_media",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("review_id", UUID, sa.ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploader_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(8), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="awaiting_upload"),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("content_type", sa.String(40), nullable=False),
        sa.Column("quarantine_key", sa.String(300), nullable=False, unique=True),
        sa.Column("processed_key", sa.String(300), unique=True),
        sa.Column("size_bytes", sa.Integer()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("alt_text", sa.String(250), nullable=False),
        sa.Column("caption", sa.String(300)),
        sa.Column("ownership_declared", sa.Boolean(), nullable=False),
        sa.Column("decided_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decided_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column("uploaded_at", TS),
        sa.CheckConstraint("kind IN ('image', 'video')", name="ck_review_media_kind"),
        sa.CheckConstraint(
            "state IN ('awaiting_upload', 'pending', 'approved', 'rejected', 'removed')", name="ck_review_media_state"
        ),
        sa.CheckConstraint("ownership_declared", name="ck_review_media_ownership"),
        sa.CheckConstraint(
            "state IN ('awaiting_upload', 'removed') OR processed_key IS NOT NULL", name="ck_review_media_processed"
        ),
    )
    op.create_index("ix_review_media_review", "review_media", ["review_id", "position"])
    op.execute("ALTER TABLE public.review_media ENABLE ROW LEVEL SECURITY")
    op.execute(REVOKE_SUPABASE_ROLES)


def downgrade() -> None:
    op.drop_table("review_media")
