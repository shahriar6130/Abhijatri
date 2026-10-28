"""The bootstrap command (Platform Foundation 8.4)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.jobs import bootstrap_admin
from app.models import AuditEvent, User, UserRole

pytestmark = pytest.mark.integration


@pytest.fixture()
def use_test_database(postgres_session: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    factory = sessionmaker(bind=postgres_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(bootstrap_admin, "SessionLocal", factory)
    return postgres_session


def _verified(session: Session, email: str) -> User:
    user = User(email=email, display_name="Owner", email_verified_at=datetime.now(UTC))
    session.add(user)
    session.commit()
    return user


def test_it_promotes_a_verified_account_once_and_audits_it(use_test_database: Session) -> None:
    owner = _verified(use_test_database, "owner@example.com")
    assert bootstrap_admin.run("Owner@Example.com", assume_yes=True) == 0
    use_test_database.expire_all()
    role = use_test_database.scalar(select(UserRole).where(UserRole.user_id == owner.id, UserRole.revoked_at.is_(None)))
    assert role is not None and role.role == "superadmin" and role.granted_by is None
    event = use_test_database.scalar(select(AuditEvent).where(AuditEvent.action == "staff.role_granted"))
    assert event is not None and event.actor_user_id is None and event.target_id == str(owner.id)


def test_it_refuses_when_a_superadmin_already_exists(use_test_database: Session) -> None:
    first = _verified(use_test_database, "owner@example.com")
    second = _verified(use_test_database, "second@example.com")
    assert bootstrap_admin.run("owner@example.com", assume_yes=True) == 0
    assert bootstrap_admin.run("second@example.com", assume_yes=True) == 2
    use_test_database.expire_all()
    assert use_test_database.scalar(select(UserRole).where(UserRole.user_id == second.id)) is None
    assert first.id != second.id


def test_it_refuses_unknown_or_unverified_accounts(use_test_database: Session) -> None:
    assert bootstrap_admin.run("ghost@example.com", assume_yes=True) == 3
    use_test_database.add(User(email="new@example.com", display_name="New"))
    use_test_database.commit()
    assert bootstrap_admin.run("new@example.com", assume_yes=True) == 3


def test_a_wrong_confirmation_cancels(use_test_database: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    _verified(use_test_database, "owner@example.com")
    monkeypatch.setattr("builtins.input", lambda _prompt: "someone-else@example.com")
    assert bootstrap_admin.run("owner@example.com") == 1
    assert use_test_database.scalar(select(UserRole)) is None
