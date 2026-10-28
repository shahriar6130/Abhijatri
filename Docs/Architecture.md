# Abhijatri Architecture

**Status:** Current implementation snapshot updated 16 October 2026. The target architecture and Gate A requirements are authoritative in `Docs/Platform-Foundation.md`; behavioural rules live in `Features/Review.md`, security controls in `Docs/Security.md`, and build-time choices in `Docs/Decisions.md`.

## 1. System flow

```text
Public PWA at app.<owned-domain> and staff UI at admin.<owned-domain>
    |  HTTPS, JSON, explicit CORS origin
    v
FastAPI API at api.<owned-domain> (Render web service, Docker, non-root)
    |  SQLAlchemy 2 / Psycopg 3, TLS, session pooler
    v
Supabase-managed PostgreSQL (schema app; source of truth)
```

- The PWA talks **only** to the FastAPI API. It holds no Supabase key and never calls Supabase directly (no Supabase Auth, Data API, or client SDK).
- All authorisation, moderation, receipt checks and rating arithmetic run on the server.
- CDN and the media pipeline are deferred (Decisions.md, Scope control). Redis (Upstash) is used **only** for the visit and ops event counters (Decisions.md, 22 Oct 2026); the API reaches it over `rediss://`, and a Redis outage never fails a request.
- The private ops dashboard (`ops/`, its own Vercel project) calls `/api/v1/ops/*` with a bearer token (`Docs/System-Monitoring-Dashboard.md`).

## 2. Backend structure (modular monolith)

| Module | Responsibility |
|---|---|
| `app/main.py` | App factory: CORS allow-list, logging, docs toggle, router. |
| `app/api.py` | HTTP layer under `/api/v1`: validation, staff dependency, error mapping (404/403/409), transaction commit/rollback. |
| `app/services.py` | Domain rules: Guest submission, receipt hashing (HMAC-SHA-256 with pepper), moderation, withdrawal, locked rating transitions, cursor encoding. |
| `app/models.py` | SQLAlchemy models and DB constraints (enums, partial unique indexes, rating checks). |
| `app/schemas.py` | Pydantic request/response contracts. |
| `app/config.py` | Typed settings and production fail-closed guard. |
| `app/db.py` | Engine, pooled sessions, `get_session` dependency. |
| `migrations/` | Alembic; the only schema-change path. |

Dependency direction: `api -> services -> models -> db`. Endpoints never perform rating arithmetic.

## 3. Core flow: submit -> moderate -> publish -> aggregate

1. The current `POST /reviews/guest` stores a `PENDING` review and first revision, deduplicated by permanent `client_draft_id` and hashed Guest scope. It currently returns a server-issued receipt. Platform Foundation 13 replaces this with a client-generated, never-reissued receipt and domain-separated keyed digest before frontend integration.
2. A moderator (`/staff/moderation/reviews/{id}/decisions`) sends `expected_version` and a decision. The service locks the review and its destination aggregate row, checks `version`, applies the `counted_rating` delta exactly once, writes an audit decision, and commits.
3. Public feed `GET /destinations/{id}/reviews` returns only `PUBLISHED` reviews ordered by `(published_at, id)` with an opaque cursor, plus the Guest Feedback aggregate.
4. The current exchange endpoint is deprecated. The target contract uses receipt-scoped POST bodies for status, withdrawal, appeal, and pending edits without creating a receipt session.

## 4. API surface today

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /api/v1/health` | none | Liveness; used by Render. |
| `GET /api/v1/health/ready` | none | Runs `SELECT 1`; 503 if the database is unreachable. |
| `POST /api/v1/reviews/guest` | Guest scope secret | 201 + receipt. |
| `GET /api/v1/destinations/{id}/reviews` | none | Public, paginated. |
| `POST /api/v1/review-receipts/exchange` | receipt token | Status. |
| `POST /api/v1/reviews/{id}/withdraw` | receipt token | Version-checked. |
| `GET /api/v1/staff/moderation/reviews` | staff | 501 in production until R04. |
| `POST /api/v1/staff/moderation/reviews/{id}/decisions` | staff | Version-checked. |
| `PUT /api/v1/staff/moderation/reviews/{id}/conflict` | staff | Locked rating transition. |
| `POST /api/v1/guest-visits` | none | `{first_visit}` only; 204; Redis day counter. |
| `GET /api/v1/ops/panels`, `/ops/panels/{id}`, `/ops/overview`, `POST /ops/jobs/visit-rollup` | ops token | Dashboard API; 404 while `OPS_DASHBOARD_TOKEN` is unset. |

Planned endpoints (member reviews, reports, appeals, verification, roles) are listed in `Features/Review.md` section 9.2.

## 5. Delivery and environments

```text
GitHub PR -> CI (lint, unit, PostgreSQL integration, migration, security, contract and build checks)
          -> protected environment approval
          -> migration job against the selected commit
          -> API deploy and readiness verification
          -> public static build and verification
          -> staff static build and verification
```

| Environment | Database | `APP_ENV` | Staff identity |
|---|---|---|---|
| Local | Docker Compose Postgres 17 | development | `X-Test-Staff-Id` header |
| CI | Postgres service container (`abhijatri_test`) | test | test header |
| Shared dev / demo | Supabase project (separate per environment) | production | disabled (501) until R04 |

### Environment variables

| Variable | Required | Purpose |
|---|---|---|
| `APP_ENV` | yes | `development`, `test`, or `production`. **Unset means production** (fail closed): the guard runs and the test staff login is unavailable. |
| `DATABASE_URL` | yes | Runtime connection; `postgres://` is normalised to `postgresql+psycopg://`; needs `sslmode=require` for remote hosts. |
| `MIGRATION_DATABASE_URL` | migration workflow only | Never present in the Render runtime environment. |
| `TEST_DATABASE_URL` | tests | Must name a database ending `_test`. |
| Receipt and scope HMAC keyring | yes | Versioned keys with separate context labels; raw keys are never committed. |
| `CORS_ALLOWED_ORIGINS` | yes (prod) | Comma-separated explicit origins. |
| `LOG_LEVEL` | no | Default `INFO`; never logs secrets. |
| `DOCS_ENABLED` | no | Defaults on outside production. |
| `TZ`, `APP_TIMEZONE` | no | Both `UTC`. Timestamps are stored as `timestamptz` and computed in UTC; the DB session is pinned with `SET TIME ZONE 'UTC'`. |
| `DEFAULT_DISPLAY_TIMEZONE` | no | Default `Asia/Dhaka`; IANA zone used for calendar rules such as the visit-month check. |
| `RECEIPT_KEYS`, `RECEIPT_KEY_CURRENT` | prod: yes (or the pepper) | JSON keyring `{"v1": "<secret>"}` and the id of the key used for new digests. Receipt, Guest-scope and network digests share the ring and differ by context label. Old keys stay until no row references their `key_id` (PF 13.4). Defaults to `{"v1": RECEIPT_PEPPER}`. |
| `ADVISORY_STALE_AFTER_DAYS` | no | Default 30. An advisory last verified longer ago than this is returned with state `STALE`; past `valid_until` it is `EXPIRED` and never shown as current. |
| `PUBLIC_CACHE_MAX_AGE_SECONDS` | no | Default 60. `Cache-Control: public, max-age` on the public destination routes only; every other route stays `no-store`. |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_RECYCLE` | no | Pool tuning for Supabase connection limits. |
| `DB_POOL_TIMEOUT`, `DB_CONNECT_TIMEOUT` | no | Seconds to wait for a pooled / new connection (default 5). Failure returns 503. |
| `DB_STATEMENT_TIMEOUT_MS`, `DB_LOCK_TIMEOUT_MS`, `DB_IDLE_IN_TRANSACTION_TIMEOUT_MS` | no | Applied to every session (defaults 5000 / 3000 / 15000). A slow query or lock wait is cancelled instead of holding a worker. |
| `REQUEST_TIMEOUT_SECONDS`, `MAX_REQUEST_BODY_BYTES` | no | Hard request deadline (default 15 s, then 504) and `Content-Length` cap (default 64 KiB, then 413). |
| `RATE_LIMIT_ENABLED`, `RATE_LIMIT_GUEST_SUBMIT`, `RATE_LIMIT_RECEIPT` | no | Per-client-IP limits on the public write endpoints (defaults 5/minute and 10/minute, then 429). |
| `ALLOW_TEST_STAFF_HEADER` | no | Local development only; enables the `X-Test-Staff-Id` stand-in login. Ignored in production. |
| `CLIENT_ADDRESS_HEADER`, `CLIENT_ADDRESS_POSITION` | prod: yes | The single provider-appended header and entry position (default right-most) from which `app/client_address.py` derives the client address. Uvicorn runs with `--no-proxy-headers`; no other forwarding header is read. The chosen header and position are recorded here after the staging forged-header test (PF 14.2): **not yet tested, Gate A evidence outstanding**. |
| `TURNSTILE_ENABLED`, `TURNSTILE_SECRET`, `TURNSTILE_HOSTNAME` | prod: yes | Server-side Turnstile validation. Production start-up fails if any is missing. Off by default only in development and test. |
| `GUEST_SUBMIT_PER_SCOPE_PER_DAY`, `GUEST_SUBMIT_PER_NETWORK_PER_HOUR`, `GUEST_SUBMIT_PER_NETWORK_PER_DAY` | no | Durable limits for new Guest drafts (defaults 3, 30, 100). |
| `RECEIPT_OPS_PER_RECEIPT_PER_HOUR`, `RECEIPT_OPS_PER_NETWORK_PER_HOUR`, `RECEIPT_FAILURES_SHORT_LIMIT`, `RECEIPT_FAILURES_LONG_LIMIT` | no | Receipt-operation limits (defaults 20, 100) and the failure tiers (5 per 15 minutes, 20 per 24 hours) that drive the progressive block. |
| `GUEST_PENDING_PER_DESTINATION`, `GUEST_PENDING_TOTAL`, `GUEST_PENDING_ALERT_RATIO` | no | Pending Guest ceilings (50, 500); a warning is logged from 80 percent; reaching a ceiling returns `503 GUEST_WRITES_PAUSED`. |
| `REDIS_URL` | prod: yes | Upstash `rediss://` URL for this environment (one database per environment). Production start-up fails if it is missing or not TLS. Locally `redis://localhost:6379/0` from `compose.yaml`. |
| `RATE_LIMIT_GUEST_VISIT`, `GUEST_VISITS_PER_NETWORK_PER_HOUR` | no | Guest-visit limits: burst pre-filter (20/minute) and durable per-network cap (60/hour, then `429 RATE_LIMITED`). |
| `REDIS_TIMEOUT_MS`, `VISIT_COUNTER_ENABLED`, `METRICS_FLUSH_SECONDS` | no | Redis command timeout (300 ms), the visit-counting kill switch, and the ops event flush interval (60 s). |
| `OPS_DASHBOARD_TOKEN`, `OPS_AUTH_FAILURES_PER_NETWORK_PER_HOUR` | no | Bearer token for `/api/v1/ops` (≥ 32 chars in production; unset = 404) and the failure limit (10 per network per hour). |
| `GUEST_WRITES_PAUSED` | no | Emergency switch. Pauses new Guest submissions only; reads, receipt status and recovery of an existing draft continue. |
| `RATE_LIMIT_GUEST_SUBMIT`, `RATE_LIMIT_RECEIPT` | no | In-memory burst pre-filter per trusted address (defaults 5 and 10 per minute). Not the authoritative limiter. |

### Deployed environments (fill in; never record secrets here)

| Environment | API URL | Database project | Updated |
|---|---|---|---|
| Staging | `https://api.<owned-domain>` | Supabase `abhijatri-staging` | |
| Production or pilot | `https://api.<owned-domain>` | Supabase `abhijatri-prod` | |
| Public frontend (interim, Vercel) | `https://<project>.vercel.app` (fill in after first deploy) | uses the API above | |
| API on Railway (not in the approved plan) | `https://abhijatri-backend.up.railway.app` | unknown; check its `DATABASE_URL` | 19 Oct 2026: live, but serving pre-merge code (`Docs/Frontend-Implemented.md` B4). 22 Oct 2026: deploys `main`, `APP_ENV=production`; ops token and CORS set, `REDIS_URL` still required before the 0009 code ships |
| Ops dashboard (Vercel, private) | `https://abhijatri-ops-44afee.vercel.app` | calls the Railway API with the ops token | 22 Oct 2026: deployed from `ops/` |

### Public frontend deployment on Vercel (interim)

Owner: Shahriar Islam (deploys from the shared Vercel account). Prepared by: Abdullah. Decision: `Docs/Decisions.md`, 2026-10-19 (Vercel).

**One-time project setup**

| Setting | Value |
|---|---|
| Git repository and branch | `shahriar6130/Abhijatri`, production branch agreed by the team (`main` after `abd` is merged) |
| Root Directory | `frontend` |
| Framework preset | Vite (also set in `frontend/vercel.json`) |
| Build command / output | `npm run build` / `dist` (from `frontend/vercel.json`) |
| Node.js version | 22 (matches CI) |
| Environment variable | `VITE_API_BASE_URL` = the deployed API origin, e.g. `https://api.<owned-domain>`, **no trailing slash**. It is baked in at build time, so changing it needs a redeploy. Set it for Production and Preview. |
| Optional variable | `VITE_ALLOWED_BACKEND_HOSTS` = extra API hostnames (comma-separated, no scheme) that the System Status page may test besides the `VITE_API_BASE_URL` host. |

`frontend/vercel.json` already provides:

- a rewrite of every path to `/index.html`, so refreshing `/destinations/<id>` or `/reviews` does not return 404 (static files still win);
- `Cache-Control: public, max-age=31536000, immutable` on hashed `/assets/*` (Security 7.1);
- `X-Content-Type-Options`, `Referrer-Policy: strict-origin-when-cross-origin`, `X-Frame-Options: DENY`, `Cross-Origin-Opener-Policy: same-origin` and a `Permissions-Policy` disabling camera, microphone, payment and geolocation (PF 16.4).

**Backend change required at the same time**

Add the exact Vercel origin to the API's `CORS_ALLOWED_ORIGINS` (comma-separated, e.g. `https://<project>.vercel.app,http://localhost:5173`) and restart the API. Without it the browser blocks every request and the site shows "Could not reach the server". Preview deployments get different URLs and will be blocked unless added; test on the production URL.

**Smoke test after deploy**

1. `/` shows "5 published destinations" and the advisory list.
2. Open Sajek Valley, refresh the page: it reloads (no 404) with advisories and contacts.
3. Switch to English: the page changes language without reloading data.
4. Submit a Guest review: a receipt `abr1_…` is shown once; "Check status" shows "Waiting for moderation".
5. Browser console has no CORS errors.

**Known limits of the interim deployment**

- Production Guest submission needs the Turnstile widget, which is not built yet (`Docs/Frontend-Implemented.md` section 8). Against an API with `TURNSTILE_ENABLED=true`, submission returns `CHALLENGE_FAILED`; reading works.
- No Content Security Policy yet: fonts still load from Google Fonts and prototype pages still hotlink images. CSP lands with self-hosted fonts (PF 16.3).
- `vercel.app` is a public suffix, like `onrender.com` (PF 5.2). Member and staff cookies (R04) need the frontend and API on one owned domain, so this deployment is for Guest features and demonstrations only until the domain is in place.

## 6. Trust boundaries

Public internet -> Render edge (TLS) -> API container -> Supabase over TLS. Secrets are injected through Render's dashboard, never committed. CI has no production credentials. Supabase's Data API and anon key are not part of the architecture.

## 7. Authentication boundary

| Actor | Credential | Transport | Reaches | Status |
|---|---|---|---|---|
| Guest | Guest scope secret and client-generated receipt; domain-separated keyed digests stored | Request body, never cookie or URL | Guest submission and receipt-scoped POST operations | Target; current server-issued exchange flow is scheduled for replacement |
| Member | Server-side session, `__Host-` HttpOnly Secure SameSite cookie, CSRF token | Cookie | Member review and account routes | Planned (R04) |
| Staff | Separate cookie name and scope, MFA, short lifetime, `can(actor, action, resource)` per request | Cookie | `/staff/*` | Test header in dev/test only; 501 in production |

Rules: Guest and Member credentials are different cookie names and scopes; a Verified Member badge never grants staff authority; staff routes are authorised server-side even if the URL is known; private responses carry `Cache-Control: no-store`.

## 8. Offline boundary

| Data | Offline treatment |
|---|---|
| Public destination pages, advisories, contacts, pack manifest | Cacheable by the service worker and stored in IndexedDB with version and generated date. |
| Published review snapshot | Stored with its age; refreshed on reconnect; an over-age snapshot is not presented as current (maximum age is an open decision, Decisions.md Step 8). |
| Review text drafts | IndexedDB only; user can delete per draft or clear all. An unsent Guest draft includes its receipt until acknowledgement. |
| Submitted-review receipts, account, staff and moderation responses | Never cached by the service worker; submitted-review receipts are removed from IndexedDB under Platform Foundation 13.5. |
| Reconnect submission | Re-sent with the same `client_draft_id`; the server returns the existing review instead of a duplicate. |
| Published-review edits | Online only (MVP uses withdraw and resubmit). |

## 9. Resolved boundary decisions

1. Cookie and domain topology is fixed by Platform Foundation 5.
2. Offline snapshot age defaults to seven days until the Step 8 measurement records a replacement.
3. Receipt custody is fixed by Platform Foundation 13.5.
4. The structured error contract is fixed by Platform Foundation 12.3.
5. Trusted client-address derivation remains a Gate A deployment test. Gate B is blocked if the provider chain cannot be verified.

## 10. Frontend Architecture (React PWA)

```text
Browser (Vite + React 18 + TypeScript)
  ├── Context Layer: LanguageContext (Bangla default / English), ThemeContext (Sage / Neon), SessionContext (guest until R04; interface only, never authorization)
  ├── Route Layer: React Router v6. Public shell: / (landing), /login. App shell: /overview, /destinations, /destinations/:id, /planner, /offline-packs, /trips, /reviews, /health
  ├── Styling: Tailwind CSS + global.css (Design tokens: Hind Siliguri, Noto Serif Bengali, Inter -0.06em)
  ├── Cache Layer: planned (R12 service worker, R13/R15 IndexedDB packs and drafts); not built yet
  └── API Client: src/api/* calling /api/v1 on VITE_API_BASE_URL (Vite also proxies /api in dev)
```

### 10.1 Page URL & Component Topology

| Route | Component | Role | Traces to Requirement |
|---|---|---|---|
| `/` | `LandingPage` (public shell) | Entry: continue as guest or sign in; links to published destinations. Not a gate | Use case: Guest and Member entry |
| `/login` | `SignInPage` (public shell) | Member sign-in (R05); disabled until the R04 account service exists | FR03, R05 |
| `/overview` | `OverviewPage` | Live counts (destinations, advisories in effect, published Guest reviews) and destinations with advisories, from `GET /destinations` | Proposal Section 1 |
| `/destinations` | `DestinationsPage` | Published destinations from `GET /destinations`, bilingual text filter, loading/error/empty states | O2, FR01, R03 |
| `/destinations/:id` | `DestinationDetailPage` | Profile from `GET /destinations/{id}`: advisories with state and source, seasonality, guide items, restrictions, contacts, published review feed | FR01, FR15, R03 |
| `/planner` | `PlannerPage` | **Not available yet** (E06 to E08): honest placeholder via `FeatureUnavailable`; no estimate is calculated or requested | O3, FR08, FR09 |
| `/offline-packs` | `OfflinePacksPage` | **Not available yet** (R12, R13): placeholder; nothing is stored | O4, FR10, FR17 |
| `/trips` | `SavedTripsPage` | **Not available yet** (E09): placeholder | FR11 |
| `/reviews` | `ReviewsPage` | Guest review submission with client-generated receipt, receipt shown once, status and withdrawal | O5, FR04, FR13, R09 |
| `/health` | `HealthCheckPage` | Real-time diagnostic console testing `GET /api/v1/health` & readiness | Acceptance testing |

### 10.2 Modular API Architecture (`src/api/`)

The frontend network and data layer is organized into isolated, domain-focused API modules under `src/api/`:

| Module File | Scope & Exported Members | Architectural Contract |
|---|---|---|
| `src/api/client.ts` | `API_BASE_URL`, `apiRequest<T>()`, `ApiError`, `NETWORK_ERROR` | Base URL (`VITE_API_BASE_URL`), `Accept-Language` from the interface language, `Content-Type` only with a body (public GETs stay CORS simple requests), and the PF 12.3 error body `{error:{code,message,request_id,field_errors}}` mapped to `ApiError`. |
| `src/api/health.ts` | `checkBackendHealth(customUrl?: string)` | Diagnostic health runner checking backend liveness (`GET /api/v1/health`) and database readiness probe (`GET /api/v1/health/ready` testing `SELECT 1`). |
| `src/api/destinations.ts` | `listDestinations()`, `listAllDestinations()`, `getDestination(id)` | Public R02 reads (API.md 5.12, 5.13). |
| `src/api/reviews.ts` | `getReviewFeed()`, `submitGuestReview()`, `getReceiptStatus()`, `withdrawGuestReview()`, `generateReceipt()`, `getGuestScopeSecret()`, `CONSENT_VERSION` | Guest review lifecycle (API.md 5.1 to 5.4, 5.8; PF 13). Secrets travel only in JSON bodies. |
| `src/api/index.ts` | Barrel export of the four modules above | Unified entrypoint (`import { ... } from '../api'`). |
| `src/components/common/FeatureUnavailable.tsx` | `FeatureUnavailable` | Placeholder for a feature without a backend: what it will do, the Gantt task, what works today. `src/data/prototypeDestinations.ts` was deleted on 28 Oct 2026. |

Implementation status and evidence: `Docs/Frontend-Implemented.md`.

