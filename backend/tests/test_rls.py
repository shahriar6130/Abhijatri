import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text

pytestmark = pytest.mark.integration

BACKEND = Path(__file__).resolve().parents[1]


def _alembic(url: str, *args: str) -> None:
    env = {**os.environ, "DATABASE_URL": url, "APP_ENV": "test"}
    subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, check=True, capture_output=True
    )


def test_every_public_table_has_row_level_security() -> None:
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    database_name = urlparse(url.replace("postgresql+psycopg", "postgresql", 1)).path.lstrip("/")
    if not database_name.endswith("_test"):
        pytest.fail("Refusing to reset a database whose name does not end with '_test'")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    try:
        _alembic(url, "upgrade", "head")
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT c.relname, c.relrowsecurity FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'public' AND c.relkind = 'r'"
                )
            ).all()
        assert rows, "migration created no tables"
        assert [name for name, enabled in rows if not enabled] == []
        with engine.connect() as conn:
            roles = conn.execute(text("SELECT rolname FROM pg_roles WHERE rolname IN ('anon', 'authenticated')")).scalars().all()
            granted = conn.execute(
                text(
                    "SELECT table_name, grantee, privilege_type FROM information_schema.role_table_grants "
                    "WHERE table_schema = 'public' AND grantee IN ('anon', 'authenticated')"
                )
            ).all()
        # RLS does not replace grants (Notification spec 10): the browser roles get nothing on any table.
        assert granted == [], f"browser roles must have no table grants: {granted}"
        if not roles:
            pytest.skip("this PostgreSQL has no Supabase roles; grants checked only for RLS")
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        engine.dispose()
