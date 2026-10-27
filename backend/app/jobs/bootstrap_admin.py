"""Create the first superadmin (Platform Foundation 8.4, Moderation spec 2.2).

    python -m app.jobs.bootstrap_admin --email owner@example.com

The person registers and verifies their email through the normal sign-up first. This command then
gives that existing account the `superadmin` role, writes an audit event, and refuses to run when an
active superadmin already exists (later grants go through `POST /admin/staff/{user_id}/role`). The
new superadmin still has to enrol an authenticator app (TOTP) before any staff route works.
"""

import argparse
import sys

from sqlalchemy import func, select

from app.admin import roles
from app.db import SessionLocal
from app.errors import ApiError
from app.models import User, UserRole


def run(email: str, *, assume_yes: bool = False) -> int:
    email = email.strip().lower()
    with SessionLocal() as session:
        existing = session.scalar(select(func.count()).select_from(UserRole).where(UserRole.role == "superadmin", UserRole.revoked_at.is_(None)))
        if existing:
            print("Refused: an active superadmin already exists. Use the staff screen to grant roles.", file=sys.stderr)
            return 2
        user = session.scalar(select(User).where(User.email == email))
        if user is None or user.email_verified_at is None:
            print("Refused: no verified account with that email. Register and verify it first.", file=sys.stderr)
            return 3
        if not assume_yes:
            typed = input(f"Make {user.display_name} <{email}> the first superadmin? Type the email to confirm: ").strip().lower()
            if typed != email:
                print("Cancelled.", file=sys.stderr)
                return 1
        try:
            roles.set_staff_role(session, actor=None, target_user_id=user.id, role="superadmin", reason="bootstrap: first superadmin")
            session.commit()
        except ApiError as error:
            session.rollback()
            print(f"Refused: {error.code}", file=sys.stderr)
            return 4
    print(f"Done. {email} is now a superadmin. Next: sign in and enrol an authenticator app (TOTP).")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first superadmin.")
    parser.add_argument("--email", required=True, help="the verified account to promote")
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt (scripts and tests)")
    arguments = parser.parse_args()
    sys.exit(run(arguments.email, assume_yes=arguments.yes))


if __name__ == "__main__":
    main()
