"""Nightly rating reconciliation (Review.md 6.3).

    python -m app.jobs.reconcile_ratings            # detect and alert; never changes a total
    python -m app.jobs.reconcile_ratings --repair   # also overwrite drifting totals, with an audit event each

Detecting recomputes every destination's totals from the published review rows and compares them with the
stored totals. A difference raises a superadmin alert and exits with status 1, so a scheduler shows it. Repair is
a deliberate second step, never the default.
"""

import sys
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.rating_integrity import ReconcileResult, run_reconciliation


def run(sessions: Callable[[], Session] = SessionLocal, *, repair: bool = False) -> ReconcileResult:
    with sessions() as session:
        try:
            result = run_reconciliation(session, repair=repair, actor=None)
            session.commit()
        except Exception:
            session.rollback()
            raise
    return result


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    result = run(repair="--repair" in args)
    print({"destinations_checked": result.destinations_checked, "drifts": len(result.drifts), "repaired": result.repaired})
    for drift in result.drifts:
        print(f"  {drift.destination_id} {drift.kind} {drift.key} stored={drift.stored} expected={drift.expected}")
    sys.exit(1 if result.drifts and not result.repaired else 0)


if __name__ == "__main__":
    main()
