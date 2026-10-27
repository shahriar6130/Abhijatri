"""Retention and expiry (Moderation spec 10, 7.3).

    python -m app.jobs.retention

- Evidence files of decided verification cases are deleted after `purge_after` (24 hours after approval,
  30 days after rejection or withdrawal); a rejected or withdrawn case row goes with them.
- Notifications: standard ones after 90 days, critical ones after 24 months.
- Sanctions past their end time expire, with a system audit event.

Nothing tied to an open appeal is deleted. `purge_after` only makes a row a candidate: each case is
locked and the open-appeal check repeated inside that lock immediately before deletion, and creating
an appeal on a verification case locks the same row, so an appeal cannot slip in between.
"""

import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import media
from app.admin import audit
from app.admin.cases import reverse_sanction
from app.db import SessionLocal
from app.models import Appeal, Notification, Sanction, VerificationCase, VerificationEvidence
from app.storage import StorageClient, StorageUnavailable, get_storage

logger = logging.getLogger(__name__)

OPEN_APPEAL = ("received", "in_review")
STANDARD_DAYS = 90
CRITICAL_DAYS = 730


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


def purge_notifications(sessions: Callable[[], Session], now: datetime) -> int:
    with sessions() as session:
        open_appeals = select(Appeal.id).where(Appeal.state.in_(OPEN_APPEAL))
        result = session.execute(
            delete(Notification).where(
                ((Notification.critical.is_(False)) & (Notification.created_at < now - timedelta(days=STANDARD_DAYS)))
                | ((Notification.critical.is_(True)) & (Notification.created_at < now - timedelta(days=CRITICAL_DAYS))),
                (Notification.appeal_id.is_(None)) | (Notification.appeal_id.not_in(open_appeals)),
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
    result["sanctions_expired"] = expire_sanctions(sessions, moment)
    return result


def main() -> None:
    print(run())
    sys.exit(0)


if __name__ == "__main__":
    main()
