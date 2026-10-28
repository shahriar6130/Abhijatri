# Testing sign-in, accounts and the moderation dashboard on localhost

How to start everything, then click through every flow and what you should see. It covers Gantt R04/R05 (accounts) and R10/R11 (moderation), and `Docs/Moderation-Dashboard-Specification.md`.

## 1. What runs where

| Part | Address | Started with |
|---|---|---|
| Public app (guests and members) | http://localhost:5173 | `cd frontend; npm run dev -- --port 5173` |
| Staff dashboard | http://localhost:5175 | `cd staff; npm run dev -- --port 5175` |
| Monitoring dashboard (visits, health) | http://localhost:5174 | `cd ops; npm run dev -- --port 5174` |
| API | http://localhost:8000 (docs at `/docs`) | `cd backend; .venv\Scripts\python -m uvicorn app.main:app --port 8000` |
| Database, Auth, Storage, mail inbox | Postgres `127.0.0.1:54322`, Auth via `http://127.0.0.1:54321`, **mail inbox http://127.0.0.1:54324** | `supabase start -x realtime,studio,edge-runtime,logflare,vector,imgproxy,postgres-meta,supavisor` from the repo root |
| Redis (visit counters) | `localhost:6379` | `docker compose up -d redis` |

Emails never leave your machine: every verification and reset email lands in the inbox at **http://127.0.0.1:54324**.

First time only: `cd backend; .venv\Scripts\python -m alembic upgrade head` (expect `0012_tasks_reports (head)` or later). `backend/.env` must hold `DATABASE_URL` (port 54322), `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_JWT_SECRET` or `SUPABASE_JWKS_URL`, `REDIS_URL`, and `CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:5174,http://localhost:5175`. Use **Chrome or Edge** on `localhost` (the session cookies are `Secure`, which these browsers accept on localhost).

Memory is tight on small machines: start only what you need (API, Supabase, one Vite app at a time).

## 2. Quick automatic check (2 minutes)

```text
cd backend
.venv\Scripts\python scripts\e2e_smoke.py
```

It signs up two accounts, reads the emails from the inbox, enrols real authenticator codes with Supabase Auth, makes the first superadmin, then walks the moderation path and prints `PASS` or `FAIL` for about 35 steps. It ends with `All end-to-end steps passed.` Run it on a database that has no superadmin yet (it uses the bootstrap command); to rerun, revoke the existing one: `docker exec supabase_db_Abhijatri psql -U postgres -c "update user_roles set revoked_at=now() where revoked_at is null"`.

Automated suites: `cd backend; pytest -q` (set `TEST_DATABASE_URL` to the `abhijatri_test` database first), `cd frontend; npm test; npm run build`, `cd staff; npm test; npm run build`, `cd ops; npm test; npm run build`.

## 3. Members: sign up, verify, sign in, reset (public app)

Open http://localhost:5173/register in a normal window. Keep http://127.0.0.1:54324 open in another tab.

| # | Case | Steps | Expected |
|---|---|---|---|
| A1 | Register | Email `nila@example.com`, name `Nila Rahman`, password `Passw0rdTest99`, press Create account | A "Check your email" panel. The inbox shows "Confirm your Abhijatri account". |
| A2 | Same answer for an existing address | Register the same email again | The same "Check your email" panel (no hint that the address exists). |
| A3 | Weak password | Password `short1` | The field shows "Use at least 10 characters." and nothing is sent. A password with no digit shows "Include at least one letter and one number." |
| A4 | Reserved name | Name `Admin` (also `m0derator`, `Abhijatri Team`) | "This name cannot be used." |
| A5 | Bad email | `not-an-email` | "Enter a valid email address." |
| A6 | Sign in before verifying | Go to /login with the right password | "Verify your email first." with a "Send the verification link again" button. |
| A7 | Verify | Open the link in the email | "Email verified" with a Sign in button. Opening the same link again shows "This link did not work". |
| A8 | Wrong password | /login with a wrong password | "The email or password is not correct." (identical for an unknown email). After 5 wrong tries: "Too many attempts. Try again in a little while." |
| A9 | Sign in | Right password | You land on /overview. The sidebar shows your name and a Sign out button, with no "Guest" tag. |
| A10 | Session survives reload | Reload the page | You are still signed in (the sidebar shows your name). |
| A11 | Cookies | Developer tools, Application, Cookies, `localhost` | `__Host-abhijatri_session` and `__Host-abhijatri_refresh`, both **HttpOnly** and **Secure**. Local Storage holds no token. |
| A12 | Sign out | Press Sign out | You are a guest again with the same guest tag as before. Reload: still signed out. |
| A13 | Forgot password | /forgot-password, enter `nila@example.com` | "Check your email" (the same for an unknown address). The inbox shows "Reset your Abhijatri password". |
| A14 | Reset | Open the reset link, enter a new password twice | "Password changed. Every device was signed out." Sign in with the new one works; the old one does not. |
| A15 | Reset link reuse | Open the same reset link again | "The reset link ... has expired" with a link to ask for a new one. |
| A16 | Guests still work | In a private window, open /overview and write a guest review | It works without an account (accounts are optional). |
| A17 | Visits | Dashboard at :5174 (Visitors panel) after A9 | Verified numbers rise by one for the day; reloading does not add another. |

## 4. Staff: first superadmin, authenticator, role management (staff dashboard)

1. Register and verify a second account for the owner (for example `owner@example.com`), as in section 3.
2. Make it the first superadmin (the command refuses if one already exists):

```text
cd backend
.venv\Scripts\python -m app.jobs.bootstrap_admin --email owner@example.com
```

   Type the email to confirm. Expected: `Done. owner@example.com is now a superadmin.`
3. Open http://localhost:5175 and sign in with that account.

| # | Case | Steps | Expected |
|---|---|---|---|
| B1 | Needs an authenticator | After the password | "Two-step verification is required" and a "Set up an authenticator app" button. |
| B2 | Enrol | Press it, scan the QR with Google Authenticator (or type the secret), enter the 6-digit code | The dashboard opens: tabs Queue, Audit, Monitoring, Staff. The header shows your name and `superadmin`. |
| B3 | Wrong code | A different 6 digits at the code step | "The email, password or code is not correct." |
| B4 | Sign out, sign in again | Password, then the current code | Straight to the dashboard. |
| B5 | A plain member has no access | Sign in at :5175 with the member from section 3 | "This account has no staff role." Calling `http://localhost:8000/api/v1/admin/queue` gives 404 for them. |
| B6 | Grant a role | Staff tab, search `nila`, press `moderator` (reason required) | A password and code dialog appears; after confirming, "Role updated." and the person is listed. |
| B7 | Old confirmation | Wait 10 minutes, then change a role | The dialog asks for the password again before it works. |
| B8 | Last superadmin | Revoke or demote yourself when you are the only superadmin | "The last superadmin cannot be removed." |
| B9 | Moderator view | Sign in as that moderator in another browser profile (enrol an authenticator) | Queue, Audit and Monitoring tabs only; no Staff tab. `GET /api/v1/admin/staff` returns 403. |

## 5. Moderation: queue, claims, decisions, reports, audit

Create something to moderate: in a private window at http://localhost:5173/reviews write a guest review for any destination.

| # | Case | Steps | Expected |
|---|---|---|---|
| C1 | It is queued | Staff dashboard, Queue | The review appears with its title, rating and text. |
| C2 | Claim | Select it, press "Claim this task" | A lease countdown (5:00) starts; decision controls appear. The queue entry reads "Yours". |
| C3 | Exclusive | In a second browser profile (another moderator) open the same item | It shows "Held by someone"; Claim is disabled. The direct call returns 409 `TASK_NOT_AVAILABLE`. |
| C4 | Heartbeat | Stay on the page for more than a minute | The countdown is topped up automatically (it does not reach 0). |
| C5 | Expiry | Close the tab and wait 5 minutes | The other moderator can now claim it. |
| C6 | Stale tab | Keep the first tab open after C5, press Submit decision | "Your claim on this task ended ... Reload." The review is unchanged. |
| C7 | Decide | Hold the lease, choose PUBLISH with reason "Meets the policy", Submit | "Done: PUBLISHED". The item leaves the queue and the review is public on the destination page. |
| C8 | Reject | For another review choose REJECT with a reason | "Done: REJECTED"; it never becomes public. |
| C9 | Escalate | As a moderator claim an item and press Escalate with a reason | It shows "Escalated". The moderator cannot claim it any more; the superadmin can. |
| C10 | Report | In the public app (http://localhost:5173) sign in as a member, open a destination with a published review, press **Report**, choose a reason, **Send report** | "Report sent. Thank you." A report task appears in the staff queue under Reports, showing the reason, the details, and the reported review. Reporting again gives the "already have an open report" message. Guests do not see a Report button. |
| C11 | Resolve a report | Claim it, press "Start review", then "Hide the review", then "Action taken" | The review leaves the public page; the report is resolved; the task closes. |
| C12 | Duplicate report | The same member reports the same review again | 409 `DUPLICATE_OPEN_REPORT`. |
| C13 | Audit | Audit tab | Events for every step: `task.claimed`, `review.publish`, `report.in_review`, `review.hide`, `report.actioned`, with who, role, time and the request id. Filter by action or target. |
| C14 | Audit is permanent | `docker exec supabase_db_Abhijatri psql -U postgres -c "update audit_events set action='x'"` | `ERROR: audit_events is append-only`. |
| C15 | Monitoring | Monitoring tab | Open tasks, oldest task age, escalated, expired claims, open reports, outbox pending, denied attempts. |
| C16 | Safe retry | `curl` a decision twice with the same `Idempotency-Key` (see section 7) | The same answer both times; the review's version rises once. |
| C17 | Stale version | Decide with an old `expected_version` | 409 `REVIEW_VERSION_CONFLICT`; nothing changed. |

## 5b. Verification, appeals, enforcement and live notifications

Keep the member signed in at http://localhost:5173 in one browser profile and the staff dashboard (http://localhost:5175) in **another profile or another browser**: every `localhost` port shares the same cookies, so one profile holds one account at a time. Set `EMAIL_PROVIDER=mailpit` in `backend/.env` and restart the API so emails reach the inbox.

| # | Case | Steps | Expected |
|---|---|---|---|
| D1 | Request verification | Member: sidebar, "Become a Verified Member", write a statement, "Request verification" | "Request submitted. Now add an evidence file." The staff queue (Verification filter) shows the request with the applicant's name and email. Each staff member gets an in-app notification "New verification request" |
| D2 | Evidence upload | Member: "Add a file", choose a JPG, PNG or PDF under 5 MB | "File uploaded."; evidence count 1. A `.txt` or a 6 MB file is refused with a clear message |
| D3 | Evidence is private | Staff: open the case without claiming it | The file buttons are disabled ("Claim the task to view the files") |
| D4 | View evidence | Staff: claim, press "File 1" | The file opens in a new tab through a link that expires in 60 seconds; the audit log shows `evidence.viewed` |
| D5 | Ask a question | Staff: "Start review", write a note, "Ask a question" | Within about 4 seconds the member's bell shows "More information is needed" without a reload; the verification page shows the question |
| D6 | Answer | Member: type an answer, "Send answer" | The case is back in the staff queue as `in_review` |
| D7 | Approve | Staff: claim again, "Approve" | The member's bell lights up within seconds: "You are now a Verified Member"; the sidebar link changes to "Verified Member ✓"; an email arrives in the inbox at once (critical notice) |
| D8 | Approve without a file | Staff: try to approve a case with no uploaded file | "At least one evidence file is needed before approval." |
| D9 | Escalate | Moderator: "Escalate" | Only a superadmin can approve or reject it now; the moderator's open tab can no longer decide it |
| D10 | Reject, then appeal | Staff rejects a case; member opens "Appeals" | The rejection is listed with a deadline (end of the 30th day, Dhaka time). Write at least 10 characters and press "Appeal": "Appeal submitted", and the bell shows "Your appeal was received" with a case reference |
| D11 | Duplicate appeal | Appeal the same decision again | "This decision has already been appealed." |
| D12 | Independent reviewer | The staff member who rejected tries to decide the appeal | The queue marks it "You made the original decision"; Claim is disabled; the API answers `403 APPEAL_REVIEWER_NOT_INDEPENDENT` |
| D13 | Overturn | A different staff member claims the appeal, writes a reason, "Overturn" | The member becomes a Verified Member; the bell shows "Your appeal was decided" |
| D14 | Emergency takedown | Staff, Enforcement tab: paste a published review id, reason `doxxing`, tick "Emergency", "Open case" | The review disappears from the destination page; a superadmin task "Emergency takedown" appears in the queue with a 24-hour deadline; a moderator cannot confirm it |
| D15 | Restriction | Superadmin, Enforcement: "Act on an account", search the member, restriction "Posting restriction", 7 days | The member gets "Account restriction"; reporting a review or requesting verification answers "Your account is temporarily restricted" |
| D16 | Suspension | Superadmin: restriction "Suspension" | The member's next page load signs them out ("This account has been disabled"); "Lift" in the case list restores access |
| D17 | Expiry | `docker exec supabase_db_Abhijatri psql -U postgres -c "update sanctions set ends_at = now() - interval '1 minute' where state = 'active'"`, then `cd backend; .venv\Scripts\python -m app.jobs.retention` | `sanctions_expired` > 0; the account is active again; the audit log shows `sanction.expired` with no actor (system) |
| D18 | Digest | `cd backend; .venv\Scripts\python -c "from app.db import SessionLocal; from app.notify import delivery; from app.notify.providers import get_provider; print(delivery.build_digests(SessionLocal), delivery.send_due(SessionLocal, get_provider()))"` | One "Your Abhijatri summary" email per person with waiting non-critical notices, once per local day after their digest time (default 08:00 Asia/Dhaka). It also runs by itself every minute |
| D19 | Monitoring | Staff: Monitoring tab | Open verification requests, open appeals, overdue emergency takedowns, active restrictions, failed outbox events, failed or unclear emails |

Automatic version of most of this (needs a superadmin with an authenticator): `cd backend; .venv\Scripts\python scripts\e2e_cases.py --staff-email <superadmin> --staff-password <password> --staff-totp-secret <secret shown at enrolment>`. It reports how many seconds the live notification took.

## 5d. Notification system v1.1 (Docs/Notification-Documentation.md)

Same two-profile setup as 5b; `EMAIL_PROVIDER=mailpit` so every email lands in http://127.0.0.1:54324.

| # | Case | Steps | Expected |
|---|---|---|---|
| N1 | Inbox page | Member: bell, "All notifications and email settings" (or `/account/notifications`) | The list with category and "Important" tags, newest first; "Load more" after 20; tabs All / Unread (count) / Archived |
| N2 | Read and archive | Press "Mark read", then "Archive" on one item | The unread count drops; the item moves to the Archived tab; "Unarchive" brings it back |
| N3 | Email preference: off | Email section: "No email (only here)", Save. Staff publishes one of the member's reviews | "Your review is published" appears in the bell, but no email arrives |
| N4 | Critical always emailed | With "off" still set, staff rejects a review | "Your review was not published" in the bell **and** an email in Mailpit within seconds |
| N5 | Daily digest | Choose "A daily summary", time a few minutes from now, Save; staff publishes another review | No email at once; after the chosen time (scanner runs every minute) one "Your Abhijatri summary (n)" email |
| N6 | Live reconnect | Stop the API for 20 s while the member page is open, then start it | The bell panel shows "Live updates paused; reconnecting"; after the restart it disappears and the list is refetched |
| N7 | Assignment | Superadmin: queue item, "Assign to" a moderator, Save | The moderator's staff Inbox tab shows "A task was assigned to you"; assigning to someone else gives the first one "A task was unassigned" |
| N8 | Role revoked | Superadmin: Staff tab, remove a moderator's role | The moderator's public bell shows "Your staff role was removed"; their old staff notices (assignments, new verification) are no longer listed |
| N9 | Deliveries | Superadmin: Notifications tab, Deliveries | Recent emails with status, tries and an address reference (no address); "Details" lists every attempt |
| N10 | Retry | Make one email ambiguous: `docker exec supabase_db_Abhijatri psql -U postgres -c "update notification_deliveries set status='ambiguous' where id = (select id from notification_deliveries order by created_at desc limit 1)"`; Details, write a reason, "Retry" | The delivery goes back to queued and is sent; the Audit tab shows `notification.delivery_retried` |
| N11 | Suppression | Notifications tab, Suppressions: add the member's email with reason `owner_request`; trigger a critical notice | The bell still shows it, but no email: the delivery is `skipped` (`suppressed`). Remove it with a reason; both changes are in the audit log |
| N12 | Template version | Templates and rules: choose `content.rejected`, new version (in_app, English) "We could not publish your review", Save draft, Activate | The next rejection uses the new title; version 1 shows `retired`; a body with `{email}` is refused ("UNKNOWN_VARIABLE") |
| N13 | Rule | Same screen: "Turn email off" for `content.published` | Later publish notices arrive in the bell only |
| N14 | Alerts | Leave a claimed task until under a minute is left | The holder's Inbox shows "Your claim is about to expire" once |
| N15 | Ops dashboard | Ops dashboard (Vercel): Notifications panel | Events waiting, oldest waiting minutes, dead letters, failed emails in the last hour, rejected callbacks, emails of the last day by status |
| N16 | Webhook (optional) | Set `BREVO_WEBHOOK_TOKEN` in `backend/.env`, restart, then `curl -X POST http://localhost:8000/api/v1/webhooks/notifications/brevo -H "content-type: application/json" -H "authorization: Bearer <token>" -d "{\"event\":\"delivered\",\"message-id\":\"<id>\",\"ts_event\":<unix time>}"` | `{"status":"processed"}`, then `"duplicate"` on a repeat; a wrong token is `403` |

## 5c. Checking the Supabase database

```text
docker exec -it supabase_db_Abhijatri psql -U postgres
```

```sql
-- the sign-in identity (Supabase Auth) and the app profile share one id
select au.email, au.email_confirmed_at, u.display_name, u.status, u.email_verified_at, u.first_visit_on, u.last_visit_on
from auth.users au join public.users u on u.id = au.id order by au.created_at desc limit 5;

-- the Verified Member "tag": an approved verification
select u.email, v.verification_type, v.status, v.method, v.decided_at
from public.verifications v join public.users u on u.id = v.user_id order by v.decided_at desc;

-- staff roles, TOTP factors (Supabase Auth), notifications and the outbox
select u.email, r.role from user_roles r join users u on u.id = r.user_id where r.revoked_at is null;
select user_id, factor_type, status from auth.mfa_factors;
select kind, priority, audience, delivery_mode, read_at is not null as read, expires_at, created_at from notifications order by created_at desc limit 10;
select d.status, d.attempt_count, d.last_error_code, n.kind from notification_deliveries d left join notifications n on n.id = d.notification_id order by d.updated_at desc limit 10;
select topic, status, attempts, last_error_code, dedupe_key from outbox_events order by created_at desc limit 10;
select action, actor_role_snapshot, target_type, occurred_at from audit_events order by occurred_at desc limit 15;
```

Expected after D7: `email_confirmed_at` set, `status = active`, and one `VERIFIED_MEMBER | APPROVED | MANUAL_REVIEW` row for the member. Evidence files are in Storage, bucket `verification-evidence` (private): `select name, created_at from storage.objects where bucket_id = 'verification-evidence';`.
## 6. Cross-checks on the database

```text
docker exec supabase_db_Abhijatri psql -U postgres -c "select role, count(*) from user_roles where revoked_at is null group by 1"
docker exec supabase_db_Abhijatri psql -U postgres -c "select action, actor_role_snapshot, target_type, occurred_at from audit_events order by occurred_at desc limit 10"
docker exec supabase_db_Abhijatri psql -U postgres -c "select task_type, status, escalated, claimed_by is not null as held from moderation_tasks order by created_at desc limit 10"
```

## 7. Calling the API by hand (optional)

Cookies are `Secure`, so use a browser session or the helper in `backend/scripts/e2e_smoke.py`, which shows every call. Useful reads: `http://localhost:8000/docs` lists all routes. A staff request needs the session cookie, `X-CSRF-Token` (from `GET /api/v1/auth/csrf`) on writes, and `Origin: http://localhost:5175`.

## 8. If something is wrong

| Symptom | Cause and fix |
|---|---|
| "Could not reach the API" on any page | The API is not running, or `CORS_ALLOWED_ORIGINS` lacks that page's address. Fix and restart the API. |
| Sign-in works but the session is gone on reload | The browser rejected the cookies. Use Chrome or Edge on `http://localhost` (not `127.0.0.1`), and the same host for the page and the API. |
| `AUTH_NOT_CONFIGURED` (501) | `backend/.env` is missing the `SUPABASE_*` values, or the API was started before they were added. |
| Verification email never arrives | `supabase start` is not running, or look at http://127.0.0.1:54324. Auth sends at most one email per address every 10 seconds. |
| `bootstrap_admin` says "no verified account" | Register and click the verification link first. |
| "a superadmin already exists" | Only the first superadmin is created by the command; later ones are granted in the Staff tab. |
| Staff sign-in shows the QR but codes fail | Your phone's clock is off; set it to automatic time. |
| `429` on sign-in | Five wrong passwords for that email in 15 minutes. Wait, or use a different address. |
| Port 54321 or 54322 in use | Another Supabase stack is running; `supabase stop`, then start again. |
