import os
from collections.abc import Generator
from datetime import datetime
from urllib.parse import urlparse

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings

# Tests must not read the developer's local .env (it enables the staff test header and sets the ops token).
# This runs before any other app import, because importing app.db already caches the settings.
Settings.model_config["env_file"] = None
os.environ.setdefault("APP_ENV", "development")
# The app's own engine (rate-limit buckets, counters) must hit the test database, never the dev one.
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
get_settings.cache_clear()

from app import models  # noqa: E402, F401
from app.admin import audit as _audit  # noqa: E402
from app.db import Base  # noqa: E402

# An audit action that is not listed in app.audit_actions fails the test that wrote it (Moderation spec 6.6).
_audit.STRICT = True


def _test_database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL", "")
    if not value:
        pytest.skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
    database_name = urlparse(value.replace("postgresql+psycopg", "postgresql", 1)).path.lstrip("/")
    if not database_name.endswith("_test"):
        pytest.fail("Refusing to reset a database whose name does not end with '_test'")
    return value


def backdate_decisions(session: Session, when: "datetime", **where: object) -> None:
    """Move decisions into the past for a test. The table is append-only, so the guard is lifted for this one
    statement only (never in application code); the next statement is guarded again."""
    from sqlalchemy import update as _update

    session.execute(text("ALTER TABLE moderation_actions DISABLE TRIGGER moderation_actions_no_change"))
    try:
        session.execute(_update(models.ModerationActionRecord).where(*[getattr(models.ModerationActionRecord, k) == v for k, v in where.items()]).values(created_at=when))
    finally:
        session.execute(text("ALTER TABLE moderation_actions ENABLE TRIGGER moderation_actions_no_change"))


@pytest.fixture()
def postgres_session() -> Generator[Session, None, None]:
    engine = create_engine(_test_database_url(), pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        yield session
        session.rollback()
    Base.metadata.drop_all(engine)
    with engine.begin() as connection:  # drop_all leaves functions behind; the migration check needs a clean database
        connection.execute(text("DROP FUNCTION IF EXISTS audit_events_are_append_only()"))
        connection.execute(text("DROP FUNCTION IF EXISTS moderation_actions_are_append_only()"))
    engine.dispose()

