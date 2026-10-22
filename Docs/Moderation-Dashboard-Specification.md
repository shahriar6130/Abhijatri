# Abhijatri Moderation Dashboard: Architecture and API Specification

**Scope:** Admin authentication and authorization, moderation queues,
verification, enforcement, appeals, audit, retention, and notification
integration.


## 1. Purpose and Scope

The Abhijatri moderation dashboard provides authorized staff with tools
to review verification cases, moderate user submissions, handle reports,
apply enforcement actions, and process appeals.

The system must provide:

-   Server-enforced authentication and role-based authorization.
-   A hybrid work queue: assigned work plus eligible unassigned work
    that staff can claim.
-   Explicit state transitions and concurrency-safe decisions.
-   Private handling of verification evidence.
-   An append-only audit trail for privileged actions and decisions.
-   Controlled retention and deletion of evidence and moderation
    records.
-   Transactional integration with notifications through a shared outbox
    contract.
-   Monitoring sufficient to detect authorization failures, queue
    stalls, and notification failures.

This specification describes the architecture and API behavior. It does
not authorize production migration until the existing schema, policies,
routes, and deployed behavior have been inspected.

## 2. Roles and Authorization Model

### 2.1 Authentication

Members, moderators, and superadmins use the same authentication system.
Authentication establishes the identity of the user; the backend
determines the user's current permissions from authoritative application
data.

The frontend may hide routes and controls based on the user's role, but
frontend checks are only a user-experience convenience. Every privileged
API request must be authorized on the server.

### 2.2 Role invariant

**V1 policy: one active staff role per user.** A user may be a normal
member without a staff role, or hold exactly one active staff role:
`moderator` or `superadmin`. A user must not simultaneously hold both
active staff roles.

Enforce this invariant in the database, not only in application code. If
the product later needs multiple simultaneous roles, revise this policy
and its constraints explicitly before implementing that change.

Recommended role table:

-   `user_roles`
    -   `user_id`
    -   `role` (`moderator` or `superadmin`)
    -   `granted_by`
    -   `granted_at`
    -   `revoked_by` (nullable)
    -   `revoked_at` (nullable)
    -   `created_at`

Use a partial unique index on `user_id` for rows where
`revoked_at IS NULL`, so only one active staff-role row can exist per
user. Add database checks for valid role values. Keep role grants and
revocations auditable.

### 2.3 Permission boundaries

-   **Member:** can access only member-facing resources allowed by the
    product.
-   **Moderator:** can process ordinary verification and
    content-moderation work assigned to them or legitimately claimed by
    them.
-   **Superadmin:** can handle escalated cases, manage staff roles, and
    perform explicitly designated high-impact operations.
-   **Appeal reviewer:** must be independent of the original
    decision-maker where staffing permits; the original decision-maker
    must not decide their own appeal.

A superadmin is not automatically permitted to bypass audit, retention,
or transaction rules.

### 2.4 Denial behavior

Unauthorized staff routes and APIs must not reveal protected case data.
The application may return `404` for staff-only resources to avoid
disclosing their existence; otherwise use consistent `401`/`403`
behavior. Choose and document a consistent API convention. Do not rely
on obscurity as the security boundary.

------------------------------------------------------------------------

## 3. System Architecture

### 3.1 System of record

Use Supabase Postgres as the authoritative store for moderation state,
role assignments, task leases, audit events, and outbox events. Use
Supabase Auth for identity, Supabase Storage for private evidence, and
Supabase Realtime only where useful for best-effort UI updates.

Redis and an external queue are optional future optimizations. They are
not required for v1 and must not become the authoritative source of task
state or notification delivery state.

### 3.2 Frontend

Admin UI routes live under `/admin`. The UI should show only actions
available to the current staff member, but the server must independently
validate every action.

Do not put service-role credentials or privileged database credentials
in the browser. Use server-side API routes or trusted backend functions
for privileged operations.

### 3.3 Storage and evidence

Verification evidence must be stored in a private bucket. Access is
granted through server-authorized requests or short-lived signed URLs.
The backend must verify that the requesting user is authorized for the
specific case before issuing a URL.

Define who may upload, replace, view, and delete each evidence item.
Record material evidence changes in the audit trail. Signed URLs should
have short expiry periods appropriate to the use case; do not treat
possession of an old URL as ongoing authorization.

### 3.4 Realtime

Realtime updates are a convenience, not a source of truth. After
receiving an update or reconnecting, the client must refresh
authoritative state. A missed event must not cause a decision to be
accepted against stale data.

------------------------------------------------------------------------

## 4. Session and Security Policy

### 4.1 Session lifetime

Use Supabase Auth session and refresh-token behavior as the identity
layer. Application policy additionally requires:

-   Moderator session target: up to 30 days, subject to the configured
    authentication provider policy and risk controls.
-   Superadmin: inactivity timeout of 8 hours.
-   Recent reauthentication for high-impact actions, including
    staff-role changes and other actions designated by the security
    policy.
-   MFA for superadmins; require MFA for moderators if supported by the
    deployment's risk policy.

These are application targets and must be verified against the actual
Supabase project configuration; do not assume that naming a duration in
this document configures the provider.

### 4.2 Current authorization and revocation

A role/account-state cache may be used for low-risk reads only if it has
a maximum TTL of 60 seconds and a reliable invalidation mechanism. That
cache does **not** guarantee immediate revocation.

For sensitive actions---including role changes, enforcement, appeal
decisions, and access to restricted evidence---read current role and
account state from the authoritative database within the controlled
operation. If the system cannot establish authorization reliably, fail
closed.

When a role is revoked or an account is disabled, invalidate relevant
caches and revoke or invalidate sessions where the authentication system
supports it. All privileged endpoints must still enforce current
authorization even if a session remains technically valid.

### 4.3 Database security

-   Enable and review RLS for tables exposed through Supabase client
    APIs.
-   Use explicit database grants; RLS alone is not a substitute for
    least-privilege grants.
-   Do not permit clients to insert or modify audit events, staff-role
    assignments, moderation decisions, or notification outbox rows
    directly.
-   Keep service-role credentials server-side only.
-   Test authorization using member, moderator, superadmin,
    revoked-role, disabled-account, and unauthenticated identities.

------------------------------------------------------------------------

## 5. Work Queue and Task Claims

### 5.1 Queue model

Use a hybrid queue:

1.  Tasks assigned to a staff member.
2.  Eligible unassigned tasks that a qualified staff member may claim.

The database is authoritative for task ownership and lease status. The
UI may display a task as available, but availability must be revalidated
atomically when the task is claimed.

### 5.2 Claim leases

A claim should include, at minimum:

-   `claimed_by`
-   `claimed_at`
-   `lease_expires_at`
-   `lease_token` or equivalent claim version
-   `updated_at`

Claim, heartbeat/renewal, release, and decision operations must verify
the current state, actor eligibility, and lease ownership in a single
controlled database operation or transaction.

A claim must not be accepted merely because the task appeared claimable
in a prior query. Concurrent claims must result in at most one valid
lease. Expired leases may be reclaimed under a documented rule.

### 5.3 Eligibility and escalation

The server must verify task eligibility for the actor at claim time and
decision time. If a task becomes escalated while a moderator has it
open, the moderator must not be able to approve it using stale UI state.
The decision operation must re-read current task/case state and enforce
the current role requirement.

### 5.4 Failure and recovery

Lease expiry must not silently change the underlying moderation decision
state. A worker or staff member may lose a lease while viewing a case;
subsequent writes must fail with a conflict response and instruct the
client to reload.

------------------------------------------------------------------------

## 6. Core Data Model

The following describes the logical schema. Inspect the existing
database and migrations before creating, renaming, or altering tables.
Reuse compatible existing structures where possible; do not blindly run
a fresh-schema migration against production.

### 6.1 `user_roles`

Suggested fields:

-   `user_id`
-   `role`
-   `granted_by`
-   `granted_at`
-   `revoked_by`
-   `revoked_at`
-   `created_at`

Constraints:

-   Role value is restricted to the approved role set.
-   At most one active staff role per user.
-   Role grant/revoke operations require superadmin authorization and
    recent reauthentication.
-   Prevent revocation of the final active superadmin.

**Concurrency rule:** granting or revoking a superadmin role must be
serialized. Lock the relevant role-management guard row or use an
equivalent transaction-level advisory lock, re-check the
active-superadmin count inside the transaction, and then apply the
change. A pre-transaction count is insufficient because two concurrent
requests could otherwise remove the last superadmins. Audit the result
in the same transaction.

### 6.2 Verification cases

A verification case should retain the applicant, current state, case
version, assigned reviewer/claim lease, evidence references, timestamps,
and decision metadata.

Use optimistic concurrency with a `version` field or a row lock. A
decision must update the case only if the expected version and allowed
prior state still match. If the update affects zero rows, return a
conflict and require the client to reload.

Define permitted transitions explicitly, for example:

-   `submitted` → `in_review`
-   `in_review` → `needs_clarification`
-   `needs_clarification` → `in_review`
-   `in_review` → `approved`
-   `in_review` → `rejected`
-   Any eligible review state → `escalated` (only under defined rules)
-   `escalated` → an allowed final decision state by a superadmin

Do not allow arbitrary state changes from a generic update endpoint.
Each transition must validate actor permissions, required fields,
evidence requirements, current version, and claim ownership where
applicable.

Rejected verification records may be retained for 30 days under the
proposed default, subject to the retention rules in Section 10. A
`purge_after` timestamp may drive cleanup, but it must not override an
open appeal, legal hold, or another documented preservation rule.

### 6.3 Content submissions, moderation tasks, actions, and reports

Keep the user-submitted content record separate from the moderation task
and from the action history.

Suggested logical entities:

-   `submissions`: original content and its lifecycle state.
-   `moderation_tasks`: queue state, assignee/claim lease, priority, and
    task version.
-   `moderation_actions`: immutable decision/action history.
-   `reports`: user reports and their review state.

Store moderation decisions as append-only actions and update the current
submission/task state in the same transaction. Do not overwrite the only
record of a prior decision.

### 6.4 Enforcement, removal, and sanctions

Represent enforcement cases and sanctions separately from the underlying
submission. Define the difference between:

-   **Hidden/taken down:** content is not publicly visible while review
    or enforcement is pending.
-   **Removed:** content has been removed from public availability under
    the applicable policy.
-   **Restored:** visibility is restored after review or appeal.
-   **Sanctioned:** an account-level restriction with a defined type,
    scope, start, and end/review date.

A takedown must not automatically imply permanent exclusion from ratings
or metrics. Keep public visibility and rating/aggregation eligibility as
separate fields, including `counts_toward_rating`, with explicit
policy-controlled transitions. Record the reason and actor for each
change.

Emergency takedown must have a defined path, authorization rule, audit
event, and follow-up review deadline. Do not leave emergency states
without an owner or review path.

### 6.5 Appeals

An appeal record should include the appellant, target type and ID,
original decision reference, reason, state, submitted time, deadline,
reviewer, and decision metadata.

Because a polymorphic `target_type`/`target_id` pair cannot normally
have a direct foreign key to multiple target tables, the backend must
validate target existence and eligibility, appellant ownership/standing,
appeal deadline, and duplicate-appeal policy in the same transaction
that creates the appeal. Use typed foreign keys or separate
target-specific tables if stronger database-level referential integrity
is practical.

Define explicitly:

-   Which decision types are appealable.
-   Who may appeal each decision.
-   How deadlines are calculated using server time and the policy's
    specified timezone.
-   Whether withdrawn or decided appeals can be reopened and under what
    conditions.
-   Whether a new appeal is allowed after a prior appeal has been
    decided.
-   How duplicate submissions are detected.
-   Which evidence and records must be preserved while an appeal is
    open.
-   How an independent reviewer is selected.

Notify eligible parties on appeal receipt and decision, as defined by
the notification policy. Preserve the original decision and audit
history; an appeal outcome must not erase the original action.

### 6.6 Audit events

Audit events are append-only records of privileged actions, state
transitions, role changes, evidence access where required, enforcement
actions, appeal outcomes, and relevant administrative failures.

Recommended fields:

-   `id` (globally unique identifier)
-   `occurred_at`
-   `actor_user_id` (nullable for system actions)
-   `actor_role_snapshot`
-   `action`
-   `target_type`
-   `target_id`
-   `request_id` or correlation ID
-   `reason` where applicable
-   `metadata` containing only approved, non-secret details

If the table is partitioned by month and uses a composite primary key
such as `(id, occurred_at)`, the API must not assume `id` alone is a
database-enforced unique lookup unless a separate global uniqueness
mechanism guarantees it. Either use a globally unique unpartitioned
identifier registry, require the partition key in lookups, or use a
schema/index strategy that guarantees the intended semantics. Document
the chosen approach and make `GET /admin/audit-events/{id}` match it.

Audit writes for a privileged decision must be in the same transaction
as the decision. Do not permit application clients to update or delete
audit events. Define partition creation, retention, archival, and query
behavior before enabling monthly partitioning in production.

### 6.7 Transactional outbox and notifications

Moderation decisions may produce notifications. The business state
change, corresponding audit event, and outbox event must be committed in
one database transaction.

Use one shared `outbox_events` contract for moderation and the
notification system. Do not create two independent outbox designs with
incompatible event IDs, status fields, retry rules, or ownership. The
notification specification may define richer notification and delivery
tables downstream, but the source event must come from the same
transactional outbox.

At minimum, an outbox event needs:

-   `id`
-   `event_type`
-   `aggregate_type` and `aggregate_id`
-   `occurred_at`
-   schema/version identifier
-   payload containing approved event facts, not secrets
-   processing status/lease metadata or an equivalent relay mechanism
-   retry and error metadata

Postgres is authoritative. Workers may use `FOR UPDATE SKIP LOCKED` or
another safe claim strategy with a short transaction/lease. Never hold a
database transaction open while calling an email provider. Design for
at-least-once processing, idempotent database effects, and provider
idempotency where supported; do not promise exactly-once email delivery.

The notification service should use a unique notification identity such
as `(event_id, recipient_id, notification_kind)`, not timestamps.
Preserve delivery-attempt history and deduplicate provider webhooks. If
the provider may have accepted a message before a worker crash,
represent the result as ambiguous/reconcilable rather than assuming
delivery failed.

------------------------------------------------------------------------

## 7. State Machines and Transition Rules

Every workflow must have an authoritative transition table maintained
with the implementation. For each transition, specify:

-   Current state and permitted next state.
-   Actor roles allowed to request the transition.
-   Required reason, evidence, or other input.
-   Version/lease checks.
-   Audit event type.
-   Notification event type, if applicable.
-   Retention or appeal implications.

The backend must reject all transitions not listed in the applicable
table. Do not expose generic endpoints that allow clients to set
arbitrary status values.

### 7.1 Verification

Use the verification transitions in Section 6.2 as the starting point.
Final approval/rejection requires a current authorized reviewer, a valid
case version, and any required lease. Escalated cases require a
superadmin decision.

### 7.2 Content moderation

Define separate states for pending review, in review, escalated,
approved/allowed, hidden/taken down, removed, and restored as needed by
the product. Avoid ambiguous states that combine queue ownership with
content visibility. Queue/lease status and content lifecycle status
should be separate fields or entities.

### 7.3 Enforcement

Sanction creation, modification, expiry, and reversal must be explicit
actions with audit records. A sanction must have a clear scope and
duration or review condition. Automatic expiry should create a traceable
system event.

### 7.4 Appeals

Appeal receipt and appeal decision are separate transitions and
notification events. The appeal decision must reference the original
action and preserve both histories.

------------------------------------------------------------------------

## 8. API Design

Use the `/admin` prefix for staff-only APIs. The exact route names may
be adapted to the existing application, but the authorization,
concurrency, and transaction rules below are mandatory.

### 8.1 General rules

-   Authenticate every request.
-   Authorize every operation on the server using current application
    state.
-   Validate all input and reject unknown or unsupported state values.
-   Use server-generated timestamps.
-   Return a stable request/correlation ID.
-   Do not return private evidence URLs or sensitive metadata to
    unauthorized users.
-   Use consistent error responses.
-   Record successful privileged decisions and relevant denied high-risk
    operations according to the audit policy.

Suggested status behavior:

-   `401`: no valid authenticated identity.
-   `403` or policy-selected `404`: authenticated but not authorized.
-   `404`: target does not exist or is intentionally concealed.
-   `409`: stale version, lost lease, duplicate/conflicting transition,
    or idempotency-key payload mismatch.
-   `422`: syntactically valid request that violates workflow/business
    validation.
-   `429`: rate limited.

### 8.2 Idempotency

For decision endpoints that may be retried, accept an idempotency key.
Scope it by actor and operation, and store a request fingerprint plus
the original result. Reuse of the same key with the same payload returns
the original result; reuse with a different payload returns
`409 Conflict`.

Do not use timestamps as idempotency identity. Idempotency does not
replace database constraints or concurrency control.

### 8.3 Suggested endpoint groups

-   `GET /admin/queue`
-   `POST /admin/tasks/{task_id}/claim`
-   `POST /admin/tasks/{task_id}/heartbeat`
-   `POST /admin/tasks/{task_id}/release`
-   `POST /admin/verification-cases/{case_id}/transition`
-   `POST /admin/submissions/{submission_id}/moderation-actions`
-   `POST /admin/reports/{report_id}/transition`
-   `POST /admin/enforcement-cases/{case_id}/actions`
-   `POST /admin/appeals`
-   `POST /admin/appeals/{appeal_id}/decision`
-   `GET /admin/audit-events`
-   `GET /admin/audit-events/{id}` (only if the ID lookup semantics in
    Section 6.6 are guaranteed)
-   `POST /admin/staff/{user_id}/role` and/or a dedicated grant/revoke
    endpoint
-   `GET /admin/monitoring/summary`

These are logical endpoint suggestions, not permission to create
duplicate routes if the application already has equivalent endpoints.

### 8.4 Bulk actions

Bulk requests must be explicit about partial success. Each item is
atomic on its own; the batch may partially succeed. Return a per-item
result containing success/failure, status, and a safe error code. If a
true all-or-nothing batch is required for a particular operation,
implement it as a separate transactionally validated operation and
document its limits.

### 8.5 Concurrency contract

For every decision endpoint:

1.  Re-read authoritative role/account state.
2.  Validate actor eligibility and target ownership/visibility.
3.  Validate the current state and expected version.
4.  Validate claim lease ownership where applicable.
5.  Apply the transition and write the immutable action/audit event.
6.  Insert any resulting outbox event.
7.  Commit once.

If any required check fails, do not partially apply the decision. Return
a conflict or authorization error as appropriate.

------------------------------------------------------------------------

## 9. API and Database Error Handling

-   Stale version: `409`, with a safe indication that the client should
    reload.
-   Lost/expired lease: `409`; do not silently reclaim the task during a
    decision.
-   Unauthorized action: `403` or policy-selected `404`.
-   Invalid transition: `422`.
-   Duplicate appeal or disallowed second appeal: stable
    conflict/business error.
-   Database or provider transient failure: retry only operations
    designed to be idempotent.
-   Avoid returning SQL, stack traces, secrets, signed URLs, or internal
    policy details to the browser.

For multi-step decisions, prefer a single database transaction or a
narrowly scoped database function so validation, state change, audit
write, and outbox insertion cannot drift apart.

------------------------------------------------------------------------

## 10. Retention and Deletion

Retention is a policy requirement, not merely a cleanup-job setting.

-   Rejected verification cases: proposed default of 30 days before
    purge, subject to the exceptions below.
-   Standard user notifications: 90 days.
-   Critical account-decision notifications: 24 months.
-   Preserve notification items tied to an open appeal while the appeal
    remains open.
-   Preserve relevant evidence and records while an appeal is open, a
    legal hold applies, or a documented policy requires retention.
-   Define evidence retention after approval and for withdrawn/closed
    cases before implementation.
-   Define separate retention rules for audit events, moderation
    actions, sanctions, reports, and delivery-attempt history.

A cleanup job must re-check preservation conditions immediately before
deletion. Avoid a race in which an appeal opens after a cleanup job
selects an item but before it deletes the evidence. Use transactional
locking or an equivalent safe protocol. `purge_after` is a candidate
eligibility time, not unconditional permission to delete.

When deletion is required, delete the underlying object and metadata
consistently and record the deletion event where policy requires it.
Avoid retaining unnecessary personal or sensitive data in audit
metadata.

------------------------------------------------------------------------

## 11. Notification Integration

The moderation dashboard should emit domain events; it should not
directly send email from a request handler.

Apply the companion notification specification and these finalized
policy decisions:

``` json
{
  "email_address_policy": "current_verified_at_send",
  "notification_retention": {
    "standard_days": 90,
    "critical_account_decisions_months": 24,
    "preserve_while_appeal_open": true
  },
  "appeals": {
    "enabled_for_all_policy_eligible_decisions": true,
    "notify_on_receipt": true,
    "notify_on_decision": true,
    "include_deadline_and_case_reference": true
  },
  "staff_recipients": {
    "resolution_policy": "event_based",
    "capture_intended_recipients": true,
    "recheck_current_authorization": true
  },
  "digest": {
    "enabled": true,
    "frequency": "daily",
    "timezone": "recipient_configured",
    "include_critical_events": false
  }
}
```

Additional requirements:

-   Resolve a user's email from the current verified address at send
    time.
-   Capture the intended staff recipients for an event, then re-check
    current authorization before disclosing sensitive details.
-   Send appeal notifications on receipt and decision for every
    policy-eligible appeal.
-   Daily digests use the recipient's configured timezone and exclude
    critical/time-sensitive events.
-   Critical/time-sensitive notices are handled outside the daily digest
    path.
-   Keep urgency/priority separate from delivery mode.
-   Use versioned immutable templates, typed variables, and controlled
    recipient resolvers.
-   Store email suppression identifiers as an HMAC of normalized email,
    not a plain hash.
-   The in-app inbox is owner-only; clients cannot insert notification
    rows directly.
-   Realtime inbox updates are best effort. The inbox database remains
    authoritative.
-   Notification-system failure must be monitored through an independent
    operational path; do not rely only on the notification system to
    report its own failure.

------------------------------------------------------------------------

## 12. Monitoring, Audit Review, and Operations

Monitor at least:

-   Queue depth and age of oldest eligible task.
-   Expired claims and repeated claim conflicts.
-   Verification and moderation decision latency.
-   Escalation volume and unresolved escalations.
-   Appeal volume, deadline proximity, and overdue appeals.
-   Authorization denials and suspicious role-management attempts.
-   Outbox backlog, oldest unprocessed event, retry count, and
    dead-letter/terminal failures.
-   Email provider failures, bounce/complaint events where available,
    and ambiguous delivery outcomes.
-   Cleanup-job failures and retention items blocked by open appeals.
-   Database errors, latency, and storage access failures.

Define thresholds, an operational owner, and a response procedure for
each alert before production. Ensure critical monitoring can reach
operators even if the in-app notification or email pipeline is
unavailable.

Review audit logs for role changes, high-impact actions, repeated
denials, and unusual access patterns. Avoid logging evidence contents,
credentials, tokens, or unnecessary personal data.

------------------------------------------------------------------------

## 13. Implementation Phases

### Phase 0 --- Inspect before migration

-   Inspect current routes, schema, migrations, RLS policies, storage
    policies, authentication settings, and existing
    moderation/notification code.
-   Map current implementation to this specification.
-   Identify reusable tables/routes and conflicting constraints.
-   Back up and prepare a rollback plan before any production migration.
-   Do not create duplicate systems without documenting why.

### Phase 1 --- Security and transaction foundation

-   Implement and test the one-active-staff-role invariant.
-   Implement race-safe last-superadmin protection.
-   Enforce current authorization for sensitive actions.
-   Define stable transition tables and version/lease checks.
-   Ensure decisions, audit events, and outbox events commit atomically.
-   Add idempotency-key storage and request fingerprint validation where
    needed.

### Phase 2 --- Content moderation

-   Implement task claims, lease renewal, release, and decision-time
    eligibility checks.
-   Separate task/lease state from content visibility.
-   Implement moderation action history and report workflows.
-   Test concurrent claims, stale tabs, escalation during review, and
    retries.

### Phase 3 --- Verification

-   Implement verification transitions and evidence authorization.
-   Add optimistic concurrency or row-lock protection.
-   Implement clarification requests, approval/rejection, escalation,
    and retention exceptions.
-   Test signed URL expiry, unauthorized evidence access, and
    cleanup/appeal races.

### Phase 4 --- Enforcement and appeals

-   Implement explicit takedown/removal/restoration and sanction
    lifecycle.
-   Implement appeal eligibility, deadlines, duplicate policy,
    independent review, and preservation rules.
-   Emit appeal-receipt and appeal-decision outbox events.
-   Test concurrent appeal submission, expired deadlines, and
    original-decision preservation.

### Phase 5 --- Outbox, notifications, and monitoring

-   Implement the shared PostgreSQL outbox and downstream
    notification/delivery records.
-   Add retry handling, delivery-attempt history, provider webhook
    deduplication, and ambiguous delivery reconciliation.
-   Implement daily digest behavior and current-verified-email
    resolution.
-   Add independent operational monitoring.
-   **Redis/BullMQ is optional** and should be added only if measured
    throughput, latency, or scheduling needs justify it. PostgreSQL
    remains authoritative.

### Phase 6 --- Production validation

-   Run role-based authorization tests for every endpoint.
-   Run concurrency tests for last-superadmin protection, claims, state
    transitions, and appeals.
-   Run failure-injection tests for worker crashes before/after provider
    acceptance.
-   Validate retention, appeal preservation, and cleanup race behavior.
-   Verify backups, recovery, alert ownership, and rollback procedures.
-   Do not enable production traffic until critical security and
    data-integrity tests pass.

------------------------------------------------------------------------

## 14. Required Acceptance Tests

Before production, verify at least the following:

1.  A user cannot hold two active staff roles.
2.  Two concurrent role-revocation requests cannot remove the last
    active superadmin.
3.  A revoked moderator cannot perform a sensitive action through a
    stale session or cached role.
4.  Two staff members cannot hold simultaneously valid claims for the
    same exclusive task.
5.  A moderator cannot decide an escalated case after escalation, even
    from a stale tab.
6.  A stale case version cannot overwrite a newer decision.
7.  A failed decision transaction leaves no orphaned audit or outbox
    event.
8.  A successful decision cannot commit without its required audit and
    outbox records.
9.  A reused idempotency key with a different payload returns a
    conflict.
10. An ineligible or late appeal is rejected consistently by the
    backend.
11. An open appeal prevents relevant evidence/notification cleanup.
12. Cleanup re-checks appeal/legal-hold state immediately before
    deletion.
13. Unauthorized users cannot access private evidence or inbox records.
14. An outbox worker crash after provider acceptance does not cause the
    system to claim exactly-once delivery.
15. Duplicate provider webhooks do not duplicate delivery state changes.
16. Audit-event lookup behavior matches the actual uniqueness and
    partitioning design.
17. Critical alerts remain observable when the notification delivery
    system is down.
18. Bulk API responses clearly report per-item success and failure.

------------------------------------------------------------------------

## 15. Decisions Locked for V1

-   One active staff role per user.
-   Supabase Postgres is the system of record.
-   Shared authentication; server-side authorization is authoritative.
-   Hybrid queue with database-backed leases.
-   Current authorization checks for sensitive actions.
-   Version-checked or row-locked state transitions.
-   Audit writes and outbox writes are transactional with business
    decisions.
-   A single shared outbox contract feeds notifications.
-   At-least-once event processing; no exactly-once email guarantee.
-   Rejected verification retention target: 30 days, with preservation
    exceptions.
-   Standard notification retention: 90 days; critical account-decision
    notifications: 24 months; preserve relevant notifications and
    evidence while an appeal is open.
-   Appeal notifications on receipt and decision for all policy-eligible
    appeals.
-   Daily recipient-timezone digest excludes critical/time-sensitive
    events.
-   Redis remains optional until measured need justifies it.


