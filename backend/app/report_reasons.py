"""Report reasons and how serious each one is (Review.md 5.4; Gantt R11).

One list serves the API validation, the database check, the queue priority, the rating rule and the labels the
apps show, so they cannot disagree. Nothing here imports the rest of the application.
"""

# Review.md 5.4: spam, harassment, false information, private information, impersonation, safety misinformation,
# copyright concern, conflict of interest, other.
REASONS: tuple[str, ...] = (
    "spam",
    "harassment",
    "false_information",
    "privacy",
    "impersonation",
    "safety_misinformation",
    "copyright",
    "conflict_of_interest",
    "other",
)
# Only the anonymous lost-receipt endpoint creates this one; a member cannot pick it.
REMOVAL_REQUEST = "removal_request"
ALL_STORED = (*REASONS, REMOVAL_REQUEST)

# Older clients sent "offensive"; it is stored as "harassment".
LEGACY_ALIASES = {"offensive": "harassment"}

# An open report with one of these reasons takes the review out of the rating until it is closed (Review.md 6.1).
RATING_SUSPENDING = frozenset({"privacy", "safety_misinformation", "conflict_of_interest"})

# These reach the queue first and use the escalated notice-and-review wording (Review.md 5.3).
HIGH_PRIORITY = frozenset({"privacy", "safety_misinformation", "impersonation", "copyright", "harassment", REMOVAL_REQUEST})

LABELS: dict[str, tuple[str, str]] = {
    "spam": ("স্প্যাম", "Spam"),
    "harassment": ("হয়রানি বা আপত্তিকর ভাষা", "Harassment or offensive language"),
    "false_information": ("ভুল তথ্য", "False information"),
    "privacy": ("ব্যক্তিগত তথ্য", "Private information"),
    "impersonation": ("ছদ্মবেশ", "Impersonation"),
    "safety_misinformation": ("নিরাপত্তা-সংক্রান্ত ভুল তথ্য", "Safety misinformation"),
    "copyright": ("কপিরাইট উদ্বেগ", "Copyright concern"),
    "conflict_of_interest": ("স্বার্থের দ্বন্দ্ব", "Conflict of interest"),
    "other": ("অন্যান্য", "Other"),
    REMOVAL_REQUEST: ("অপসারণের অনুরোধ", "Removal request"),
}


def normalise(code: str) -> str | None:
    """The stored code for what a client sent, or None when it is not a reason a member may report."""
    mapped = LEGACY_ALIASES.get(code, code)
    return mapped if mapped in REASONS else None


def priority(code: str) -> int:
    """Queue priority: 2 for serious reasons, 1 otherwise (higher is shown first)."""
    return 2 if code in HIGH_PRIORITY else 1
