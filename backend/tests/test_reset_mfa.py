"""The operator command that removes a lost authenticator (app/jobs/reset_mfa.py)."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.jobs import reset_mfa
from app.models import AuditEvent, OutboxEvent, User

pytestmark = pytest.mark.integration


class FakeAuth:
    def __init__(self, factors: list[dict[str, Any]]) -> None:
        self.factors = factors
        self.deleted: list[str] = []

    def admin_list_factors(self, user_id: str) -> list[dict[str, Any]]:
        return [f for f in self.factors if f["id"] not in self.deleted]

    def admin_delete_factor(self, user_id: str, factor_id: str) -> None:
        self.deleted.append(factor_id)


@pytest.fixture()
def sessions(postgres_session: Session, monkeypatch: pytest.MonkeyPatch) -> sessionmaker[Session]:
    factory = sessionmaker(bind=postgres_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(reset_mfa, "SessionLocal", factory)
    return factory


def test_it_removes_every_factor_audits_and_tells_the_person(postgres_session: Session, sessions: sessionmaker[Session]) -> None:
    user = User(email="boss@example.com", display_name="Boss", email_verified_at=datetime.now(UTC))
    postgres_session.add(user)
    postgres_session.commit()
    auth = FakeAuth([{"id": "f1", "factor_type": "totp"}, {"id": "f2", "factor_type": "totp"}])
    assert reset_mfa.run(" Boss@Example.com ", assume_yes=True, gotrue=auth) == 0  # type: ignore[arg-type]
    assert auth.deleted == ["f1", "f2"]
    event = postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "staff.mfa_reset"))
    assert event is not None and event.actor_user_id is None and event.event_metadata == {"factors_removed": 2}
    assert postgres_session.scalar(select(OutboxEvent).where(OutboxEvent.topic == "security.mfa_reset")) is not None
    assert reset_mfa.run("boss@example.com", assume_yes=True, gotrue=auth) == 0, "nothing left: still fine"


def test_it_refuses_unknown_accounts_and_a_wrong_confirmation(postgres_session: Session, sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch) -> None:
    auth = FakeAuth([{"id": "f1"}])
    assert reset_mfa.run("ghost@example.com", assume_yes=True, gotrue=auth) == 3  # type: ignore[arg-type]
    postgres_session.add(User(email="mod@example.com", display_name="Mod", email_verified_at=datetime.now(UTC)))
    postgres_session.commit()
    monkeypatch.setattr("builtins.input", lambda _prompt: "someone-else@example.com")
    assert reset_mfa.run("mod@example.com", gotrue=auth) == 1  # type: ignore[arg-type]
    assert auth.deleted == []
