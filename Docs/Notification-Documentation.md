# Abhijatri Notification System: Architecture and API Specification

**Version:** 2.0 (31 October 2026). Restructures v1.1 into Frontend, Backend and Database parts and aligns it with the implemented system.
**Status:** Implemented 28 October 2026, except the items marked **Planned** (section 16).
**Channels:** in-app inbox and email. Push and SMS are future channels (section 17.2).
**Base path:** every route below is under `/api/v1`.
**Companion documents:** `Docs/Moderation-Dashboard-Specification.md` (the workflows that produce events), `Docs/api/API.md` 5.21 (wire contract), `Docs/Schema.md`, `Docs/Decisions.md`.

Where this document and `API.md` differ on a request or response shape, `API.md` and the OpenAPI snapshot win and this document is corrected.

---

## 1. Purpose and guarantees

The notification system tells members, moderators and superadmins about decisions and work that concern them, reliably and without leaking anything they are not entitled to see.

| Guarantee | How it is met |
|---|---|
| No decision without its event | The business change, its audit row and its outbox event commit in one transaction. A rolled-back decision leaves no event. |
| No duplicate inbox items | One notification per `(event, recipient, kind)`, enforced by a unique index. Retries and parallel workers are safe. |
| Honest email delivery | Email is at-least-once and best effort. A timeout is recorded as `ambiguous` and never resent automatically. No exactly-once claim. |
| The inbox is the truth | Live updates (Server-Sent Events) only signal; the page refetches after any reconnect. |
| No leaks | Payloads and templates carry only allowlisted variables. No ID images, tokens, internal notes or email addresses in payloads, logs or API responses. |
| Role boundaries | Staff notices are shown only while the person still holds a staff role. A revoked moderator is told about the revocation but loses earlier staff notices. |
| Notifications are not the record | The decision, audit event and appeal remain authoritative; deleting a notification deletes nothing else. |

## 2. Review of the owner's requirements

| Requirement (owner draft, 22 Oct) | Verdict | Resolution |
|---|---|---|
| A proper notification system for every moderation outcome | **Keep** | Every workflow emits a catalogued event (section 6). |
| Moderator emails the member for clarification (unclear ID image, ambiguous details) | **Corrected** | Moderators do not send email from their own accounts. They set the case to `needs_clarification` with a question; the system sends a templated notice with a link to `/account/verification`. The question is the only free text, and it is recorded. No document is attached to any email. |
| Members are told in detail about suspension, removal and verification results | **Keep** | Each notice states what happened and, where appealable, says "appeal within 30 days" and links to `/account/appeals`. Detail stays behind sign-in; emails stay short. |
| Notify on appeal | **Keep** | Receipt (with reference and deadline) and decision notices to the member; a queue notice to staff. |
| Monitoring of moderators and failures | **Keep** | Alerts for queue overdue, lease expiry, escalations, repeated denials, delivery failures, outbox backlog and webhook anomalies, plus the independent ops dashboard panel. |
| Fast, reliable delivery for a good user experience | **Keep** | The request returns as soon as the decision commits. The worker turns events into notifications within seconds and sends critical email at once. |

## 3. Architecture

```
 business request (moderation, verification, appeal, role change, sanction)
        |  one transaction
        v
 state change + audit_events row + outbox_events row (dedupe_key, recipient policy)
        |
        v  notification worker (claims with FOR UPDATE SKIP LOCKED, lease, every 2 s)
 rules (registry.py) -> resolve recipients -> render template (bn + en)
        |  one short transaction
        v
 notifications (inbox)  +  notification_deliveries (email, if due now)
        |                                   |
        v                                   v  no transaction open during the call
 GET /notifications, SSE stream        email provider (Brevo / Resend / SMTP / Gmail)
        |                                   |
 bell, inbox page, staff inbox         attempt row; provider webhook -> delivered / bounced
```

### 3.1 Database choice

**Recommendation: Supabase Postgres is the only store for notifications. Use Upstash Redis later only as a fan-out signal for live updates. Do not use Cassandra or MongoDB.**

| Store | Role | Reason |
|---|---|---|
| **Supabase Postgres** | Outbox, inbox, deliveries, attempts, templates, rules, preferences, suppressions, digests. | The event must commit with the decision that caused it, and inbox creation must be idempotent across retries. Both need transactions and unique constraints in the same database as the moderation tables. |
| **Upstash Redis** | Not used by notifications today. Planned use: pub/sub to wake live streams (P-N2). | Live signals are disposable, so a fast cache suits them. Losing Redis must only delay the bell, never lose a notification. |
| Cassandra | Not used. | Suits huge append-only write volumes; Abhijatri's inbox volume is small and needs joins and transactions. |
| MongoDB | Not used. | Would split the outbox from the decisions and break the one-transaction guarantee. |

A queue product such as BullMQ or SQS is not needed while the Postgres outbox keeps up. The trigger to add one is the outbox backlog alert (older than 10 minutes) firing under normal load.

## 4. Roles and what each receives

| Recipient | Receives | Where |
|---|---|---|
| Member | Outcomes of their reviews, reports, verification, appeals, account actions, security notices | Public app bell and `/account/notifications`; email |
| Moderator | Assignments, lease expiry, escalation result, new verification requests and appeals in the queue, queue overdue | Staff dashboard Inbox; email for high priority |
| Superadmin | Everything a moderator gets, plus escalations needing a decision, emergency takedowns, role changes, security anomalies and notification-system alerts | Staff dashboard Inbox; email |

Staff are members, so every staff member also gets member notices about their own content and account.

## 5. Priority and delivery mode

These are separate. Priority says how urgent; delivery mode says how email is sent.

| Priority | Email | Can the person turn email off? |
|---|---|---|
| `critical` | Immediately | No |
| `high` | Immediately | No |
| `normal` | By preference: `immediate`, `digest` (default, daily at local time, default 08:00 Asia/Dhaka) or `off` | Yes |
| `low` | By preference | Yes |

The in-app notice is always created, whatever the email preference. A rule may be set to `email: false` (for example the lease warning, which is useful only on screen).

## 6. Event catalogue

Events come from successful business actions only. The catalogue is code (`app/notify/registry.py`); superadmins can tune priority, email and enabled per rule but cannot add events, recipients or links from the database.

### 6.1 Member notices

| Event | Notice kind | Priority | Link |
|---|---|---|---|
| `review.state_changed` (PUBLISH) | `content.published` | normal | destination page |
| `review.state_changed` (REQUEST_CHANGES) | `content.changes_requested` | high | `/account` |
| `review.state_changed` (REJECT) | `content.rejected` | critical | `/account/appeals` |
| `review.state_changed` (HIDE) | `content.hidden` | critical | `/account/appeals` |
| `review.state_changed` (RESTORE) | `content.restored` | normal | destination page |
| `enforcement.opened` (takedown) | `content.taken_down` | critical | `/account/appeals` |
| `enforcement.opened` (account) | `account.case_opened` | critical | `/account/appeals` |
| `enforcement.state_changed` | `content.restored`, `content.removed`, `account.removed` | normal / critical | `/account/appeals` |
| `sanction.created` | `account.warning`, `account.restricted`, `account.suspended` | critical | `/account/appeals` |
| `sanction.ended` | `account.restriction_lifted`, `account.suspension_lifted` | critical | none |
| `verification.submitted` | `verification.submitted` | normal | `/account/verification` |
| `verification.state_changed` | `verification.clarification_requested` (with `{question}`), `verification.approved`, `verification.rejected` | high / critical | `/account/verification`, `/account/appeals` |
| `appeal.received` | `appeal.received` (with `{reference}`, `{deadline}`) | critical | `/account/appeals` |
| `appeal.decided` | `appeal.decided` (with `{reference}`, `{outcome}`) | critical | `/account/appeals` |
| `report.state_changed` | `report.actioned`, `report.dismissed` | normal | none |
| `security.password_changed` | `security.account_action_required` | critical | `/account/notifications` |
| `security.mfa_reset` | `security.mfa_reset` | critical | staff dashboard |
| `staff.role_changed` | `staff.role_granted` (with `{role}`), `staff.role_revoked` | critical | staff dashboard / none |

### 6.2 Staff notices

| Event | Notice kind | Recipients | Priority |
|---|---|---|---|
| `verification.submitted` | `staff.verification_submitted` | staff captured at event time | normal |
| `appeal.received` | `appeal.submitted` | staff captured at event time | normal |
| `task.assigned` | `moderation.task_assigned`, `moderation.appeal_assigned`; `moderation.task_unassigned` to the previous assignee | the named person | high / normal |
| `task.lease_expiring` | `moderation.task_lease_expiring` (no email) | the lease holder | high |
| `task.escalated` | `moderation.escalated` (no email) to the holder; `moderation.escalation_required` to superadmins | holder; superadmins | normal / high |
| `moderation.queue_overdue` | `moderation.queue_overdue` (`{count}` tasks older than 24 h, daily) | moderators | normal |
| `enforcement.opened` (emergency) | `moderation.emergency_takedown` | superadmins | critical |
| `moderation.security_anomaly` | `moderation.security_anomaly` (`{count}` denials) | superadmins | high |
| `staff.role_changed` | `staff.role_changed` | superadmins | normal |
| `notification.delivery_failure_threshold_reached` | same | superadmins | high |
| `notification.outbox_backlog_threshold_reached` | same | superadmins | high |
| `notification.provider_webhook_anomaly` | same | superadmins | high |

`verification.expired` and `account.removal_requested` are catalogued but have no workflow in v1 and are never emitted.

---

# Part A: Frontend

## 7. Public app

| Element | File | Behaviour |
|---|---|---|
| Bell | `frontend/src/components/layout/NotificationBell.tsx` | Unread count, latest items, link to the inbox. Opens an `EventSource` on `/notifications/stream`; on reconnect it refetches the inbox and shows "Live updates paused; reconnecting" while down. |
| Inbox page | `/account/notifications` (`NotificationsPage.tsx`) | Paginated (cursor), unread filter, archived view, mark read, archive, mark all read. Each item shows category, time and an action link from the allowlisted route list. |
| Preferences | same page | Standard email `immediate`, `digest` or `off`; time zone; local digest time. Shows that critical and high-priority email cannot be turned off. |
| API client | `frontend/src/api/account.ts` | Cookie session, CSRF header on writes, no Supabase key. |

Text is stored in Bangla and English side by side; the page shows the user's language. Detail stays on authenticated pages (verification, appeals); notifications carry a short summary and a link.

## 8. Staff dashboard

| Tab | Who | Behaviour |
|---|---|---|
| Inbox | staff | Same `GET /notifications` feed (staff and member items), polled every 30 s. |
| Notifications | superadmin | Deliveries with status counts and attempt history; outbox by status with oldest pending age; suppressions (HMAC prefix only, add with reason, remove with reason); templates (versions per channel and language, create draft, activate); rules (priority, email, enabled). |

Links with the `staff:/` prefix open the staff dashboard; all others open the public app. The frontend never builds a link from user input.

## 9. States every view handles

Loading, empty, error with retry, offline, stale after reconnect (refetch), and for superadmin views, forbidden (`403`) if the role was revoked during the session.

---

# Part B: Backend

## 10. Module map

| Module | Responsibility |
|---|---|
| `app/notify/events.py` | `emit()`: writes the outbox row inside the caller's transaction, captures staff recipients, sets `dedupe_key`. |
| `app/notify/registry.py` | Catalogue: templates (code-defined version 1), rules (event → kind, resolver, priority, audience, route, conditions), allowed variables and routes. Self-checks at import. |
| `app/notify/messages.py` | Recipient resolvers (`payload_user`, `captured_staff`) and rendering. |
| `app/notify/worker.py` | Outbox relay loop (every 2 s), defaults sync, scanners (every 60 s). |
| `app/notify/delivery.py` | Email sending, retries, ambiguous handling, digests. |
| `app/notify/providers.py` | Provider adapters: `mailpit`, `resend`, `brevo`, `smtp`, `gmail`, `none`, and a recording provider for tests. Selected by `EMAIL_PROVIDER`. |
| `app/notify/webhooks.py` | Signed provider callbacks, deduplication, bounce and complaint suppression. |
| `app/notify/alerts.py` | Deduplicated operational alerts (also logged at ERROR). |
| `app/notify/admin_routes.py` | Superadmin monitoring, suppressions, templates, rules. |
| `app/member_routes.py` | Inbox, preferences, SSE stream. |
| `app/jobs/retention.py` | Expiry of notifications and processed outbox rows. |

## 11. Processing pipeline

1. **Emit.** A producer calls `events.emit()` inside its business transaction. The row holds `topic` (event type), `aggregate_type`/`id`/`version`, `dedupe_key` (unique), a minimal schema-checked payload, the `recipient_policy` and any captured staff ids.
2. **Claim.** The worker selects due events (`pending`, `retry`, or `processing` with an expired lease) with `FOR UPDATE SKIP LOCKED`, records itself as lease owner, and commits.
3. **Process** each event in one short transaction: match rules, resolve recipients, render the active template version, insert notifications with `ON CONFLICT DO NOTHING`, decide each one's email mode, queue immediate deliveries, mark the event `processed`.
4. **Fail safely.** An error moves the event to `retry` with backoff; after 6 tries it becomes `dead_letter`, visible to superadmins and the ops dashboard.
5. **Send email** in `delivery.send_due` with **no transaction open** during the provider call; record an attempt row and the result.
6. **Signal.** Open SSE streams pick up new rows; clients refetch on reconnect.
7. **Scan** every 60 s: build due digests and raise alerts.

### 11.1 Recipient resolution

- `payload_user`: the person named in the event (author, applicant, appellant, reporter, assignee, target of a role change).
- `captured_staff`: staff ids captured **when the event happened**, re-checked against their **current** role when the notice is created. Someone who lost the role, or no longer holds the required role (`role=superadmin` rules), gets nothing.
- A role-revocation notice is a member notice, so it still reaches the person who lost the role.
- Email addresses are never recipient identity. The current verified address is read at send time. An unverified or suppressed address makes the delivery `skipped` with a reason; the inbox item stays.

### 11.2 Email delivery and retries

| Situation | Result |
|---|---|
| Provider accepted | `accepted`; a webhook may later mark `delivered` or `bounced` |
| Temporary error or 429 | Retry after about 1 min, 5 min, 30 min, 2 h (±10 % jitter), then `failed_permanently` |
| 4xx other than 429 | `failed_permanently` at once |
| Timeout after sending, or worker died mid-send | `ambiguous`; never resent automatically; a superadmin may retry after checking |
| Hard bounce or complaint (webhook) | Delivery `bounced`; address added to suppressions |

Every attempt writes a row in `notification_delivery_attempts`. Error summaries are redacted.

### 11.3 Digest

At each person's local digest time, eligible normal and low-priority items not yet emailed are gathered into one digest (unique per person and local day), linked back by `notifications.digest_id`, and sent as one delivery. Critical and high items never wait for a digest. Re-running the job cannot send the same digest twice.

### 11.4 Alerts

| Alert | Trigger | To |
|---|---|---|
| Lease expiring | 1 minute before a claim lapses | Lease holder |
| Queue overdue | Tasks open longer than 24 h, once a day | Moderators |
| Escalation required | Task escalated | Superadmins |
| Security anomaly | Repeated `403` denials from one staff account | Superadmins |
| Delivery failures | 5 or more failures in an hour | Superadmins |
| Outbox backlog | Oldest unprocessed event older than 10 minutes | Superadmins |
| Webhook anomaly | 5 or more failed signature checks in an hour | Superadmins |

Each alert fires once per window. Because these travel through the system they monitor, they are also logged at ERROR and shown on the independent ops dashboard (`app/ops/providers/notifications.py`), which reads the tables directly.

## 12. Endpoint reference

Member routes need a session (writes need `X-CSRF-Token`). Superadmin routes follow the staff rules (non-staff `404`, moderator `403`, TOTP `aal2`) and every write is audited. No response contains an email address or an email body.

### 12.1 Member inbox and preferences

| Method | Route | Purpose |
|---|---|---|
| GET | `/notifications?limit=1..50&cursor=&archived=false&unread_only=false` | Own notices, newest first, with `next_cursor` and `unread` |
| GET | `/notifications/unread-count` | `{ unread }` |
| PATCH | `/notifications/{notification_id}` | `{ read?, archived? }` on own item only; other fields `422` |
| POST | `/notifications/mark-all-read` | `{ unread: 0 }` |
| GET | `/notification-preferences` | Mode, time zone, local time, `always_immediate` |
| PUT | `/notification-preferences` | Same fields; IANA time zone required |
| GET | `/notifications/stream` | Server-Sent Events: `unread` on connect, then `notification` events; connection lasts 5 minutes, then the browser reconnects |

### 12.2 Superadmin operations

| Method | Route | Purpose |
|---|---|---|
| GET | `/admin/notification-deliveries?status=&limit=` | Deliveries and status counts |
| GET | `/admin/notification-deliveries/{delivery_id}` | One delivery with attempt history |
| POST | `/admin/notification-deliveries/{delivery_id}/retry` | `{ reason }`; only `ambiguous` or `failed_permanently` |
| GET | `/admin/notification-outbox?status=&limit=` | Outbox rows, counts, `oldest_unprocessed_at` |
| GET | `/admin/notification-suppressions?active=true` | Suppressions (HMAC prefix only) |
| POST | `/admin/notification-suppressions` | `{ email, channel, reason_code }` |
| DELETE | `/admin/notification-suppressions/{suppression_id}` | `{ removal_reason }` |
| GET | `/admin/notification-templates` | Keys, allowed variables, audience, live rule settings, active versions |
| GET | `/admin/notification-templates/{template_key}/versions` | All versions |
| POST | `/admin/notification-templates/{template_key}/versions` | New draft for one channel and language; only allowed `{variables}` |
| POST | `/admin/notification-templates/{template_key}/versions/{version}/activate` | Activate; previous active version retires |
| PATCH | `/admin/notification-rules/{template_key}` | `{ priority?, email?, enabled? }` |
| POST | `/admin/tasks/{task_id}/assign` | Assign a task (produces assignment notices) |

### 12.3 Provider webhook

`POST /webhooks/notifications/{provider}` for `resend` (Svix signature, `RESEND_WEBHOOK_SECRET`) or `brevo` (`Authorization: Bearer <BREVO_WEBHOOK_TOKEN>`). No session. Outside a 5-minute timestamp window, bad signature or non-JSON is refused and counted for the anomaly alert. A provider without a configured secret is `404`. Each `(provider, provider_event_id)` is processed once.

## 13. Security rules

1. Clients cannot create notifications or change recipient, priority, delivery state or expiry; `PATCH` accepts only `read` and `archived` on one's own item.
2. Template variables are allowlisted per key (`reference`, `deadline`, `question`, `count`, `outcome`, `role`); links come from an allowlisted route list.
3. The clarification question is the only moderator free text and is shown to the applicant only.
4. Suppressions store an HMAC of the normalised address, never the address or a plain hash.
5. Webhooks are signed, replay-protected and deduplicated; only a redacted payload is kept.
6. Logs never contain addresses, subjects or bodies (tested).
7. Staff notices are filtered on every read by the reader's current role.

## 14. Scaling path

Each step is triggered by a measurement:

1. **Separate worker process** when the API runs more than one instance or the free plan's sleep delays notices. The worker is already safe to run in parallel.
2. **Live-update fan-out (P-N2).** Today each open SSE stream queries Postgres every 2 seconds, so 100 open tabs make about 50 small queries a second against a pool of 5 to 7 connections. Before that becomes a load, switch to Postgres `LISTEN/NOTIFY` (one listener per API instance) or Redis pub/sub, and query only when signalled.
3. **Partition `notifications` by month** only if it passes several million rows; `expires_at` cleanup is enough until then.
4. **A dedicated queue** only if the outbox backlog alert fires under normal load.

---

# Part C: Database

## 15. Tables

All in Supabase Postgres (migrations `0014`, `0017`). RLS is on and `anon` and `authenticated` have no grants; only the API's database role reaches them.

| Table | Purpose | Key constraints |
|---|---|---|
| `outbox_events` | Shared outbox for every domain event (also used by moderation) | Unique `dedupe_key`; status `pending`/`processing`/`processed`/`retry`/`dead_letter`; `lease_until`, `available_at`, attempt count, error code |
| `notifications` | One inbox item per event, recipient and kind | Unique `(event_id, recipient_user_id, kind)`; `priority`, `audience`, `template_key`+`template_version`, title and body in `bn` and `en`, allowlisted `link`, `delivery_mode`, `digest_id`, `read_at`, `archived_at`, `expires_at`, optional linked appeal |
| `notification_deliveries` | One email delivery of a notification or a digest | Exactly one of `notification_id`/`digest_id`; unique per subject and channel; status, attempts, next attempt, send lease, provider message id, `destination_ref` (HMAC), redacted error |
| `notification_delivery_attempts` | Append-only send history | Unique `(delivery_id, attempt_number)` |
| `notification_provider_events` | Provider callbacks, stored once | Unique `(provider, provider_event_id)`; redacted payload |
| `notification_templates` | Versioned texts per key, channel and language | Unique `(template_key, channel, locale, version)`; one active per key, channel and language |
| `notification_rules` | Live tuning of catalogue rules | PK `template_key`; priority, email, enabled |
| `notification_preferences` | Per-person email mode, time zone, local time | PK `recipient_user_id` |
| `notification_suppressions` | Addresses not to email | One active row per HMAC and channel; reason, added and removed by |
| `notification_digests` | One daily summary per person | Unique `(recipient_user_id, window_date)` |

### 15.1 Retention

| Data | Kept |
|---|---|
| Standard notifications | 90 days (`expires_at`) |
| Critical notifications | 24 months |
| Notifications linked to an open appeal | Until the appeal closes, then the rule above |
| Processed outbox events | 30 days, unless a notification still refers to them |
| Delivery attempts, provider events | With their delivery (review with a privacy check before launch) |

Cleanup runs in `app/jobs/retention.py`, which re-checks open appeals before deleting. **The job has no production schedule yet** (P-N1).

### 15.2 Indexes that keep reads fast

| Index | Serves |
|---|---|
| `ix_notifications_recipient_created (recipient_user_id, created_at)` | Inbox pages (keyset cursor), unread count, SSE polling |
| `ix_notifications_expires_at` | Retention cleanup |
| `ix_notifications_digest_queue (delivery_mode, digest_id)` | Digest building |
| `ix_outbox_events_relay (status, available_at)` | Worker claim |
| `ix_notification_deliveries_due (status, next_attempt_at)` | Retry scan |
| `ix_notification_deliveries_message (provider_message_id)` | Webhook lookup |

When unread counts grow slow, add a partial index `(recipient_user_id) WHERE read_at IS NULL AND archived_at IS NULL`. Every new list endpoint gets a matching index and a cursor, never `OFFSET`.

## 16. Planned

| ID | Change | Why |
|---|---|---|
| P-N1 | Schedule `app/jobs/retention.py` (GitHub Actions cron calling an ops-token job route, like `visit-rollup.yml`) | Without it, notification expiry, outbox cleanup and suspension expiry do not run in production. |
| P-N2 | Signal-based SSE (Postgres `LISTEN/NOTIFY` or Redis pub/sub) instead of a 2-second poll per stream | Removes the per-tab database load (14.2). |
| P-N3 | Run the worker as its own process when the API scales out or sleeps | Notices are delayed while a free instance sleeps. |
| P-N4 | Notices for the Planned moderation items: `content.reopened`, `verification.reopened`, `account.suspension_expired` | Needed once Moderation P-01, P-03 and P-05 exist. |

---

## 17. Extending the system

### 17.1 Add a new notification

1. In the business code, call `events.emit()` inside the same transaction as the change, with a stable event type and minimal payload. Capture staff recipients there if staff should be told.
2. In `app/notify/registry.py`, add a `Template` (Bangla and English, allowed variables) and a `Rule` (event, kind, resolver, source field, priority, audience, route, conditions, required role).
3. If it links somewhere new, add the route to `ROUTES`.
4. Restart: version 1 of the template is stored automatically; superadmins can publish later versions from the dashboard.
5. Test: event created with the decision, one notice per recipient, revoked staff excluded, no email when the rule says so.

No database migration is needed for a new event.

### 17.2 Add a new channel (push or SMS)

1. Add the value to the `channel` check on `notification_deliveries` and `notification_templates` (migration).
2. Write an adapter with the same `send()` contract as `providers.py` (returns a provider message id, raises a permanent or temporary failure).
3. Add the channel to the rule model (`push: bool`) and to preferences.
4. Reuse deliveries, attempts, retries, suppressions and webhooks unchanged.

The event contract and the inbox do not change.

### 17.3 Change email provider

Set `EMAIL_PROVIDER` (`brevo`, `resend`, `smtp`, `gmail`, `mailpit` locally) and its secrets. For delivery and bounce tracking, configure that provider's webhook to `/webhooks/notifications/{provider}` (Resend and Brevo are supported).

---

# Part D: Verification

## 18. Acceptance tests

Implemented in `backend/tests/` on PostgreSQL:

- [x] A decision, its audit row and its outbox event commit together; a rollback leaves no event.
- [x] Two workers or a replayed event create one notification per recipient and kind.
- [x] A crash after the provider call is `ambiguous`; failures retry on schedule then fail permanently.
- [x] Every attempt has a history row.
- [x] Webhook signatures are verified and duplicates ignored.
- [x] The current verified address is used at send time; suppressed addresses are skipped.
- [x] The digest is sent once at local time and never delays critical items.
- [x] Standard and critical expiry is applied per row; notices linked to an open appeal are kept.
- [x] Appealable notices link to appeals with the 30-day deadline.
- [x] A revoked moderator is told and loses staff notices; captured staff are re-checked.
- [x] RLS is on for every table with no client grants; members reach only their own items.
- [x] Superadmin retries, template activation, rule changes and suppression changes are audited.
- [x] Alerts fire once per window; the ops panel reads the tables independently.
- [x] Logs contain no addresses or bodies.

To add with the Planned items: the retention job runs on schedule in staging (P-N1); SSE load test with 200 open streams stays within the database pool (P-N2).
