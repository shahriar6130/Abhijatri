# Abhijatri Security and Privacy Specification

**Status:** Approved specification for the current project scope  
**Date:** 15 October 2026  
**Companion documents:** `Features/Review.md` and `Docs/Decisions.md`  
**Scope:** Review platform, accounts, verification, moderation, offline support, deployment, and Verified Member review media (core since Review.md amendment A1)  
**Release rule:** A control marked **Deploy gate** must be implemented and evidenced before a public production launch. A requirement in this document is not a claim that the current semester build already implements it.

## 1. Security principles

1. **Deny by default.** Every protected request is authenticated and authorised on the server.
2. **Collect the minimum.** Abhijatri does not require raw NID storage, advertising identifiers, or exact location for the Review MVP.
3. **Separate identity, verification, and authority.** A Verified Member badge does not grant staff permissions.
4. **Cache by allowlist.** A response is private and non-cacheable unless a route-specific policy explicitly declares it public.
5. **Preserve rating integrity.** Moderation, eligibility, conflict, withdrawal, deletion, and account-deletion actions use the same locked aggregate-transition rules.
6. **Design for weak networks without weakening privacy.** Offline data is bounded, dated, removable, and limited to approved public content and user-controlled drafts.
7. **Separate duties.** Runtime, migration, worker, retention, and audit identities receive only the privileges they need.
8. **Claim only what is evidenced.** Planned controls are labelled as requirements or deployment gates until tests prove them.

## 2. Status and trust boundaries

### 2.1 Status legend

| Label | Meaning |
|---|---|
| Implemented | Present in the repository and covered by an available test or migration check. |
| Build requirement | Required during the named implementation step. |
| Deploy gate | Required before public production traffic or real personal data. |
| Conditional | Applies only if Redis, a CDN, or a similar optional component is introduced. |

### 2.2 Current implementation boundary

The current backend implements the first review slice: Guest submission, hashed Guest scope and receipt credentials, permanent draft deduplication, moderation, publication, withdrawal, stable public-feed ordering, locked aggregate updates, and development-only staff identity injection. It does **not** yet provide production authentication, staff MFA, CSRF middleware, rate limiting, Redis, a CDN, object storage, the media pipeline, or production deployment controls.

The development header used to identify staff is allowed only when `APP_ENV` is `development` or `test`. Production must fail closed until the real authentication adapter is configured. Test headers must never be accepted by a public deployment.

**Implemented (15 October 2026):** the backend refuses to start when `APP_ENV` is not `development`/`test` and the receipt pepper is the default or shorter than 32 characters, CORS origins are `*` or empty, or the database URL lacks `sslmode=require` on a non-local host. Interactive API docs are off by default in production. CI runs lint, unit tests, real-PostgreSQL integration tests, migration/model drift checks, a dependency audit, and a secret scan; evidence is the `.github/workflows/ci.yml` run history. The database host is Supabase-managed PostgreSQL reached only by the backend (no browser-facing Supabase key or Data API); record it in the processor register below before real personal data is accepted. Migration `0002_enable_rls` enables row-level security on every public table and revokes Data API role grants as defence in depth; the Supabase Data API should also be disabled in the dashboard.

### 2.3 Trust boundaries

```text
Browser and IndexedDB
        -> DNS and TLS edge
        -> reverse proxy or load balancer
        -> FastAPI application
        -> PostgreSQL

Conditional later components:
        -> Redis for expiring abuse counters only
        -> private object storage and media worker
        -> CDN for explicitly public, processed content only
```

Each boundary must document the accepted protocol, authenticated identity, trusted forwarding headers, encryption, cache behaviour, logging, timeouts, size limits, and failure behaviour.

## 3. Privacy and data governance

### 3.1 Applicable law and review

As of 15 October 2026, the primary official sources relevant to this specification include the [Personal Data Protection Act, 2026](https://bdlaws.minlaw.gov.bd/act-print-1692.html) and the [Cyber Security Act, 2026](https://bdlaws.minlaw.gov.bd/act-print-1710.html). The 2026 Cyber Security Act replaced the 2025 Cyber Security Ordinance; the project must not cite the repealed ordinance as current law.

The Personal Data Protection Act addresses lawful processing, consent evidence, data-subject rights, transparency, controller and processor responsibilities, erasure propagation, and conditions for cross-border transfer. This specification is an engineering control document, not legal advice.

**Deploy gate:** Before launch, record:

- The statutes, regulations, and official guidance checked.
- The check date and reviewer.
- Abhijatri's controller and processor roles.
- The lawful basis and purpose for every personal-data category.
- Whether any data leaves Bangladesh and the transfer condition relied upon.
- Any notification period or procedure required for a personal-data breach.

The legal register must be reviewed again when law, regulation, hosting region, verification method, or product scope changes.

### 3.2 Data inventory

| Data | Purpose | Planned location | Classification | MVP status |
|---|---|---|---|---|
| Guest display-name snapshot and review content | Moderation and publication | PostgreSQL | May be personal data | Implemented |
| Guest scope hash | Permanent offline-draft deduplication | PostgreSQL | Pseudonymous credential-derived data | Implemented |
| Guest tag (`reviews.guest_tag`) | Public pseudonym shown as "Anonymous guest · 1C669-J0TDY" on the guest's published reviews; derived from the scope secret (Guest-Identity-and-Visits 3.1) | PostgreSQL, public with the review | Public pseudonym; never logged (log filter redacts the pattern) | Implemented 22 Oct 2026 |
| Daily visit counters | Guest / Verified, new / returning visits per Asia/Dhaka day | Upstash Redis (8-day TTL), then `visit_daily_stats` | Aggregate, no identifiers | Implemented 22 Oct 2026 |
| Receipt hash | Guest review management | PostgreSQL | Pseudonymous authentication data | Implemented |
| Client draft UUID | Retry safety | PostgreSQL and IndexedDB | Pseudonymous identifier | Implemented |
| Member email and password hash | Authentication | PostgreSQL | Personal data | Build requirement |
| Verification decision metadata | Verified Member badge | PostgreSQL | Personal data | Schema foundation present |
| Verification evidence | One-time manual inspection | Private evidence storage | Sensitive personal data | Deploy gate; no real evidence in semester demo |
| Moderation and role audit metadata | Accountability | Insert-only database records | Staff personal data | Partial; complete audit boundary required |
| Rate-limit keys | Abuse prevention | Database or conditional Redis with TTL | Pseudonymous | Step 4 decision |
| Proxy and security logs | Security operations | Restricted log store | May include IP address | Deploy gate |
| Offline review draft | User-controlled drafting | Browser IndexedDB | May be personal data | Frontend build requirement |
| Public offline destination pack | Weak-network access | Service Worker and browser storage | Public content only | Step 8 build requirement |
| Review images | Verified Member review evidence | Private quarantine, then processed storage | May contain personal data | Core (Review.md A1) |

Secrets, tokens, raw verification documents, and private review bodies must not appear in analytics, application logs, URLs, cache keys, audit notes, or error-monitoring payloads.

### 3.3 Data minimisation

- Guest reviews require a display name but no account, email, phone number, or NID.
- Exact coordinates are not collected for review submission. A later user-initiated nearby search must request location only when used and must not place coordinates in logs or URLs.
- Verification stores the decision, method, approver, decision time, expiry, and revocation state. Evidence is temporary and private.
- Moderation notes contain reason codes and minimum necessary context, not copied review bodies or identity documents.
- Raw IP addresses are not used as permanent identity. CGNAT-sensitive abuse controls combine cautiously weighted network signals with account or Guest-scope signals.
- Media is excluded from the mandatory MVP. If introduced, EXIF and GPS metadata are removed during trusted re-encoding.

### 3.4 Consent and notices

The review submission notice, Privacy Policy, Terms and Conditions, and notice-and-takedown process must be versioned and available in Bangla and English with equal prominence. `consent_version` on each review revision records the submission notice accepted for that version.

The submission notice must explain:

- "Your reviews from this browser show the same guest tag, so readers can see they came from the same guest." (Guest-Identity-and-Visits 3.3, added 22 Oct 2026.)

- The review becomes public only after moderation.
- The display-name snapshot and review may identify the author.
- Published content can appear in time-bounded offline packs on other devices.
- Pending drafts stored in IndexedDB are not encrypted by the browser by default.
- How to withdraw, appeal, report, request removal, or exercise data rights.
- Which rating, moderation, and retention rules apply.

Only strictly necessary cookies are permitted in the MVP: authenticated member session, staff session, and an optional language preference. CSRF protection uses a synchronizer token, not a cookie. Guest receipts are sent in request bodies and never create a receipt session. Cloudflare Turnstile is used on Guest write forms and is named in the privacy notice. No advertising or third-party behavioural tracking is permitted. If non-essential tracking is introduced, it requires a separate privacy review and an opt-in consent mechanism before loading.

### 3.5 Children and student verification

The Personal Data Protection Act, 2026 defines a child as a person under 18 unless another age is prescribed. Student-focused features therefore create a material child-data risk.

**Deploy gate:** Before allowing real users, decide and document the minimum age, guardian-consent process where required, child-accessible notices, and whether student-ID verification is permitted. Until that decision is implemented, the semester demonstration uses controlled adult test accounts and synthetic evidence only. Raw NID or student-ID images must not be collected from real users.

### 3.6 Data-subject and Guest controls

| Control | Member | Guest |
|---|---|---|
| Access | Export account-owned data in a documented format. | View receipt-scoped review and moderation status. |
| Rectification | Edit only while `PENDING` or `CHANGES_REQUESTED`; published content uses withdraw and resubmit. | Same through a valid receipt. |
| Withdrawal | Remove public visibility and subtract any counted rating transactionally. | Same through a valid receipt. |
| Complaint or appeal | Account-owned report or appeal. | Receipt appeal or rate-limited public report. |
| Lost access | Auth recovery process. | Public removal request with reasonable claim verification. |
| Erasure | Account-deletion workflow. | Withdrawal followed by retention-controlled erasure. |

The exact account-deletion choice remains open in `Docs/Decisions.md`. Before implementation, choose deletion or defensible anonymisation. Either path must remove public personal linkage, subtract `counted_rating` under row locks, update affected aggregates exactly once, emit audit and outbox events, and prevent restoration from backups. Public launch is blocked until this decision and workflow are tested.

Rights requests are acknowledged and completed within the period required by current law and regulations. The internal target is 30 calendar days unless an applicable rule requires less time.

### 3.7 Retention schedule

The Review specification's content-retention rules remain authoritative. The following operational defaults complete them and require legal confirmation before launch.

| Record | Default retention |
|---|---|
| Published review | Until withdrawal, deletion, or policy action. |
| Inactive pending review | 30 days, then erase after any required notice. |
| Rejected review and revision content | 30-day appeal window, then tombstone personal content. |
| Guest receipt record | Through content or appeal lifetime; erase or revoke on final content erasure. |
| Idempotency replay response | 72 hours. |
| Verification evidence | At most seven days while pending; erase within 24 hours after decision. |
| Conditional quarantine media | 24 hours if unattached. |
| Rate-limit counters | At most 24 hours unless an active abuse case requires a documented exception. |
| Raw IP in restricted proxy logs | 30 days, subject to legal review. |
| Authentication and security-event logs | 90 days, subject to legal review. |
| Abuse-case extract | Until case closure, normally no more than 180 days. |
| Staff audit metadata | Two years, then review; no review body or evidence content. |
| Transactional-email delivery metadata | 30 days; never store message bodies unnecessarily. |
| Backup containing erased content | Rotate out within 35 days. |
| Non-content deletion ledger | At least until every affected backup has expired. |

Retention jobs run under a dedicated identity, are idempotent, and create an audit event. A restoration procedure reapplies the deletion ledger before restored content can become public.

### 3.8 Processors and cross-border transfer

**Deploy gate:** Maintain a processor register for hosting, database, object storage, email, DNS, monitoring, and any CDN or Redis provider. Record purpose, data categories, legal entity, region, subprocessors, security terms, breach commitments, deletion support, and exit procedure.

**Upstash (added 22 Oct 2026):** Redis in ap-southeast-1, one database per environment, holding aggregate visit and request counters only (no guest tag, secret, IP, user id or user agent). Purpose: visit statistics and the ops dashboard (`Docs/Decisions.md`, 22 Oct 2026).

No personal data is transferred outside Bangladesh until the legal transfer condition, destination suitability, required consent or contract basis, and actual storage region are documented against the Personal Data Protection Act, 2026 and applicable regulations.

## 4. Identity and access control

### 4.1 Application authorisation

- All protected operations call one server-side policy boundary: `can(actor, action, resource)`.
- Direct knowledge of `/admin`, a staff hostname, a review UUID, or a receipt-scoped URL grants no authority.
- Moderator, Administrator, and Super Administrator roles are stored in the database and assigned only by authorised staff.
- Moderators cannot assign roles, approve their own review, or access verification evidence without a separate permission.
- Review conflict changes, eligibility changes, role assignments, verification decisions, aggregate repairs, retention overrides, and deletion actions require a reason and audit record.
- Resource ownership is checked on every read and write. List endpoints must apply the same policy as item endpoints.
- Production errors do not reveal whether an inaccessible private object exists.

### 4.2 Authentication and sessions

**Build requirement:** Member authentication provides registration, email verification, sign-in, sign-out, password reset, session revocation, and secure recovery. Passwords use Argon2id with parameters recorded and periodically reviewed. Passwords and reset tokens are never logged.

Cookie-authenticated state changes require CSRF protection. Member and staff session cookies use `Secure`, `HttpOnly`, `SameSite=Lax` or stricter, `Path=/`, no `Domain` attribute, and the `__Host-` prefix. Member and staff sessions use different cookie names and cannot authorize each other's endpoints.

Guest receipt requirements:

- The client generates the receipt as `abr1_` followed by 43 base64url characters, representing 256 random bits, before the first submission. The server validates its exact format and rejects documented weak or test values.
- The server stores only `(key_id, HMAC-SHA-256 digest)` under a versioned keyring. Receipt and Guest-scope inputs use different fixed HMAC context labels.
- Receipts are never reissued, and comparison is constant-time.
- The receipt is sent in the JSON body of a rate-limited POST. It never appears in a cookie, URL, URL fragment, log, or analytics event.
- It is stored in IndexedDB only while its draft is unsent, shown after acknowledgement for the user to save, and then removed according to Platform Foundation 13.5.
- A receipt can access only its review, appeal, withdrawal, status, and allowed pending-edit operations. A lost receipt uses the moderated removal-request process.

### 4.3 Staff authentication

**Deploy gate:**

- MFA is mandatory for Moderator, Administrator, and Super Administrator accounts.
- Passkeys or hardware-backed factors are preferred for Super Administrators.
- Staff sessions have short idle and absolute lifetimes and are revoked on credential or role changes.
- Recent reauthentication is required for role assignment, verification decisions, retention overrides, deletion, and aggregate repair.
- The initial Super Administrator is created through a one-time bootstrap command, never public registration.
- A break-glass recovery procedure is time-limited, alerts another owner, and creates an audit event and post-use review.
- No shared staff accounts. At least two authorised people understand recovery.
- Active staff access is reviewed quarterly and after team membership changes.

### 4.4 Database separation of duties

| Identity | Minimum privilege |
|---|---|
| `abhijatri_app` | Required application DML through per-table forced-RLS policies, including the in-process outbox worker; no DDL; `INSERT` and narrowly required `SELECT` on audit storage. |
| `abhijatri_migrator` | Owns schema `app`; migrations and approved backfills only; credential exists only in protected GitHub Environments. |
| `abhijatri_retention` | `EXECUTE` on declared retention and cleanup functions only. |
| `abhijatri_backup` | `SELECT` through explicit RLS policies for `pg_dump --enable-row-security`; no modification. |
| Read-only operations and audit-reader roles | Deferred until a staff reporting feature requires them; audit is read through `can()`-protected staff endpoints. |

**Deploy gate:** Revoke `UPDATE`, `DELETE` and `TRUNCATE` on audit records from application-facing identities. The retention identity alone may tombstone revision content through fixed-search-path functions. The outbox worker runs in-process under `abhijatri_app`; a separate worker identity is required if it moves out of process.

## 5. Cryptography, secrets, and transport

### 5.1 Stored secrets

- Receipt and Guest-scope secrets use keyed HMAC-SHA-256 digests with a versioned high-entropy keyring. The two credential classes use different fixed context labels.
- Passwords use Argon2id; passwords are not encrypted reversibly.
- Session, CSRF, password-reset, and email-verification secrets are generated with a cryptographically secure generator and have explicit expiries.
- Secrets are injected by an environment or secret manager, separated by environment, and never committed to source control or container images.
- Pepper or signing-key rotation has a documented migration and emergency-revocation procedure.

### 5.2 Encryption at rest

**Deploy gate:** Database volumes, private object storage, logs, and backups use provider-managed encryption at rest with AES-256 or an equivalently reviewed modern control. Backups use separate access policy and preferably separate keys from live data. Key access is logged and least-privileged. The project records the actual provider, algorithm, key owner, and rotation method instead of merely claiming encryption.

### 5.3 Encryption in transit

**Deploy gate:**

- TLS 1.2 is the minimum; TLS 1.3 is enabled and preferred.
- A TLS 1.3-only policy is avoided unless low-end Android compatibility testing proves it safe.
- HSTS is enabled after HTTPS is stable. `includeSubDomains` and preload are enabled only after every subdomain is HTTPS-only.
- Traffic crossing host or trust boundaries among the edge, application, PostgreSQL, conditional Redis, and object storage is encrypted.
- Certificate issuance is restricted with CAA, and unexpected certificates are monitored through Certificate Transparency logs.

## 6. Application and API security

### 6.1 Input and content safety

- Pydantic and database constraints enforce field types, lengths, rating range, enum states, author shape, and uniqueness.
- SQL is parameterised through SQLAlchemy. Dynamic sort fields and identifiers are selected from allowlists.
- Review text is stored and rendered as plain text. User HTML is never trusted.
- Bangla display names are NFC-normalised. Reserved names and badge-like impersonation are rejected using a separate comparison skeleton without rewriting legitimate Bangla text.
- Request-body, field-count, header-count, and total-header-size limits are consistent at the edge and origin.
- File upload is unavailable until the conditional media threat model and processing pipeline pass acceptance tests.

### 6.2 Abuse controls

Starting values are recorded in Platform Foundation 14.3 and tuned through measured abuse and usability tests. Guest write limits combine a per-credential hard ceiling, a higher network-digest hard ceiling, a fresh server-validated Cloudflare Turnstile token, and per-destination and global pending-review caps.

Network ceilings are deliberately higher than per-credential limits because Bangladeshi mobile carriers may place unrelated users behind CGNAT. They remain enforceable ceilings because a Guest scope is free to regenerate. The application cannot force a managed Turnstile widget to become interactive; Cloudflare chooses interaction. Rate-limit keys are pseudonymised and expire.

### 6.3 Concurrency and rating integrity

- Every moderation, eligibility, conflict, restore, withdrawal, deletion, and account-deletion transition locks the review and destination aggregate rows with `SELECT ... FOR UPDATE`.
- The request supplies the expected review `version`; a stale transition fails with a conflict.
- `counted_rating` records the contribution currently present in an aggregate. The transaction removes the old contribution and applies the new one at most once.
- Rejected reviews have `counted_rating = NULL`; rejecting a never-published review has zero aggregate delta.
- Conflict flag changes use the same locked transition and audit path.
- A nightly reconciliation compares stored aggregates with a full source-row recomputation and repairs only through an explicit audited operation.

### 6.4 Browser security headers

Every HTML response uses a restrictive Content Security Policy with no unsafe inline script, `frame-ancestors 'none'`, `X-Content-Type-Options: nosniff`, a conservative `Referrer-Policy`, a restrictive `Permissions-Policy`, and `Cross-Origin-Opener-Policy` where compatible. Geolocation is disabled except for a user-initiated nearby feature. CORS uses an explicit origin allowlist and never combines a wildcard origin with credentials.

## 7. Cache and offline safety

### 7.1 Cache allowlist

Only the following response classes may be stored in a shared cache:

| Route class | Policy |
|---|---|
| Versioned static assets with hashed filenames | `public, max-age=31536000, immutable`. |
| Published destination pages and bounded public review feeds | Short explicit TTL, locale-aware key, purge on moderation or deletion. |
| Versioned public destination packs | Explicit version and maximum age. |
| Conditional processed and approved media | Public CDN path with deletion purge. |

Authentication, account, receipt, report, verification, moderation, staff, upload-intent, and cookie-dependent responses use `Cache-Control: no-store`. Responses containing `Set-Cookie` or depending on `Authorization` always bypass shared caches.

The existing public route `GET /api/v1/destinations/{destination_id}/reviews` returns published reviews only. Any future owner or staff item endpoint remains private and `no-store`; a separately named public item endpoint is required before individual published reviews are cached.

### 7.2 Cache deception and poisoning controls

- Cacheability is determined by an exact route allowlist, never file extension, suffix, or response `Content-Type` alone.
- Unknown paths and extra path segments return `404`; encoded slashes, dot segments, semicolons, null bytes, and duplicate separators are rejected or consistently normalised before routing and cache-key construction.
- Cache keys use the configured canonical scheme and host, normalised path, locale, representation encoding, and allowlisted query parameters only.
- Client-supplied forwarding and rewrite headers are stripped at the edge. The application trusts forwarding headers only from configured proxies and never builds security-sensitive absolute URLs from arbitrary request headers.
- Cacheable responses do not reflect request headers, cookies, or unkeyed query values.
- GET and HEAD requests with bodies are rejected at both edge and origin.
- Unsupported methods return `405`; `TRACE` and `CONNECT` are disabled.
- Error responses use `no-store`, except a deliberately documented few-second edge policy for generic overload protection.
- Public review and destination cache entries use surrogate keys or equivalent tags so moderation, withdrawal, conflict changes, and deletion can purge all affected representations.

### 7.3 Request smuggling and parser consistency

**Deploy gate:** Edge, proxy, and ASGI server use patched supported versions and compatible parsing rules. Reject both `Content-Length` and `Transfer-Encoding`, conflicting or duplicate lengths, malformed chunking, and ambiguous request targets. Strip hop-by-hop headers at the edge. Test the real deployed proxy chain, particularly any HTTP/2-to-HTTP/1.1 conversion.

### 7.4 Service Worker and IndexedDB

- The Service Worker caches only the app shell, versioned assets, and user-selected public destination packs.
- It never caches authenticated, receipt, verification, report, private-community, or staff responses.
- It honours `no-store` and refuses responses containing `Set-Cookie` or an authenticated request context.
- Destination packs include schema version, content version, source dates, snapshot time, and an explicit maximum age selected at Step 8.
- Reconnection checks freshness and applies the deletion ledger before presenting a refreshed pack as current.
- An expired pack is labelled unavailable or stale according to the Step 8 decision; it is never silently presented as current safety guidance.
- IndexedDB drafts are not encrypted by default. The interface discloses this, offers per-draft and clear-all deletion, and avoids storing verification evidence, receipts of submitted reviews, private emergency contacts, or private-community conversations. The receipt of an unsent Guest draft is stored with that draft only until acknowledgement under Platform Foundation 13.5. Public emergency numbers in a destination pack are public content.
- The application calls `navigator.storage.persist()` where supported and handles refusal without claiming durability.
- Service-worker cache names are versioned. Activation removes obsolete caches only after the replacement is ready.
- Sign-out clears session-derived local state. Public packs may remain only because they contain no private account data.

## 8. Object storage and media security

This section applies to the Verified Member image pipeline, which is in core scope since Review.md amendment A1 (20 October 2026). Guests cannot upload media.

- Separate private prefixes or buckets are used for `quarantine/`, `processed/`, `evidence/`, and `backups/`.
- Public ACLs are blocked. Quarantine and evidence are never routed through a CDN.
- The API can create constrained presigned upload policies for quarantine only. The media worker alone reads quarantine and writes processed objects. The CDN origin identity reads approved processed objects only.
- The worker verifies file signature, decodes with CPU, memory, pixel, and time limits, rejects SVG and archives, strips metadata, and re-encodes to an approved raster format.
- The worker cannot reach cloud metadata services or arbitrary network destinations.
- Unattached quarantine objects and abandoned multipart uploads expire automatically.
- Media removal deletes public metadata, removes or tombstones objects under policy, and purges every CDN representation. Purge failure is retried and alerted.

## 9. Infrastructure, DNS, backup, and incident response

### 9.1 Network and runtime

- Only the edge accepts public traffic on ports 80 and 443; HTTP redirects to HTTPS.
- Application, database, workers, and conditional Redis/object storage administration remain private.
- Security groups are default-deny. Egress is allowlisted by workload.
- Application containers run as non-root with a read-only root filesystem where practical and a dedicated writable temporary directory.
- Administrative access uses a provider session manager or MFA-protected bastion, not public password SSH.
- Production, staging, test, and development use separate credentials and data.

### 9.2 DNS

**Deploy gate:** Enable DNSSEC where supported, registrar and transfer lock, registrar MFA, and at least two named recovery owners. Publish CAA records for the selected certificate authority, monitor Certificate Transparency, remove dangling DNS records, and review the zone quarterly. The team does not operate an open recursive resolver.

### 9.3 Backups and recovery

- Backups are encrypted, access-logged, and separated from live runtime credentials.
- Restore tests run on a schedule and verify schema, content state, aggregate reconciliation, and deletion-ledger reapplication.
- Recovery objectives are measured and recorded; the proposal does not claim untested uptime or recovery times.
- A restored review cannot become public until current moderation, withdrawal, deletion, and retention records are applied.

### 9.4 Incident response

**Deploy gate:** Name an incident owner and backup. Maintain severity definitions, containment and evidence procedures, user and authority notification decision trees, contact details, and templates. Include rotation procedures for database credentials, session secrets, email credentials, receipt pepper, signing keys, object-storage credentials, and DNS access. Notification timing follows current law and regulation rather than an invented universal deadline.

Every material incident produces a post-incident review and tracked corrective actions. Secrets discovered in source control are revoked and rotated; deleting the file alone is insufficient.

## 10. Security testing and release gates

### 10.1 Automated security tests

- Database constraints reject ratings outside 1 to 5, invalid author shape, duplicate active Member visits, and duplicate client draft identities.
- Concurrent moderation applies an aggregate delta once and rejects the stale version.
- Random publish, hide, restore, withdraw, conflict, and deletion sequences match a full aggregate recomputation on real PostgreSQL.
- Hidden, rejected, withdrawn, and deleted reviews never appear in the public feed.
- Unauthenticated and ordinary users cannot access staff endpoints.
- A moderator cannot moderate their own review.
- Every protected or cookie-setting route returns `no-store`.
- A route-policy inventory test fails when a new route has no explicit cache classification.
- Pending or receipt-scoped content never appears through a public route or shared cache.
- Path-confusion, forwarded-header spoofing, ambiguous-length, GET-body, oversized-header, IDOR, CSRF, and CORS tests run against the deployed proxy chain.
- Bangla name normalisation, reserved-name, badge-impersonation, and conjunct-rendering tests pass.
- Dependency, secret, and container scans run in CI; unresolved critical findings block release.

### 10.2 Public deployment checklist

- [ ] Current legal register and lawful-purpose mapping reviewed.
- [ ] Child and student-verification decision implemented.
- [ ] Bangla and English Privacy Policy, Terms, submission notice, cookie notice, and takedown process published.
- [ ] Account deletion or anonymisation decision implemented and tested with aggregate subtraction.
- [ ] Processor and cross-border transfer registers complete.
- [ ] Production authentication replaces the development staff header.
- [ ] Staff MFA, recent reauthentication, break-glass recovery, and access review enabled.
- [ ] CSRF, session revocation, login throttling, and recovery controls tested.
- [ ] Separate database roles deployed and audit immutability verified.
- [ ] Encryption at rest, TLS configuration, HSTS rollout, secrets, and key rotation verified.
- [ ] Exact abuse limits, CGNAT-aware keys, challenge, and pending-review cap recorded.
- [ ] Route cache allowlist and `no-store` inventory pass in staging.
- [ ] Offline snapshot maximum age and deletion refresh behavior implemented.
- [ ] Smuggling and parser tests pass against the actual edge and origin chain.
- [ ] DNSSEC, registrar protection, CAA, and certificate monitoring active.
- [ ] Encrypted backup restoration and deletion-ledger reapplication tested.
- [ ] Incident-response exercise completed and corrective actions closed.
- [ ] Conditional media and CDN gates pass if those components are included.

### 10.3 Manual review

A team member who did not implement the control performs an authenticated and unauthenticated walkthrough using a browser and intercepting proxy. The review covers staff-route access, IDOR, receipt isolation, CSRF, cache deception, forwarded-header poisoning, public/private route separation, withdrawal, deletion, offline staleness, and Bangla error messages. Findings receive severity, owner, evidence, retest result, and release disposition.

## 11. Exclusions and change control

Payment-card processing, live vendor inventory, agency onboarding, private-community chat, real-time location sharing, and machine-learning moderation require separate threat models before implementation. Sandbox payment demonstrations must not accept real money or production credentials.

The Review specification remains frozen. Security decisions made while building are recorded in `Docs/Decisions.md`. A change that affects schema, public claims, retention, rating integrity, authentication, or legal basis requires an explicit decision-log entry and updated tests.
