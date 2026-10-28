"""Email providers behind one small interface.

- ``mailpit``: the local development inbox (http://127.0.0.1:54324); nothing leaves the machine.
- ``resend``: production, over HTTPS with an ``Idempotency-Key`` so a retried send is not delivered twice.
- ``gmail``: the Gmail API over HTTPS, sending as the authorised Gmail account (no SMTP port needed).
- ``recording``: tests.

A provider returns the provider's message id, raises ``SendFailed`` when the message was certainly not
accepted, and raises ``SendAmbiguous`` when it may have been (a timeout after the request was sent).
"""

import base64
import smtplib
import ssl
import threading
import time
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import make_msgid
from typing import Protocol

import httpx

from app.config import get_settings


class SendFailed(Exception):
    """The message was certainly not accepted. ``permanent``: retrying cannot help (a 4xx other than 429,
    a refused recipient); otherwise the delivery is retried on the schedule."""

    def __init__(self, message: str, *, permanent: bool = False, code: str | None = None) -> None:
        super().__init__(message)
        self.permanent = permanent
        self.code = code


def _rejected(status: int) -> bool:
    return 400 <= status < 500 and status != 429


class SendAmbiguous(Exception):
    pass


@dataclass(frozen=True)
class Email:
    to: str
    subject: str
    text: str
    html: str
    idempotency_key: str


class Provider(Protocol):
    name: str

    def send(self, email: Email) -> str: ...


class MailpitProvider:
    name = "mailpit"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def send(self, email: Email) -> str:
        settings = get_settings()
        body = {
            "From": {"Email": settings.email_from_address, "Name": "Abhijatri"},
            "To": [{"Email": email.to}],
            "Subject": email.subject,
            "Text": email.text,
            "HTML": email.html,
            "Headers": {"X-Idempotency-Key": email.idempotency_key},
        }
        try:
            with httpx.Client(timeout=10, transport=self._transport) as client:
                response = client.post(f"{settings.mailpit_url}/api/v1/send", json=body)
        except httpx.TimeoutException as error:
            raise SendAmbiguous(type(error).__name__) from error
        except httpx.HTTPError as error:
            raise SendFailed(type(error).__name__) from error
        if response.status_code >= 300:
            raise SendFailed(f"mailpit {response.status_code}", permanent=_rejected(response.status_code), code=f"http_{response.status_code}")
        return str(response.json().get("ID", ""))


class ResendProvider:
    name = "resend"
    URL = "https://api.resend.com/emails"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def send(self, email: Email) -> str:
        settings = get_settings()
        headers = {"Authorization": f"Bearer {settings.resend_api_key}", "Idempotency-Key": email.idempotency_key}
        body = {"from": settings.email_from, "to": [email.to], "subject": email.subject, "text": email.text, "html": email.html}
        try:
            with httpx.Client(timeout=15, transport=self._transport) as client:
                response = client.post(self.URL, json=body, headers=headers)
        except (httpx.ReadTimeout, httpx.WriteTimeout) as error:
            raise SendAmbiguous(type(error).__name__) from error  # the request may have reached Resend
        except httpx.HTTPError as error:
            raise SendFailed(type(error).__name__) from error
        if response.status_code >= 300:
            raise SendFailed(f"resend {response.status_code}", permanent=_rejected(response.status_code), code=f"http_{response.status_code}")
        return str(response.json().get("id", ""))


class BrevoProvider:
    """Brevo (formerly Sendinblue) transactional email over HTTPS. Free plan: 300 emails a day.

    The sender address must be verified in Brevo (Senders, domains and IPs). The API key lives only in
    the server environment (`BREVO_API_KEY`).
    """

    name = "brevo"
    URL = "https://api.brevo.com/v3/smtp/email"

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def send(self, email: Email) -> str:
        settings = get_settings()
        body = {
            "sender": {"name": settings.email_from_name, "email": settings.email_from_address},
            "to": [{"email": email.to}],
            "subject": email.subject,
            "htmlContent": email.html,
            "textContent": email.text,
            "headers": {"X-Mailin-custom": email.idempotency_key},
        }
        headers = {"api-key": settings.brevo_api_key or "", "accept": "application/json"}
        try:
            with httpx.Client(timeout=15, transport=self._transport) as client:
                response = client.post(self.URL, json=body, headers=headers)
        except (httpx.ReadTimeout, httpx.WriteTimeout) as error:
            raise SendAmbiguous(type(error).__name__) from error
        except httpx.HTTPError as error:
            raise SendFailed(type(error).__name__) from error
        if response.status_code >= 300:
            try:
                reason = str(response.json().get("code") or response.status_code)
            except ValueError:
                reason = str(response.status_code)
            raise SendFailed(f"brevo {response.status_code} {reason}", permanent=_rejected(response.status_code), code=f"http_{response.status_code}")
        return str(response.json().get("messageId", ""))


class SmtpProvider:
    """Any SMTP server with STARTTLS (port 587) or TLS (port 465), e.g. Gmail with an app password."""

    name = "smtp"

    def send(self, email: Email) -> str:
        settings = get_settings()
        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = email.to
        message["Subject"] = email.subject
        message_id = make_msgid(idstring=email.idempotency_key, domain=settings.email_from_address.split("@")[-1])
        message["Message-ID"] = message_id
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        context = ssl.create_default_context()
        try:
            if settings.smtp_port == 465:
                server: smtplib.SMTP = smtplib.SMTP_SSL(settings.smtp_host or "", settings.smtp_port, timeout=20, context=context)
            else:
                server = smtplib.SMTP(settings.smtp_host or "", settings.smtp_port, timeout=20)
                server.starttls(context=context)
            with server:
                server.login(settings.smtp_username or "", settings.smtp_password or "")
                try:
                    server.send_message(message)
                except (TimeoutError, smtplib.SMTPServerDisconnected) as error:
                    raise SendAmbiguous(type(error).__name__) from error  # the server may already have the message
        except SendAmbiguous:
            raise
        except smtplib.SMTPRecipientsRefused as error:
            raise SendFailed(type(error).__name__, permanent=True, code="recipient_refused") from error
        except (smtplib.SMTPException, OSError) as error:
            raise SendFailed(type(error).__name__) from error
        return message_id


@dataclass
class RecordingProvider:
    name: str = "recording"
    sent: list[Email] = field(default_factory=list)
    fail_with: type[Exception] | None = None

    def send(self, email: Email) -> str:
        if self.fail_with is not None:
            raise self.fail_with("test")
        self.sent.append(email)
        return f"rec-{len(self.sent)}"


class GmailProvider:
    """Sends through the Gmail API (HTTPS, port 443) as the account that authorised the app.

    Railway blocks outbound SMTP below the Pro plan; HTTPS is not blocked. A refresh token (from
    ``python -m app.jobs.gmail_authorize``) is exchanged for a short-lived access token, cached until
    shortly before it expires. Scope: ``gmail.send`` only (cannot read the mailbox). Limit: about
    500 recipients a day for a personal account.
    """

    name = "gmail"
    TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - an endpoint, not a secret
    SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
    _lock = threading.Lock()
    _token: tuple[str, float] | None = None  # (access token, expiry as monotonic time), shared per process

    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport

    def _access_token(self, client: httpx.Client) -> str:
        with GmailProvider._lock:
            if GmailProvider._token and GmailProvider._token[1] > time.monotonic() + 60:
                return GmailProvider._token[0]
            settings = get_settings()
            response = client.post(
                self.TOKEN_URL,
                data={
                    "client_id": settings.gmail_client_id or "",
                    "client_secret": settings.gmail_client_secret or "",
                    "refresh_token": settings.gmail_refresh_token or "",
                    "grant_type": "refresh_token",
                },
            )
            if response.status_code != 200:
                # invalid_grant means the token was revoked or expired: fix the configuration, then the retry works.
                raise SendFailed(f"gmail token {response.status_code}", code="gmail_token")
            body = response.json()
            GmailProvider._token = (str(body["access_token"]), time.monotonic() + float(body.get("expires_in", 3600)))
            return GmailProvider._token[0]

    def send(self, email: Email) -> str:
        settings = get_settings()
        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = email.to
        message["Subject"] = email.subject
        message["Message-ID"] = make_msgid(domain="abhijatri")
        message["X-Abhijatri-Key"] = email.idempotency_key
        message.set_content(email.text)
        message.add_alternative(email.html, subtype="html")
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
        try:
            with httpx.Client(timeout=15, transport=self._transport) as client:
                token = self._access_token(client)
                response = client.post(self.SEND_URL, json={"raw": raw}, headers={"Authorization": f"Bearer {token}"})
        except (httpx.ReadTimeout, httpx.WriteTimeout) as error:
            raise SendAmbiguous(type(error).__name__) from error  # the request may have reached Gmail
        except httpx.HTTPError as error:
            raise SendFailed(type(error).__name__) from error
        if response.status_code == 401:
            GmailProvider._token = None  # the access token expired early: the retry fetches a new one
            raise SendFailed("gmail 401", code="http_401")
        if response.status_code >= 300:
            raise SendFailed(f"gmail {response.status_code}", permanent=_rejected(response.status_code), code=f"http_{response.status_code}")
        return str(response.json().get("id", ""))


def get_provider() -> Provider | None:
    provider = get_settings().email_provider
    if provider == "mailpit":
        return MailpitProvider()
    if provider == "resend":
        return ResendProvider()
    if provider == "smtp":
        return SmtpProvider()
    if provider == "brevo":
        return BrevoProvider()
    if provider == "gmail":
        return GmailProvider()
    return None
