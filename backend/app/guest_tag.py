"""The guest tag: a random-looking public label per browser (Guest-Identity-and-Visits 3.1).

``guest_tag = CrockfordBase32(SHA-256("abhijatri:guest-tag:v1\\n" + guest_scope_secret))[first 50 bits]``

The browser computes the same value with WebCrypto to show its badge offline; the server computes
it from the scope secret in ``POST /reviews/guest`` so a client can never post under another tag.
A plain hash is deliberate: the secret has 384 random bits, and the tag grants no authority.
"""

import hashlib
import re

PREFIX = "abhijatri:guest-tag:v1\n"
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
BITS = 50
STORED_LENGTH = 10
DISPLAY_PATTERN = re.compile(r"\b[0-9A-HJKMNP-TV-Z]{5}-[0-9A-HJKMNP-TV-Z]{5}\b")


def stored_guest_tag(guest_scope_secret: str) -> str:
    """The ten-character tag as stored in ``reviews.guest_tag`` (no dash)."""
    digest = hashlib.sha256((PREFIX + guest_scope_secret).encode("utf-8")).digest()
    value = int.from_bytes(digest[:7], "big") >> (56 - BITS)
    return "".join(
        ALPHABET[(value >> (5 * (STORED_LENGTH - 1 - index))) & 31] for index in range(STORED_LENGTH)
    )


def display_guest_tag(stored: str | None) -> str | None:
    """``1C669J0TDY`` -> ``1C669-J0TDY``; ``None`` for reviews written before the tag existed."""
    if not stored:
        return None
    return f"{stored[:5]}-{stored[5:]}"


def guest_tag(guest_scope_secret: str) -> str:
    return display_guest_tag(stored_guest_tag(guest_scope_secret)) or ""
