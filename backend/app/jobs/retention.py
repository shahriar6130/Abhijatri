"""Retention and expiry (Moderation spec 10, 7.3).

    python -m app.jobs.retention

- Evidence files of decided verification cases are deleted after `purge_after` (24 hours after approval,
  30 days after rejection or withdrawal); a rejected or withdrawn case row goes with them.
- Notifications: standard ones after 90 days, critical ones after 24 months.
- Sanctions past their end time expire, with a system audit event.
- A rejected review's title, body and media are removed 30 days after the rejection unless an appeal is open;
  `reviews.purged_at` records it and the review can no longer be reopened (Moderation spec P-03).
- The contact left on an anonymous report or removal request is erased 30 days after the report is closed.

Nothing tied to an open appeal is deleted. `purge_after` only makes a row a candidate: each case is
locked and the open-appeal check repeated inside that lock immediately before deletion, and creating
an appeal on a verification case locks the same row, so an appeal cannot slip in between.
"""

import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import media
from app.admin import audit
from app.admin.cases import reverse_sanction
from app.db import SessionLocal
from app.models import (
    Appeal,
    ModerationActionRecord,
    ModerationDecision,
    Notification,
    OutboxEvent,
    Report,
    Review,
    ReviewMedia,
    ReviewRevision,
    ReviewStatus,
    Sanction,
    VerificationCase,
    VerificationEvidence,
)
from app.storage import MEDIA_BUCKET, StorageClient, StorageUnavailable, get_storage

logger = logging.getLogger(__name__)

OPEN_APPEAL = ("received", "in_review")
STANDARD_DAYS = 90
CRITICAL_DAYS = 730
OUTBOX_DAYS = 30


def purge_verification(sessions: Callable[[], Session], storage: StorageClient, now: datetime) -> dict[str, int]:
    evidence_files = cases_deleted = 0
    with sessions() as session:
        candidates = list(
            session.scalars(
                select(VerificationCase.id).where(
                    VerificationCase.purge_after < now, VerificationCase.state.in_(("approved", "rejected", "withdrawn"))
                )
            )
        )
    for case_id in candidates:
        with sessions() as session:
            case = session.scalar(select(VerificationCase).where(VerificationCase.id == case_id).with_for_update(skip_locked=True))
            if case is None or case.purge_after is None or case.purge_after >= now:
                continue
            if session.scalar(select(Appeal.id).where(Appeal.verification_case_id == case.id, Appeal.state.in_(OPEN_APPEAL))):
                continue  # preserved while the appeal is open
            files = list(session.scalars(select(VerificationEvidence).where(VerificationEvidence.case_id == case.id, VerificationEvidence.status != "deleted")))
            try:
                storage.delete([f.object_key for f in files])
            except StorageUnavailable:
                logger.warning("evidence purge postponed: storage unavailable")
                continue
            for item in files:
                item.status, item.deleted_at = "deleted", now
            evidence_files += len(files)
            if case.state in ("rejected", "withdrawn"):
                audit.record(session, actor=None, action="retention.case_purged", target_type="verification_case", target_id=case.id, metadata={"files": len(files)})
                session.delete(case)
                cases_deleted += 1
            else:
                audit.record(session, actor=None, action="retention.evidence_purged", target_type="verification_case", target_id=case.id, metadata={"files": len(files)})
                case.purge_after = None
            session.commit()
    return {"evidence_files": evidence_files, "cases": cases_deleted}


REJECTED_REVIEW_DAYS = 30
CONTACT_DAYS = 30
REMOVED_TEXT = "[removed]"


def purge_rejected_reviews(sessions: Callable[[], Session], storage: StorageClient, now: datetime) -> int:
    """Redact rejected reviews 30 days after the rejection (Moderation spec P-03). Each review is locked and its
    open-appeal check repeated inside the lock, so a reopen or an appeal filed meanwhile wins over the purge."""
    cutoff = now - timedelta(days=REJECTED_REVIEW_DAYS)
    with sessions() as session:
        rejected_at = (
            select(ModerationActionRecord.review_id, func.max(ModerationActionRecord.created_at).label("at"))
            .where(ModerationActionRecord.decision == ModerationDecision.REJECT)
            .group_by(ModerationActionRecord.review_id)
            .subquery()
        )
        candidates = list(
            session.scalars(
                select(Review.id)
                .join(rejected_at, rejected_at.c.review_id == Review.id)
                .where(Review.status == ReviewStatus.REJECTED, Review.purged_at.is_(None), rejected_at.c.at < cutoff)
            )
        )
    purged = 0
    for review_id in candidates:
        with sessions() as session:
            review = session.scalar(select(Review).where(Review.id == review_id).with_for_update(skip_locked=True))
            if review is None or review.status != ReviewStatus.REJECTED or review.purged_at is not None:
                continue  # reopened, or purged by another run
            actions = session.scalars(
                select(ModerationActionRecord.id).where(ModerationActionRecord.review_id == review.id, ModerationActionRecord.decision == ModerationDecision.REJECT)
            ).all()
            if session.scalar(select(Appeal.id).where(Appeal.moderation_action_id.in_(actions), Appeal.state.in_(OPEN_APPEAL))):
                continue  # preserved while the appeal is open
            files = list(session.scalars(select(ReviewMedia).where(ReviewMedia.review_id == review.id, ReviewMedia.state != "removed")))
            keys = [k for item in files for k in (item.quarantine_key, item.processed_key) if k]
            try:
                if keys:
                    storage.delete(keys, MEDIA_BUCKET)
            except StorageUnavailable:
                logger.warning("rejected-review media purge postponed: storage unavailable")
                continue
            for item in files:
                item.state = "removed"
            for revision in session.scalars(select(ReviewRevision).where(ReviewRevision.review_id == review.id)):
                revision.title, revision.body = REMOVED_TEXT, REMOVED_TEXT
            review.purged_at = now
            audit.record(session, actor=None, action="review.purged", target_type="review", target_id=review.id, metadata={"media": len(files)})
            session.commit()
            purged += 1
    return purged


def erase_report_contacts(sessions: Callable[[], Session], now: datetime) -> int:
    """The contact on an anonymous report is kept only for a follow-up: erased 30 days after the report is closed."""
    with sessions() as session:
        reports = list(
            session.scalars(
                select(Report).where(
                    Report.contact.is_not(None), Report.state.in_(("actioned", "dismissed")),
                    Report.resolved_at < now - timedelta(days=CONTACT_DAYS),
                ).with_for_update(skip_locked=True)
            )
        )
        for report in reports:
            report.contact = None
            audit.record(session, actor=None, action="retention.contact_erased", target_type="report", target_id=report.id)
        session.commit()
        return len(reports)


def purge_notifications(sessions: Callable[[], Session], now: datetime) -> int:
    """Delete notifications past their own ``expires_at`` (90 days, critical 24 months), except those
    linked to an appeal that is still open; that check is part of the same DELETE (spec 6.2)."""
    with sessions() as session:
        open_appeals = select(Appeal.id).where(Appeal.state.in_(OPEN_APPEAL))
        result = session.execute(
            delete(Notification).where(
                Notification.expires_at < now,
                (Notification.appeal_id.is_(None)) | (Notification.appeal_id.not_in(open_appeals)),
            )
        )
        session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


def purge_outbox(sessions: Callable[[], Session], now: datetime) -> int:
    """Processed or dead-lettered events older than 30 days that no remaining notification points to."""
    with sessions() as session:
        result = session.execute(
            delete(OutboxEvent).where(
                OutboxEvent.status.in_(("processed", "dead_letter")),
                OutboxEvent.created_at < now - timedelta(days=OUTBOX_DAYS),
                ~select(Notification.id).where(Notification.event_id == OutboxEvent.id).exists(),
            )
        )
        session.commit()
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


def expire_sanctions(sessions: Callable[[], Session], now: datetime) -> int:
    expired = 0
    with sessions() as session:
        for sanction in session.scalars(select(Sanction).where(Sanction.state == "active", Sanction.ends_at < now).with_for_update(skip_locked=True)):
            reverse_sanction(session, None, sanction, expired=True)
            expired += 1
        session.commit()
    return expired


def purge_review_media(sessions: Callable[[], Session], storage: StorageClient, now: datetime) -> int:
    """Uploads never completed within 24 hours (Review.md 8)."""
    with sessions() as session:
        try:
            purged = media.purge_abandoned(session, storage, now)
            session.commit()
        except StorageUnavailable:
            session.rollback()
            logger.warning("abandoned review media kept until storage answers")
            return 0
    return purged


def run(sessions: Callable[[], Session] = SessionLocal, storage: StorageClient | None = None, now: datetime | None = None) -> dict[str, int]:
    moment = now or datetime.now(UTC)
    store = storage or get_storage()
    result = purge_verification(sessions, store, moment)
    result["abandoned_media"] = purge_review_media(sessions, store, moment)
    result["notifications"] = purge_notifications(sessions, moment)
    result["outbox_events"] = purge_outbox(sessions, moment)
    result["sanctions_expired"] = expire_sanctions(sessions, moment)
    result["rejected_reviews"] = purge_rejected_reviews(sessions, store, moment)
    result["report_contacts"] = erase_report_contacts(sessions, moment)
    return result


def main() -> None:
    print(run())
    sys.exit(0)


if __name__ == "__main__":
    main()
