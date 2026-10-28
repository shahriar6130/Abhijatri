"""Member authentication and staff roles (Gantt R04, Moderation-Dashboard-Specification 2.2 and 6.1).

- ``users.status`` / ``disabled_at``: an account can be disabled; it then fails closed everywhere.
- ``user_roles``: staff roles as the specification defines them (``moderator`` or ``superadmin``),
  with a partial unique index so a user has at most one active role.
- ``role_admin_guard``: a single row locked to serialise superadmin grants and revocations.
- ``auth_session_activity``: last request time per Auth session, for the superadmin inactivity limit.
- Existing ``user_platform_roles`` grants are copied (MODERATOR -> moderator; ADMINISTRATOR and
  SUPER_ADMINISTRATOR -> superadmin). The old tables stay until the /admin API replaces /staff.

Revision ID: 0010_auth_roles
Revises: 0009_guest_tag_visit_stats
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0010_auth_roles"
down_revision: str | None = "0009_guest_tag_visit_stats"
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

NEW_TABLES = ("user_roles", "role_admin_guard", "auth_session_activity")


def upgrade() -> None:
    op.add_column("users", sa.Column("status", sa.String(20), nullable=False, server_default="active"))
    op.add_column("users", sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint("ck_users_status", "users", "status IN ('active', 'disabled')")

    op.create_table(
        "user_roles",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('moderator', 'superadmin')", name="ck_user_roles_role"),
    )
    op.create_index(
        "uq_user_roles_one_active", "user_roles", ["user_id"], unique=True, postgresql_where=sa.text("revoked_at IS NULL")
    )

    op.create_table(
        "role_admin_guard",
        sa.Column("id", sa.SmallInteger(), primary_key=True),
        sa.CheckConstraint("id = 1", name="ck_role_admin_guard_single_row"),
    )
    op.execute("INSERT INTO role_admin_guard (id) VALUES (1)")

    op.create_table(
        "auth_session_activity",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_auth_session_activity_user", "auth_session_activity", ["user_id"])

    # One active role per user: the highest of the old grants wins.
    op.execute(
        """
        INSERT INTO user_roles (user_id, role, granted_at)
        SELECT DISTINCT ON (upr.user_id)
               upr.user_id,
               CASE WHEN pr.code = 'MODERATOR' THEN 'moderator' ELSE 'superadmin' END,
               upr.assigned_at
        FROM user_platform_roles upr
        JOIN platform_roles pr ON pr.id = upr.role_id
        WHERE pr.code IN ('MODERATOR', 'ADMINISTRATOR', 'SUPER_ADMINISTRATOR')
          AND (upr.expires_at IS NULL OR upr.expires_at > now())
        ORDER BY upr.user_id, (pr.code = 'MODERATOR')
        """
    )

    for table in NEW_TABLES:
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(REVOKE_SUPABASE_ROLES)


def downgrade() -> None:
    op.drop_table("auth_session_activity")
    op.drop_table("role_admin_guard")
    op.drop_index("uq_user_roles_one_active", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_constraint("ck_users_status", "users", type_="check")
    op.drop_column("users", "disabled_at")
    op.drop_column("users", "status")
    op.execute(REVOKE_SUPABASE_ROLES)
