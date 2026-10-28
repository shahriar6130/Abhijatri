"""The SMTP email provider (Gmail and others), against a fake SMTP server."""

import smtplib
from collections.abc import Generator
from email.message import EmailMessage
from typing import Any

import pytest

from app.config import get_settings
from app.notify import providers
from app.notify.providers import Email, SendAmbiguous, SendFailed, SmtpProvider

EMAIL = Email(to="nila@example.com", subject="Hello", text="plain", html="<p>html</p>", idempotency_key="notification-1")


class FakeSMTP:
    instances: list["FakeSMTP"] = []
    fail_on: str | None = None

    def __init__(self, host: str, port: int, timeout: float, **_: Any) -> None:
        self.host, self.port, self.calls, self.sent = host, port, [], []
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *_: Any) -> None:
        self.calls.append("quit")

    def starttls(self, context: Any) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        if FakeSMTP.fail_on == "login":
            raise smtplib.SMTPAuthenticationError(535, b"bad credentials")
        self.calls.append(f"login:{user}")

    def send_message(self, message: EmailMessage) -> None:
        if FakeSMTP.fail_on == "send":
            raise smtplib.SMTPServerDisconnected("connection lost")
        self.sent.append(message)


@pytest.fixture(autouse=True)
def smtp_settings(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    for name, value in {"EMAIL_PROVIDER": "smtp", "SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "587", "SMTP_USERNAME": "sender@gmail.com", "SMTP_PASSWORD": "app-password-for-tests", "EMAIL_FROM": "Abhijatri <sender@gmail.com>"}.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(providers.smtplib, "SMTP", FakeSMTP)
    FakeSMTP.instances, FakeSMTP.fail_on = [], None
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_sends_with_starttls_and_login() -> None:
    assert isinstance(providers.get_provider(), SmtpProvider)
    message_id = SmtpProvider().send(EMAIL)
    server = FakeSMTP.instances[0]
    assert (server.host, server.port) == ("smtp.gmail.com", 587)
    assert server.calls[:2] == ["starttls", "login:sender@gmail.com"]
    sent = server.sent[0]
    assert sent["To"] == "nila@example.com" and sent["From"] == "Abhijatri <sender@gmail.com>"
    assert sent["Message-ID"] == message_id and "notification-1" in message_id
    assert {part.get_content_type() for part in sent.iter_parts()} == {"text/plain", "text/html"}


def test_bad_credentials_are_a_failure_and_a_lost_connection_is_ambiguous() -> None:
    FakeSMTP.fail_on = "login"
    with pytest.raises(SendFailed):
        SmtpProvider().send(EMAIL)
    FakeSMTP.fail_on = "send"
    with pytest.raises(SendAmbiguous):
        SmtpProvider().send(EMAIL)


def test_production_requires_the_smtp_password(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import ValidationError
    from test_config import _prod

    monkeypatch.delenv("SMTP_PASSWORD")
    with pytest.raises(ValidationError, match="SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD"):
        _prod(email_provider="smtp", smtp_host="smtp.gmail.com", smtp_username="a@gmail.com")
    assert _prod(email_provider="smtp", smtp_host="smtp.gmail.com", smtp_username="a@gmail.com", smtp_password="app-password").email_provider == "smtp"


def test_brevo_sends_through_the_api_and_maps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    from app.notify.providers import BrevoProvider

    monkeypatch.setenv("BREVO_API_KEY", "xkeysib-test")
    get_settings.cache_clear()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(201, json={"messageId": "<abc@smtp-relay.mailin.fr>"})

    assert BrevoProvider(transport=httpx.MockTransport(handler)).send(EMAIL) == "<abc@smtp-relay.mailin.fr>"
    body = __import__("json").loads(seen[0].content)
    assert seen[0].url == "https://api.brevo.com/v3/smtp/email" and seen[0].headers["api-key"] == "xkeysib-test"
    assert body["sender"] == {"name": "Abhijatri", "email": "sender@gmail.com"} and body["to"] == [{"email": "nila@example.com"}]
    assert body["htmlContent"] == "<p>html</p>" and body["textContent"] == "plain"
    with pytest.raises(SendFailed):
        BrevoProvider(transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"code": "unauthorized"}))).send(EMAIL)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(SendAmbiguous):
        BrevoProvider(transport=httpx.MockTransport(timeout)).send(EMAIL)
