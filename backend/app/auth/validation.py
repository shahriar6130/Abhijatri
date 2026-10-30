"""Input rules for sign-up and password changes (Platform Foundation 8.5, Review.md display names)."""

import re
import unicodedata

from app.errors import ApiError

EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,63}")
MIN_PASSWORD = 10
MAX_PASSWORD = 128
DISPLAY_NAME_MAX = 80

# Names that look official. Compared after case folding and confusable folding.
RESERVED_NAMES = frozenset(
    {"admin", "administrator", "moderator", "abhijatri", "support", "staff", "system", "official", "root", "team"}
)
# "1" reads as either "i" or "l"; both readings are tried.
_CONFUSABLE_I = str.maketrans({"0": "o", "1": "i", "!": "i", "3": "e", "4": "a", "5": "s", "7": "t", "$": "s", "@": "a"})
_CONFUSABLE_L = str.maketrans({"0": "o", "1": "l", "!": "i", "3": "e", "4": "a", "5": "s", "7": "t", "$": "s", "@": "a"})


def normalize_email(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().lower()


def normalize_display_name(value: str) -> str:
    return unicodedata.normalize("NFC", value).strip()


def public_author_name(name: str | None) -> str | None:
    """The name shown beside a published review. An email address is never public, so a name that
    contains "@" (an older account whose name was its sign-in email) is withheld and the page says "Member"."""
    return None if name is None or "@" in name else name


def _folds(value: str) -> set[str]:
    base = unicodedata.normalize("NFKC", value).casefold()
    return {re.sub(r"[^a-zঀ-৿]", "", base.translate(table)) for table in (_CONFUSABLE_I, _CONFUSABLE_L)}


def _only_reserved_words(folded: str) -> bool:
    """True when the whole name is made of reserved words, e.g. "abhijatriteam"."""
    remaining = folded
    changed = True
    while remaining and changed:
        changed = False
        for word in sorted(RESERVED_NAMES, key=len, reverse=True):
            if remaining.startswith(word):
                remaining, changed = remaining[len(word) :], True
                break
    return not remaining


def is_reserved(name: str) -> bool:
    for folded in _folds(name):
        if not folded:
            continue
        if _only_reserved_words(folded):
            return True
        if any(folded.startswith(word) and len(folded) <= len(word) + 2 for word in RESERVED_NAMES):
            return True
    return False


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return "TOO_SHORT"
    if len(password) > MAX_PASSWORD:
        return "TOO_LONG"
    if not (re.search(r"[A-Za-z]", password) and re.search(r"\d", password)):
        return "WEAK"
    return None


def validate_registration(email: str, password: str, display_name: str) -> None:
    errors: list[dict[str, str]] = []
    if not EMAIL.fullmatch(email):
        errors.append({"field": "email", "code": "INVALID_VALUE"})
    if (problem := password_problem(password)) is not None:
        errors.append({"field": "password", "code": problem})
    if not 1 <= len(display_name) <= DISPLAY_NAME_MAX:
        errors.append({"field": "display_name", "code": "TOO_SHORT" if not display_name else "TOO_LONG"})
    elif "@" in display_name:  # a name that is an email address would be published beside the review
        errors.append({"field": "display_name", "code": "INVALID_VALUE"})
    if errors:
        raise ApiError("VALIDATION_FAILED", field_errors=errors)
    if is_reserved(display_name):
        raise ApiError("RESERVED_DISPLAY_NAME")


def validate_new_password(password: str) -> None:
    if (problem := password_problem(password)) is not None:
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "password", "code": problem}])
