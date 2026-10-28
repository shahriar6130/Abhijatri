"""Guest tag on reviews, member visit days, and daily visit totals (Guest-Identity-and-Visits 4.5).

- ``reviews.guest_tag``: the public pseudonym derived from the guest scope secret (3.1), stored
  without its dash. Only guest reviews may carry one.
- ``users.first_visit_on`` / ``last_visit_on``: member visit days, written once R04 sign-in exists.
- ``visit_daily_stats``: four integers per Asia/Dhaka day, rolled up from Redis. Nothing in it
  identifies a visitor.
- ``guest_visits`` is retired: its per-day totals move to ``guest_total_legacy`` (they cannot be
  split into new and returning), then the table is dropped. Its rows were pre-release test data.

Revision ID: 0009_guest_tag_visit_stats
Revises: 0008_guest_visits_count_only
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0009_guest_tag_visit_stats"
down_revision: str | None = "0008_guest_visits_count_only"
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

COUNT_COLUMNS = ("guest_new", "guest_returning", "member_new", "member_returning", "guest_total_legacy")


def upgrade() -> None:
    op.add_column("reviews", sa.Column("guest_tag", sa.CHAR(10), nullable=True))
    op.create_check_constraint(
        "ck_review_guest_tag",
        "reviews",
        "guest_tag IS NULL OR (author_user_id IS NULL AND guest_tag ~ '^[0-9A-HJKMNP-TV-Z]{10}$')",
    )

    op.add_column("users", sa.Column("first_visit_on", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("last_visit_on", sa.Date(), nullable=True))

    op.create_table(
        "visit_daily_stats",
        sa.Column("day", sa.Date(), primary_key=True),
        *(sa.Column(column, sa.Integer(), nullable=True) for column in COUNT_COLUMNS),
        sa.Column("rolled_up_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        *(
            sa.CheckConstraint(f"{column} IS NULL OR {column} >= 0", name=f"ck_visit_daily_stats_{column}")
            for column in COUNT_COLUMNS
        ),
    )
    op.execute(
        "INSERT INTO visit_daily_stats (day, guest_total_legacy, rolled_up_at) "
        "SELECT (visited_at AT TIME ZONE 'Asia/Dhaka')::date, count(*), now() "
        "FROM guest_visits GROUP BY 1"
    )
    op.drop_index("ix_guest_visits_visited_at", table_name="guest_visits")
    op.drop_table("guest_visits")

    op.execute("ALTER TABLE public.visit_daily_stats ENABLE ROW LEVEL SECURITY")
    op.execute(REVOKE_SUPABASE_ROLES)


def downgrade() -> None:
    op.create_table(
        "guest_visits",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("visited_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_guest_visits_visited_at", "guest_visits", ["visited_at"])
    op.execute("ALTER TABLE public.guest_visits ENABLE ROW LEVEL SECURITY")
    op.drop_table("visit_daily_stats")
    op.drop_column("users", "last_visit_on")
    op.drop_column("users", "first_visit_on")
    op.drop_constraint("ck_review_guest_tag", "reviews", type_="check")
    op.drop_column("reviews", "guest_tag")
    op.execute(REVOKE_SUPABASE_ROLES)
