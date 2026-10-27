"""End-to-end check of sign-up, TOTP, moderation and reports against the real local stack.

Run from `backend/` with the API on :8000 and `supabase start` running:

    .venv\\Scripts\\python scripts\\e2e_smoke.py

It creates fresh accounts (random emails), reads the verification emails from Mailpit, enrols real
TOTP with Supabase Auth, makes the first one superadmin through the bootstrap command, then walks the
whole moderation path. It prints PASS or FAIL per step and exits non-zero on the first failure. It
leaves its test data in your local development database.
"""

import base64
import os
import re
import sys
import time
import uuid
from datetime import date
from pathlib import Path

import httpx
import pyotp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `app` imports when run as a script

API = "http://localhost:8000/api/v1"
MAILPIT = "http://127.0.0.1:54324/api/v1"
ORIGIN = "http://localhost:5173"
PASSWORD = "Passw0rdE2eTest"  # noqa: S105 - a throwaway value for accounts this script creates on a local stack


class Browser:
    """Keeps cookies by hand: the session cookies are `Secure`, which a plain http client would not send."""

    def __init__(self, name: str) -> None:
        self.name, self.cookies, self.csrf = name, {}, None
        self.http = httpx.Client(base_url=API, timeout=30, headers={"Origin": ORIGIN, "X-Forwarded-For": "198.51.100." + str(uuid.uuid4().int % 200 + 1)})

    def call(self, method: str, path: str, json: dict | None = None, headers: dict | None = None) -> httpx.Response:
        merged = {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items()), **(headers or {})}
        if method != "GET" and self.csrf:
            merged["X-CSRF-Token"] = self.csrf
        response = self.http.request(method, path, json=json, headers=merged)
        for cookie in response.headers.get_list("set-cookie"):
            name, _, rest = cookie.partition("=")
            value = rest.split(";")[0]
            if "max-age=0" in cookie.lower() or not value:
                self.cookies.pop(name, None)
            else:
                self.cookies[name] = value
        return response

    def refresh_csrf(self) -> None:
        self.csrf = self.call("GET", "/auth/csrf").json()["csrf_token"]


def check(label: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + label + (f"  [{detail}]" if detail and not ok else ""))
    if not ok:
        sys.exit(1)


def mail_token(email: str) -> str:
    for _ in range(30):
        for message in httpx.get(f"{MAILPIT}/messages").json()["messages"]:
            if message["To"][0]["Address"] == email:
                html = httpx.get(f"{MAILPIT}/message/{message['ID']}").json()["HTML"]
                match = re.search(r"token_hash=([^&\"<\s]+)", html)
                if match:
                    return match.group(1)
        time.sleep(0.5)
    raise SystemExit(f"no email arrived for {email}")


def sign_up_and_in(browser: Browser, email: str, name: str) -> None:
    r = browser.call("POST", "/auth/register", {"email": email, "password": PASSWORD, "display_name": name})
    check(f"{browser.name}: register -> 202", r.status_code == 202, r.text)
    r = browser.call("POST", "/auth/login", {"email": email, "password": PASSWORD})
    check(f"{browser.name}: login before verifying -> 403 EMAIL_NOT_VERIFIED", r.status_code == 403 and r.json()["error"]["code"] == "EMAIL_NOT_VERIFIED", r.text)
    r = browser.call("POST", "/auth/verify-email", {"token_hash": mail_token(email)})
    check(f"{browser.name}: email link verifies", r.status_code == 200, r.text)
    r = browser.call("POST", "/auth/login", {"email": email, "password": PASSWORD})
    check(f"{browser.name}: login -> 200", r.status_code == 200 and r.json()["authenticated"], r.text)
    browser.refresh_csrf()


def enrol_totp(browser: Browser) -> None:
    r = browser.call("POST", "/auth/mfa/enroll")
    check(f"{browser.name}: TOTP enrol returns a secret and QR", r.status_code == 200 and r.json()["secret"] and r.json()["qr_code"], r.text)
    factor, secret = r.json()["factor_id"], r.json()["secret"]
    r = browser.call("POST", "/auth/mfa/verify", {"factor_id": factor, "code": "000000"})
    check(f"{browser.name}: a wrong TOTP code is refused", r.status_code == 401, r.text)
    r = browser.call("POST", "/auth/mfa/verify", {"factor_id": factor, "code": pyotp.TOTP(secret).now()})
    check(f"{browser.name}: the right TOTP code gives aal2", r.status_code == 200 and r.json()["aal"] == "aal2", r.text)
    browser.csrf = r.json()["csrf_token"]


def main() -> None:
    run = uuid.uuid4().hex[:8]
    boss, reader = Browser("boss"), Browser("reader")
    boss_email, reader_email = f"boss-{run}@example.com", f"reader-{run}@example.com"

    sign_up_and_in(boss, boss_email, f"Boss {run}")
    sign_up_and_in(reader, reader_email, f"Reader {run}")

    from app.jobs import bootstrap_admin  # noqa: PLC0415 - needs the app settings, so imported late

    code = bootstrap_admin.run(boss_email, assume_yes=True)
    if code == 2:
        print("note  a superadmin already exists from an earlier run. The bootstrap command only creates the FIRST one;")
        print("      to rerun this script, revoke that role first (or run it on a fresh database).")
    check("bootstrap makes the first superadmin", code == 0)

    r = boss.call("GET", "/admin/queue")
    check("superadmin without TOTP -> 403 MFA_REQUIRED", r.status_code == 403 and r.json()["error"]["code"] == "MFA_REQUIRED", r.text)
    enrol_totp(boss)
    check("queue opens after TOTP", boss.call("GET", "/admin/queue").status_code == 200)
    check("a plain member gets 404 for staff routes", reader.call("GET", "/admin/queue").status_code == 404)

    # a destination and a guest review
    from sqlalchemy import select  # noqa: PLC0415

    from app.db import SessionLocal  # noqa: PLC0415
    from app.models import Destination, DestinationStatus  # noqa: PLC0415

    with SessionLocal() as db:
        destination = Destination(status=DestinationStatus.PUBLISHED, name_bn="কক্সবাজার", name_en=f"E2E Bay {run}")
        db.add(destination)
        db.commit()
        destination_id = str(destination.id)
        assert db.scalar(select(Destination.id).where(Destination.id == destination.id)) is not None
    guest = httpx.post(
        f"{API}/reviews/guest",
        headers={"Origin": ORIGIN, "X-Forwarded-For": "198.51.100.250"},
        json={
            "destination_id": destination_id, "client_draft_id": str(uuid.uuid4()), "guest_scope_secret": uuid.uuid4().hex + uuid.uuid4().hex[:11],
            "receipt_secret": "abr1_" + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="), "guest_display_name": "Rahim", "language": "EN",
            "traveller_type": "SOLO", "comfort_tier": "STANDARD", "visit_month": date.today().replace(day=1).isoformat(),
            "title": f"Lovely bay {run}", "body": "A long enough review body for the validation rules.", "overall_rating": 5, "consent_version": "v1",
        },
    )
    check("a guest review is accepted (no account needed)", guest.status_code in (200, 201), guest.text)
    review_id = guest.json()["review_id"]

    queue = boss.call("GET", "/admin/queue").json()["items"]
    task = next(i for i in queue if i["subject_id"] == review_id)
    check("the review is in the queue with its content", task["subject"]["title"] == f"Lovely bay {run}")
    lease = boss.call("POST", f"/admin/tasks/{task['id']}/claim").json()["lease_token"]
    r = reader.call("POST", f"/admin/tasks/{task['id']}/claim")
    check("a second person cannot claim the same task", r.status_code == 404)
    version = task["subject"]["version"]
    body = {"task_id": task["id"], "lease_token": lease, "expected_version": version, "decision": "PUBLISH", "reason_code": "meets-policy"}
    r = boss.call("POST", f"/admin/submissions/{review_id}/moderation-actions", {**body, "expected_version": version + 5})
    check("a stale version -> 409", r.status_code == 409, r.text)
    r = boss.call("POST", f"/admin/submissions/{review_id}/moderation-actions", body, {"Idempotency-Key": f"e2e-{run}-publish"})
    check("PUBLISH works", r.status_code == 200 and r.json()["status"] == "PUBLISHED", r.text)
    again = boss.call("POST", f"/admin/submissions/{review_id}/moderation-actions", body, {"Idempotency-Key": f"e2e-{run}-publish"})
    check("the same retry returns the same answer", again.status_code == 200 and again.json() == r.json())
    feed = httpx.get(f"{API}/destinations/{destination_id}/reviews").json()
    check("the published review is public", any(item.get("title") == f"Lovely bay {run}" for item in feed["items"]), str(feed)[:200])

    # a report by the other member
    r = reader.call("POST", f"/reviews/{review_id}/reports", {"reason_code": "spam", "details": "advert"})
    check("a member can report the review", r.status_code == 201, r.text)
    check("a duplicate open report -> 409", reader.call("POST", f"/reviews/{review_id}/reports", {"reason_code": "spam"}).status_code == 409)
    report_task = next(i for i in boss.call("GET", "/admin/queue", ).json()["items"] if i["task_type"] == "report" and i["subject"]["review_id"] == review_id)
    report_lease = boss.call("POST", f"/admin/tasks/{report_task['id']}/claim").json()["lease_token"]
    subject = report_task["subject"]
    hide = {"task_id": report_task["id"], "lease_token": report_lease, "expected_version": subject["review_version"], "decision": "HIDE", "reason_code": "reported-spam"}
    r = boss.call("POST", f"/admin/submissions/{review_id}/moderation-actions", hide)
    check("HIDE under the report's lease", r.status_code == 200 and r.json()["status"] == "HIDDEN", r.text)
    r = boss.call("POST", f"/admin/reports/{subject['report_id']}/transition", {"to": "actioned", "expected_version": subject["version"], "reason_code": "report-confirmed", "task_id": report_task["id"], "lease_token": report_lease})
    check("the report is resolved", r.status_code == 200 and r.json()["state"] == "actioned", r.text)
    feed = httpx.get(f"{API}/destinations/{destination_id}/reviews").json()
    check("the hidden review left the public feed", not any(item.get("title") == f"Lovely bay {run}" for item in feed["items"]))

    # audit
    events = boss.call("GET", "/admin/audit-events", ).json()["items"]
    actions = {event["action"] for event in events}
    check("the audit log has the whole story", {"task.claimed", "review.publish", "review.hide", "report.actioned"} <= actions, str(actions))

    # roles
    reader_id = reader.call("GET", "/auth/session").json()["user"]["id"]
    r = boss.call("POST", f"/admin/staff/{reader_id}/role", {"role": "moderator", "reason": "joins the team"})
    check("the superadmin grants a moderator role (password just confirmed)", r.status_code == 200, r.text)
    r = reader.call("GET", "/admin/queue")
    check("a new moderator still needs TOTP -> 403 MFA_REQUIRED", r.status_code == 403 and r.json()["error"]["code"] == "MFA_REQUIRED", r.text)
    enrol_totp(reader)
    check("the moderator can open the queue after TOTP", reader.call("GET", "/admin/queue").status_code == 200)
    check("a moderator cannot manage roles -> 403", reader.call("GET", "/admin/staff").status_code == 403)
    boss_id = boss.call("GET", "/auth/session").json()["user"]["id"]
    r = boss.call("POST", f"/admin/staff/{boss_id}/role", {"role": None, "reason": "stepping down"})
    check("the last superadmin cannot be removed -> 409", r.status_code == 409 and r.json()["error"]["code"] == "LAST_SUPERADMIN", r.text)

    # sign-out
    check("logout -> 204", boss.call("POST", "/auth/logout").status_code == 204)
    check("the session is gone", boss.call("GET", "/auth/session").json() == {"authenticated": False})
    print("\nAll end-to-end steps passed.")


if __name__ == "__main__":
    main()
