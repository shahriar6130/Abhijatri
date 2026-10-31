# Abhijatri Moderation Dashboard: Architecture and API Specification

**Version:** 2.0 (31 October 2026). Restructures v1 (22 October 2026) into Frontend, Backend and Database parts and aligns it with the implemented system.
**Status:** Implemented 27 October 2026, except the items marked **Planned** (section 12).
**Base path:** every route below is under `/api/v1`.
**Companion documents:** `Docs/Notification-Documentation.md` (notifications), `Docs/api/API.md` 5.17 to 5.21 (wire contract), `Docs/Schema.md` (tables), `Docs/Decisions.md` (owner decisions), `Docs/System-Monitoring-Dashboard.md` (ops dashboard).

Where this document and `API.md` differ on a request or response shape, `API.md` and the OpenAPI snapshot (`Docs/api/openapi-v1.json`) win and this document is corrected.

---

## 1. Purpose and scope

The moderation dashboard is the staff workspace in which moderators and superadmins:

- review submitted reviews and their photos and videos (publish, hide, reject, restore);
- handle reports against published reviews;
- verify members, ask for clarification, and escalate exceptional cases;
- take down content, restrict or suspend accounts, and reverse those actions;
- decide appeals independently of the original decision-maker;
- manage staff roles (superadmins only);
- inspect the audit trail and queue health.

Every decision is authorised on the server, recorded in an append-only audit log, and produces its notification through the shared transactional outbox (Notification spec).

## 2. Review of the owner's design

The owner's draft (22 October 2026) proposed one login, a hybrid queue, routine verification by moderators with escalation, a private `/admin` URL that never logs out, per-moderator keys, 30-day retrieval of rejections, hide-but-still-count, suspensions, appeals and notifications. The verdict on each point:

| Proposal | Verdict | Resolution |
|---|---|---|
| One login page for members and staff | **Keep** | One Supabase Auth account. Staff are members with an active row in `user_roles`. |
| Hybrid queue (assigned plus claimable) | **Keep** | Database leases of 5 minutes, renewed by heartbeat. Superadmins can assign a task to a person. |
| Moderators verify routine cases, superadmins decide escalated ones | **Keep** | Enforced in the transition rule on the server, not just in the UI. Escalated cases need `superadmin`. |
| Private `www.abhijatri.com/admin` that "cannot be reached" | **Corrected** | The dashboard is a separate build on `admin.<owned-domain>` (`staff/`). Its privacy comes from authorisation, not the URL: non-staff get `404` from every `/admin/*` route. A secret URL is not a security boundary. |
| Access "never lost" until the role is removed | **Corrected** | Access lasts while the role is active **and** the session is valid. Sessions renew on use (refresh cookie 30 days), so an active moderator stays signed in. A superadmin idle for 8 hours signs in again. Revoking a role takes effect on the next request. A session that can never expire would be the single biggest risk in the system. |
| Assign roles from the dashboard during development, move to the database later | **Corrected** | Keep dashboard assignment permanently. It is safer than editing the database by hand, because it is serialised, needs a fresh password, protects the last superadmin, and is audited. Direct SQL edits skip all of that and should be used only for the first superadmin (`python -m app.jobs.bootstrap_admin`). |
| A key for each moderator and each task | **Replaced** | No reusable moderator secrets. Identity is the authenticated user id. Each task, case and request has a UUID and a request id. The audit log records actor, role snapshot, action, target and request id for every decision. |
| Reject goes to "Rejected" for 30 days with retrieval | **Keep, partly built** | Rejected verification cases and their evidence are purged after 30 days unless an appeal is open (implemented). A staff "Rejected" list and the 30-day purge of rejected reviews are **Planned** (P-03). |
| Hide: not public, but still counted in the rating | **Changed (owner, 31 Oct)** | A hidden review leaves the rating by default (Review.md line 476). For a takedown, the moderator may set `counts_toward_rating: true` to keep the rating of a genuine review hidden for a privacy problem. Wiring that flag into the rating is P-00. |
| Moderators see fellow moderators; only superadmins change roles | **Keep, partly built** | Role changes are superadmin-only (implemented). A read-only staff list for moderators is **Planned** (P-04). |
| Assign moderators from the Verified Members list | **Keep, partly built** | Today a superadmin finds a person by email. A Verified Members list, and a rule that a new moderator must be a Verified Member, are **Planned** (P-02). |
| Suspension ends automatically | **Keep, gap found** | Expiry is done by the retention job, which has no schedule in production yet. **Planned** (P-01): schedule it and also check the end time on every request. |
| Appeals and a full notification system | **Keep** | Implemented: 30-day appeal window (Asia/Dhaka), one appeal per decision, independent reviewer, notices on receipt and decision. |

### 2.1 Supabase Auth versus Platform Foundation 8.1

Platform Foundation 8.1 called for first-party authentication without Supabase Auth. On 27 October 2026 the owner chose Supabase Auth (`Docs/Decisions.md`). The decision stands, with the safeguard that kept Platform Foundation's intent: **the browser never calls Supabase.** The API proxies sign-up, sign-in, reset and TOTP, keeps tokens in `HttpOnly` `__Host-` cookies, and no Supabase key reaches either frontend.

## 3. Architecture

```
 Public app (Vite, app.<domain>)        Staff dashboard (Vite, admin.<domain>)
   member pages: verification,            Queue · Inbox · Media · Enforcement
   appeals, reports, notifications        Audit · Monitoring · Staff* · Notifications*
                \                                   /            (* superadmin)
                 \        HTTPS, cookies, CSRF      /
                  v                                v
                 FastAPI backend (/api/v1, Render, Singapore)
   auth proxy · role check · CSRF · idempotency · leases · transitions
   audit · outbox · notification worker (in process) · retention job
          |                    |                      |
          v                    v                      v
   Supabase Postgres    Supabase Storage        Upstash Redis
   (system of record)   (private buckets)       (counters only)
```

### 3.1 Database choice

**Recommendation: Supabase Postgres as the only system of record, Upstash Redis for counters only. Do not add Cassandra or MongoDB.**

| Store | Use in Abhijatri | Why |
|---|---|---|
| **Supabase Postgres** | Everything that must be correct: roles, tasks and leases, cases, sanctions, appeals, audit, outbox, notifications. | Moderation is transactional. A decision must change the review, write the action, the audit row and the outbox event in **one commit**, with row locks, unique constraints and version checks. Only a relational database gives that across tables. |
| **Upstash Redis** | Daily visit counters (in use). Later, if measured: a short role cache, rate limits, a fast queue signal. | Fast and cheap for disposable numbers. Never authoritative: if Redis is lost, no decision or task state is lost. |
| **Supabase Storage** | Verification evidence and review media in private buckets. | Files do not belong in table rows. Access only through short-lived signed URLs issued after a server-side check. |
| Cassandra | Not used. | Built for very large write volumes across data centres. It has no multi-row transactions or joins, which moderation needs. Abhijatri's volume is far below where it pays off. |
| MongoDB | Not used. | Moderation data is relational (case → task → action → appeal → audit). A second database would split the source of truth and break single-transaction decisions. |

Speed for the user comes from indexes, keyset pagination, small payloads and the outbox (the request returns before any email is sent), not from a second database. Revisit only when a measurement shows a need (section 11.4).

---

# Part A: Frontend

## 4. Applications

| App | Folder | Host | Users |
|---|---|---|---|
| Public app | `frontend/` | `app.<owned-domain>` (Vercel) | Guests and members |
| Staff dashboard | `staff/` | `admin.<owned-domain>` (Vercel) | Moderators and superadmins |
| Ops dashboard | `ops/` | separate, bearer token | Operator (System-Monitoring-Dashboard.md) |

Both Vite apps call the API with `credentials: 'include'`, send `X-CSRF-Token` on writes, and hold no Supabase key. The staff app reads `VITE_API_BASE_URL`.

## 5. Staff dashboard

### 5.1 Sign-in and session

1. The staff member signs in with the same email and password as on the public app (`POST /auth/login`).
2. The dashboard opens only when `GET /auth/session` returns `role` (`moderator` or `superadmin`) and `aal: "aal2"`. First-time staff enrol an authenticator (`POST /auth/mfa/enroll`, then `/auth/mfa/verify`). Later sign-ins ask for the 6-digit code.
3. A member without a role sees the sign-in screen only; the API answers `404` to every `/admin/*` call.
4. High-impact actions (role changes) ask for the password again (`POST /auth/reauth`, valid 10 minutes).
5. On `401 AUTH_REQUIRED` the app returns to sign-in; on `403 REAUTH_REQUIRED` it opens the password prompt and retries.

### 5.2 Screens

| Tab | Who | Purpose | API |
|---|---|---|---|
| Queue | staff | Reviews, reports, verification cases and appeals in one list, filterable by `task_type`. Claim, decide, escalate, release. | `GET /admin/queue`, task and decision routes |
| Inbox | staff | Staff notifications (assignments, escalations, alerts). Polls every 30 s. | `GET /notifications` |
| Media | staff | Recent photos and videos and their state; correct a decision. | `GET /admin/media`, `POST /admin/media/{id}/decision` |
| Enforcement | staff | Takedowns and account cases with their sanctions; open, remove, restore, reverse. | `/admin/enforcement-cases*` |
| Audit | staff | Search the audit trail by action, target, actor and date. | `GET /admin/audit-events` |
| Monitoring | staff | Queue depth, oldest task, escalations, expired claims, open reports, outbox backlog, denials. | `GET /admin/monitoring/summary` |
| Staff | superadmin | Find a person, grant or revoke `moderator` / `superadmin`. | `GET /admin/staff`, `GET /admin/users`, `POST /admin/staff/{id}/role` |
| Notifications | superadmin | Deliveries, outbox, suppressions, templates, rules. | Notification spec section 9 |

The tab list is a role-filtered array in `staff/src/App.tsx`. Hiding a tab is a convenience; the server refuses the call anyway.

### 5.3 Queue interaction rules

- **Claim before deciding.** "Open" calls `claim` and stores the returned `lease_token`. The decision form is disabled without a live lease.
- **Heartbeat** every 60 seconds while the task is open; the server lease is 5 minutes. A `moderation.task_lease_expiring` notice warns one minute before expiry.
- **Release** when the moderator leaves without deciding.
- **Send `expected_version`** with every decision. On `409 REVIEW_VERSION_CONFLICT` or `409 LEASE_LOST`, show "This item changed. Reload." and refetch. Never retry a decision automatically with a new version.
- **Send an `Idempotency-Key`** (one per decision attempt) so a double click or network retry cannot apply a decision twice.
- **Escalated items** show who they need. A moderator can see but not decide them (`403`).
- **Own content and own cases** cannot be decided (`403 SELF_MODERATION_FORBIDDEN`); the form says so.
- **Evidence** opens through a 60-second signed URL requested on click, never preloaded or cached.
- **Bulk actions** (up to 25) show the per-item result list the API returns; partial success is normal.

### 5.4 States every screen handles

Loading, empty, error with retry, offline (`NETWORK_ERROR`), stale (conflict, reload), and forbidden. Text is Bangla and English (`makeT`).

## 6. Public app (member side of moderation)

| Route | Purpose | API |
|---|---|---|
| `/account/verification` | Apply, upload evidence (up to 3 files, 5 MB, JPEG/PNG/PDF), answer clarification questions, withdraw. | `/verifications*` |
| `/account/reviews` | The member's reviews and their moderation state. | review routes |
| `/account/appeals` | Decisions that can be appealed, with deadline; file and withdraw appeals. | `GET /appeals/mine`, `POST /appeals` |
| Report button on a published review | Report with a reason code. | `POST /reviews/{id}/reports` |
| `/account/notifications` and the bell | Decisions and outcomes. | Notification spec |

Evidence files are uploaded straight to the one-time `upload_url` (private bucket) and confirmed with `.../complete`. The browser never sees a Storage key.

## 7. Extending the frontend

To add a new staff screen: add a component under `staff/src/screens/`, add one entry to the `tabs` array with its role condition, add its calls to `staff/src/api.ts`, and add its labels in both languages. The server route must exist and enforce the role first; the tab is only a view of it.

---

# Part B: Backend

## 8. Module map

| Module | Responsibility |
|---|---|
| `app/auth/` | Supabase Auth proxy, cookies, CSRF, TOTP, re-authentication, superadmin inactivity limit, `Principal` (user, current role, aal). |
| `app/admin/routes.py` | `/admin/*` HTTP layer. |
| `app/admin/tasks.py` | Queue, claim, heartbeat, release, assign, escalate (leases). |
| `app/admin/actions.py` | Review moderation decisions and bulk actions. |
| `app/admin/cases.py` | Verification, reports, enforcement, sanctions, appeals. |
| `app/admin/roles.py` | Staff role grant and revoke. |
| `app/admin/audit.py` | Append-only audit writes and queries. |
| `app/admin/idempotency.py` | Stored results for retried decisions. |
| `app/member_routes.py` | Member verification, appeals, reports, notifications. |
| `app/notify/` | Outbox events, worker, delivery (Notification spec). |
| `app/jobs/retention.py` | Purges and sanction expiry. |
| `app/jobs/bootstrap_admin.py`, `reset_mfa.py` | First superadmin; TOTP reset. |

## 9. Request pipeline

Every staff decision runs these steps in order, in **one** database transaction:

1. **Authenticate.** Read the session cookie; refresh once if expired; reject a disabled account (`403 ACCOUNT_DISABLED`).
2. **Authorise.** Read the role from `user_roles` in the database (never from the token or the body). No role: `404`. Role too low: `403`, written to the audit log as `denied.<action>`.
3. **CSRF and origin** for cookie-authenticated writes.
4. **Idempotency.** Same key and payload returns the stored result; same key, different payload is `409 IDEMPOTENCY_KEY_REUSED`.
5. **Lease.** The task is held by the caller with this `lease_token` and is not expired, else `409 LEASE_LOST`. A decision never reclaims a lease silently.
6. **State and version.** The target's current state allows the transition (`422 TRANSITION_NOT_ALLOWED`) and `expected_version` matches (`409 ..._VERSION_CONFLICT`).
7. **Policy checks.** Escalation role, self-moderation, evidence present, independent appeal reviewer.
8. **Write** the new state, the immutable action row, the audit row and the outbox event.
9. **Commit once.** Any failure rolls back all of it; no orphan audit or outbox rows.

The actor id always comes from the session. A `user_id`, `role` or `actor_id` in a request body is never trusted as authority.

## 10. Permission matrix (enforced on the server)

| Action | Member | Moderator | Superadmin |
|---|---|---|---|
| Submit a review, report a published review | Yes | Yes | Yes |
| Apply for verification, answer clarification | Yes | Yes | Yes |
| See and claim queue tasks | No | Yes | Yes |
| Publish, request changes, hide, reject, restore a review; decide media | No | Yes | Yes |
| Approve, reject, ask clarification on routine verification | No | Yes | Yes |
| Decide an escalated task or case | No | No | Yes |
| Open a takedown, warning or posting restriction | No | Yes | Yes |
| Apply a suspension | No | No | Yes |
| Emergency takedown follow-up | No | No | Yes |
| Decide an appeal | No | Yes, if not the original decider | Yes, if not the original decider |
| Assign a task to a person | No | No | Yes |
| Grant or revoke staff roles | No | No | Yes, with password within 10 min |
| Read audit events, monitoring summary | No | Yes | Yes |
| Notification operations (deliveries, templates, suppressions) | No | No | Yes |
| Decide one's own review, case or appeal | No | No | No |

## 11. Workflows

### 11.1 State machines

The server rejects any transition not listed. There is no generic "set status" endpoint.

**Review moderation** (`reviews.status`, decision via `moderation-actions`)

| From | Decision | To | Effect on rating |
|---|---|---|---|
| `PENDING`, `UNDER_REVIEW` | `PUBLISH` | `PUBLISHED` | Counted |
| `PENDING`, `UNDER_REVIEW` | `REQUEST_CHANGES` | `CHANGES_REQUESTED` (author edits and resubmits) | Not counted |
| `PENDING`, `UNDER_REVIEW` | `REJECT` | `REJECTED` | Not counted |
| `PUBLISHED` | `HIDE` | `HIDDEN` | Removed from the rating. A takedown with `counts_toward_rating: true` keeps it (P-00, owner decision 31 Oct) |
| `HIDDEN` | `RESTORE` | `PUBLISHED` | Counted again |

Every rating change goes through the locked delta path on `destination_rating_stats`, in the same transaction as the decision.

**Verification case**: `submitted → in_review → needs_clarification → in_review → approved | rejected`; any review state `→ escalated` (superadmin decides); applicant may `withdraw`. Approval needs at least one uploaded file and writes a `verifications` row. Verification and staff role are separate.

**Report**: `open → in_review | actioned | dismissed`; `in_review → actioned | dismissed`.

**Enforcement case and sanction**: opening a case on a review hides it and records `counts_toward_rating`. Actions: `remove`, `restore`, `close`, `reverse_sanction`. Sanction kinds: `warning`, `posting_restriction`, `suspension` (superadmin only; disables the account while active). Every sanction has `ends_at` or `review_on`. Emergency takedowns get `follow_up_due_at` (24 h) and a superadmin task.

**Appeal**: `received → in_review → upheld | overturned`; `withdrawn` while open. Overturning restores a hidden review, returns a rejected review to the queue, grants a rejected verification, or reverses an enforcement and its sanctions. The original decision row is kept.

### 11.2 Appeal policy

- Appealable: review moderation actions, enforcement cases, verification decisions.
- Deadline: end of the 30th day after the decision, Asia/Dhaka (`409 APPEAL_WINDOW_CLOSED`).
- One appeal per decision (`409 DUPLICATE_APPEAL`), including after it is decided; a withdrawn appeal may be filed again.
- Reviewer must not be the original decider (`403 APPEAL_REVIEWER_NOT_INDEPENDENT`).
- An open appeal blocks deletion of the evidence and notifications it relates to.

### 11.3 Background jobs

| Job | How it runs | Does |
|---|---|---|
| Notification worker | Thread in the API process, every 2 s; scanners every 60 s | Outbox to notifications and email, digests, alerts (lease expiring, queue overdue, escalations, denials). |
| Retention | `python -m app.jobs.retention` (**no schedule yet**, P-01) | Purges decided verification evidence (24 h after approval, 30 days after rejection or withdrawal), expired notifications, processed outbox rows after 30 days; expires sanctions. Re-checks open appeals under a row lock immediately before deleting. |

### 11.4 Scaling path

Each step is triggered by a measurement, not by expectation:

1. **Worker out of the API process** when the API runs more than one instance or the free plan's sleep delays notifications. The worker is already safe to run in parallel (`FOR UPDATE SKIP LOCKED`).
2. **Role cache in Redis** (TTL 60 s, invalidated on change) for read-only screens if role lookups show up in latency. Decisions keep reading the database.
3. **Audit partitioning by month** when `audit_events` passes about 10 million rows. `id` must stay globally unique so `GET /admin/audit-events/{id}` keeps working.
4. **A Redis queue (or similar)** only if outbox lag stays above the 10-minute alert under normal load.

## 12. Endpoint reference

Conventions: staff routes need a session with a role and `aal2` (non-staff `404`, lower role `403`); writes need `X-CSRF-Token`; decisions accept `Idempotency-Key`; all responses are `no-store`. Full bodies are in `API.md` 5.18 and 5.19.

### 12.1 Authentication (`/auth`)

| Method | Route | Purpose |
|---|---|---|
| POST | `/auth/register`, `/auth/verify-email`, `/auth/resend-verification` | Account and email confirmation |
| POST | `/auth/login`, `/auth/logout` | Session cookies |
| GET | `/auth/session`, `/auth/csrf` | Session payload with `role` and `aal`; CSRF token |
| POST | `/auth/password-reset/request`, `/auth/password-reset/confirm` | Reset; ends every session |
| POST | `/auth/mfa/enroll`, `/auth/mfa/verify` | TOTP enrolment and step-up to `aal2` |
| POST | `/auth/reauth` | Fresh password for high-impact actions |

### 12.2 Queue and tasks

| Method | Route | Who | Purpose |
|---|---|---|---|
| GET | `/admin/queue?task_type=&limit=` | staff | Open tasks, oldest and highest priority first, with `claimable` and `lease_active` |
| POST | `/admin/tasks/{task_id}/claim` | staff | Take a 5-minute lease |
| POST | `/admin/tasks/{task_id}/heartbeat` | holder | Extend the lease |
| POST | `/admin/tasks/{task_id}/release` | holder | Return to the shared queue |
| POST | `/admin/tasks/{task_id}/escalate` | holder | Needs a superadmin; lease ends |
| POST | `/admin/tasks/{task_id}/assign` | superadmin | Assign to a person or unassign (`user_id: null`) |

### 12.3 Content

| Method | Route | Who | Purpose |
|---|---|---|---|
| POST | `/admin/submissions/{review_id}/moderation-actions` | staff | `PUBLISH`, `REQUEST_CHANGES`, `REJECT`, `HIDE`, `RESTORE`; optional `rejected_media_ids` (API.md 5.18 still omits `REQUEST_CHANGES` and should be updated) |
| POST | `/admin/submissions/{review_id}/conflict` | staff | Declare a conflict of interest |
| POST | `/admin/bulk/moderation-actions` | staff | Up to 25 decisions, per-item result |
| POST | `/admin/submissions/{review_id}/media/{media_id}/url` | staff | 5-minute signed URL to inspect media |
| GET | `/admin/media?state=&limit=` | staff | Recent media |
| POST | `/admin/media/{media_id}/decision` | staff | Correct a media decision |
| POST | `/reviews/{review_id}/reports` | member | Report a published review |
| POST | `/admin/reports/{report_id}/transition` | staff | `in_review`, `actioned`, `dismissed` |

### 12.4 Verification

| Method | Route | Who | Purpose |
|---|---|---|---|
| GET | `/verifications/mine` | member | Own case and evidence state |
| POST | `/verifications` | member | Open a case |
| POST | `/verifications/{case_id}/evidence` | applicant | One-time upload URL |
| POST | `/verifications/{case_id}/evidence/{evidence_id}/complete` | applicant | Confirm the upload |
| POST | `/verifications/{case_id}/respond` | applicant | Answer clarification; back to the queue |
| POST | `/verifications/{case_id}/withdraw` | applicant | Withdraw |
| POST | `/admin/verification-cases/{case_id}/transition` | staff holding the task | `in_review`, `needs_clarification` (needs `note`), `approved`, `rejected`, `escalated` |
| POST | `/admin/verification-cases/{case_id}/evidence/{evidence_id}/url` | holder or superadmin | 60-second signed URL; audited `evidence.viewed` |

### 12.5 Enforcement and appeals

| Method | Route | Who | Purpose |
|---|---|---|---|
| GET | `/admin/enforcement-cases?state=` | staff | Cases with review or account and sanctions |
| POST | `/admin/enforcement-cases` | staff (suspension: superadmin) | Takedown or account action, optional sanction, `emergency`, `counts_toward_rating` |
| POST | `/admin/enforcement-cases/{case_id}/actions` | staff (emergency: superadmin) | `remove`, `restore`, `close`, `reverse_sanction` |
| GET | `/appeals/mine` | member | Own appeals and appealable decisions with deadlines |
| POST | `/appeals` | member with standing | File an appeal |
| POST | `/appeals/{appeal_id}/withdraw` | appellant | Withdraw |
| POST | `/admin/appeals/{appeal_id}/decision` | staff holding the task, not the original decider | `upheld` or `overturned` with `note` |

### 12.6 Staff, audit and monitoring

| Method | Route | Who | Purpose |
|---|---|---|---|
| GET | `/admin/staff` | superadmin | Active staff and roles |
| GET | `/admin/users?q=` | superadmin | Find an account by email (3+ characters, 10 rows) |
| POST | `/admin/staff/{user_id}/role` | superadmin, fresh password | `moderator`, `superadmin` or `null`; `409 LAST_SUPERADMIN` |
| GET | `/admin/audit-events?action=&target_type=&target_id=&actor_user_id=&before=&limit=` | staff | Audit search, newest first |
| GET | `/admin/audit-events/{event_id}` | staff | One event (`id` is globally unique) |
| GET | `/admin/monitoring/summary` | staff | Queue and system health counters |

### 12.7 Planned (gaps against the owner's design)

| ID | Change | Endpoint or job | Why |
|---|---|---|---|
| P-00 | **Decided 31 Oct 2026 (owner):** hidden reviews are not counted by default; a takedown with `counts_toward_rating: true` keeps the rating | In `open_enforcement` and the enforcement `actions` route, pass the flag to the rating delta path: when `true`, hiding keeps the review's counted rating (`rating_eligibility` stays eligible); when changed later, move the aggregate under the same lock. Plain `HIDE` from the queue always removes the rating. | The flag is stored today but has no effect, so the stored value and the rating can disagree. |
| P-01 | Schedule retention and check sanction end time on every request | `POST /ops/jobs/retention` (ops token) called by a GitHub Actions cron like `visit-rollup.yml`; `_set_account_state` and `ensure_not_restricted` treat `ends_at < now` as expired and reverse it lazily | Today a suspension only ends when someone runs the job by hand. Expiry must not depend on one job. |
| P-02 | Verified Members list; new moderators must be Verified Members | `GET /admin/members?verified=true&q=&after=&limit=` (superadmin); `POST /admin/staff/{id}/role` returns `422 NOT_VERIFIED_MEMBER` for `moderator` | Owner design: moderators are chosen from verified members. |
| P-03 | Rejected and Hidden lists with 30-day recovery for reviews | `GET /admin/reviews?status=REJECTED\|HIDDEN&after=&limit=` (staff), each with `recoverable_until`; `POST /admin/submissions/{id}/moderation-actions` `REOPEN` (`REJECTED → PENDING`, superadmin, within 30 days); retention purges rejected review bodies and media after 30 days unless an appeal is open | Owner design: "Rejected" and "Hidden" segments, 30-day retrieval. |
| P-04 | Moderators see fellow moderators | `GET /admin/staff` open to moderators with `display_name` and `role` only (no email) | Owner design. |
| P-05 | Superadmin reopens a rejected verification within 30 days | `POST /admin/verification-cases/{id}/reopen` (`rejected → in_review`, reason required) | Today only an appeal can reverse it. |
| P-06 | Explicit reason codes catalogue | `GET /admin/reason-codes` from one server list | Consistent decisions; the UI stops hard-coding codes. |

## 13. Errors

| Status | Code | Meaning |
|---|---|---|
| 401 | `AUTH_REQUIRED` | No valid session |
| 403 | `ACCOUNT_DISABLED`, `ACCOUNT_RESTRICTED` | Account suspended or restricted |
| 403 | `FORBIDDEN`, `REAUTH_REQUIRED`, `SELF_MODERATION_FORBIDDEN`, `APPEAL_REVIEWER_NOT_INDEPENDENT` | Staff, but not allowed |
| 404 | `NOT_FOUND` | Missing, or a staff route for a non-staff caller |
| 409 | `LEASE_LOST`, `TASK_NOT_AVAILABLE`, `REVIEW_VERSION_CONFLICT`, `IDEMPOTENCY_KEY_REUSED`, `LAST_SUPERADMIN`, `DUPLICATE_APPEAL`, `APPEAL_WINDOW_CLOSED`, `DUPLICATE_OPEN_REPORT`, `VERIFICATION_ALREADY_OPEN` | Conflict; reload or stop |
| 422 | `TRANSITION_NOT_ALLOWED`, `EVIDENCE_REQUIRED`, `VALIDATION_FAILED` | Business or input rule |
| 429 | `RATE_LIMITED` | Too many requests |

Clients branch on `code`, never on `message`. No response carries SQL, stack traces, secrets or signed URLs to someone not entitled to them.

## 14. Security rules

1. Authorisation is read from the database on every staff request. A revoked role stops working on the next request, even with a valid session.
2. Staff need TOTP (`aal2`). Superadmins sign in again after 8 hours idle. Role changes need a password entered within 10 minutes.
3. The last superadmin cannot be removed; superadmin changes are serialised on `role_admin_guard`.
4. No Supabase key, service-role key or Storage path is ever sent to a browser.
5. Evidence and media are in private buckets; signed URLs last 60 s (evidence) or 5 min (media) and every evidence view is audited.
6. Audit rows cannot be updated, deleted or truncated (database triggers). They contain no passwords, tokens, document images or email bodies.
7. Denied staff attempts are audited; repeated denials raise `moderation.security_anomaly`.
8. Test the negative path: every staff route is tested for anonymous, member, moderator, revoked-role and disabled-account callers.

## 15. Extending the backend: adding a new workflow

Example: a new task type such as "destination edit suggestion".

1. **Database:** add the subject table with `state` and `version`; add the type to `ck_moderation_tasks_type`; one migration.
2. **Transitions:** write a transition table (from, to, role, required fields) in a new function in `app/admin/cases.py` (or a new module), following the pipeline in section 9.
3. **Route:** `POST /admin/<subjects>/{id}/transition` in `app/admin/routes.py`, using the existing role, lease, idempotency and audit helpers.
4. **Queue:** create a `moderation_tasks` row when the subject is submitted; the queue, claim, lease, assign and monitoring work without change.
5. **Notifications:** emit an outbox event and add a rule and template in `app/notify/registry.py` (Notification spec 18).
6. **Appeals:** if appealable, add a typed foreign key column to `appeals` and extend `ck_appeals_one_target`.
7. **Tests:** authorisation for every role, stale version, lost lease, double submit, and rollback leaving no audit or outbox row.
8. **Docs:** add the routes to `API.md`, the table to `Schema.md`, the decision to `Decisions.md`.

---

# Part C: Database

## 16. Tables

All tables are in Supabase Postgres. RLS is on for every table and the `anon` and `authenticated` roles have **no grants**; only the API's database role reads or writes them.

| Area | Table | Key constraints |
|---|---|---|
| Identity | `users` | `id` = Supabase Auth user id; `status` `active`/`disabled` |
| Roles | `user_roles` | `role` in (`moderator`, `superadmin`); partial unique `(user_id) WHERE revoked_at IS NULL`; granted/revoked by and at |
| Roles | `role_admin_guard` | Single row locked `FOR UPDATE` for superadmin changes |
| Sessions | `auth_session_activity` | Last request per session for the 8-hour superadmin limit; no token stored |
| Queue | `moderation_tasks` | type, subject, status, `required_role`, `escalated`, `assigned_to`, `claimed_by`, `lease_expires_at`, `lease_token`, `version`; partial unique `(task_type, subject_id) WHERE status = 'open'` |
| Content | `reviews`, `review_revisions`, `review_media` | Review state machine, `version`, `counted_rating`; media states |
| Content | `moderation_actions` | Append-only decision history |
| Reports | `reports` | One open report per reporter and review |
| Verification | `verification_cases`, `verification_evidence`, `verifications` | One open case per applicant; `purge_after`; evidence metadata only (files in Storage) |
| Enforcement | `enforcement_cases`, `sanctions` | Exactly one subject (review or user); `counts_toward_rating`; `follow_up_due_at`; sanction needs an end or review date |
| Appeals | `appeals` | Typed foreign keys to the three target tables, exactly one set; one non-withdrawn appeal per target; deadline; original decider |
| Audit | `audit_events` | Globally unique `id`; triggers refuse UPDATE, DELETE, TRUNCATE; no FK to `users` so the log outlives accounts |
| Retries | `idempotency_keys` | PK `(actor_user_id, operation, key)`, request fingerprint, stored result |
| Outbox | `outbox_events` | Shared with notifications; unique `dedupe_key` |

The Notification tables are listed in the Notification spec, Part C.

## 17. Concurrency in the database

- **Claims:** the task row is locked (`SELECT ... FOR UPDATE`), then status, role eligibility, assignment and live lease are checked inside the lock. Another live lease means `409 TASK_NOT_AVAILABLE`. A task assigned to someone else can be claimed only by a superadmin.
- **Decisions:** `UPDATE ... WHERE id = :id AND version = :expected_version` and `version = version + 1`; zero rows means `409`.
- **Superadmin changes:** lock `role_admin_guard`, re-count active superadmins inside the lock, then change.
- **Appeal versus purge:** the retention job locks the case and re-checks for an open appeal before deleting; filing an appeal locks the same row.

## 18. Retention

| Data | Kept | Then |
|---|---|---|
| Verification evidence, approved case | 24 hours after approval | File deleted |
| Rejected or withdrawn verification case and evidence | 30 days | Row and files deleted (unless an appeal is open) |
| Rejected review | Indefinitely today | **Planned** P-03: body and media purged after 30 days unless appealed |
| Sanctions, enforcement cases, appeals, moderation actions | Kept (account history) | Revisit with a privacy review |
| Audit events | Kept, append-only | Partition and archive when large (11.4) |
| Notifications | 90 days; critical 24 months; longer while an appeal is open | Deleted |
| Processed outbox events | 30 days | Deleted |
| Media uploads not completed | 24 hours | Deleted |

`purge_after` makes a row a candidate; it never overrides an open appeal.

## 19. Storage buckets

| Bucket | Content | Access |
|---|---|---|
| `verification-evidence` | ID documents and other proof | Private; one-time upload URL; 60 s signed read URL for the holder of the case or a superadmin |
| `review-media` | Review photos and video (`quarantine/` until checked) | Private; staff 5-minute URL; public feed 1-hour signed URL for approved media only |

## 20. Redis

Redis holds the daily visit counters (`abj:{env}:visits:{date}`, 8-day TTL) and nothing from moderation. If Redis is unavailable, moderation is unaffected. Any future use (role cache, rate limit) must be safe to lose and must never decide a write.

---

# Part D: Verification

## 21. Acceptance tests

Implemented in `backend/tests/` on PostgreSQL. Each must keep passing:

1. A user cannot hold two active staff roles.
2. Two concurrent revocations cannot remove the last superadmin.
3. A revoked moderator is refused on the next request.
4. Two staff cannot hold valid leases on the same task.
5. A moderator cannot decide an escalated task from a stale tab.
6. A stale version cannot overwrite a newer decision.
7. A failed decision leaves no audit or outbox row; a successful one always has both.
8. A reused idempotency key with another payload returns `409`.
9. A late or duplicate appeal is refused; the original decider cannot decide the appeal.
10. An open appeal blocks evidence and notification purges.
11. Members and other staff cannot read private evidence.
12. Bulk responses report each item.

Tests to add with the Planned items: P-01 (an expired suspension stops blocking at once even if the job has not run), P-02 (granting `moderator` to an unverified member is refused), P-03 (a rejected review can be reopened on day 29 and is purged after day 30 unless appealed).
