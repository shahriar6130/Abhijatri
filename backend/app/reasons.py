"""The reason codes staff may give with a decision (Moderation spec P-06).

One server list, served by ``GET /admin/reason-codes``, so the staff app stops hard-coding its own. A group is
*strict* when the server refuses any code outside it (review decisions, report resolutions, reopen, hide pending
decision). The other groups are guidance: the apps offer them, free text is still accepted, because those forms
take the moderator's own words (enforcement and sanctions, verification notes).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Reason:
    code: str
    bn: str
    en: str


# Existing codes keep their spelling so decisions already in the database still read well.
GROUPS: dict[str, tuple[bool, tuple[Reason, ...]]] = {
    "publish": (True, (Reason("meets-policy", "নীতিমালা মেনে চলে", "Meets the policy"),)),
    "reject": (
        True,
        (
            Reason("spam", "স্প্যাম", "Spam"),
            Reason("offensive", "আপত্তিকর ভাষা", "Offensive language"),
            Reason("off-topic", "বিষয়বহির্ভূত", "Off topic"),
            Reason("privacy", "ব্যক্তিগত তথ্য", "Personal information"),
        ),
    ),
    "hide": (
        True,
        (
            Reason("reported-spam", "রিপোর্ট করা স্প্যাম", "Reported spam"),
            Reason("policy-violation", "নীতিমালা লঙ্ঘন", "Policy violation"),
            Reason("legal-request", "আইনি অনুরোধ", "Legal request"),
            Reason("privacy-pending", "গোপনীয়তার অভিযোগ, সিদ্ধান্তের অপেক্ষায়", "Privacy complaint, pending a decision"),
            Reason("safety-pending", "নিরাপত্তার অভিযোগ, সিদ্ধান্তের অপেক্ষায়", "Safety complaint, pending a decision"),
        ),
    ),
    "restore": (True, (Reason("hidden-in-error", "ভুলে লুকানো হয়েছিল", "Hidden in error"), Reason("complaint-resolved", "অভিযোগের নিষ্পত্তি হয়েছে", "Complaint resolved"))),
    "request_changes": (
        True,
        (
            Reason("remove-personal-info", "ব্যক্তিগত তথ্য সরান", "Remove personal information"),
            Reason("add-detail", "আরও বিস্তারিত লিখুন", "Add more detail"),
            Reason("fix-language", "ভাষা বা বানান ঠিক করুন", "Fix language or spelling"),
            Reason("wrong-destination", "গন্তব্য বা মাস ঠিক করুন", "Check the destination or month"),
        ),
    ),
    "reopen": (
        True,
        (
            Reason("rejected-in-error", "ভুলে বাতিল হয়েছিল", "Rejected in error"),
            Reason("author-corrected", "লেখক সংশোধন করেছেন", "Author corrected the problem"),
        ),
    ),
    "report_resolution": (
        True,
        (
            Reason("looking", "পর্যালোচনা শুরু", "Start review"),
            Reason("report-confirmed", "ব্যবস্থা নেওয়া হয়েছে", "Action taken"),
            Reason("report-dismissed", "প্রত্যাখ্যাত", "Dismissed"),
            Reason("duplicate-report", "একই অভিযোগ আগেই নিষ্পত্তি হয়েছে", "Already handled"),
            Reason("ownership-verified", "মালিকানা যাচাই হয়েছে", "Ownership verified"),
            Reason("ownership-not-verified", "মালিকানা যাচাই হয়নি", "Ownership could not be verified"),
        ),
    ),
    # Guidance only: the forms for these take the moderator's own words.
    "enforcement": (False, (Reason("policy-violation", "নীতিমালা লঙ্ঘন", "Policy violation"), Reason("legal-request", "আইনি অনুরোধ", "Legal request"))),
}

# Which group a review decision uses.
DECISION_GROUP = {
    "PUBLISH": "publish",
    "REJECT": "reject",
    "HIDE": "hide",
    "RESTORE": "restore",
    "REQUEST_CHANGES": "request_changes",
    "REOPEN": "reopen",
}


def codes(group: str) -> frozenset[str]:
    return frozenset(reason.code for reason in GROUPS[group][1])


def is_valid(group: str, code: str) -> bool:
    strict, _ = GROUPS[group]
    return code in codes(group) if strict else True


def catalogue() -> dict[str, object]:
    return {
        group: {"strict": strict, "reasons": [{"code": r.code, "bn": r.bn, "en": r.en} for r in reasons]}
        for group, (strict, reasons) in GROUPS.items()
    }
