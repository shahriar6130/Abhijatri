# Abhijatri Notification System
## Architecture and API Specification — v1.1

**Stack:** Frontend + separate backend/API + Supabase PostgreSQL  
**Channels in v1:** In-app notifications and email  
**Policy decisions locked:** Current verified email; 90-day standard retention / 24-month critical retention; preserve notifications linked to open appeals; appeals for all policy-eligible decisions; event-based staff recipient resolution; daily digest.


---

## 1. Goals and guarantees

The system must provide reliable, auditable notifications for member, moderator, and superadmin workflows while respecting role boundaries and protecting sensitive information.

### Guarantees

- **Durable business events:** a committed moderation action and its outbox event are written in the same database transaction.
- **Exactly-once logical inbox creation:** idempotency constraints prevent duplicate logical in-app notifications for the same event, recipient, and notification kind.
- **External delivery is at-least-once / best-effort:** email providers can time out after accepting a message. The system cannot promise exactly-once email delivery in every failure mode. Use provider idempotency keys where supported, record ambiguous outcomes, and reconcile them.
- **In-app inbox is the source of truth:** realtime is a best-effort update signal; clients can refetch the inbox or poll.
- **Authorization is checked server-side:** frontend visibility is not an authorization boundary.
- **Auditable decisions:** notification delivery state does not replace the underlying moderation decision, audit record, appeal, or evidence.
- **No sensitive payload leakage:** events and email templates contain only the minimum data needed. Do not put identity images, verification secrets, access tokens, or internal-only notes in notification payloads or logs.

### Non-goals for v1

- Push notifications and SMS (future channels).
- Redis/BullMQ before measured volume or operational need justifies it.
- A guarantee that an email reaches a recipient's inbox.
- Using notifications as the authoritative record of a moderation decision.

---

## 2. Channels and urgency

### Channels

1. **In-app:** durable notification row in PostgreSQL.
2. **Email:** external delivery attempt tracked independently.
3. **Future:** push/SMS adapters can be added without changing the business-event contract.

Realtime may announce that the inbox changed, but it is not a separate durable notification channel.

### Urgency versus delivery mode

Keep these concepts separate:

- `priority`: `critical`, `high`, `normal`, or `low`.
- `delivery_mode`: `immediate` or `digest`.

Critical notifications are never delayed into a digest. A user's preference may control standard email delivery mode, but cannot disable mandatory in-app notices or critical operational/security notifications.

---

## 3. Event catalogue

Events are produced by successful business actions, not by UI clicks alone. Use stable event names and versioned payload schemas.

### Member-facing events

- `verification.submitted`
- `verification.clarification_requested`
- `verification.approved`
- `verification.rejected`
- `verification.expired`
- `content.published`
- `content.hidden`
- `content.rejected`
- `content.taken_down`
- `content.restored`
- `account.suspended`
- `account.suspension_lifted`
- `account.removal_requested` (only if this workflow exists)
- `account.removed`
- `appeal.submitted`
- `appeal.received`
- `appeal.decided`
- `security.account_action_required` (when applicable)

Clarification requests must state what needs correction, provide an authenticated resubmission route, and avoid exposing moderator-only notes. Rejected signup-verification records must remain retrievable for 30 days under the moderation retention policy; that is separate from notification retention.

### Moderator-facing events

- `moderation.task_assigned`
- `moderation.task_unassigned`
- `moderation.task_lease_expiring`
- `moderation.queue_overdue`
- `moderation.escalated`
- `moderation.appeal_assigned`
- `moderation.security_anomaly`

### Superadmin-facing events

- `staff.role_granted`
- `staff.role_revoked`
- `moderation.emergency_takedown`
- `moderation.escalation_required`
- `notification.delivery_failure_threshold_reached`
- `notification.outbox_backlog_threshold_reached`
- `notification.provider_webhook_anomaly`

Use a controlled event registry. New event types should be added through code/schema review rather than allowing arbitrary event names from clients.

---

## 4. Architecture and processing flow

1. An authenticated backend action validates authorization and business rules.
2. In one short PostgreSQL transaction, the backend writes:
   - the moderation/business state transition;
   - the audit record;
   - an outbox event with a stable deduplication key and schema version.
3. An outbox worker claims pending events using a lease/claim mechanism.
4. The event processor validates the schema and resolves recipients using the event's recipient policy.
5. In a short transaction, it creates one logical inbox notification per recipient and any required external delivery records. Unique constraints make retries safe.
6. The transaction commits.
7. An email worker claims delivery work, commits the claim, and calls the provider **outside** the database transaction.
8. The worker records the provider result and a delivery-attempt record.
9. Realtime publishes an inbox-change signal. Clients still refetch the persisted inbox.
10. Reconciliation jobs detect expired leases, stuck sends, ambiguous provider outcomes, retry exhaustion, and outbox backlog.

Never hold a database transaction open while making an email-provider network call.

### Outbox claim safety

Workers must use atomic claiming (for example, `FOR UPDATE SKIP LOCKED` or an equivalent safe claim operation), a lease expiry, bounded retries, and a terminal/dead-letter state. A worker crash must not permanently strand an event.

### Event ordering

Include `aggregate_type`, `aggregate_id`, and `aggregate_version` where ordering matters. Notification rendering must use immutable event facts or a carefully selected snapshot rather than blindly reading current state and accidentally describing an old event as if it were current.

---

## 5. Recipient resolution policy

### Member recipients

Resolve the intended member from the business event and store the recipient ID on the logical notification. Email address is not the member identity key.

### Staff recipients — finalized: event-based

- For assignment, unassignment, appeal assignment, role changes, and other person-specific events, capture explicit intended recipient IDs at event creation.
- For role-based broadcasts, record the recipient-resolution policy and the relevant role/target context at event time; do not silently resolve all recipients only from whatever roles exist when a delayed worker runs.
- Before revealing restricted case or staff information, re-check current authorization at delivery/render time.
- A role-revocation event must still reach the affected person, even though their staff permissions have been revoked.
- Revoked staff must not retain access to restricted case details through old notification links or realtime subscriptions.

---

## 6. Final notification policy

### 6.1 Email address — current verified address

Resolve the member's **current verified email address at send time**. Never send to a newly changed but unverified address. If there is no verified address, retain the in-app notification and mark email as skipped/blocked with a reason. Do not store email addresses in event payloads unless a narrowly justified, audited workflow requires a snapshot.

### 6.2 Retention — preserve

- Standard notifications: 90 days.
- Critical account-decision notifications: 24 months.
- Notifications linked to an open appeal: preserve until the appeal is closed and the applicable retention policy is satisfied.
- Audit history, delivery attempts, and moderation evidence have separate retention policies; deleting an inbox item must not delete the underlying decision history.
- Use per-row `expires_at` and a cleanup job for v1. Do not introduce time partitioning until volume and retention requirements justify it.

### 6.3 Appeals — always for policy-eligible decisions

Every decision that policy marks appealable must include an appeal route, case/decision reference, and applicable deadline. Send receipt and decision notifications. Preserve the original decision and appeal history. Where practical, assign an independent reviewer. “Always” does not make every action indefinitely appealable; eligibility and deadlines remain explicit policy rules.

### 6.4 Staff recipients — event-based

Use the event-based recipient rules in Section 5. Current authorization must still be checked before disclosing restricted content.

### 6.5 Digest — daily

- Daily digest at a configurable recipient-local time and timezone.
- Only eligible non-critical notifications may be batched.
- Critical, security-sensitive, and time-sensitive notifications are sent immediately.
- Store digest membership so retrying a digest job does not duplicate its logical summary.
- Digest delivery must link to authenticated, allowlisted application routes.

---

## 7. Data model

Names below are proposed logical tables. Inspect the current schema before creating migrations; reuse or migrate existing tables rather than blindly duplicating them.

### 7.1 `notification_outbox`

Suggested fields:

- `id UUID PRIMARY KEY`
- `dedupe_key TEXT NOT NULL UNIQUE`
- `event_type TEXT NOT NULL`
- `schema_version INTEGER NOT NULL`
- `aggregate_type TEXT NULL`
- `aggregate_id UUID/TEXT NULL`
- `aggregate_version BIGINT NULL`
- `payload JSONB NOT NULL` (minimal, schema-validated, no sensitive documents/secrets)
- `recipient_policy JSONB NOT NULL` (controlled policy identifier/context, not executable code)
- `created_at TIMESTAMPTZ NOT NULL`
- `occurred_at TIMESTAMPTZ NOT NULL`
- `status TEXT NOT NULL` (`pending`, `processing`, `processed`, `retry`, `dead_letter`)
- `attempt_count INTEGER NOT NULL DEFAULT 0`
- `next_attempt_at TIMESTAMPTZ NULL`
- `lease_owner TEXT NULL`
- `lease_expires_at TIMESTAMPTZ NULL`
- `last_error_code TEXT NULL`
- `processed_at TIMESTAMPTZ NULL`

Keep processed outbox rows for 30 days by default, unless incident investigation or audit policy requires longer.

### 7.2 `notifications`

One durable in-app item per recipient and logical notification kind.

- `id UUID PRIMARY KEY`
- `event_id UUID NOT NULL REFERENCES notification_outbox(id)`
- `recipient_id UUID NOT NULL`
- `notification_kind TEXT NOT NULL` (stable logical identifier)
- `type TEXT NOT NULL`
- `priority TEXT NOT NULL`
- `template_key TEXT NOT NULL`
- `template_version INTEGER NOT NULL`
- `locale TEXT NOT NULL`
- `title TEXT NOT NULL`
- `body TEXT NOT NULL`
- `action_route TEXT NULL` (allowlisted internal route, not arbitrary URL)
- `created_at TIMESTAMPTZ NOT NULL`
- `read_at TIMESTAMPTZ NULL`
- `archived_at TIMESTAMPTZ NULL`
- `expires_at TIMESTAMPTZ NULL`
- `appeal_id UUID/TEXT NULL` (if applicable)

Constraint: `UNIQUE (event_id, recipient_id, notification_kind)`. Do **not** include `created_at` in this idempotency key. Use a normal table with a simple UUID primary key in v1; defer partitioning.

### 7.3 `notification_deliveries`

Tracks one external-channel delivery for a logical notification.

- `id UUID PRIMARY KEY`
- `notification_id UUID NOT NULL REFERENCES notifications(id)`
- `channel TEXT NOT NULL` (`email` in v1)
- `destination_ref TEXT NULL` (avoid storing raw destination where possible; use controlled reference or protected field)
- `status TEXT NOT NULL` (`queued`, `sending`, `accepted`, `delivered`, `bounced`, `failed_permanently`, `skipped`, `ambiguous`)
- `attempt_count INTEGER NOT NULL DEFAULT 0`
- `next_attempt_at TIMESTAMPTZ NULL`
- `provider_message_id TEXT NULL`
- `last_error_code TEXT NULL`
- `last_error_summary TEXT NULL` (redacted)
- `created_at TIMESTAMPTZ NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

Constraint: `UNIQUE (notification_id, channel)` unless the product explicitly supports multiple distinct destinations for the same channel.

“Accepted” means accepted by the provider, not guaranteed inbox delivery.

### 7.4 `notification_delivery_attempts`

Append-only attempt history; do not rely only on the latest error fields.

- `id UUID PRIMARY KEY`
- `delivery_id UUID NOT NULL REFERENCES notification_deliveries(id)`
- `attempt_number INTEGER NOT NULL`
- `started_at TIMESTAMPTZ NOT NULL`
- `finished_at TIMESTAMPTZ NULL`
- `outcome TEXT NOT NULL` (`accepted`, `transient_failure`, `permanent_failure`, `ambiguous`, `skipped`)
- `provider_message_id TEXT NULL`
- `error_class TEXT NULL`
- `error_code TEXT NULL`
- `redacted_error_summary TEXT NULL`

Constraint: `UNIQUE (delivery_id, attempt_number)`. Never log provider credentials, full message bodies, verification secrets, or identity-document URLs.

### 7.5 `notification_provider_events`

Deduplicates provider callbacks/webhooks.

- `id UUID PRIMARY KEY`
- `provider TEXT NOT NULL`
- `provider_event_id TEXT NOT NULL`
- `event_type TEXT NOT NULL`
- `delivery_id UUID NULL REFERENCES notification_deliveries(id)`
- `received_at TIMESTAMPTZ NOT NULL`
- `processed_at TIMESTAMPTZ NULL`
- `redacted_payload JSONB NULL`

Constraint: `UNIQUE (provider, provider_event_id)`.

### 7.6 `notification_templates`

Versioned template records:

- `id UUID PRIMARY KEY`
- `template_key TEXT NOT NULL`
- `channel TEXT NOT NULL`
- `locale TEXT NOT NULL`
- `version INTEGER NOT NULL`
- `subject_template TEXT NULL`
- `title_template TEXT NULL`
- `body_template TEXT NOT NULL`
- `variable_schema JSONB NOT NULL`
- `status TEXT NOT NULL` (`draft`, `active`, `retired`)
- `created_by UUID NOT NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `activated_at TIMESTAMPTZ NULL`

Constraint: `UNIQUE (template_key, channel, locale, version)`. Published versions are immutable; edits create a new version. Enforce at most one active version per key/channel/locale. Validate variables against an allowlisted schema.

### 7.7 `notification_rules`

Stores controlled configuration for event-to-template/channel/priority behavior. Use allowlisted resolver identifiers and validated rule fields, not arbitrary executable logic stored in the database. Business code must still validate and emit supported events.

### 7.8 `notification_preferences`

- `recipient_id UUID PRIMARY KEY`
- `standard_email_mode TEXT NOT NULL` (`immediate`, `digest`, `off`, subject to policy)
- `digest_timezone TEXT NOT NULL`
- `digest_local_time TIME NOT NULL`
- `updated_at TIMESTAMPTZ NOT NULL`

Critical in-app notices and mandatory security/account notifications cannot be disabled by a standard preference. Avoid mixing priority with delivery mode.

### 7.9 `notification_suppressions`

- `id UUID PRIMARY KEY`
- `destination_hmac TEXT NOT NULL`
- `channel TEXT NOT NULL`
- `reason_code TEXT NOT NULL`
- `created_by UUID NULL`
- `created_at TIMESTAMPTZ NOT NULL`
- `removed_by UUID NULL`
- `removed_at TIMESTAMPTZ NULL`
- `removal_reason TEXT NULL`

Use an HMAC of a normalized destination rather than a plain hash, because email addresses are guessable. Restrict access. Adding/removing suppressions requires audit entries and a reason.

### 7.10 `notification_digests`

- `id UUID PRIMARY KEY`
- `recipient_id UUID NOT NULL`
- `scheduled_for TIMESTAMPTZ NOT NULL`
- `status TEXT NOT NULL` (`queued`, `sending`, `accepted`, `failed`, `ambiguous`)
- `notification_ids UUID[] NOT NULL` or a join table if queryability is required
- `delivery_id UUID NULL REFERENCES notification_deliveries(id)`
- `created_at TIMESTAMPTZ NOT NULL`

Add a unique key for recipient + digest window to prevent duplicate logical digests.

---

## 8. Idempotency, retries, and failure handling

### Retry schedule

Use bounded exponential/backoff scheduling aligned to the initial policy: immediate attempt, then approximately 1 minute, 5 minutes, 30 minutes, and 2 hours. Apply jitter where appropriate. After the configured maximum, mark the delivery permanently failed and alert operators through a deduplicated operational alert path.

- Hard bounce / invalid destination: permanent failure or suppression according to provider classification.
- Temporary provider error: retry.
- Timeout after request submission: `ambiguous` unless provider status or idempotency support resolves the outcome.
- A provider webhook is authenticated, replay-protected, and deduplicated.
- Do not retry forever.
- Do not generate an unbounded notification loop when a failure notification itself fails. Use deduplicated alerts and independent monitoring.

### Crash cases to test

- Business transaction rolls back: no outbox event exists.
- Business transaction commits but worker is down: outbox eventually processes.
- Two workers claim work concurrently: one logical notification per uniqueness key.
- Worker crashes after provider accepts email but before recording success: state becomes ambiguous/reconciled; do not falsely claim exactly-once email.
- Provider webhook is delivered twice: one provider event is processed.
- A delivery lease expires: another worker can recover it safely.
- Email address changed before send: current verified address is used.
- Recipient loses a role while a job is delayed: no unauthorized case details are disclosed.
- Appeal opens before expiry cleanup: linked notifications are preserved.
- Realtime disconnects: inbox recovers through refetch/polling.

---

## 9. API specification

All application endpoints require authenticated server-side authorization, except provider webhooks, which use provider signature authentication and replay protection.

### Member inbox

- `GET /api/notifications?cursor=...&limit=...`
- `GET /api/notifications/unread-count`
- `PATCH /api/notifications/{notificationId}` — mark read/archive only; validate ownership.
- `POST /api/notifications/mark-all-read` — scoped to the authenticated user.
- `GET /api/notification-preferences`
- `PUT /api/notification-preferences` — validate supported modes and timezone.

Clients must not be allowed to insert arbitrary notifications or change recipient IDs, priority, delivery status, or expiry.

### Admin delivery monitoring — superadmin only

- `GET /api/admin/notification-deliveries`
- `GET /api/admin/notification-deliveries/{deliveryId}`
- `GET /api/admin/notification-outbox?status=...`
- `POST /api/admin/notification-deliveries/{deliveryId}/retry` — only for retryable states, with an audit record.
- `POST /api/admin/notification-suppressions`
- `DELETE /api/admin/notification-suppressions/{suppressionId}` — require removal reason and audit actor.

Redact destinations and message details from general monitoring views. Limit access to full provider diagnostics.

### Template management — superadmin only

- `POST /api/admin/notification-templates/{key}/versions` — create a new draft version with channel, locale, and validated variable schema.
- `POST /api/admin/notification-templates/{key}/versions/{version}/activate`
- `GET /api/admin/notification-templates/{key}/versions`

Do not use a single ambiguous `PUT /templates/{key}` endpoint for versions that differ by channel and locale. Activation is a separate audited operation.

### Provider webhook

- `POST /api/webhooks/notifications/{provider}`

Verify provider signature, timestamp/replay window, expected content type, and provider event ID. Deduplicate with `(provider, provider_event_id)`. Do not require a normal member session token for provider callbacks.

---

## 10. Security and Supabase controls

- PostgreSQL is the source of truth.
- Apply both SQL grants and Row Level Security; RLS does not replace grants.
- Members can read only their own notification rows and update only permitted fields on their own rows.
- No client-side inserts into notifications, outbox, deliveries, attempts, provider events, templates, rules, or suppressions.
- Service-role/secret keys must never be shipped to the browser.
- Use the backend API for privileged writes and policy validation.
- Realtime is best-effort. Subscribe only to appropriately scoped records; avoid exposing sensitive staff data in shared channels.
- Authorization must be rechecked for sensitive action links and restricted case details.
- Use fixed application origins and allowlisted internal action routes; never build action URLs from untrusted user-supplied URLs.
- Rate-limit user-triggered messages. Keep mandatory system processing on a separate controlled path so user preferences or abuse limits do not silently suppress critical events.
- Logs must be redacted and access-controlled.

---

## 11. Jobs and operational monitoring

Suggested jobs:

- Outbox poll/claim worker: short polling interval, configurable.
- Delivery retry worker: frequent bounded scan of due retries.
- Lease reconciliation: recover expired worker claims.
- Ambiguous-send reconciliation: query provider status where supported; otherwise surface for controlled review.
- Overdue moderation/task scan.
- Daily digest scheduler and sender.
- Notification expiry cleanup respecting appeal preservation.
- Processed outbox cleanup after the configured retention window.
- Delivery/provider webhook reconciliation.
- Health checks and backlog alerts.

Metrics:

- Outbox pending count and oldest event age.
- Event-to-inbox latency.
- Email acceptance/failure/bounce rates.
- Retry count and ambiguous delivery count.
- Dead-letter count and age.
- Webhook signature failures and duplicate callback rate.
- Digest build/send failures.
- Notification cleanup failures.

Alerting must be deduplicated. A notification subsystem must not rely exclusively on itself to report its own total failure.

---

## 12. UI requirements

- Notification bell with unread count.
- Paginated inbox with read/unread state, category, and timestamp.
- Clear action label and authenticated route.
- Preferences for standard email immediate/daily digest/off where policy permits.
- Daily digest summary.
- Superadmin-only monitoring for outbox, deliveries, retries, suppression and provider status.
- Empty, loading, error, retry, and stale/reconnect states.
- Sensitive details remain behind authenticated role-checked pages; email/inbox previews contain minimal content.

---

## 13. Implementation phases

### Phase 0 — inspect and reconcile

Inspect current Supabase schema, RLS policies, backend authentication, moderation audit/event structure, current email provider, and existing notification tables. Produce a migration plan; do not create duplicate tables blindly.

### Phase 1 — durable event and inbox core

Implement the outbox, versioned event contracts, recipient policy, idempotent inbox creation, owner-only access, and realtime/refetch behavior. Test duplicate and concurrent event processing.

### Phase 2 — email delivery

Add delivery rows, attempt history, provider adapter, bounded retries, verified-current-address resolution, signed webhooks, webhook dedupe, and ambiguous-outcome handling. Test provider timeout and worker crash scenarios.

### Phase 3 — catalogue and preferences

Add the moderation event catalogue, versioned templates, member/moderator/superadmin notifications, appeal notices, preferences, and daily digest.

### Phase 4 — operations

Add superadmin monitoring, dead-letter/reconciliation workflows, backlog alerts, redacted diagnostics, and incident procedures.

### Phase 5 — retention and load validation

Enforce expiry policy, open-appeal preservation, 30-day processed-outbox cleanup, load tests, and authorization tests. Add Redis/BullMQ or partitioning only if measurements justify the added complexity.

---

## 14. Acceptance checklist

- [ ] Business state, audit row, and outbox event commit atomically.
- [ ] Duplicate/replayed events create one logical inbox notification per recipient/kind.
- [ ] Email delivery is described honestly as at-least-once/best-effort, with ambiguous outcomes tracked.
- [ ] Each email attempt has a history row.
- [ ] Provider webhook signatures and duplicate events are handled.
- [ ] Current verified email is used at send time.
- [ ] Daily digest never delays critical events and is idempotent.
- [ ] Standard/critical expiry rules are applied per row.
- [ ] Notifications linked to open appeals are preserved.
- [ ] Every policy-eligible decision offers an appeal route and deadline.
- [ ] Role changes do not leak restricted information to revoked staff.
- [ ] RLS and SQL grants are tested for every role.
- [ ] Realtime outage does not lose notifications.
- [ ] Admin retries, template activation, and suppression changes are audited.
- [ ] Failure alerts are deduplicated and independent monitoring exists.
- [ ] No sensitive documents, secrets, or unredacted message bodies appear in logs.

---

