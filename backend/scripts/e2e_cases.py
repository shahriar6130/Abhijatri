"""End-to-end check of verification, evidence, appeals, enforcement and live notifications on the local stack.

Run from `backend/` with the API on :8000 (EMAIL_PROVIDER=mailpit) and `supabase start` running:

    .venv\\Scripts\\python scripts\\e2e_cases.py --staff-email <superadmin email> --staff-password <password> --staff-totp-secret <base32>

The staff account must already be a superadmin with an authenticator enrolled (the secret is the one shown
when it was enrolled). A fresh member is created each run. Prints PASS or FAIL per step.
"""

import argparse
import base64
import json
import os
import sys
import threading
import time
import uuid
from datetime import date
from pathlib import Path

import httpx
import pyotp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import e2e_smoke as smoke  # noqa: E402
from e2e_smoke import API, ORIGIN, Browser, check  # noqa: E402

PNG = bytes.fromhex("89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082")


def staff_login(email: str, password: str, secret: str) -> Browser:
    staff = Browser("staff")
    r = staff.call("POST", "/auth/login", {"email": email, "password": password})
    check("staff: password sign-in", r.status_code == 200, r.text)
    staff.refresh_csrf()
    factor = r.json()["mfa_factors"][0]["id"]
    r = staff.call("POST", "/auth/mfa/verify", {"factor_id": factor, "code": pyotp.TOTP(secret).now()})
    check("staff: TOTP gives aal2", r.status_code == 200 and r.json()["aal"] == "aal2", r.text)
    staff.csrf = r.json()["csrf_token"]
    return staff


class Stream(threading.Thread):
    """Reads the member's live notification stream (Server-Sent Events) in the background."""

    def __init__(self, member: Browser) -> None:
        super().__init__(daemon=True)
        self.member, self.events, self.ready = member, [], threading.Event()

    def run(self) -> None:
        cookie = "; ".join(f"{k}={v}" for k, v in self.member.cookies.items())
        with httpx.stream("GET", f"{API}/notifications/stream", headers={"Cookie": cookie, "Origin": ORIGIN}, timeout=httpx.Timeout(10.0, read=60.0)) as response:
            event = None
            for line in response.iter_lines():
                if line.startswith("event:"):
                    event = line.split(":", 1)[1].strip()
                elif line.startswith("data:") and event:
                    self.events.append((time.monotonic(), event, json.loads(line.split(":", 1)[1])))
                    if event == "unread":
                        self.ready.set()


def wait_for(stream: Stream, kind: str, since: float, seconds: float = 20) -> float | None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        for at, event, data in stream.events:
            if event == "notification" and data["notification"]["kind"] == kind and at >= since:
                return at - since
        time.sleep(0.2)
    return None


def claim(staff: Browser, subject_id: str) -> tuple[str, str]:
    items = staff.call("GET", "/admin/queue").json()["items"]
    task = next(i for i in items if i["subject_id"] == subject_id)
    lease = staff.call("POST", f"/admin/tasks/{task['id']}/claim").json()["lease_token"]
    return task["id"], lease


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staff-email", required=True)
    parser.add_argument("--staff-password", required=True)
    parser.add_argument("--staff-totp-secret", required=True)
    args = parser.parse_args()

    run = uuid.uuid4().hex[:6]
    member = Browser("member")
    email = f"member-{run}@example.com"
    smoke.sign_up_and_in(member, email, f"Member {run}")
    staff = staff_login(args.staff_email, args.staff_password, args.staff_totp_secret)

    stream = Stream(member)
    stream.start()
    check("member: live notification stream connected", stream.ready.wait(10))

    # ---- verification with a private evidence file ----
    r = member.call("POST", "/verifications", {"statement": "Student at BUET, CSE."})
    check("member: verification requested", r.status_code == 201, r.text)
    case_id = r.json()["id"]
    r = member.call("POST", f"/verifications/{case_id}/evidence", {"content_type": "image/png", "size_bytes": len(PNG)})
    check("member: signed upload URL issued", r.status_code == 200, r.text)
    put = httpx.put(r.json()["upload_url"], content=PNG, headers={"Content-Type": "image/png"})
    check("member: file sent straight to the private bucket", put.status_code == 200, put.text)
    r = member.call("POST", f"/verifications/{case_id}/evidence/{r.json()['evidence_id']}/complete")
    check("member: upload confirmed", r.status_code == 200 and r.json()["status"] == "uploaded", r.text)

    task_id, lease = claim(staff, case_id)
    subject = next(i for i in staff.call("GET", "/admin/queue").json()["items"] if i["subject_id"] == case_id)["subject"]
    link = staff.call("POST", f"/admin/verification-cases/{case_id}/evidence/{subject['evidence'][0]['id']}/url")
    check("staff: 60-second evidence link works", link.status_code == 200 and httpx.get(link.json()["url"]).content == PNG, link.text)
    body = {"reason_code": "start", "task_id": task_id, "lease_token": lease}
    check("staff: start review", staff.call("POST", f"/admin/verification-cases/{case_id}/transition", {**body, "to": "in_review", "expected_version": 1}).status_code == 200)
    started = time.monotonic()
    r = staff.call("POST", f"/admin/verification-cases/{case_id}/transition", {**body, "to": "approved", "expected_version": 2, "reason_code": "documents-ok"})
    check("staff: approve", r.status_code == 200, r.text)
    delay = wait_for(stream, "verification.approved", started)
    check(f"member: approval notification arrived live ({delay:.1f} s)" if delay is not None else "member: approval notification arrived live", delay is not None)
    check("member: session now says verified_member", member.call("GET", "/auth/session").json()["verified_member"] is True)
    time.sleep(3)
    inbox = httpx.get("http://127.0.0.1:54324/api/v1/messages").json()["messages"]
    check("member: approval email in the inbox (critical = immediate)", any(m["To"][0]["Address"] == email and "Verified Member" in m["Subject"] for m in inbox))

    # ---- a published member review, a takedown, an appeal, an overturn ----
    from app.db import SessionLocal  # noqa: PLC0415
    from app.models import Destination, DestinationStatus, Review  # noqa: PLC0415

    with SessionLocal() as db:
        destination = Destination(status=DestinationStatus.PUBLISHED, name_bn="সাজেক", name_en=f"Sajek {run}")
        db.add(destination)
        db.commit()
        destination_id = destination.id
    guest = httpx.post(f"{API}/reviews/guest", headers={"Origin": ORIGIN, "X-Forwarded-For": "198.51.100.240"}, json={
        "destination_id": str(destination_id), "client_draft_id": str(uuid.uuid4()), "guest_scope_secret": uuid.uuid4().hex + uuid.uuid4().hex[:11],
        "receipt_secret": "abr1_" + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("="), "guest_display_name": "Tmp", "language": "EN",
        "traveller_type": "SOLO", "comfort_tier": "STANDARD", "visit_month": date.today().replace(day=1).isoformat(),
        "title": f"Clouds at Sajek {run}", "body": "A long enough review body for the validation rules.", "overall_rating": 5, "consent_version": "v1"})
    review_id = guest.json()["review_id"]
    member_id = member.call("GET", "/auth/session").json()["user"]["id"]
    with SessionLocal() as db:  # make it this member's review (member reviews arrive with R07)
        review = db.get(Review, uuid.UUID(review_id))
        review.author_user_id, review.guest_display_name, review.guest_scope_hash, review.guest_scope_key_id, review.guest_tag = uuid.UUID(member_id), None, None, None, None
        db.commit()
    task_id, lease = claim(staff, review_id)
    version = next(i for i in staff.call("GET", "/admin/queue").json()["items"] if i["subject_id"] == review_id)["subject"]["version"]
    started = time.monotonic()
    r = staff.call("POST", f"/admin/submissions/{review_id}/moderation-actions", {"task_id": task_id, "lease_token": lease, "expected_version": version, "decision": "PUBLISH", "reason_code": "meets-policy"})
    check("staff: publish the member's review", r.status_code == 200, r.text)
    check("member: 'review published' arrived live", wait_for(stream, "review.published", started) is not None)

    r = staff.call("POST", "/admin/enforcement-cases", {"review_id": review_id, "reason_code": "doxxing", "emergency": True, "counts_toward_rating": False})
    check("staff: emergency takedown", r.status_code == 201 and r.json()["review"]["status"] == "HIDDEN", r.text)
    enforcement_id = r.json()["case_id"]
    feed = httpx.get(f"{API}/destinations/{destination_id}/reviews").json()["items"]
    check("public: the hidden review left the feed", not feed)

    appealable = member.call("GET", "/appeals/mine").json()["appealable"]
    target = next(a for a in appealable if a["target_type"] == "enforcement_case")
    check("member: the takedown is appealable with a deadline", target["open"] and target["deadline_at"])
    r = member.call("POST", "/appeals", {"target_type": "enforcement_case", "target_id": enforcement_id, "reason": "My review shows no personal data at all."})
    check("member: appeal filed", r.status_code == 201, r.text)
    appeal_id = r.json()["id"]
    check("member: duplicate appeal refused", member.call("POST", "/appeals", {"target_type": "enforcement_case", "target_id": enforcement_id, "reason": "Again, please check it."}).status_code == 409)
    check("member: 'appeal received' arrived live", wait_for(stream, "appeal.received", started) is not None)

    task_id, lease = claim(staff, appeal_id)
    r = staff.call("POST", f"/admin/appeals/{appeal_id}/decision", {"outcome": "overturned", "expected_version": 1, "note": "No personal data found.", "task_id": task_id, "lease_token": lease})
    check("staff: the original decider cannot decide the appeal", r.status_code == 403 and r.json()["error"]["code"] == "APPEAL_REVIEWER_NOT_INDEPENDENT", r.text)
    staff.call("POST", f"/admin/tasks/{task_id}/release", {"lease_token": lease})
    print("note  an independent reviewer would now overturn it (the second staff account in the guide).")

    # ---- audit and monitoring ----
    actions = {e["action"] for e in staff.call("GET", "/admin/audit-events").json()["items"]}
    check("audit: every step recorded", {"verification.approved", "evidence.viewed", "enforcement.opened", "appeal.received", "denied.appeal.decide"} & actions >= {"verification.approved", "evidence.viewed", "enforcement.opened", "appeal.received"}, str(actions))
    summary = staff.call("GET", "/admin/monitoring/summary").json()
    check("monitoring: outbox drained, nothing failed", summary["outbox_failed"] == 0 and summary["outbox_pending"] <= 2, str(summary))
    print("\nAll case and notification steps passed.")


if __name__ == "__main__":
    main()
