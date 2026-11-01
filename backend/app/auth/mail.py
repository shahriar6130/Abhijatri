"""Verification and password-reset emails sent by this API (AUTH_EMAIL_DELIVERY=app).

Supabase Auth only issues the one-time token (``admin/generate_link`` sends nothing); the email goes
out through the configured provider (Brevo, SMTP, Resend or the local Mailpit inbox). Sending runs
after the response is returned, so a known and an unknown address answer in the same time. The token
is never logged.
"""

import hashlib
import logging
from datetime import UTC, datetime
from html import escape
from urllib.parse import quote

from app.config import get_settings
from app.notify.providers import Email, SendAmbiguous, SendFailed, get_provider

logger = logging.getLogger(__name__)


def _link(path: str, token_hash: str, kind: str) -> str:
    return f"{get_settings().frontend_base_url.rstrip('/')}/{path}?token_hash={quote(token_hash)}&type={kind}"


def _email(to: str, subject: str, heading_en: str, heading_bn: str, line_en: str, line_bn: str, link: str, footer_en: str, footer_bn: str, key: str) -> Email:
    text = f"{heading_en}\n{line_en}\n{link}\n{footer_en}\n\n{heading_bn}\n{line_bn}\n{footer_bn}"
    html = (
        f'<div style="font-family:Arial,sans-serif;max-width:520px">'
        f"<h2>{escape(heading_en)}</h2><p>{escape(line_en)}</p>"
        f'<p><a href="{escape(link)}" style="display:inline-block;padding:12px 20px;background:#1b4d2b;color:#fff;border-radius:999px;text-decoration:none">{escape(heading_en)}</a></p>'
        f'<p style="font-size:12px;color:#666">{escape(link)}</p><p style="font-size:12px;color:#666">{escape(footer_en)}</p>'
        f"<hr><h2>{escape(heading_bn)}</h2><p>{escape(line_bn)}</p><p style=\"font-size:12px;color:#666\">{escape(footer_bn)}</p></div>"
    )
    return Email(to=to, subject=subject, text=text, html=html, idempotency_key=key)


def verification_email(to: str, token_hash: str, name: str | None) -> Email:
    greeting = f"Hello {name}," if name else "Hello,"
    return _email(
        to,
        "Confirm your Abhijatri account / আপনার অভিযাত্রী অ্যাকাউন্ট নিশ্চিত করুন",
        "Confirm your email", "ইমেইল নিশ্চিত করুন",
        f"{greeting} open this link to verify your email address. It works for 24 hours.",
        "আপনার ইমেইল যাচাই করতে লিংকটি খুলুন। এটি ২৪ ঘণ্টা কার্যকর।",
        _link("verify-email", token_hash, "signup"),
        "If you did not create an account, ignore this email.", "আপনি অ্যাকাউন্ট না খুললে এই ইমেইলটি উপেক্ষা করুন।",
        f"verify-{token_hash[:16]}",
    )


def reset_email(to: str, token_hash: str) -> Email:
    return _email(
        to,
        "Reset your Abhijatri password / পাসওয়ার্ড রিসেট করুন",
        "Choose a new password", "নতুন পাসওয়ার্ড দিন",
        "Open this link to choose a new password. It works for 1 hour.",
        "নতুন পাসওয়ার্ড দিতে লিংকটি খুলুন। এটি ১ ঘণ্টা কার্যকর।",
        _link("reset-password", token_hash, "recovery"),
        "If you did not ask for this, ignore this email; your password is unchanged.", "আপনি না চাইলে উপেক্ষা করুন; পাসওয়ার্ড বদলায়নি।",
        f"reset-{token_hash[:16]}",
    )


def existing_account_email(to: str) -> Email:
    """Someone signed up with an address that already has an account. Only the inbox owner reads this, so it tells
    them without telling the person at the form (who sees the usual "check your email")."""
    base = get_settings().frontend_base_url.rstrip("/")
    return _email(
        to,
        "You already have an Abhijatri account / আপনার ইতিমধ্যে একটি অভিযাত্রী অ্যাকাউন্ট আছে",
        "You already have an account", "আপনার ইতিমধ্যে অ্যাকাউন্ট আছে",
        "Someone, probably you, tried to sign up with this email address, which already has an account. Sign in instead. "
        f"If you forgot your password, reset it here: {base}/forgot-password",
        "এই ইমেইলে ইতিমধ্যে একটি অ্যাকাউন্ট আছে, তাই নতুন করে খোলা যায়নি। সাইন ইন করুন; "
        f"পাসওয়ার্ড ভুলে গেলে এখানে রিসেট করুন: {base}/forgot-password",
        f"{base}/login",
        "If this was not you, you can ignore this email; nothing changed on your account.",
        "আপনি না করলে এই ইমেইলটি উপেক্ষা করুন; আপনার অ্যাকাউন্টে কিছু বদলায়নি।",
        f"existing-{hashlib.sha256(to.encode()).hexdigest()[:16]}-{datetime.now(UTC).date().isoformat()}",
    )


def deliver(email: Email) -> None:
    """Runs after the response (FastAPI background task). Failures are logged without the token or address."""
    provider = get_provider()
    if provider is None:
        logger.warning("account email not sent: EMAIL_PROVIDER is none")
        return
    try:
        provider.send(email)
    except SendAmbiguous:
        logger.warning("account email may not have been delivered (%s)", provider.name)
    except SendFailed as error:
        logger.warning("account email failed via %s: %s", provider.name, error)
