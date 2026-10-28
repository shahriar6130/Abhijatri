"""Remove a staff member's authenticator so they can set it up again (lost or replaced phone).

    python -m app.jobs.reset_mfa --email owner@example.com

There is deliberately no button for this: removing two-step verification with only a password would
defeat it. Whoever can run this command already controls the server. The person sees the QR code
again at their next staff sign-in. The reset is audited and the person gets a security notice.
"""

import argparse
import sys

from sqlalchemy import select

from app.admin import audit
from app.auth.gotrue import GoTrueClient, GoTrueError, GoTrueUnavailable
from app.db import SessionLocal
from app.models import User
from app.notify import events


def run(email: str, *, assume_yes: bool = False, gotrue: GoTrueClient | None = None) -> int:
    email = email.strip().lower()
    client = gotrue or GoTrueClient()
    with SessionLocal() as session:
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            print("Refused: no account with that email.", file=sys.stderr)
            return 3
        try:
            factors = client.admin_list_factors(str(user.id))
        except (GoTrueError, GoTrueUnavailable) as error:
            print(f"Refused: Supabase Auth did not answer ({type(error).__name__}).", file=sys.stderr)
            return 4
        if not factors:
            print(f"{email} has no authenticator. The QR code appears at the next staff sign-in.")
            return 0
        if not assume_yes:
            typed = input(f"Remove {len(factors)} authenticator(s) of {user.display_name} <{email}>? Type the email to confirm: ").strip().lower()
            if typed != email:
                print("Cancelled.", file=sys.stderr)
                return 1
        for factor in factors:
            client.admin_delete_factor(str(user.id), str(factor.get("id")))
        audit.record(
            session, actor=None, action="staff.mfa_reset", target_type="user", target_id=user.id,
            reason="authenticator reset by the operator", metadata={"factors_removed": len(factors)},
        )
        events.emit(session, "security.mfa_reset", user.id, {"user_id": str(user.id)}, aggregate_type="user")
        session.commit()
    print(f"Done. {email} will see the QR code at the next staff sign-in.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove a staff member's authenticator so they can enrol again.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt (scripts and tests)")
    arguments = parser.parse_args()
    sys.exit(run(arguments.email, assume_yes=arguments.yes))


if __name__ == "__main__":
    main()
