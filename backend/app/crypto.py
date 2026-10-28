"""Keyed digests for receipts, Guest scopes and network addresses (Platform Foundation 13.2, 13.4).

Every digest is HMAC-SHA-256 over a fixed context label plus the value, under a versioned key.
The labels make a digest from one credential class unusable as another, and the key id is
stored next to the digest so keys can rotate without invalidating stored credentials.
"""

import base64
import binascii
import hashlib
import hmac
import re

from app.config import get_settings

RECEIPT_LABEL = "abhijatri:review-receipt:v1"
GUEST_SCOPE_LABEL = "abhijatri:guest-scope:v1"
NETWORK_LABEL = "abhijatri:network:v1"
EMAIL_DESTINATION_LABEL = "abhijatri:email-destination:v1"  # notification suppressions and delivery refs
LEGACY_KEY_ID = "legacy"

RECEIPT_PREFIX = "abr1_"
_RECEIPT_BODY = re.compile(r"[A-Za-z0-9_-]{43}")
_MIN_DISTINCT_BYTES = 9  # 32 random bytes essentially never have fewer than this many distinct values


def current_key_id() -> str:
    return get_settings().receipt_key_current


def digest(label: str, key_id: str, value: str) -> bytes:
    key = get_settings().hmac_keyring[key_id].encode("utf-8")
    message = label.encode("ascii") + b"\x00" + value.encode("utf-8")
    return hmac.new(key, message, hashlib.sha256).digest()


def candidate_digests(label: str, value: str) -> list[tuple[str, bytes]]:
    """Digests of ``value`` under every retained key, current key first."""
    ring = get_settings().hmac_keyring
    current = current_key_id()
    ordered = [current, *sorted(key_id for key_id in ring if key_id != current)]
    return [(key_id, digest(label, key_id, value)) for key_id in ordered]


def receipt_format_problem(value: str) -> str | None:
    """Return why ``value`` is not an acceptable receipt, or None when it is.

    The server cannot prove the client used a secure generator, so it enforces the exact
    format and rejects values that are demonstrably not 32 random bytes.
    """
    if not value.startswith(RECEIPT_PREFIX):
        return "prefix"
    body = value[len(RECEIPT_PREFIX) :]
    if not _RECEIPT_BODY.fullmatch(body):
        return "length_or_alphabet"
    try:
        raw = base64.urlsafe_b64decode(body + "=")
    except (binascii.Error, ValueError):
        return "encoding"
    if len(raw) != 32 or base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=") != body:
        return "encoding"
    if len(set(raw)) < _MIN_DISTINCT_BYTES:
        return "weak"
    return None
