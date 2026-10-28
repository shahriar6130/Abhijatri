# Platform Foundation

## 1. Purpose

The Platform Foundation defines the shared architecture, security controls, data rules, deployment procedures, quality standards and operational requirements that Abhijatri features depend on.

The foundation directly supports:

- destination information
- community reviews
- identity and verification
- moderation
- bilingual presentation
- low-bandwidth and selected offline use
- auditability and operational recovery

Private community functions, cost estimation, reservations, bookings and demonstration payments are not foundation deliverables. Each needs its own approved feature specification and must not delay the Destination and Review vertical slice.

## 2. Authority Order

Authority is domain-specific:

1. `Docs/Abhijatri_Project_Proposal.pdf` governs approved semester scope, milestone gates and final acceptance boundaries.
2. `Docs/Abhijatri Project Gantt — CSE 3102.xlsx` governs accepted task dates, primary ownership, dependencies and effort allocation. It cannot broaden the proposal scope or weaken security and feature requirements.
3. `Docs/Security.md` governs security and privacy requirements.
4. Approved feature specifications govern feature behaviour and acceptance criteria. A file under `Features/` is authoritative only when its header explicitly says it is approved or final.
5. `Docs/Platform-Foundation.md` governs shared platform architecture, engineering controls and release gates.
6. `Docs/Decisions.md` records approved decisions and amendments; it does not independently override a higher domain authority.
7. `Docs/Architecture.md`, `Docs/Schema.md`, `Docs/API.md` and the generated OpenAPI snapshot describe the target and as-built design within the authorities above.
8. Database migrations and constraints are as-built evidence, not permission to contradict an approved requirement.
9. Implementation comments and informal discussion are non-authoritative.

Rules:

- The governing document for the affected domain controls a conflict. A lower-authority document cannot amend it by restating a different rule.
- A lower document can change a higher one only through a dated amendment merged into the higher document itself. The amendment is referenced from `Decisions.md`. Until it is merged, the higher document governs.
- A migration, constraint or implementation that contradicts a specification is a defect. It is fixed in code, or the specification is amended under the rule above. It is never accepted silently.
- Security restrictions cannot be weakened through a feature document, a decision entry or an implementation shortcut.
- `Features/Execution.md` controls the approved dependency sequence only. It cannot amend the proposal, security requirements, this foundation, an approved feature specification, or the accepted Gantt schedule.

## 3. Scope Control

### 3.1 Foundation Scope

The foundation includes:

- React and TypeScript application shell
- FastAPI modular-monolith backend
- PostgreSQL integration
- environment configuration
- secret management
- database roles and row-level security
- authentication foundation
- bilingual infrastructure
- PWA and offline foundation
- API conventions
- audit and observability
- continuous integration
- deployment and recovery procedures

### 3.2 Initial Application Modules

Only the following backend packages shall exist under `backend/app/`:

```text
app/
  main.py          application factory
  api/             HTTP routers, one module per feature, mounted under /api/v1
  auth/
  destinations/
  reviews/
  moderation/
  offline/
  notifications/
  audit/
  jobs/            scheduled job entry points (Section 23 and Section 24)
  shared/          config, database session, keyring, errors, client address
```

The current flat modules (`api.py`, `services.py`, `models.py`, `schemas.py`, `config.py`, `db.py`) are moved into these packages in one refactor before Gate A. A package and a module with the same name cannot coexist, so `app/api.py` is removed in the same change that creates `app/api/`.

The following modules shall not be created until their specifications and schedules are approved:

- private community
- cost estimator
- bookings
- reservations
- payments
- vendor management
- group tours

Creating empty folders or placeholder services for unapproved features is prohibited because it creates false progress and encourages hidden scope expansion.

### 3.3 Architecture Style

Abhijatri shall use a modular monolith.

A microservice architecture is outside the semester scope. A module may become a separate service later only when measured load, independent deployment needs or operational isolation justify the change.

## 4. System Architecture

```text
Public PWA:  app.<owned-domain>    Render static site (prerendered destination pages + PWA)
Staff UI:    admin.<owned-domain>  Render static site (separate build)
                 |
                 | HTTPS, credentialed fetch (same registrable site)
                 v
FastAPI API: api.<owned-domain>    Render web service (Docker)
                 |
                 | PostgreSQL protocol over TLS, Supavisor session pooler
                 v
Supabase PostgreSQL                schema "app", roles in Section 10

Scheduled jobs: GitHub Actions (migrations, backup, retention, cleanup)
Email:          Resend HTTPS API, sending subdomain mail.<owned-domain>
Challenge:      Cloudflare Turnstile (browser widget + server-side validation)
```

The browser communicates only with FastAPI and the two static sites. It never accesses application tables through Supabase REST, GraphQL or client libraries, and it holds no Supabase key.

## 5. Domain and Origin Topology

### 5.1 Required Domain

The team shall choose the top-level domain by 17 October 2026, and acquire and control one registrable domain by 20 October 2026.

A generic top-level domain such as `.com`, `.app` or `.org` shall be used, because it can be registered within the deadline. A `.bd` or `.com.bd` domain may be added later as a redirect. It shall not be on the critical path.

The registrar account shall have MFA and transfer lock enabled, with two named recovery owners (`Security.md` 9.2).

The final domain shall replace `<owned-domain>` in configuration and documentation.

| Name | Type | Purpose |
|---|---|---|
| `app.<owned-domain>` | Web host | Public PWA |
| `api.<owned-domain>` | Web host | FastAPI API |
| `admin.<owned-domain>` | Web host | Staff interface |
| `mail.<owned-domain>` | Email sending subdomain only | SPF, DKIM, DMARC and return-path records for Resend. It has no web host and no A or CNAME record for browsers. |

The public and staff interfaces are separate builds. Staff assets and routes shall never be included in the public build or in a destination pack.

Render's Hobby workspace includes two custom domains. The three web hosts therefore cost one additional custom domain, currently USD 0.25 per month, which is accepted.

### 5.2 Why Render Subdomains Are Insufficient

`onrender.com` is a public suffix. Separate services such as `frontend.onrender.com` and `api.onrender.com` are therefore different sites for cookie purposes. The project shall use subdomains of a team-controlled domain. See the [Public Suffix List](https://publicsuffix.org/list/public_suffix_list.dat).

### 5.3 Cookie Topology

`app.`, `admin.` and `api.<owned-domain>` share one registrable domain, so requests between them are same-site.

The API sets exactly two cookies, both host-only on `api.<owned-domain>`:

| Cookie | Used by | `SameSite` |
|---|---|---|
| `__Host-abhijatri_session` | Member session | `Lax` |
| `__Host-abhijatri_staff_session` | Staff session | `Strict` |

Both cookies shall use:

- `Secure`
- `HttpOnly`
- `Path=/`
- no `Domain` attribute
- the lifetimes in Section 8.5
- server-side revocation

The `__Host-` prefix prevents a parent-domain cookie from shadowing them.

The staff interface uses the staff session only. Member sessions shall not authorize staff endpoints, and staff sessions shall not authorize member endpoints.

Guest receipts are not cookies. They are presented in the request body (Section 13). No receipt session cookie exists.

### 5.4 DNS and Transport Security

Render supports custom domains, managed TLS certificates and HTTPS redirection. Its certificate authorities are Let's Encrypt and Google Trust Services. See [Render custom domains](https://render.com/docs/custom-domains) and [Render managed TLS](https://render.com/docs/tls).

The team shall:

- enable DNSSEC when the registrar and DNS provider support it
- publish CAA records `0 issue "letsencrypt.org"` and `0 issue "pki.goog"`
- monitor Certificate Transparency logs for the domain
- redirect HTTP to HTTPS
- disable each service's `onrender.com` subdomain after its custom domain is verified
- leave DNS records unproxied (no CDN or Cloudflare proxy in front of Render). A proxy changes the client-address chain in Section 14.2 and may only be added through an amendment to this document.
- remove dangling DNS records, and review the zone before Gate B
- enable HSTS separately on `app.`, `api.` and `admin.` after each host is confirmed to work over HTTPS
- begin with `max-age=300` and raise it to 86400 after one week without errors
- omit `includeSubDomains` unless the apex domain is also served over HTTPS and deliberately sends the parent-domain HSTS policy; a header sent by one subdomain does not protect its sibling subdomains
- not request HSTS preload during the semester

TLS 1.2 is the minimum and TLS 1.3 is preferred (`Security.md` 5.3).

### 5.5 Domain Schedule

| Task | Deadline |
|---|---:|
| Choose the top-level domain | 17 October 2026 |
| Acquire the domain; enable registrar MFA and transfer lock | 20 October 2026 |
| Configure `app`, `api` and `admin` records | 21 October 2026 |
| Verify Render custom domains and TLS; disable `onrender.com` subdomains | 22 October 2026 |
| Verify the Resend sending subdomain (SPF, DKIM, DMARC) | 24 October 2026 |
| Cookie, CORS and CSRF spike: a stub session endpoint on staging proves cookie scope, credentialed CORS and the CSRF token flow | 27 October 2026 |
| Full cookie, CORS and CSRF validation with real authentication | 23 November 2026 (with authentication acceptance, Section 9) |

Failure to obtain a domain does not block local Destination development. It does block production authentication, transactional email and Gate B.

## 6. Immediate Credential Containment

Credential rotation is Gate Zero and takes priority over all feature work.

If a Supabase credential, database password, receipt or scope key, encryption key, email API key, Turnstile secret, session secret or equivalent credential has appeared in a chat, AI tool, screenshot, document, repository or shared message, it shall be treated as compromised.

The team shall immediately:

1. Rotate the exposed credential.
2. Revoke the previous credential.
3. Update the approved deployment environments.
4. Search source history, documents and screenshots for further exposure.
5. Run the repository secret scanner over the full history.
6. Record the rotation date and responsible member, without recording the secret.
7. Confirm that no real credential exists in the repository.

Rotating the receipt and scope key follows the keyring procedure in Section 13.4. Existing receipts stay valid under the retained key unless that key itself was exposed. In that case, affected guests use the removal-request process.

The configuration template is `backend/.env.example`.

`.gitignore` and the secret-scanner configuration shall cover:

```text
.env
.env.*
!.env.example
env.example
*.pem
*.key
*.dump
*.age
```

The `*.dump` and `*.age` rules keep backup files out of the repository (Section 23).

## 7. Environment Separation

### 7.1 Environments

| Environment | `APP_ENV` | Purpose | Database |
|---|---|---|---|
| Local | `development` | Individual development | Local PostgreSQL 17 container |
| Test | `test` | Automated integration and migration tests | Disposable CI PostgreSQL 17 container |
| Staging | `staging` | Shared acceptance and security testing; no production data | Supabase project `abhijatri-staging` |
| Production or pilot | `production` | Approved pilot and final demonstration | Supabase project `abhijatri-prod` |

The existing Supabase project `abhijatri-dev` is renamed `abhijatri-staging`, and `Decisions.md` is updated to match.

Local and test environments shall never use staging or production credentials. Staging shall never contain production data.

Supabase grants two free projects per user, counted across every organization where the user is an Owner or Administrator. Paused projects do not count ([Supabase billing](https://supabase.com/docs/guides/platform/billing-on-supabase)). Both projects shall be owned by one named team member, whose other free-project usage is checked before Gate A.

If two projects cannot be kept, the team shall use:

- one Supabase project for production or pilot
- local or disposable PostgreSQL for pre-production testing
- no shared staging environment containing production data

Schema prefixes are not an acceptable substitute for isolation between production and testing.

All environments shall run the same PostgreSQL major version. The Supabase projects' version is read from the dashboard and recorded. Local, CI and the backup client use the same major version.

### 7.2 Configuration Validation

Every environment shall declare:

- environment name
- public application origin
- staff application origin
- API origin
- database connection method and runtime role
- cookie security mode
- allowed CORS origins
- email adapter
- Turnstile site key, secret key and expected hostnames
- keyring identifiers (receipt and scope HMAC keys, encryption keys)
- client-address mode (Section 14.2)
- build version

Every `APP_ENV` other than `development` and `test` is treated as production-like. Startup in staging and production shall be rejected when any of the following is true:

- a required secret is absent, too short, or fails its format check
- a secret equals any value in `backend/.env.example`, a value used in CI, or a documented development default
- an origin uses `localhost`, `127.0.0.1` or plain `http`
- CORS contains a wildcard
- trusted-proxy configuration contains a wildcard
- Turnstile uses a Cloudflare test key
- the development identity handler is enabled
- debug mode is enabled
- the database URL lacks TLS (`sslmode=require` or stricter)
- the runtime database role is `postgres` or any role with `BYPASSRLS`. This is checked against `current_user` and `pg_roles` at startup.

Each rejection rule has a unit test in `tests/test_config.py`. The example-value test reads `.env.example` itself, so a new example value is covered automatically.

## 8. Authentication and Identity

### 8.1 Authentication Decision

Abhijatri shall use first-party authentication implemented in FastAPI and PostgreSQL.

Supabase Auth shall not be used in the first implementation, because FastAPI is the sole application access boundary.

### 8.2 Account Capabilities

The identity module shall provide:

- registration
- email verification
- login and logout
- password reset
- opaque server-side sessions
- session revocation
- verification records
- member suspension
- staff role assignment
- staff TOTP multi-factor authentication
- recent reauthentication for privileged staff actions
- security audit events

Phone, NID and student-ID verification are deferred until separately specified.

Real users are not admitted until the minimum-age and student-verification decision required by `Security.md` 3.5 is implemented. Until then, demonstrations use controlled adult test accounts.

### 8.3 Roles and Verification

Authorization role codes, as stored in `platform_roles.code`:

- `MEMBER`
- `MODERATOR`
- `ADMINISTRATOR`
- `SUPER_ADMINISTRATOR`

`VERIFIED_MEMBER` is a verification type, not a role.

The Verified Member badge is derived from active, unexpired, unrevoked verification records. Revoking or expiring a verification removes the badge without changing the member's authorization role. Rating eligibility follows `Features/Review.md` 6.3.

### 8.4 Initial Super Administrator

The first super administrator is created through an interactive management command (`python -m app.jobs.bootstrap_admin`).

The command shall:

- accept the initial identity at run time
- never embed credentials in migrations or source code
- refuse to run when an active super administrator already exists
- record an audit event
- require email verification before first login
- force a password change on first login
- require TOTP enrolment on first login
- block every privileged action until MFA enrolment is complete

The last active super administrator cannot be demoted, suspended or deleted through ordinary administration.

The break-glass recovery procedure shall be documented. It shall require two designated team members, be time-limited, notify the other super administrators, create a high-priority audit event and be followed by a recorded post-use review (`Security.md` 4.3).

### 8.5 Password and Session Security

Passwords use Argon2id. The parameters are recorded in `Decisions.md` and reviewed before Gate B.

The database stores the SHA-256 digest of each opaque session token, never the raw token. Session tokens contain at least 256 bits from a cryptographically secure generator.

| Session | Idle timeout | Absolute lifetime |
|---|---|---|
| Member | 7 days | 30 days |
| Staff | 30 minutes | 8 hours |

Recent reauthentication (password and TOTP within the last 5 minutes) is required for:

- role assignment or removal
- verification decisions
- retention overrides
- deletion actions
- aggregate repair

A session is rotated (a new token is issued and the old one revoked) after:

- login
- password reset
- privilege elevation or reauthentication
- staff role change
- detection of suspicious activity
- MFA recovery

All sessions of a user are revoked on a password change, password reset, suspension or role removal.

State-changing cookie-authenticated requests require the CSRF token described in Section 16.2.

Registration, verification, login and reset responses shall not reveal whether an email address exists. Status code, body and timing class shall be materially the same for known and unknown addresses.

### 8.6 TOTP Protection

TOTP secrets cannot be hashed, because the server must use them to verify codes.

They are encrypted with AES-256-GCM using a key from the encryption keyring (Section 15.1). Each record stores:

- encryption `key_id`
- nonce
- ciphertext
- creation time
- rotation state

Recovery codes are hashed separately with Argon2id and are single-use.

An accepted TOTP code cannot be reused within its time step. The last accepted step is stored per user. Verification allows one step of clock tolerance either side. Repeated failures are rate-limited and recorded as security audit events.

### 8.7 Email Provider

Resend is the initial transactional-email provider, used through its HTTPS API.

Production-like delivery requires the verified sending subdomain `mail.<owned-domain>`. Local and automated tests use a recording adapter that sends no external email.

The provider interface shall remain replaceable.

Free-plan limits are 100 emails per day (reset at 00:00 UTC, which is 06:00 in Dhaka) and 3,000 per month. The provider-wide daily cap in Section 15.3 is therefore 80, leaving headroom for staff and test messages. See the [Resend quotas](https://www.resend.com/docs/knowledge-base/account-quotas-and-limits.md).

## 9. Authentication Delivery Track

Authentication runs in parallel with the guest Destination and Review slice. Gate A requires only approval of its specification and interfaces, not a finished implementation.

| Authentication deliverable | Target |
|---|---:|
| Domain selected and registered | 20 October 2026 |
| `Features/Identity-Access-Verification.md` written and approved | 22 October 2026 |
| Account, session and CSRF schema | 5 November 2026 |
| Registration, verification, login and logout | 12 November 2026 |
| Password reset and session revocation | 15 November 2026 |
| Staff roles, TOTP, reauthentication and last-admin protection | 20 November 2026 |
| Authentication security and integration acceptance, including the full cookie, CORS and CSRF validation from Section 5.5 | 23 November 2026 |

Public Destination content and guest-review development may continue without member authentication.

Local and test environments may use the development-only identity handler (Section 25) for moderation testing. A shared environment shall not use it.

## 10. Database Isolation

### 10.1 Application Schema

Application tables are stored in a PostgreSQL schema named `app`. It is not listed in the Supabase Data API exposed schemas.

The Supabase-managed roles `anon`, `authenticated` and `service_role` shall have no privilege on schema `app` or any object in it. `anon` and `authenticated` are the Data API's browser roles. `service_role` is Supabase's server-key role and is not used by Abhijatri.

The Supabase Data API shall be disabled in each project's dashboard. The CI test in Section 10.7 checks the grants regardless.

### 10.2 Database Roles

| Role | Login | Purpose | Where its credential lives |
|---|---|---|---|
| `abhijatri_migrator` | yes | Owns all objects in `app`; runs migrations | Protected GitHub Environment only |
| `abhijatri_app` | yes | FastAPI runtime, including the in-process outbox worker | Render service environment |
| `abhijatri_retention` | yes | Retention, tombstoning and expired-row cleanup jobs | Protected GitHub Environment only |
| `abhijatri_backup` | yes | Logical backup reads | Protected GitHub Environment only |

Rules:

- Only `abhijatri_migrator` owns tables, sequences, functions and policies in `app`.
- No role in this table has `BYPASSRLS`, `SUPERUSER`, `CREATEROLE` or `CREATEDB`.
- The runtime shall never connect as `postgres`. The Supabase `postgres` role is used only for creating these roles and for documented recovery.
- Each login role's `search_path` is set to `app`.
- Read-only operations views and an audit-reader role (`Security.md` 4.4) are deferred until a staff reporting feature needs them. Until then, audit records are read only through staff API endpoints protected by `can()`.

### 10.3 Forced Row-Level Security and Policy Model

Every table in `app` enables and forces row-level security.

Row-level security in Abhijatri is a **role-level allowlist and defence in depth**. It is not per-user isolation. Per-user and per-resource authorization is enforced in FastAPI by `can(actor, action, resource)` (`Security.md` 4.1). PF-13 evidence shall not claim more than this.

Policies follow these rules:

- **`abhijatri_app`.** Policies are written per table and per command, listing only the commands the runtime needs (for example, `INSERT` and `SELECT` on audit tables only). Tables the runtime never touches have no runtime policy.
- **`abhijatri_migrator`.** It has an explicit policy for each command used in data migrations and backfills. DDL is not affected by RLS.
- **`abhijatri_backup`.** It has `SELECT` policies on every backed-up table and no other command.
- **`abhijatri_retention`.** Its policies are limited to the rows and columns described in Section 10.5.
- **Request context.** Each request transaction sets `SET LOCAL app.request_id` and, when authenticated, `SET LOCAL app.actor_id`. Audit triggers may record these. Policies do not depend on them in the first implementation.

### 10.4 Audit Table Rules

The runtime role's access to audit tables is limited to:

- `INSERT`
- `SELECT` where a staff API endpoint needs it

The runtime role has no `UPDATE`, `DELETE` or `TRUNCATE` privilege on audit tables.

Audit entries are append-only from the application's perspective.

Database administrators may perform documented recovery operations. Each one requires separate written evidence and a post-operation audit entry.

### 10.5 Retention Role

Only `abhijatri_retention` may tombstone protected revision content after the approved retention condition is met (`Security.md` 3.7).

It operates through `SECURITY DEFINER` functions owned by the migrator. Each function has a fixed `search_path`, and the role has `EXECUTE` on those functions only. It never receives general `UPDATE` on application tables.

The same role runs the cleanup of expired rate-limit buckets, idempotency records, outbox payload metadata and inactive pending reviews, using one function per rule.

Every retention action creates an audit record containing:

- affected record
- retention rule
- execution time
- job identifier
- result

### 10.6 Migration Helper

The repository shall provide one migration helper for creating application tables.

The helper shall apply:

1. `app` schema placement
2. primary and foreign keys
3. required `CHECK` constraints
4. RLS enablement
5. forced RLS
6. the role policies from Section 10.3
7. least-privilege grants

CI still inspects the resulting database directly. The helper reduces mistakes but does not replace verification.

Login roles are created outside Alembic, because `abhijatri_migrator` has no `CREATEROLE`. The script `backend/scripts/create_roles.sql` creates them with `LOGIN` but no password, so they cannot authenticate until a password is set:

- On Supabase, an administrator runs the script once per project as `postgres`, then sets each password with `ALTER ROLE ... PASSWORD` directly in the SQL editor. Passwords are never written to the repository.
- In CI and local development, the container superuser runs the script, with throwaway passwords, before `alembic upgrade head`.

The move from `public` to `app` is one migration (`0003_app_schema_and_roles`). The existing tables are owned by `postgres`, so this migration runs exactly once per Supabase project as `postgres`, through the protected workflow with a one-time approval. Every later migration runs as `abhijatri_migrator`. The migration shall:

- create schema `app` owned by `abhijatri_migrator`
- move every existing table and sequence with `ALTER ... SET SCHEMA app`
- change ownership to `abhijatri_migrator`
- enable and force RLS and create the policies
- grant the role privileges
- revoke the Supabase roles' privileges

Alembic's version table moves to `app` through `version_table_schema="app"`. Migration `0002_enable_rls` remains in history. Its `public`-only test is replaced by the test in Section 10.7.

### 10.7 CI Database Security Test

`tests/test_database_security.py` runs against real PostgreSQL after `alembic upgrade head`. It fails if:

- an application table exists outside schema `app`
- RLS or forced RLS is missing on any table in `app`
- any object in `app` is owned by a role other than `abhijatri_migrator`
- any `abhijatri_*` role has `BYPASSRLS`, `SUPERUSER`, `CREATEROLE` or `CREATEDB`
- `anon`, `authenticated`, `service_role` or `PUBLIC` holds any privilege in `app`
- the runtime role can `UPDATE`, `DELETE` or `TRUNCATE` an audit table
- `pg_dump --enable-row-security` run as `abhijatri_backup` does not return every seeded row
- `abhijatri_retention` holds any table privilege, or any function privilege other than the declared retention functions
- the runtime role holds a privilege that is not in the declared grant manifest (`backend/app/shared/grants.py`)

## 11. Data Standards

### 11.1 Identifiers

Externally visible records use UUIDs. The server assigns record identifiers. The only client-generated identifiers are `client_draft_id` (`Features/Review.md` 4.1) and `Idempotency-Key` values.

### 11.2 Time

Stored timestamps use `timestamptz` in UTC.

Bangladesh-facing calendar decisions use the `Asia/Dhaka` IANA time zone, including:

- visit month
- advisory validity
- seasonal rules
- local dates
- public holidays

### 11.3 Money

This standard applies to later specifications. No foundation module stores money.

Money uses PostgreSQL `NUMERIC(14,2)`. Binary floating-point types are prohibited. Python uses `Decimal`. API values are serialized as decimal strings with an ISO 4217 currency code.

### 11.4 Unicode Normalization

User-facing and searchable text is normalized to Unicode NFC before comparison or persistence, where normalization is appropriate.

Normalization shall never alter:

- passwords
- opaque tokens and receipts
- cryptographic secrets
- signatures
- encoded binary content

Impersonation checks use a separate confusable skeleton and never rewrite stored text (`Features/Review.md` 3.4).

Bangla search and duplicate-detection tests cover visually equivalent Unicode sequences, ZWJ and ZWNJ, and conjunct rendering.

## 12. API Contract

### 12.1 Versioning

Public application endpoints begin with:

```text
/api/v1/
```

Additive changes stay in v1. Breaking changes require `/api/v2` or an explicitly managed compatibility period recorded in `Decisions.md`.

### 12.2 OpenAPI Contract

The FastAPI OpenAPI document is generated in CI and compared with the approved snapshot `Docs/api/openapi-v1.json`.

An unreviewed difference fails CI.

### 12.3 Error Format

Every error response, including validation errors, uses this structure:

```json
{
  "error": {
    "code": "REVIEW_NOT_FOUND",
    "message": "A safe user-facing message",
    "request_id": "uuid",
    "field_errors": [
      { "field": "visit_month", "code": "FUTURE_MONTH" }
    ]
  }
}
```

Rules:

- FastAPI's default `{"detail": ...}` body and its default 422 body are replaced by exception handlers.
- `Docs/API.md` is updated to this format. It supersedes the planned `{code, message, details}` format.
- Clients branch on `code`, never on `message`.
- `message` is available in Bangla and English, selected by `Accept-Language`.

The API shall not expose stack traces, SQL, secrets, internal paths or account-existence information.

### 12.4 Idempotency

Retryable write operations accept:

```text
Idempotency-Key: <UUID>
```

The server stores:

- a digest of the key, scoped by actor or guest scope
- endpoint
- request fingerprint
- result reference
- creation time
- expiry time, 72 hours after creation (`Security.md` 3.7)

Rules:

- A unique constraint on (scope, endpoint, key digest) enforces uniqueness.
- Reusing a key with a different request fingerprint returns `409 IDEMPOTENCY_KEY_REUSED`.
- Idempotency records only replay recent responses. Permanent duplicate prevention for reviews is the `client_draft_id` uniqueness in `Features/Review.md` 4.1.

## 13. Guest Review Receipts

### 13.1 Receipt Decision

This section replaces the server-issued receipt in `Features/Review.md` 4.2 and `Security.md` 4.2. Annex A gives the amendment text.

- The client generates the receipt secret before the first submission.
- The server validates its format and stores only a keyed digest.
- Receipts are never reissued. The current behaviour of issuing a new receipt on a duplicate retry is removed. That behaviour let anyone holding the long-lived guest scope secret mint a new receipt for every review in that scope.
- A lost receipt is handled through the moderated removal-request process (`Features/Review.md` 5.4).

### 13.2 Receipt Format and Validation

The client generates 32 bytes with `crypto.getRandomValues` and encodes them as unpadded base64url. The receipt is that string with the prefix `abr1_`, which makes accidental leaks detectable by secret scanners and log filters.

```text
abr1_ + 43 base64url characters   (48 characters in total)
```

The server cannot prove that the client used a secure generator. It shall therefore enforce:

- the exact prefix, length and base64url character set
- rejection of known weak values (all-zero, repeated single character, and values from tests or documentation)
- HTTPS-only transport through HSTS (Section 5.4)
- strict binding to one review
- rate limits (Section 14)

Possession of a receipt reveals only its review and the status information `Features/Review.md` 4.2 permits.

### 13.3 Receipt Use

The receipt is sent in the JSON body of a `POST` request on every receipt operation. It is never sent in a cookie, a URL, a URL fragment or a header that could be logged.

Receipt operations are:

- status
- withdrawal
- appeal
- pending-review edit

Each is rate-limited per receipt digest and per network digest.

On a duplicate submission (same guest scope and `client_draft_id`), the server compares the digest of the receipt in the request with the stored digest:

- **Match:** the server returns the existing review with `duplicate_recovered: true`.
- **Mismatch:** the server returns `409 DRAFT_ALREADY_SUBMITTED` without revealing the review identifier.

### 13.4 Receipt Storage, Lookup and Key Rotation

The server stores, in `review_receipts`:

- `key_id`
- `digest`, computed as HMAC-SHA-256(receipt key for `key_id`, receipt)
- review identifier
- creation time
- revocation time

The lookup index is unique on `(key_id, digest)`.

The guest scope digest (`reviews.guest_scope_hash`) uses the same keyring and gains a `guest_scope_key_id` column. Receipt and guest-scope HMAC inputs are domain-separated with fixed context labels, such as `abhijatri:review-receipt:v1` and `abhijatri:guest-scope:v1`, before hashing. A digest from one credential class can therefore never be accepted as the other. Draft deduplication survives key rotation.

Rotation procedure:

1. Add a new key and make it current. Old keys are retained, not deleted.
2. On lookup, compute a candidate digest under each retained key and query by `(key_id, digest)`.
3. On each successful use, re-digest under the current key in the same transaction.
4. A retained key is deleted only after no rows reference its `key_id`, or when it is known to be compromised.

Receipt and scope secrets shall not appear in logs, analytics, URLs, referrer headers, error payloads or audit metadata.

### 13.5 Receipt Custody on the Device

The receipt exists before submission, so it must survive an offline period:

1. While a draft is unsent, its receipt is stored in IndexedDB with the draft.
2. After the server acknowledges the review, the application shows the receipt once. It asks the user to save it by copying it, downloading a small text file, or using the device share sheet.
3. When the user confirms, or after 7 days, the receipt is deleted from IndexedDB.
4. The submission notice explains that a lost receipt cannot be recovered and that removal is available through the removal-request process.

Draft export (Section 18.2) excludes receipts of submitted reviews. It includes the receipt of an unsent draft only after the user explicitly confirms, because the receipt is needed to submit that draft later.

## 14. Guest Abuse Controls

### 14.1 Composite Protection

A client-generated guest scope is not a primary abuse boundary.

Unauthenticated review submission, report and removal endpoints require a composite control:

1. a trusted client address (Section 14.2), stored only as a keyed network digest
2. a valid Cloudflare Turnstile token
3. the guest scope as a supplemental signal
4. endpoint-specific limits (Section 14.3)
5. a global and per-destination pending-queue capacity
6. duplicate and content checks

Turnstile runs in managed mode. Most visitors see no interactive challenge. Cloudflare presents one only when its own risk signals call for it, which satisfies the risk-based challenge rule in `Security.md` 6.2 (as amended in Annex A).

Tokens are validated server-side, including:

- `success`
- expected `hostname` (`app.<owned-domain>`)
- expected `action` per endpoint

Tokens are single-use and valid for 300 seconds. Siteverify calls use an `idempotency_key` so that a siteverify network retry does not consume the token twice. See [Turnstile server-side validation](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/) and [hostname management](https://developers.cloudflare.com/turnstile/additional-configuration/hostname-management/).

Turnstile is a processor and is listed in the processor register (Section 23.5). The privacy notice names it.

### 14.2 Trusted Client Address

The API derives the client address in one place: `app/shared/client_address.py`.

1. Uvicorn runs **without** `--proxy-headers`, and `--forwarded-allow-ips` is not set. Wildcard trusted proxies are prohibited.
2. The application reads the provider-appended entry only. That is the right-most `X-Forwarded-For` entry added by Render's edge, or a provider header that Render documents as set by its edge. The left-most entry and any other client-supplied value are never used.
3. The selected header and position are recorded in `Docs/Architecture.md` after the staging test below.
4. A test on staging sends requests with forged `X-Forwarded-For`, `Forwarded`, `X-Real-IP` and `CF-Connecting-IP` values and proves that the selected provider-derived address cannot be replaced by a client value. This test runs before 27 October 2026 and again at Gate B.
5. If that test fails, client-address rate limiting is not considered implemented. Gate B then requires either a hosting path with a documented, authenticated client-address contract or an approved edge proxy whose origin cannot be bypassed. The application shall not guess which forwarded value is trustworthy.
6. IPv4 addresses are used as-is. IPv6 addresses are truncated to their /64 prefix. The digest is HMAC-SHA-256 with a dedicated key and context label from the keyring.

The raw address is kept in memory only for the request and is never written to the database or to application logs. Render's own platform logs are covered by the processor register.

Carrier-grade NAT means many legitimate users share an address. A network digest is therefore never the sole key for a hard block.

### 14.3 Limits

Limits are configuration values. The starting values below are recorded in `Decisions.md` and tuned by the Step 4 measurement (`Security.md` 6.2, as amended).

| Action | Per-credential hard limit | Network hard limit | Additional control |
|---|---|---|---|
| Guest review submission | 3 new drafts per guest scope per 24 hours | 30 per network digest per hour and 100 per 24 hours | A fresh managed Turnstile token for every new draft |
| Guest reports | 10 per guest scope per hour | 60 per network digest per hour | A fresh managed Turnstile token |
| Guest removal requests | 3 per guest scope per 24 hours | 20 per network digest per 24 hours | A fresh managed Turnstile token |
| Receipt operations | 20 per receipt digest per hour | 100 per network digest per hour | Progressive delay after repeated failures |
| Verification and reset email | 3 per address digest per hour; 10 per account per day | 30 per network digest per hour | Equivalent responses for known and unknown addresses |
| Login failures | Progressive delay per account | 100 failures per network digest per hour | Alert and temporary cooldown |
| Pending guest reviews per destination | Not applicable | Configurable ceiling, default 50 | Administrator alert at 80 % |
| Total pending guest reviews | Not applicable | Configurable ceiling, default 500 | Administrator alert at 80 % |

The network ceilings are deliberately higher than per-credential limits to reduce harm to users behind carrier-grade NAT, but they are real hard limits because guest scopes are free to regenerate. The event allowance in Section 14.6 may temporarily raise a known shared-network ceiling for a supervised usability session.

The application cannot force Cloudflare's managed widget to become interactive for a selected network. Cloudflare decides whether interaction is required. Abhijatri therefore treats a valid Turnstile token as one control and enforces its own credential, network and queue ceilings independently.

Reaching a global or per-destination pending ceiling temporarily stops new **guest** submissions for the affected scope. Public reading, member submissions and moderator access continue.

### 14.4 Order of Checks

Guest review submission runs in this order:

1. Validate the request schema and the receipt format.
2. Look up an existing review for (guest scope digest, `client_draft_id`). If one exists, apply Section 13.3 and return. Do not validate Turnstile and do not count the request.
3. Look up an `Idempotency-Key` replay. If found, return the stored response without counting it.
4. Validate the Turnstile token.
5. Increment the rate-limit counters in their own committed transaction (Section 14.5).
6. Check the limits and pending ceilings.
7. Run the business transaction.

The first submission of a queued offline draft therefore needs a fresh Turnstile token. The application does not auto-submit queued drafts in the background. On reconnection, it shows pending drafts and the user submits them, completing the challenge (`Features/Review.md` 7.3). A retry after a lost response is recovered at step 2 and needs no new challenge.

### 14.5 Counter Durability

The authoritative counter increment commits in its own database transaction before the protected business operation runs. A later validation failure or business rollback does not erase the attempt count.

Counters are stored in `app.rate_limit_buckets`, keyed by (rule, key digest, window start). Expired buckets are removed by the retention role's cleanup job (Section 10.5) within 24 hours (`Security.md` 3.7).

Each application instance may keep a bounded in-memory pre-filter for obvious bursts. It is an optimization, not the authoritative limiter.

Redis remains deferred until measured traffic justifies it.

### 14.6 Testing Allowance and Emergency Switch

- **Event allowance.** For usability sessions on one shared network, an administrator may grant a time-boxed allowance of at most 8 hours that raises the soft thresholds for one network digest. Granting it requires recent reauthentication and creates an audit event. It never disables Turnstile or the per-scope hard limits.
- **Emergency switch.** An administrator may disable all guest writes, or enable hard network-digest limits, with an audit event. Public reading is unaffected.

## 15. Transactional Outbox

### 15.1 Encrypted Payload

Verification and reset emails need temporary access to a raw bearer token. Sensitive outbox payload fields are therefore encrypted with AES-256-GCM before storage.

Each record contains:

- encryption `key_id`
- nonce
- ciphertext
- authenticated metadata (outbox ID, template, recipient digest, expiry) bound as associated data
- creation time
- attempt count
- next-attempt time
- lease owner
- lease expiry
- completion time
- last error (provider error code only, never the payload)

The keyring is supplied through environment secrets, outside the database. It is versioned by `key_id`, and old keys are retained until no ciphertext references them.

After successful delivery, or when the message expires, the ciphertext and nonce are set to `NULL`. Non-sensitive delivery metadata is kept for 30 days (`Security.md` 3.7) and then removed by the retention job.

Expired reset or verification messages are never sent.

### 15.2 Worker

The MVP uses an in-process outbox worker in the API service, running as `abhijatri_app`.

Claiming uses a lease, so no database lock is held during the external call:

1. In a short transaction, select due rows with `FOR UPDATE SKIP LOCKED`, set `lease_owner` and `lease_expiry` (now plus 2 minutes), increment `attempt_count`, and commit.
2. Outside any transaction, decrypt the payload and call Resend with `Idempotency-Key: outbox-<row id>`. Resend then does not send the same message twice within its idempotency window, even if the worker crashed after Resend accepted it.
3. In a new transaction, mark the row complete and scrub the payload. On failure, record the error code and set `next_attempt_at` with exponential backoff (maximum 6 attempts).

A row whose lease has expired without completion becomes eligible again.

Delivery is attempted immediately after the enqueuing request commits, so request-initiated email is not delayed by Render's spin-down. Retries scheduled while the free instance is spun down run when it next wakes. This is an accepted MVP limitation. Verification and reset links remain valid for their full lifetime (60 minutes for reset, 24 hours for verification), and a user can request another.

### 15.3 Email Abuse Controls

Email initiation has:

- per-recipient limits (Section 14.3)
- per-account limits (Section 14.3)
- trusted-network soft limits (Section 14.3)
- a provider-wide daily cap of 80 messages (Section 8.7), after which non-security email is deferred and an administrator is alerted
- a global emergency disable switch

Known and unknown email addresses produce equivalent public responses.

An external email failure does not roll back the primary account transaction.

## 16. Cross-Origin and Browser Security

### 16.1 CORS

Production CORS allows only these exact origins:

```text
https://app.<owned-domain>
https://admin.<owned-domain>
```

| Setting | Value |
|---|---|
| `allow_credentials` | `true` |
| Allowed methods | `GET`, `POST`, `PUT`, `PATCH`, `DELETE` (only the ones routes use) |
| Allowed request headers | `Content-Type`, `Idempotency-Key`, `X-CSRF-Token`, `Accept-Language` |
| Preflight cache | `max_age` of 600 seconds |

Wildcard origins are never combined with credentials.

Public `GET` routes for destinations and reviews are designed as CORS "simple" requests, with no custom headers and no credentials. They therefore need no preflight round trip on slow networks.

### 16.2 CSRF

The API's cookies are host-only on `api.<owned-domain>`, so JavaScript on `app.` or `admin.` cannot read them. CSRF therefore uses a synchronizer token:

1. `GET /api/v1/auth/csrf` returns `{ "csrf_token": "..." }` for the current session. The response is `no-store`.
2. The server stores the token's digest bound to the session, and rotates it whenever the session rotates.
3. Every state-changing cookie-authenticated request sends the token in `X-CSRF-Token`. The server compares the token in constant time.

Checks on `Origin` and `Sec-Fetch-Site` are added as defence in depth. They never replace the token.

Guest receipt and guest submission endpoints use no cookies, so they need no CSRF token. They are protected by the controls in Section 14.

### 16.3 Content Security Policy

The frontend uses a Content Security Policy that restricts:

- script sources: `'self'` and `https://challenges.cloudflare.com`
- style sources: `'self'`
- image sources: `'self'`, `data:`, and documented licensed image origins
- connection destinations: `'self'`, `https://api.<owned-domain>` and `https://challenges.cloudflare.com`
- frames: `frame-src https://challenges.cloudflare.com`
- form targets: `form-action 'self'`
- base URI: `base-uri 'none'`
- object embedding: `object-src 'none'`

Production uses no `unsafe-eval` and no unsafe inline script. Any added external origin is documented in this section.

The staff interface uses a stricter policy. It allows no Turnstile and no external images, and sets `frame-ancestors 'none'`. The public interface also sets `frame-ancestors 'none'`.

### 16.4 Security Headers

Shared environments provide:

- HSTS following the rollout in Section 5.4
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin` (staff: `no-referrer`)
- a `Permissions-Policy` that disables camera, microphone, payment and geolocation (geolocation is re-enabled only for a future user-initiated nearby feature)
- `Cross-Origin-Opener-Policy: same-origin`
- CSP frame restrictions
- `Cache-Control` following the route allowlist in `Security.md` 7.1. Every API response is `no-store` unless the route is in that allowlist.

Static-site headers are set in the Render static site configuration. API headers are set by middleware and covered by tests.

## 17. Destination Provenance and Licensing

Every maintained destination, advisory, contact, price, image and safety record includes the applicable provenance metadata:

- source type
- source URL or reference
- publisher
- effective date
- retrieval or verification date
- expiry or next-review date
- language
- licence or permission
- researcher
- reviewer

The system shall not scrape or republish images without an appropriate licence or permission.

Allowed image sources are:

- team-owned photographs
- explicitly licensed vendor contributions
- open-licence sources with the required attribution
- public-domain material

Sponsored content never changes rating calculations.

Expired advisories are never presented as current.

## 18. Offline and Low-Bandwidth Foundation

### 18.1 Allowed Offline Content

The **service worker cache** may hold only:

- the application shell and versioned static assets
- prerendered public destination pages
- user-selected public destination packs (approved destination text, bilingual guidance, dated advisories, public contact information, and a bounded snapshot of published reviews)

**IndexedDB** may hold only:

- destination pack data
- the user's own review drafts, with the receipt of an unsent draft (Section 13.5)
- the guest scope secret
- the language preference

Neither store shall hold:

- authentication responses or sessions
- private community data
- staff pages or assets
- moderation queues
- verification evidence
- receipts of submitted reviews (after Section 13.5 step 3)
- any response marked `no-store` or carrying `Set-Cookie`

Saved trips are not a foundation feature. They need their own specification before any trip data is stored offline.

### 18.2 Storage Persistence and Export

Structured offline data uses IndexedDB.

The application calls `navigator.storage.persist()` where supported. A refusal does not block use, but the user is told that the browser may evict data.

Because iOS and other browsers may remove site data, the application provides:

- a persistence-status display
- a draft-loss warning
- user-initiated draft export
- draft import where practical
- per-draft deletion and clear-all deletion

Exports exclude session credentials, receipts of submitted reviews and unrelated private information. The receipt of an unsent draft is included only on explicit confirmation (Section 13.5).

Sign-out clears session-derived local state.

### 18.3 Map Content

Offline packs initially contain:

- coordinates
- addresses
- landmark descriptions
- textual directions
- emergency contacts
- licensed static illustrations where appropriate

Public OpenStreetMap tile servers shall not be bulk-downloaded or prefetched for offline packs.

### 18.4 Cache Versioning and Freshness

Every offline pack includes:

- pack version
- content version
- generation time
- advisory verification time
- expiry time
- language
- integrity identifier (SHA-256 of the pack)

Service-worker cache names are versioned. Activation removes obsolete caches only after the replacement is ready.

On reconnection, the application checks the pack manifest and applies removals before presenting a refreshed pack as current.

The maximum snapshot age for reviews and safety-sensitive information is the Step 8 decision in `Decisions.md`. Until it is recorded, the default is 7 days. Expired safety information is clearly marked and never appears current.

## 19. Performance and Device Budget

### 19.1 Supported Targets

Primary support covers:

- current and previous Chrome versions on Android
- Android 10 and later
- current and previous desktop Chrome and Edge
- Safari on iOS 16.4 and later for primary flows, with documented offline limitations

The reference low-end device has about 2 GB RAM and an entry-level Android processor. The team records the exact model used.

### 19.2 Rendering Strategy

Destination pages are **prerendered to static HTML** at build time from the approved published destination content. The first useful content therefore arrives in the first HTML response, with no JavaScript or API call required.

- Publishing or changing destination content triggers a static-site rebuild through the protected workflow.
- Time-sensitive data (advisory status and review feed) is fetched after first render.
- The prerendered advisory block shows its verification time, so stale HTML is never presented as current (Section 17).

### 19.3 Asset Budgets

All sizes are compressed transfer sizes on a cold cache.

| Budget | Limit |
|---|---|
| Critical path for first useful content (HTML, render-blocking CSS, render-blocking fonts) | ≤ 100 KiB |
| Render-blocking JavaScript | 0 KiB (scripts are `defer` or `type=module`) |
| Total JavaScript for the initial route | ≤ 200 KiB |
| Total CSS | ≤ 50 KiB |
| Bangla web font | One critical subset WOFF2 weight, ≤ 40 KiB, `font-display: swap`; any second weight loads after useful content and remains inside the route total |
| Eager full-resolution user media | none |
| Application shell cache | ≤ 1 MiB unless justified in `Decisions.md` |

CI fails when a budget is exceeded (Section 27).

### 19.4 Network Tests

First visits are tested with a custom **Abhijatri Slow 3G** profile:

- 400 kbps downstream
- 400 kbps upstream
- 400 ms round-trip time
- cold cache, with DNS not cached

Tests run with WebPageTest or Chrome DevTools custom throttling on the reference device or its emulation. The target is useful destination content (the destination name and summary text visible) within 5 seconds.

This target is feasible under these budgets. About 1.6 seconds of connection setup (4 round trips) plus 100 KiB at about 49 KiB/s is roughly 3.7 seconds.

No first-visit guarantee is made for GPRS-class 2G.

For constrained 2G or unstable connectivity, the targets apply to repeat use:

- the cached application shell opens without network
- cached destination content remains readable
- drafts remain editable
- queued submissions wait safely for the user to submit them (Section 14.4)
- reconnection does not create duplicates

Lighthouse scores are quality signals, not load-time guarantees. Lighthouse CI uses its default mobile throttling, which differs from the Abhijatri Slow 3G profile. Both results are recorded.

Required Lighthouse CI scores on the destination page and the review form:

- Performance: 80
- Accessibility: 90
- Best Practices: 90

The installability and service-worker checks shall also pass.

## 20. Accessibility

Primary flows target WCAG 2.2 Level AA.

The implementation provides:

- keyboard-operable controls
- visible focus that is not obscured
- semantic headings
- appropriate labels
- understandable bilingual validation errors
- sufficient colour contrast
- usable text enlargement to 200 %
- minimum target sizes
- meaningful image alternatives
- no dependence on colour alone
- accessible authentication: paste allowed in password and TOTP fields, and no cognitive puzzle (Turnstile managed mode satisfies this)
- correct Bangla conjunct rendering

Automated checks are supplemented by a keyboard review, a screen-reader pass with TalkBack, and usability testing.

## 21. Database Connectivity

Supabase documents that direct database connections use IPv6 unless the IPv4 add-on is enabled. The shared Supavisor pooler is IPv4 in both session and transaction mode. Transaction mode does not support prepared statements or session state. See [Supabase connection guidance](https://supabase.com/docs/guides/database/connecting-to-postgres).

Before migration automation is finalized (by Gate A), the team tests each of the following combinations and records the results:

| From | Roles tested |
|---|---|
| Render | `abhijatri_app` |
| GitHub-hosted CI | `abhijatri_migrator`, `abhijatri_retention`, `abhijatri_backup` |

The tests prove that custom login roles authenticate through the session pooler (user name format `role.project-ref`).

Connection methods:

- FastAPI: shared session pooler, port 5432
- CI migrations, retention and backup: shared session pooler, selected because the workflow shall not depend on direct IPv6 availability. Direct connectivity may be used only after it is demonstrated in the actual runner.
- Transaction pooler: not used. Abhijatri relies on row locks, `SET LOCAL` and session-stable connections (`Decisions.md`, 15 October 2026).

Connection budgeting shall satisfy:

```text
API instances × uvicorn workers × (pool_size + max_overflow)
  + concurrent CI and job connections
≤ pooler client limit for the project − operational reserve (5)
```

The pooler and database connection limits are read from each project's dashboard and recorded in `Docs/Architecture.md`.

## 22. Migration and Deployment

### 22.1 Deployment Ordering

Render auto-deploy is set to **Off** for the production and staging API services and for both static sites. This supersedes `autoDeployTrigger: checksPass` in `render.yaml` and the 15 October "Deploy trigger" decision.

The protected workflow `.github/workflows/deploy.yml` shall:

1. Build and test the selected commit through the CI workflow (Section 27).
2. Obtain the required approval through the GitHub Environment `production` (or `staging`) with required reviewers.
3. Acquire a PostgreSQL advisory lock for migrations.
4. Apply migrations with the environment's `abhijatri_migrator` credential.
5. Run the migration smoke tests and the database security test (Section 10.7) against the target database.
6. Trigger the API deploy hook with `ref=<tested commit SHA>`.
7. Poll `/api/v1/health/ready` until the API reports the expected build and database revision.
8. Trigger the public static-site build so destination prerendering reads from the new ready API, then verify its build version and destination snapshot version.
9. Trigger the staff static-site build and verify its build version.
10. Record the deployed revisions and content snapshot in the workflow summary and in `Docs/Architecture.md`.

The API and public static site shall not deploy concurrently when the public build depends on API data. This ordering prevents the prerendered destination pages from capturing content through an old API or an incompatible schema.

Render's deploy hook accepts `ref=<commit SHA>`, and deploying a specific commit also turns auto-deploy off ([Render deploys](https://render.com/docs/deploys)). Render's own pre-deploy command is available only on paid plans, which is why migrations run from GitHub Actions.

Credential placement:

- The migrator, retention and backup credentials exist only as secrets of the protected GitHub Environments. They are separate per environment.
- They are never present in the Render service environment.
- `MIGRATION_DATABASE_URL` is removed from `render.yaml`.
- The Render deploy-hook URL is itself a secret of the protected Environment.

### 22.2 Migration Compatibility

Migrations use expand, migrate and contract:

1. Add backward-compatible structures.
2. Deploy compatible code.
3. Backfill.
4. Enforce the new rules.
5. Remove obsolete structures in a later release.

Application containers never run migrations at startup. `alembic upgrade head` is removed from the `Dockerfile` command. At startup, the API checks that the database revision equals the revision it was built for and refuses to become ready otherwise.

## 23. Backup and Restore

### 23.1 Backup Execution

A scheduled GitHub Actions workflow (`.github/workflows/backup.yml`) runs daily at 21:00 UTC (03:00 in Dhaka) in the protected `production` Environment.

The workflow shall:

- use a pinned PostgreSQL client with the same major version as the server (Section 7.1)
- connect as `abhijatri_backup` through the session pooler
- run `pg_dump --format=custom --schema=app --enable-row-security`
- validate that each table meets its minimum expected row count, declared in `backend/app/jobs/backup_expectations.py` (for example, destinations ≥ 1). Tables with no declared minimum are reported but do not fail the job.
- encrypt the dump with the public `age` recipient key before it touches disk outside the runner's temporary directory
- generate a SHA-256 checksum of the encrypted file
- upload the encrypted artifact and checksum
- delete every unencrypted file
- report failure visibly through a failed workflow run and a notification to the custodians

### 23.2 Backup Storage and Retention

| Copy | Location | Retention |
|---|---|---|
| Daily | Private GitHub Actions artifact | 35 days, set through `retention-days: 35` |
| Weekly | Private team-controlled Google Drive folder, uploaded by Shahriar Islam and verified by Md. Irfan Iqbal | Deleted after 35 days |

The 35-day limit satisfies `Security.md` 3.7, which requires backups containing erased content to rotate out within 35 days. A backup is never kept longer, even for convenience.

No unencrypted dump is retained after the job. The weekly copy is recorded in the backup evidence register with its checksum, upload date, uploader, verifier and deletion date. A missed weekly copy creates a failed operational check rather than being silently ignored.

### 23.3 Encryption-Key Custody

Backups use public-key encryption with `age`.

The backup workflow holds only the public recipient key.

Private key custody:

- primary custodian: Shahriar Islam
- recovery custodian: Syed Muhtasim Alam

The private key is stored in each custodian's password-manager vault. It shall not be stored:

- in the repository
- in GitHub artifacts or secrets
- with the backup file
- in project documentation
- in chat

### 23.4 Restore Exercise

A complete restore is tested by **15 December 2026**. It is repeated by **14 January 2027** if the schema changed materially in between.

The restore runs into a disposable local PostgreSQL container of the same major version. The container's superuser restores the dump, so forced RLS does not block the restore. The `abhijatri_*` roles are created first, so ownership and grants are preserved.

The restore report records:

- backup date
- restore date
- PostgreSQL versions (server and client)
- person responsible
- duration
- schema verification (`tests/test_database_security.py` passes on the restored database)
- row-count verification against the backup's recorded counts
- deletion-ledger reapplication before any restored review is treated as publishable (`Security.md` 9.3)
- aggregate reconciliation result
- representative functional verification
- identified limitations

Supabase recommends regular off-site logical exports for Free Plan projects. See [Supabase backup guidance](https://supabase.com/docs/guides/platform/backups).

### 23.5 Processor Register

Before real personal data is accepted, the processor and cross-border register (`Security.md` 3.8) shall list at least:

| Processor | Service |
|---|---|
| Render | API and static hosting, platform logs |
| Supabase | Database |
| GitHub | Code, CI, backup artifacts |
| Google Drive | Weekly backups |
| Resend | Email |
| Cloudflare | Turnstile |
| Upstash | Redis: aggregate visit and request counters only, ap-southeast-1 (added 22 Oct 2026) |
| Domain registrar and DNS provider | Domain and DNS |

## 24. Free-Tier Readiness

Supabase pauses Free Plan projects after 7 days of low activity, and a paused project can be resumed from the dashboard ([Supabase project pausing](https://supabase.com/docs/guides/platform/free-project-pausing)). Render spins down Free web services after 15 minutes without inbound traffic, and waking takes about one minute ([Render free](https://render.com/docs/free)). Render also grants 750 free instance hours per workspace each month.

The daily backup job also calls `/api/v1/health/ready`. This reduces pause risk but is not relied upon.

During the final testing and demonstration period, the team schedules:

- a readiness check 24 hours before a planned demonstration, including the Supabase project state
- a database activity and API readiness check on the morning of the demonstration
- an API warm-up at least 10 minutes before the presentation
- a final online and offline smoke test before the presentation

This is a demonstration-readiness procedure, not a substitute for suitable hosting.

If reliable cold-start behaviour cannot be achieved on the free plans, the team shall temporarily use a paid Render instance for the demonstration period. That decision is due by 4 January 2027.

## 25. Development-Only Identity

The development identity handler (`X-Test-Staff-Id`) is registered only when `APP_ENV` is `development` or `test`.

Staging and production shall not register or advertise it. The current behaviour of returning `501` from staff routes in production is replaced by the real staff authentication at the 20 November milestone.

Tests shall prove that:

- local and test environments can use the handler
- staging and production cannot register it
- the production OpenAPI document contains no development identity header
- production startup rejects development-auth configuration (Section 7.2)

## 26. Logging and Audit

Logs include:

- request identifier
- environment
- deployment version
- route template (not the raw path)
- status
- duration
- a safe actor identifier where appropriate

Logs shall not include:

- passwords
- raw session or CSRF tokens
- receipts or guest scope secrets (the `abr1_` prefix is redacted by a log filter as a backstop)
- reset or verification tokens
- TOTP secrets
- encryption keys
- raw IP addresses
- request bodies of review, report and removal endpoints
- private drafts
- unnecessary personal information

Security-sensitive actions create append-only audit records (Section 10.4).

## 27. Continuous Integration

Every change runs:

1. backend formatting and linting
2. frontend formatting and linting
3. type checking (backend and frontend)
4. backend unit tests, including configuration validation
5. frontend unit tests
6. PostgreSQL integration tests
7. migration tests (`upgrade head`, `check`, `downgrade` to the previous revision)
8. the database security test (Section 10.7)
9. authentication security tests
10. secret scanning over the full history
11. dependency vulnerability checks
12. frontend production builds (public and staff)
13. asset-budget checks (Section 19.3)
14. OpenAPI snapshot comparison
15. Lighthouse CI
16. requirement-traceability validation (Section 28)

PostgreSQL locking, constraints, moderation transitions, idempotency, rate-limit counters, the outbox lease and aggregate tests use real PostgreSQL.

Steps that need the frontend run as soon as `frontend/package.json` exists, and are required checks from Gate A.

## 28. Requirement Identifiers

Platform Foundation requirements use the identifiers `PF-01` to `PF-30`. They shall not reuse Gantt task identifiers such as `F01` or `R04`.

| Range | Concern | Sections |
|---|---|---|
| PF-01 to PF-03 | Architecture, domain and environments | 3, 4, 5, 7.1 |
| PF-04 to PF-06 | Credentials, secrets and configuration | 6, 7.2 |
| PF-07 to PF-10 | Identity, sessions and staff authorization | 8, 9, 25 |
| PF-11 to PF-14 | Database isolation | 10 |
| PF-15 | Data standards | 11 |
| PF-16 to PF-19 | API, receipts, abuse resistance and outbox | 12, 13, 14, 15 |
| PF-20 to PF-21 | Browser security, provenance and licensing | 16, 17 |
| PF-22 to PF-24 | Offline, bilingual and accessibility, performance | 18, 19, 20 |
| PF-25 to PF-28 | Deployment, connectivity, backup and operations | 21, 22, 23, 24, 26 |
| PF-29 | Continuous integration and traceability | 27, 28 |
| PF-30 | Security deployment approval | 29, `Security.md` 10.2 |

The traceability matrix (`Docs/Traceability.md`) maps each PF identifier to its tests and evidence. CI fails when a PF identifier has no test reference or when a test references an unknown identifier.

## 29. Delivery Gates

### 29.1 Gate Zero: Credential Containment

Due 20 October 2026. Gate Zero requires:

- exposed credentials rotated
- previous credentials revoked
- `.env.example` and `.gitignore` corrected (Section 6)
- repository and history scanned
- deployment secrets updated
- evidence recorded

### 29.2 Gate A: Foundation Ready for Feature Development

**Window:** 22 to 29 October 2026

| Requirement | Proposed owner |
|---|---|
| Gate Zero completed | Shahriar Islam |
| Annex A amendments merged into `Security.md`, `Review.md`, `Architecture.md` and `API.md` | Shahriar Islam |
| Backend package refactor (Section 3.2) | Syed Muhtasim Alam |
| `app` schema, database roles and policy model (migration `0003`) | Syed Muhtasim Alam |
| Database security test active in CI | Md. Irfan Iqbal |
| Connectivity test from Render and CI recorded (Section 21) | Syed Muhtasim Alam |
| Frontend public and staff skeletons building in CI | Abdullah Bin Sorwar Choudhury |
| Bangla and English infrastructure working | Abdullah Bin Sorwar Choudhury |
| PWA foundation building | Abdullah Bin Sorwar Choudhury |
| FastAPI and PostgreSQL integration working | Syed Muhtasim Alam |
| Identity specification approved | Shahriar Islam |
| Domain acquired and custom domains verified | Shahriar Islam |
| Trusted client address test passed on staging (Section 14.2) | Syed Muhtasim Alam |
| Traceability matrix started | Md. Irfan Iqbal |

Owners reflect the role allocation in the final proposal and accepted Gantt chart and shall be confirmed by the project leader by 20 October 2026. If any Gate A item will not be met by 29 October, the project leader records the slip and its new date in `Decisions.md` by 27 October.

Gate A does not require completed member authentication or staff MFA.

### 29.3 Gate B: Release and Formal Testing Entry

**Deadline:** 3 January 2027

Gate B requires:

- in-scope feature development frozen
- authentication track accepted
- staff MFA, reauthentication and authorization accepted
- guest abuse controls active, and trusted client address re-verified
- outbox encryption, lease and retry behaviour tested
- production migration workflow tested end to end
- production auto-deploy off
- connection strategy and budget verified
- backup and restore test passed (by 15 December 2026)
- offline privacy controls tested
- performance and accessibility evidence recorded
- processor register complete
- security deployment gates passed
- no blocker or critical defect open

## 30. Development Freeze and Post-Freeze Work

### 30.1 Development Freeze

The team shall complete planned feature development by 3 January 2027.

After this date, no new major features are introduced.

### 30.2 Testing Phase

From 4 to 11 January 2027, work focuses on:

- complete test execution
- requirement coverage
- defect recording
- defect correction
- regression testing
- performance verification
- accessibility verification
- security verification
- usability sessions (using the event allowance in Section 14.6 where needed)
- evidence collection

### 30.3 Enhancement and Finalization

From 12 to 17 January 2027, only controlled work is allowed:

- correction of identified defects
- safe usability improvements
- performance optimization
- content correction
- documentation completion
- demonstration preparation
- deployment stabilization

An enhancement may be accepted only when it:

- does not change the fundamental architecture
- does not require a destructive migration
- does not weaken completed tests
- can be fully tested before 17 January
- is approved by the project leader and the SQA lead

18 January 2027 is a submission contingency date, not an additional development day.

## 31. Acceptance Criteria

| ID | Acceptance criterion |
|---|---|
| PF-01 | The modular-monolith package layout matches Section 3.2, with no packages for unapproved features. |
| PF-02 | The owned domain, web hosts, sending subdomain, TLS, CAA and HSTS rollout are configured and verified. |
| PF-03 | Local, test, staging and production boundaries are documented and enforced, on one PostgreSQL major version. |
| PF-04 | Exposed credentials are rotated and revoked, with recorded evidence. |
| PF-05 | No repository, image or build artifact contains an unapproved secret or backup file. |
| PF-06 | Staging and production reject every unsafe configuration in Section 7.2, including example secrets and wildcard proxies. |
| PF-07 | The identity specification and authentication track are approved and accepted. |
| PF-08 | Password, session lifetime, rotation, CSRF and account-enumeration tests pass. |
| PF-09 | Staff TOTP, replay protection, reauthentication, break-glass and last-admin protection pass. |
| PF-10 | Verification status is derived independently from authorization roles, and development identity is absent outside local and test. |
| PF-11 | Application tables reside in the non-exposed `app` schema with no Supabase-role grants. |
| PF-12 | Migrator, runtime, retention and backup roles are separated, and none has `BYPASSRLS`. |
| PF-13 | All application tables use enabled and forced RLS under the documented role-level policy model. |
| PF-14 | Audit, backup and retention permissions pass the database security test. |
| PF-15 | Identifier, time, Unicode and money standards have passing tests. |
| PF-16 | Versioned API, error format and OpenAPI snapshot contracts pass. |
| PF-17 | Idempotency and client-generated receipts (format, digest, key rotation, no reissue, custody) pass. |
| PF-18 | Guest endpoints enforce the trusted client address, challenge, limits, order of checks and pending ceilings. |
| PF-19 | Outbox encryption, lease claiming, provider idempotency, retry and scrubbing pass. |
| PF-20 | CORS, CSRF, CSP and security-header tests pass for the API and both static sites. |
| PF-21 | Provenance metadata is required for maintained records, and image licensing is recorded. |
| PF-22 | Approved destination content works offline, and private or `no-store` data is never cached. |
| PF-23 | Bangla-first presentation, Unicode tests and WCAG 2.2 AA evidence are recorded. |
| PF-24 | Asset budgets pass in CI, and the Slow 3G, device and Lighthouse evidence is recorded. |
| PF-25 | Migrations run before deployment only through the protected workflow, and containers never migrate. |
| PF-26 | Pooler connectivity for every role, and the connection budget, are verified and recorded. |
| PF-27 | An encrypted backup and a dated restore test with deletion-ledger reapplication succeed. |
| PF-28 | Logging exclusions, audit records, retention jobs and the free-tier readiness procedure are in place. |
| PF-29 | CI, OpenAPI and traceability checks pass on the release revision. |
| PF-30 | All applicable `Security.md` deployment gates have recorded evidence. |

## 32. Explicit Deferrals

The following remain outside the Platform Foundation:

- Redis, except the Upstash visit and ops event counters (`Docs/Decisions.md`, 22 Oct 2026); rate limiting and caching stay on PostgreSQL and in-process memory
- content-delivery network integration and any proxy in front of Render
- automatic media transcoding
- microservices
- native mobile applications
- production phone OTP
- automated NID verification
- machine-learning recommendations
- real payment transfer
- live vendor inventory
- real booking obligations
- private community implementation
- group-tour matching
- saved trips
- read-only operations and audit-reader database roles

These may be considered only through separate specifications and schedule approval.

## 33. Completion Rule

A foundation requirement is complete only when:

1. the implementation exists
2. the relevant tests pass
3. its security and privacy consequences are reviewed
4. acceptance evidence is recorded
5. the documentation matches actual behaviour
6. the requirement is traceable
7. no blocker or critical defect remains

A screen, deployment, written claim or successful demonstration alone does not prove completion.

---

## Annex A. Companion amendments applied at adoption

The adoption change applies the following amendments to the higher-authority documents in Section 2. They are retained here as a traceability record, not as pending instructions.

### A.1 `Docs/Security.md` 3.4 (cookies)

Replace "authenticated session, receipt session, CSRF protection where applicable, and an optional language preference" with:

> authenticated member session, staff session, and an optional language preference. CSRF protection uses a synchronizer token, not a cookie. Guest receipts are sent in request bodies, not cookies. Cloudflare Turnstile is used on guest write forms and is named in the privacy notice.

### A.2 `Docs/Security.md` 4.2 (guest receipt requirements)

Replace the bullet list under "Guest receipt requirements" with:

> - The client generates the receipt (`abr1_` followed by 43 base64url characters, 256 bits) with the browser cryptographic API before the first submission. The server validates its exact format and rejects known weak values.
> - The server stores only `(key_id, HMAC-SHA-256 digest)` using a versioned keyring. Receipts are never reissued. The guest scope digest uses the same keyring.
> - Receipt comparison is constant-time.
> - The receipt is sent in the JSON body of a rate-limited POST for each operation. It never appears in a cookie, URL, URL fragment, log or analytics event. No receipt session is created.
> - The receipt is kept in IndexedDB only while its draft is unsent, shown once after acknowledgement for the user to save, then deleted (Platform Foundation 13.5).
> - A receipt can access only its review, appeal, withdrawal and allowed pending-edit operations. A lost receipt uses the moderated removal-request process.

### A.3 `Docs/Security.md` 4.4 (database separation of duties)

Replace the identity table with:

> | Identity | Minimum privilege |
> |---|---|
> | `abhijatri_app` | Required application DML through per-table RLS policies, including the in-process outbox worker; no DDL; insert-only access to audit storage plus narrowly required `SELECT`. |
> | `abhijatri_migrator` | Owns schema `app`; migrations only; credential exists only in protected GitHub Environments. |
> | `abhijatri_retention` | `EXECUTE` on declared retention and cleanup functions only. |
> | `abhijatri_backup` | `SELECT` through RLS policies for `pg_dump --enable-row-security`; no modification. |
> | Read-only operations and audit-reader roles | Deferred until a staff reporting feature requires them; audit is read through `can()`-protected staff endpoints. |
>
> The outbox worker runs in-process under `abhijatri_app`, because a second credential in the same process would add no isolation. A separate worker identity is required if the worker moves out of process.

### A.4 `Docs/Security.md` 6.2 (abuse controls)

Replace the second paragraph with:

> Starting limits are configuration values recorded in `Docs/Decisions.md` and tuned by measurement. Guest write limits combine a per-credential ceiling, a higher network-digest ceiling, a fresh server-validated Cloudflare Turnstile token and per-destination and global pending-review caps. Network limits are deliberately higher because Bangladeshi mobile carriers place many unrelated users behind CGNAT, but they remain hard ceilings because guest scopes are free to regenerate. Cloudflare alone decides whether a managed Turnstile challenge requires interaction. Rate-limit keys are pseudonymised and expire.

### A.5 `Docs/Security.md` 7.4 (service worker and IndexedDB)

Replace "avoids storing verification evidence, receipt secrets, emergency contacts, or private-community conversations" with:

> avoids storing verification evidence, receipts of submitted reviews, private emergency contacts or private-community conversations. The receipt of an unsent draft is stored with that draft until acknowledgement (Platform Foundation 13.5). Public emergency numbers in destination packs are public content.

### A.6 `Features/Review.md` 4.2 (guest receipt)

Replace the section body with:

> The client generates the receipt secret (256 bits, format in Platform Foundation 13.2) before the first submission. The server stores only its keyed digest under a versioned keyring and compares in constant time. Receipts are never reissued.
>
> - The receipt is sent in the JSON body of a rate-limited POST for each operation. It is never placed in a URL or fragment, and no receipt session cookie is created.
> - It remains valid while the review content or appeal record exists.
> - It is revoked when the review is finally erased.
> - A rejected review remains visible through the receipt during the 30-day appeal period, including the public-safe decision reason and appeal deadline.
>
> The receipt permits status checks, withdrawal, appeal and a revision only while the review is `PENDING` or `CHANGES_REQUESTED`. Submitting a revision means editing the unpublished review through `PATCH /api/v1/reviews/{review_id}/pending`; it never means editing published content. The receipt cannot access another review or identify other users. A lost receipt is handled through the removal-request process in 5.4.

In `Features/Review.md` 3.2, replace step 7 with "The client keeps the receipt it generated in step 2; the server stores its digest." Add "and a receipt secret" to step 2.

In the 9.2 API list, `POST /api/v1/review-receipts/exchange` becomes `POST /api/v1/review-receipts/status`, and `GET /api/v1/review-receipts/status` is removed. Receipt endpoints are all POST with the receipt in the body.

### A.7 `Docs/Architecture.md`

Update sections 4, 5 and 7 to match Sections 4, 14.2, 21 and 22 of this specification. Close the open questions in section 9:

- Question 1 is answered by Section 5.3.
- Question 2 is answered by Section 18.4.
- Question 3 is answered by Section 13.5.
- Question 4 is answered by Section 12.3.

## Annex B. Decision record applied at adoption

> ## 2026-10-16 (Platform Foundation revision 3)
>
> | Decision | Rule | Reason |
> |---|---|---|
> | Foundation adopted | `Docs/Platform-Foundation.md` revision 3 is adopted together with its companion amendments to `Security.md`, `Review.md`, `Architecture.md`, `API.md` and `Decisions.md`. `Features/Execution.md` controls dependency sequence only and cannot amend the Foundation. | Keeps shared platform rules separate from implementation ordering. |
> | Schema changes | Supersedes 2026-10-15 "Schema changes": migrations run only from the protected GitHub workflow; containers never run `alembic upgrade head`; `MIGRATION_DATABASE_URL` is removed from Render. | Keeps the migrator credential out of the runtime (Foundation 22). |
> | Deploy trigger | Supersedes 2026-10-15 "Deploy trigger": Render auto-deploy is Off; deploys use the deploy hook with the tested commit SHA. | Migrations must precede deploys of exactly the tested commit. |
> | Environments | `abhijatri-dev` is renamed `abhijatri-staging`. | Matches Foundation 7.1. |
> | Receipts | Client-generated, never reissued, keyed digest with `key_id`; guest scope digest uses the same keyring. | Removes receipt minting from the guest scope secret and survives key rotation. |
> | Starting abuse limits | Values in Foundation 14.3, including higher but enforceable network ceilings, to be tuned by measured abuse and usability tests. | A client-generated guest scope is not an abuse boundary, and Turnstile interactivity cannot be forced by the application. |
> | HMAC domain separation | Receipt and guest-scope digests use distinct fixed context labels even when they share a keyring. | Prevents a digest from one credential class being accepted as another. |
> | Deployment order | Deploy and verify the API before building the public static site; deploy the staff site last. | Prerendered destination pages must use the new ready API and compatible schema. |
> | Argon2id parameters | Record the chosen `time_cost`, `memory_cost` and `parallelism` here when the authentication schema lands (5 November 2026). | Security 4.2. |

