"""Which outbox events notify whom, and what they say (Moderation spec 11).

Every message exists in Bangla and English. "Critical" marks an account decision: it is emailed at once
and kept 24 months; everything else goes into the daily digest and is kept 90 days. Staff recipients
captured on the event are re-checked against their current role before anything is disclosed.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OutboxEvent, Report, Review, UserRole


@dataclass(frozen=True)
class Message:
    recipient: uuid.UUID
    kind: str
    critical: bool
    title_bn: str
    title_en: str
    body_bn: str
    body_en: str
    link: str | None = None
    appeal_id: uuid.UUID | None = None


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except ValueError:
        return None


def _current_staff(session: Session, ids: list[str]) -> list[uuid.UUID]:
    wanted = [i for i in (_uuid(v) for v in ids) if i]
    if not wanted:
        return []
    return list(session.scalars(select(UserRole.user_id).where(UserRole.user_id.in_(wanted), UserRole.revoked_at.is_(None))))


REVIEW_TEXT = {
    "PUBLISHED": (False, "আপনার রিভিউ প্রকাশিত হয়েছে", "Your review is published", "মডারেটর আপনার রিভিউ প্রকাশ করেছেন।", "A moderator published your review."),
    "REJECTED": (True, "আপনার রিভিউ প্রকাশ করা হয়নি", "Your review was not published", "রিভিউটি নীতিমালার সাথে মেলেনি। ৩০ দিনের মধ্যে আপিল করতে পারবেন।", "The review did not meet the policy. You can appeal within 30 days."),
    "HIDDEN": (True, "আপনার রিভিউ লুকানো হয়েছে", "Your review was hidden", "রিভিউটি এখন জনসমক্ষে দেখা যাচ্ছে না। ৩০ দিনের মধ্যে আপিল করতে পারবেন।", "The review is no longer public. You can appeal within 30 days."),
}


def messages_for(session: Session, event: OutboxEvent) -> list[Message]:
    p, topic = event.payload, event.topic
    out: list[Message] = []

    if topic == "review.state_changed":
        review = session.get(Review, _uuid(p.get("review_id")))
        status = str(p.get("status"))
        if review is not None and review.author_user_id and status in REVIEW_TEXT:
            critical, tbn, ten, bbn, ben = REVIEW_TEXT[status]
            out.append(Message(review.author_user_id, f"review.{status.lower()}", critical, tbn, ten, bbn, ben, f"/destinations/{review.destination_id}"))

    elif topic == "report.state_changed" and p.get("state") in ("actioned", "dismissed"):
        report = session.get(Report, _uuid(p.get("report_id")))
        if report is not None:
            done = p["state"] == "actioned"
            out.append(Message(
                report.reporter_user_id, f"report.{p['state']}", False,
                "আপনার রিপোর্ট পর্যালোচনা হয়েছে", "Your report was reviewed",
                "ধন্যবাদ। মডারেটর ব্যবস্থা নিয়েছেন।" if done else "ধন্যবাদ। মডারেটর কোনো সমস্যা পাননি।",
                "Thank you. A moderator took action." if done else "Thank you. A moderator found no problem.",
            ))

    elif topic == "verification.submitted":
        for staff in _current_staff(session, p.get("staff_recipients", [])):
            out.append(Message(staff, "staff.verification_submitted", False, "নতুন যাচাই আবেদন", "New verification request", "সারিতে একটি নতুন যাচাই আবেদন আছে।", "A new verification request is in the queue."))

    elif topic == "verification.state_changed":
        applicant, state = _uuid(p.get("applicant_id")), p.get("state")
        texts = {
            "approved": (True, "আপনি এখন যাচাইকৃত সদস্য", "You are now a Verified Member", "অভিনন্দন! আপনার রিভিউ এখন কমিউনিটি রেটিংয়ে গণনা হবে।", "Congratulations! Your reviews now count towards the Community Rating."),
            "rejected": (True, "যাচাই আবেদন অনুমোদিত হয়নি", "Verification was not approved", "৩০ দিনের মধ্যে আপিল করতে পারবেন।", "You can appeal within 30 days."),
            "needs_clarification": (False, "যাচাইয়ের জন্য আরও তথ্য দরকার", "More information is needed", "মডারেটর আপনার আবেদনে প্রশ্ন রেখেছেন। উত্তর দিন।", "A moderator has a question about your request. Please answer it."),
        }
        if applicant and state in texts:
            critical, tbn, ten, bbn, ben = texts[state]
            out.append(Message(applicant, f"verification.{state}", critical, tbn, ten, bbn, ben, "/account/verification"))

    elif topic == "appeal.received":
        appeal_id, appellant = _uuid(p.get("appeal_id")), _uuid(p.get("appellant_id"))
        deadline = str(p.get("deadline_at", ""))[:10]
        reference = str(appeal_id)[:8]
        if appellant:
            out.append(Message(appellant, "appeal.received", True, "আপিল গ্রহণ করা হয়েছে", "Your appeal was received",
                               f"আপিল নম্বর {reference}। একজন স্বাধীন মডারেটর এটি দেখবেন। শেষ তারিখ {deadline}।",
                               f"Case reference {reference}. An independent moderator will review it. Deadline {deadline}.",
                               "/account/appeals", appeal_id))
        for staff in _current_staff(session, p.get("staff_recipients", [])):
            out.append(Message(staff, "staff.appeal_received", False, "নতুন আপিল", "New appeal", f"আপিল {reference} সারিতে আছে।", f"Appeal {reference} is in the queue.", None, appeal_id))

    elif topic == "appeal.decided":
        appellant, upheld = _uuid(p.get("appellant_id")), p.get("outcome") == "upheld"
        reference = str(p.get("appeal_id"))[:8]
        if appellant:
            out.append(Message(appellant, "appeal.decided", True, "আপিলের সিদ্ধান্ত", "Your appeal was decided",
                               f"আপিল {reference}: মূল সিদ্ধান্ত বহাল।" if upheld else f"আপিল {reference}: মূল সিদ্ধান্ত বাতিল করা হয়েছে।",
                               f"Appeal {reference}: the original decision stands." if upheld else f"Appeal {reference}: the original decision was reversed.",
                               "/account/appeals", _uuid(p.get("appeal_id"))))

    elif topic == "enforcement.opened":
        subject = _uuid(p.get("subject_id"))
        if subject:
            out.append(Message(subject, "enforcement.opened", True, "আপনার কনটেন্ট বা অ্যাকাউন্টে ব্যবস্থা", "Action on your content or account",
                               "নীতিমালা অনুযায়ী ব্যবস্থা নেওয়া হয়েছে। ৩০ দিনের মধ্যে আপিল করতে পারবেন।", "Action was taken under the policy. You can appeal within 30 days.", "/account/appeals"))
        for staff in _current_staff(session, p.get("staff_recipients", [])):
            out.append(Message(staff, "staff.emergency_takedown", True, "জরুরি টেকডাউন: ২৪ ঘণ্টার মধ্যে পর্যালোচনা", "Emergency takedown: review within 24 hours",
                               "একটি জরুরি টেকডাউন সুপারঅ্যাডমিনের পর্যালোচনার অপেক্ষায়।", "An emergency takedown is waiting for a superadmin review."))

    elif topic in ("sanction.created", "sanction.ended"):
        user = _uuid(p.get("user_id"))
        if user:
            created = topic == "sanction.created"
            out.append(Message(user, topic, created, "অ্যাকাউন্টে সীমাবদ্ধতা" if created else "সীমাবদ্ধতা শেষ", "Account restriction" if created else "Restriction ended",
                               "আপনার অ্যাকাউন্টে একটি সীমাবদ্ধতা যোগ হয়েছে।" if created else "আপনার অ্যাকাউন্টের সীমাবদ্ধতা শেষ হয়েছে।",
                               "A restriction was placed on your account." if created else "The restriction on your account has ended.", "/account/appeals"))
    return out
