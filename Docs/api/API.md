# Abhijatri API Contract (v1)

**Status:** Approved target contract, 18 October 2026. **Contract version:** `1.0.0-draft` (`info.version` stays `0.1.0` until the first frontend integration).

**Sources:** `Docs/Platform-Foundation.md` (PF) sections 5.3, 12, 13, 14 and 16; `Features/Review.md` (RV) sections 4, 5, 9; `Docs/Security.md` 7.1. Where this document and those sources differ, the sources win and this document is corrected.

**Snapshot:** `Docs/api/openapi-v1.json` is the machine-readable snapshot of the routes in code. CI fails if it drifts. Regenerate with `cd backend && uv run python scripts/export_openapi.py`.

**Status labels used below:**

| Label | Meaning |
|---|---|
| Implemented | In code and matches this contract. |
| Change required | In code, but differs from this contract. Section 6 lists the differences. |
| Planned | Not in code. Built by the task named in the table. |

## 1. Conventions

| Topic | Rule | Source |
|---|---|---|
| Base path | `/api/v1`. Additive fields and endpoints stay in v1. Breaking changes need `/api/v2` or a managed compatibility period recorded in `Decisions.md`. | PF 12.1 |
| Format | JSON, UTF-8. Identifiers are UUIDs. Timestamps are UTC ISO-8601. Name fields are NFC-normalised. | PF 11 |
| Errors | Section 2. Clients branch on `code`, never on `message`. | PF 12.3 |
| Concurrency | Every mutation of a review sends `expected_version`. A stale value returns `409 REVIEW_VERSION_CONFLICT`. | RV 6.1 |
| Pagination | Opaque `after` cursor over `(published_at, id)` descending. `limit` 1 to 50, default 20. `next_cursor` is `null` on the last page. Cursors are not reused across sort orders. | RV 9.3 |
| Idempotency | Section 3. | PF 12.4 |
| Caching | Every response is `Cache-Control: no-store` unless the route is marked Public in Section 4. | Security 7.1, PF 16.4 |
| Language | `message` in errors is Bangla or English, chosen by `Accept-Language`. Bangla is the default. | PF 12.3 |
| Secrets | Receipt and guest scope secrets travel only in JSON request bodies. They never appear in URLs, fragments, cookies, headers, logs, analytics or error bodies. | PF 13.3, 13.4 |

### 1.1 Credentials

| Credential | Used by | How it is sent |
|---|---|---|
| None | Public reads, health | Nothing. Public `GET` routes are CORS simple requests: no custom headers, no credentials. |
| Guest scope secret | Guest submission | `guest_scope_secret` in the body. Supplemental signal only, not an abuse boundary (PF 14.1). |
| Guest receipt | Receipt operations | `receipt_secret` in the body (Section 5.1). |
| Member session | Member endpoints | Cookie `__Host-abhijatri_session` (the Supabase access token, `HttpOnly`, `SameSite=Lax`) with `__Host-abhijatri_refresh` (the refresh token); `X-CSRF-Token` on writes. Implemented 27 Oct 2026. |
| Staff session | `/admin/*` (replaces `/staff/*`) | The same session cookies. Staff are members who hold an active row in `user_roles` and have passed TOTP (`aal2`). The role is read from the database on every request, never from the token. Non-staff get `404`, staff of the wrong role `403`. |

Identity is provided by Supabase Auth (decision of 27 Oct 2026, deviating from PF 8.1); the browser still talks only to this API, which proxies Auth and keeps the tokens in cookies. The cookies are host-only, `Secure`, `HttpOnly`, `Path=/`, with no `Domain` attribute (PF 5.3). No receipt cookie exists. Cookie sessions across different sites (for example Vercel and Railway) need the owned same-site domain (PF 5.5).

The development-only `X-Test-Staff-Id` header remains for the old `/staff/moderation/*` routes while `APP_ENV` is `development` or `test`; they return `501 STAFF_AUTH_NOT_CONFIGURED` in production and are replaced by `/admin/*`.

### 1.2 CORS and CSRF

| Setting | Value (PF 16.1) |
|---|---|
| Allowed origins | `https://app.<owned-domain>`, `https://admin.<owned-domain>`. Never a wildcard. |
| `allow_credentials` | `true` |
| Allowed methods | Only those routes use: `GET`, `POST`, `PUT`, `PATCH` |
| Allowed request headers | `Content-Type`, `Idempotency-Key`, `X-CSRF-Token`, `Accept-Language` |
| Preflight cache | 600 seconds |

CSRF uses a synchronizer token (PF 16.2). `GET /auth/csrf` returns `{ "csrf_token": "..." }` for the current session. Every state-changing cookie-authenticated request sends it in `X-CSRF-Token`. Guest submission and receipt endpoints use no cookies and need no CSRF token.

## 2. Error format

Every error, including validation errors, uses one shape (PF 12.3). FastAPI's default `{"detail": ...}` and default 422 bodies are replaced by exception handlers.

```json
{
  "error": {
    "code": "REVIEW_VERSION_CONFLICT",
    "message": "এই রিভিউটি ইতিমধ্যে পরিবর্তিত হয়েছে।",
    "request_id": "8d1f5a0e-2c7b-4c55-9b0f-0a3e2f6b1c44",
    "field_errors": []
  }
}
```

`field_errors` is a list of `{ "field": "...", "code": "..." }` and is empty when not a validation error. The `X-Request-ID` response header carries the same `request_id`. Errors never contain stack traces, SQL, secrets, internal paths, or whether an account exists.

| HTTP | `code` | When |
|---|---|---|
| 401 | `AUTH_REQUIRED` | Missing or invalid session. |
| 401 | `INVALID_CREDENTIALS` | Wrong email or password, or a wrong TOTP code. Never says which. |
| 403 | `EMAIL_NOT_VERIFIED` | Correct password, address not yet verified. |
| 403 | `ACCOUNT_DISABLED` | The account has been disabled. |
| 403 | `MFA_REQUIRED` | A staff action needs a session that passed TOTP (`aal2`). |
| 403 | `REAUTH_REQUIRED` | A high-impact action needs a password check within the last 10 minutes. |
| 403 | `FORBIDDEN` | Authenticated but not permitted. |
| 403 | `SELF_MODERATION_FORBIDDEN` | A moderator acts on their own review. |
| 403 | `CSRF_INVALID` | Missing or wrong `X-CSRF-Token`. |
| 403 | `CHALLENGE_FAILED` | Turnstile token missing, expired, reused or invalid. |
| 404 | `NOT_FOUND` | Route, destination or review does not exist. |
| 404 | `RECEIPT_NOT_FOUND` | Receipt does not match the review. Same response as a missing review, so existence is not leaked. |
| 409 | `REVIEW_VERSION_CONFLICT` | `expected_version` is stale. |
| 409 | `INVALID_TRANSITION` | The decision is not allowed from the current state. |
| 409 | `DRAFT_ALREADY_SUBMITTED` | Duplicate draft with a different receipt (Section 5.2). |
| 409 | `MEMBER_REVIEW_EXISTS` | A member already has an active review of that destination for that visit month (Section 5.20). |
| 409 | `RESERVED_DISPLAY_NAME` | Display name is reserved (for example `Admin`, `Moderator`). |
| 409 | `IDEMPOTENCY_KEY_REUSED` | Same `Idempotency-Key` with a different request body. |
| 409 | `DUPLICATE_OPEN_REPORT` | The same scope already has an open report on this review. |
| 409 | `APPEAL_WINDOW_CLOSED` | Appeal sent after the 30-day window. |
| 413 | `PAYLOAD_TOO_LARGE` | Request body exceeds the configured limit. |
| 422 | `TOKEN_INVALID_OR_EXPIRED` | An email verification or password-reset link is wrong, used or expired. |
| 422 | `VALIDATION_FAILED` | Schema validation failed; see `field_errors`. |
| 422 | `INVALID_CURSOR` | `after` cannot be decoded. |
| 422 | `INVALID_RECEIPT_FORMAT` | Receipt is not `abr1_` plus 43 base64url characters, or is a known weak value. |
| 429 | `RATE_LIMITED` | A limit in Section 7 was hit. `Retry-After` is set. |
| 503 | `GUEST_WRITES_PAUSED` | Pending ceiling reached or emergency switch on (PF 14.3, 14.6). Public reads continue. |
| 500 | `INTERNAL_ERROR` | Unexpected failure. |
| 501 | `AUTH_NOT_CONFIGURED` | The Supabase settings are missing, so no sign-in route works. |
| 501 | `STAFF_AUTH_NOT_CONFIGURED` | Old `/staff/*` route in production (replaced by `/admin/*`). |
| 503 | `SERVICE_UNAVAILABLE` | Database unavailable or pool exhausted. `Retry-After` is set. |
| 504 | `REQUEST_TIMEOUT` | Request exceeded the server timeout. |

## 3. Idempotency

Retryable writes accept `Idempotency-Key: <UUID>` (PF 12.4).

- The server stores a digest of the key scoped by actor or guest scope, the endpoint, a request fingerprint, a result reference, the creation time and an expiry 72 hours later.
- A unique constraint on (scope, endpoint, key digest) enforces uniqueness.
- The same key with the same body returns the stored response. The same key with a different body returns `409 IDEMPOTENCY_KEY_REUSED`.
- Idempotency only replays recent responses. Permanent duplicate prevention for reviews is the `client_draft_id` uniqueness in RV 4.1.

## 4. Endpoints

### 4.1 Platform

| Method and path | Credential | Cache | Status |
|---|---|---|---|
| `GET /health` (also `HEAD`) | none | no-store | Implemented |
| `GET /health/ready` (also `HEAD`) | none | no-store | Change required |
| `GET /auth/csrf` | member or staff session | no-store | Implemented 27 Oct 2026 (section 5.17) |
| `POST /guest-visits` | none (body `{ "first_visit": bool }` only, no cookie) | no-store | Implemented; Redis day counters since 22 Oct 2026 (section 5.14) |
| `GET /guest-visits/stats` | — | — | **Removed 22 Oct 2026**: traffic volume is not public; the numbers moved to `GET /ops/overview` (5.16) |
| `GET /ops/panels` | ops token (`Authorization: Bearer`) | no-store | Implemented 22 Oct 2026 (section 5.16) |
| `GET /ops/panels/{panel_id}` | ops token | no-store | Implemented 22 Oct 2026 (section 5.16) |
| `GET /ops/overview` | ops token | no-store | Implemented 22 Oct 2026 (section 5.16) |
| `POST /ops/jobs/visit-rollup` | ops token | no-store | Implemented 22 Oct 2026 (section 5.16) |
| `POST /ops/jobs/rating-reconciliation` | ops token | no-store | Implemented 31 Oct 2026 (R08) |

`/health` returns `{ "status": "ok" }`. `/health/ready` checks the database and returns `503 SERVICE_UNAVAILABLE` if it is down. It must also report the deployed build and the database migration revision, because the deploy workflow polls it for both (PF 22.1):

```json
{ "status": "ok", "build": "82ecb52", "db_revision": "0002" }
```

### 4.2 Guest reviews and receipts

| Method and path | Credential | Cache | Status |
|---|---|---|---|
| `POST /reviews/guest` | guest scope + receipt + Turnstile | no-store | Change required: only `Idempotency-Key` replay (order-of-checks step 3, WP4) is pending. Client receipt, `201`/`200`, `409`, Turnstile, durable limits, ceilings and the emergency switch are done (WP3, WP5). |
| `POST /review-receipts/status` | receipt | no-store | Implemented (WP3). Replaced the legacy `POST /review-receipts/exchange`, which is removed. |
| `POST /reviews/{review_id}/withdraw` | receipt | no-store | Implemented (WP3, WP5 receipt limits). Idempotency-Key replay is added with WP4. |
| `PATCH /reviews/{review_id}/pending` | receipt or owner | no-store | Implemented 29 Oct 2026 (R07, section 5.5) |
| `POST /review-receipts/appeals` | receipt | no-store | Implemented 29 Oct 2026 (R07, section 5.6) |

### 4.3 Public reads

| Method and path | Credential | Cache | Status |
|---|---|---|---|
| `GET /destinations/{destination_id}/reviews` | none | Public, short TTL | Implemented (error body aside) |
| `GET /destinations` | none | Public, short TTL | Implemented (R02) |
| `GET /destinations/{destination_id}` | none | Public, short TTL | Implemented (R02) |
| `GET /destinations/{destination_id}/pack/manifest` | none | Public, versioned | Planned (R14) |
| `GET /review-parameters` | none | Public, short TTL | Implemented 20 Oct 2026 (section 5.15) |

Public responses vary by `Accept-Language` and are purged on moderation or deletion (Security 7.1).

### 4.4 Reports and removal

| Method and path | Credential | Cache | Status |
|---|---|---|---|
| `POST /public/review-reports` | guest scope + Turnstile | no-store | Planned (R11) |
| `POST /public/removal-requests` | guest scope + Turnstile | no-store | Planned (R11) |
| `POST /reviews/{review_id}/reports` | member | no-store | Planned (R11) |

### 4.5 Members and verification

| Method and path | Credential | Cache | Status |
|---|---|---|---|
| `POST /auth/register`, `/auth/verify-email`, `/auth/resend-verification`, `/auth/login`, `/auth/logout`, `/auth/password-reset/request`, `/auth/password-reset/confirm`, `GET /auth/session`, `POST /auth/mfa/enroll`, `/auth/mfa/verify`, `/auth/reauth` | none or member | no-store | Implemented 27 Oct 2026 (R04, section 5.17) |
| `POST /reviews/member` | member | no-store | Implemented 27 Oct 2026 (section 5.20) |
| `GET /reviews/mine` | member | no-store | Implemented 29 Oct 2026 (R07, section 5.5a) |
| `GET /reviews/{review_id}` | owner or staff | no-store | Implemented 29 Oct 2026 (R07, section 5.5a) |
| `POST /verifications` | member | no-store | Planned (R04) |

### 4.6 Staff

| Method and path | Credential | Cache | Status |
|---|---|---|---|
| `GET /staff/moderation/reviews` | staff | no-store | Change required |
| `POST /staff/moderation/reviews/{review_id}/decisions` | staff | no-store | Implemented (error body aside) |
| `PUT /staff/moderation/reviews/{review_id}/conflict` | staff | no-store | Implemented (error body aside) |
| `GET /staff/verifications` | staff | no-store | Planned (R11) |
| `POST /staff/verifications/{verification_id}/decisions` | staff | no-store | Planned (R11) |
| `POST /staff/users/{user_id}/roles` | super administrator, recent reauthentication | no-store | Planned (R11) |

`POST /reviews/{review_id}/media-intents` (Verified Member only, constrained presigned upload into quarantine) is in core scope since Review.md amendment A1 (20 Oct 2026). Planned with R07 and the media pipeline; its shape is set when Review.md section 8 is implemented.

## 5. Request and response shapes

### 5.1 Guest receipt

The client generates the receipt before the first submission: 32 bytes from `crypto.getRandomValues`, encoded as unpadded base64url, with the prefix `abr1_`. The result is 48 characters (PF 13.2).

The server:

- validates the prefix, length and character set, and rejects known weak values;
- stores only `(key_id, HMAC-SHA-256 digest)` under a versioned keyring, with the context label `abhijatri:review-receipt:v1`;
- never generates, returns or reissues a receipt.

The guest scope digest uses the same keyring with the label `abhijatri:guest-scope:v1` and its own `guest_scope_key_id` (PF 13.4).

A receipt allows status, withdrawal, appeal, and editing while the review is `PENDING` or `CHANGES_REQUESTED`. It reveals only its own review. A lost receipt cannot be recovered; the user files a removal request instead.

### 5.2 `POST /reviews/guest`

```http
POST /api/v1/reviews/guest
Content-Type: application/json
Idempotency-Key: 4a7e0b52-3f6d-4c1a-9a2e-6c1f0d7b8e21
```

```json
{
  "destination_id": "6f1c2c9e-0c0e-4a3b-9a55-2f4f7e1d2b10",
  "client_draft_id": "0b9b2b1e-7a43-4c2e-8b57-0e0d8f6d6a11",
  "guest_scope_secret": "<43 to 200 character random secret kept by the client>",
  "receipt_secret": "abr1_<43 base64url characters>",
  "turnstile_token": "<token from the managed widget>",
  "guest_display_name": "Sadia Rahman",
  "language": "BN",
  "traveller_type": "FAMILY",
  "comfort_tier": "STANDARD",
  "visit_month": "2026-09-01",
  "title": "Good family trip",
  "body": "At least twenty characters of plain text, up to 6000.",
  "overall_rating": 4,
  "category_ratings": { "FOOD": 4, "SAFETY_PERCEPTION": 5 },
  "consent_version": "2026-10-01"
}
```

Field rules: `guest_display_name` 1 to 80 characters; `title` 3 to 160; `body` 20 to 6000, plain text; `overall_rating` 1 to 5; `visit_month` is the first day of a month and not in the future in the display time zone. Unknown fields return 422.

**`category_ratings` (implemented 20 Oct 2026, Review.md amendment A2):** optional object whose keys are the `ReviewCategory` values (Section 8) and whose values are integers 1 to 5; at most seven keys. A missing key means not applicable; an empty object is the same as omitting the field. An unknown key or a value outside 1 to 5 returns `422 VALIDATION_FAILED` with a field error under `category_ratings`. Ratings are stored per revision in `review_category_ratings`. On publication they move the per-category Guest Feedback (or, for an eligible Verified Member, Community) aggregate in the same transaction as the overall rating, and leave it on hide, withdrawal or conflict. The client sends the field when `VITE_REVIEW_CATEGORY_RATINGS=true`. `body` is the reviewer's free-text note. A Guest submission never carries images.

Response `201`:

```json
{
  "review_id": "d3a8f0a4-5d0e-4c43-9a0b-1f7e55c0a001",
  "status": "PENDING",
  "version": 1,
  "duplicate_recovered": false
}
```

The response contains no receipt. The client already holds it.

**Order of checks (PF 14.4):**

1. Validate the schema and the receipt format.
2. Look up an existing review for (guest scope digest, `client_draft_id`). If found, compare receipt digests: a match returns `200` with the existing review and `duplicate_recovered: true`; a mismatch returns `409 DRAFT_ALREADY_SUBMITTED` without the review id. Turnstile is not checked and nothing is counted.
3. Look up an `Idempotency-Key` replay. If found, return the stored response without counting it.
4. Validate the Turnstile token (hostname and action checked).
5. Increment rate-limit counters in their own committed transaction.
6. Check limits and pending ceilings.
7. Create the review.

A retry after a lost response is recovered at step 2 and needs no new challenge. Queued offline drafts are not auto-submitted; the user submits them on reconnection and completes the challenge.

### 5.3 `POST /review-receipts/status`

```json
{ "review_id": "d3a8f0a4-5d0e-4c43-9a0b-1f7e55c0a001", "receipt_secret": "abr1_..." }
```

Response `200`:

```json
{
  "review_id": "d3a8f0a4-5d0e-4c43-9a0b-1f7e55c0a001",
  "status": "REJECTED",
  "version": 2,
  "published_at": null,
  "decision_reason": "PERSONAL_INFORMATION",
  "appeal_deadline": "2026-11-17T17:59:59Z",
  "appeal_state": null
}
```

`appeal_state` is `null`, `received`, `in_review`, `upheld` or `overturned`.

`decision_reason` is the public-safe reason code and `appeal_deadline` is 30 days after rejection. Both are `null` unless the review was rejected (RV 4.2). A wrong receipt returns `404 RECEIPT_NOT_FOUND`.

### 5.4 `POST /reviews/{review_id}/withdraw`

```json
{ "receipt_secret": "abr1_...", "expected_version": 2 }
```

Response `200`: the same body as 5.3. Withdrawal removes the review from public view and its rating contribution in one transaction. A signed-in member omits `receipt_secret` and uses their session and CSRF token; another person's review answers `404 NOT_FOUND`.

Withdrawal is idempotent. If the review is already `WITHDRAWN` or `DELETED`, the server returns `200` with the current state **before** checking `expected_version`, so a retry after a lost response succeeds.

### 5.5 `PATCH /reviews/{review_id}/pending`

Allowed only while the review is `PENDING` or `CHANGES_REQUESTED` (RV 4.2, 5.2). Creates a new `review_revision`. Published reviews cannot be edited in the MVP; the author withdraws and submits a new review.

```json
{
  "receipt_secret": "abr1_...",
  "expected_version": 2,
  "title": "Good family trip",
  "body": "Edited text, at least twenty characters.",
  "overall_rating": 4,
  "visit_month": "2026-09-01"
}
```

Every content field is optional (`language`, `traveller_type`, `comfort_tier`, `visit_month`, `title`, `body`, `overall_rating`, `category_ratings`, `consent_version`); at least one is required, and `null` is refused (omit a field to keep it). `category_ratings`, when sent, replaces the whole set and `{}` clears it. The destination cannot change. Unknown fields return 422.

Response `200`: `{ "review_id": "...", "status": "PENDING", "version": 3, "revision": 2 }`. The previous revision becomes `SUPERSEDED`, the review returns to the moderation queue and nothing is counted. A member owner sends no `receipt_secret` and uses their session and CSRF token instead; another person's review answers `404 NOT_FOUND`. Any state other than `PENDING` or `CHANGES_REQUESTED` returns `409 INVALID_TRANSITION`; a stale `expected_version` returns `409 REVIEW_VERSION_CONFLICT`; moving a member review onto a month they already reviewed returns `409 MEMBER_REVIEW_EXISTS`. A wrong receipt returns `404 RECEIPT_NOT_FOUND` and counts toward the progressive block.

`CHANGES_REQUESTED` is reached when a moderator decides `REQUEST_CHANGES` (Section 5.10); the receipt status then shows the public-safe `decision_reason`.

### 5.5a Owner reads: `GET /reviews/{review_id}` and `GET /reviews/mine`

Both need a member session and answer `Cache-Control: no-store`.

`GET /reviews/{review_id}` is for the review's author or a moderator; anyone else gets `404 NOT_FOUND`. It returns the current revision (`language`, `traveller_type`, `comfort_tier`, `title`, `body`, `overall_rating`, `category_ratings`, `consent_version`), `status`, `version`, `rating_eligibility`, `visit_month`, `created_at`, `published_at`, `withdrawn_at`, `decision_reason`, `appeal_deadline`, `appeal_state`, the `revisions` history (`sequence`, `status`, `created_at`) and the review's `media` (`id`, `kind`, `state`, `alt_text`, `caption`). Moderators also get `guest_display_name`, `author_user_id` and `conflict_declared`; authors get them as `null`.

`GET /reviews/mine?status=&destination_id=&after=&limit=` lists the signed-in member's own reviews, newest first by the stable tuple `(created_at, id)`. `limit` defaults to 20 (maximum 50). `after` is the opaque `next_cursor` of the previous page; a cursor from another listing returns `422 INVALID_CURSOR`. Response: `{ "items": [{ "id", "destination_id", "status", "version", "overall_rating", "title", "visit_month", "created_at", "published_at", "appeal_deadline" }], "next_cursor": "..." | null }`.

### 5.6 `POST /review-receipts/appeals`

```json
{ "review_id": "...", "receipt_secret": "abr1_...", "statement": "Plain text, 20 to 2000 characters." }
```

Response `201`: `{ "appeal_id": "...", "status": "OPEN", "deadline_at": "..." }`. Only for a `REJECTED` review within its appeal window (the end of the 30th day after the rejection in Asia/Dhaka); otherwise `409 APPEAL_WINDOW_CLOSED`. A second appeal against the same decision returns `409 DUPLICATE_APPEAL`. The appeal joins the staff appeal queue and is decided by a moderator other than the one who rejected the review. The outcome appears as `appeal_state` in the receipt status (5.3); an overturned rejection returns the review to `PENDING`.

### 5.7 Reports and removal requests

Report reasons (RV 5.4): `SPAM`, `HARASSMENT`, `FALSE_INFORMATION`, `PRIVATE_INFORMATION`, `IMPERSONATION`, `SAFETY_MISINFORMATION`, `COPYRIGHT`, `CONFLICT_OF_INTEREST`, `OTHER`.

`POST /public/review-reports`:

```json
{
  "review_id": "...",
  "guest_scope_secret": "...",
  "turnstile_token": "...",
  "reason": "PRIVATE_INFORMATION",
  "details": "Optional plain text, up to 1000 characters.",
  "contact_email": null
}
```

`POST /public/removal-requests` uses the same body without `reason`, with `details` explaining the request, and is the recovery path for a lost receipt. Both return `202 { "status": "RECEIVED" }`. A report never removes a review by itself. Duplicate open reports from the same scope return `409 DUPLICATE_OPEN_REPORT`.

`POST /reviews/{review_id}/reports` is the member version: same `reason` and `details`, no guest scope or Turnstile, session and CSRF instead.

### 5.8 `GET /destinations/{destination_id}/reviews`

Query: `after` (optional cursor, at most 200 characters), `limit` (1 to 50, default 20).

```json
{
  "items": [
    {
      "id": "...",
      "author_type": "GUEST",
      "guest_tag": "1C669-J0TDY",
      "status": "PUBLISHED",
      "overall_rating": 4,
      "published_at": "2026-10-15T08:30:00Z",
      "title": "Good family trip",
      "body": "...",
      "category_ratings": { "FOOD": 4, "SAFETY_PERCEPTION": 5 }
    }
  ],
  "next_cursor": "MjAyNi0xMC0xNVQwODozMDowMCswMDowMHwuLi4",
  "guest_rating_average": 4.0,
  "guest_rating_count": 1,
  "guest_category_averages": [
    { "category": "FOOD", "average": 4.0, "count": 1 },
    { "category": "SAFETY_PERCEPTION", "average": 5.0, "count": 1 }
  ]
}
```

**The guest's typed name is never in the public feed** (owner, 22 Oct 2026): `author_type` is `GUEST` or `MEMBER`, and a guest review is shown only as "Anonymous guest · tag". Moderators still see `guest_display_name` in `GET /staff/moderation/reviews`. `guest_tag` is the guest's public pseudonym, computed by the server from the scope secret (Guest-Identity-and-Visits 3.1). Clients show it as "Anonymous guest · 1C669-J0TDY" (বেনামী অতিথি). It is `null` for member reviews and for guest reviews written before 22 Oct 2026. `category_ratings` is `{}` when the reviewer rated no category. `guest_category_averages` lists only categories with at least one counted rating, in the Section 8 order, each with its own count.

Only `PUBLISHED` reviews appear. Guest ratings feed Guest Feedback only, never Community Rating (RV 6.2). The response carries a short public `Cache-Control` TTL (Security 7.1), not `no-store`.

### 5.9 `GET /staff/moderation/reviews`

Query: `after` (cursor over submission time and id, ascending), `limit` (1 to 50, default 20). Returns reviews in `PENDING` or `UNDER_REVIEW`, oldest first.

```json
{
  "items": [
    {
      "review_id": "...",
      "destination_id": "...",
      "status": "PENDING",
      "version": 1,
      "author_kind": "GUEST",
      "guest_display_name": "Sadia Rahman",
      "language": "BN",
      "overall_rating": 4,
      "visit_month": "2026-09-01",
      "title": "Good family trip",
      "body": "...",
      "conflict_declared": false,
      "submitted_at": "2026-10-15T07:10:00Z"
    }
  ],
  "next_cursor": null
}
```

Moderators need the content to decide, so the queue returns it. The response is `no-store`.

**Current code (20 Oct 2026):** a bare list (at most 100, oldest first) of `review_id`, `status`, `version`, `counted_rating`, `destination_id`, `guest_display_name`, `overall_rating`, `title`, `body`, `category_ratings` and `created_at`. Paging and the remaining fields above are still a change required (Section 6).

### 5.10 `POST /staff/moderation/reviews/{review_id}/decisions`

```json
{ "expected_version": 1, "decision": "PUBLISH", "reason_code": "OK", "note": null }
```

`decision` is one of `PUBLISH`, `REJECT`, `HIDE`, `RESTORE`. `reason_code` is 2 to 60 characters; `note` is at most 500.

Allowed transitions: `PUBLISH` and `REJECT` from `PENDING` or `UNDER_REVIEW`; `HIDE` from `PUBLISHED`; `RESTORE` from `HIDDEN`. Anything else returns `409 INVALID_TRANSITION`.

Response `200`:

```json
{ "review_id": "...", "status": "PUBLISHED", "version": 2, "counted_rating": null }
```

`counted_rating` is `null` for guest reviews and the 1 to 5 value for an eligible Verified Member review. Every decision records actor, reason, note, previous state, new state and time in the audit log, in the same transaction as the rating delta.

### 5.11 `PUT /staff/moderation/reviews/{review_id}/conflict`

```json
{ "expected_version": 2, "conflict_declared": true, "reason_code": "OWNER_LINK", "note": null }
```

Response `200`: same shape as 5.10. Changing the flag on a published review locks the review and the destination aggregate, removes any previous `counted_rating`, recalculates eligibility and applies the new delta in one transaction (RV 6.1). The audit log records it as `SET_CONFLICT` or `CLEAR_CONFLICT`.

### 5.12 `GET /destinations`

Query: `after` (optional cursor, at most 300 characters), `limit` (1 to 50, default 20). Returns `PUBLISHED` destinations ordered by `name_en`, then `id`. The cursor is over `(name_en, id)` and is not reusable on other routes. An undecodable cursor returns `422`.

```json
{
  "items": [
    {
      "id": "6f1c2c9e-0c0e-4a3b-9a55-2f4f7e1d2b10",
      "name_bn": "কক্সবাজার",
      "name_en": "Cox's Bazar",
      "region_bn": "চট্টগ্রাম বিভাগ",
      "region_en": "Chattogram Division",
      "summary_bn": "...",
      "summary_en": "...",
      "latitude": 21.4272,
      "longitude": 92.0058,
      "community_rating": { "average": null, "count": 0, "category_averages": [] },
      "guest_feedback": {
        "average": 4.5, "count": 2,
        "category_averages": [{ "category": "FOOD", "average": 4.5, "count": 2 }]
      },
      "active_advisory_count": 1,
      "last_updated": "2026-10-19T06:00:00Z"
    }
  ],
  "next_cursor": null
}
```

All text fields carry both languages in every response, so the client picks the language and an offline pack needs only one fetch. Profile fields are `null` until content is entered (R01). `community_rating.average` stays `null` until Verified Member ratings exist; Guest Feedback is never mixed into it (RV 6.2). `active_advisory_count` counts published advisories that are in effect and not expired on the Asia/Dhaka date.

### 5.13 `GET /destinations/{destination_id}`

Query: `include_expired` (boolean, default `false`). Returns one `PUBLISHED` destination. A draft, archived or unknown destination returns `404` with the same body, so existence is not leaked.

```json
{
  "id": "6f1c2c9e-0c0e-4a3b-9a55-2f4f7e1d2b10",
  "name_bn": "...", "name_en": "...",
  "region_bn": "...", "region_en": "...",
  "summary_bn": "...", "summary_en": "...",
  "seasonality_bn": "...", "seasonality_en": "...",
  "restrictions_bn": "...", "restrictions_en": "...",
  "latitude": 21.4272, "longitude": 92.0058,
  "community_rating": { "average": null, "count": 0, "category_averages": [] },
  "guest_feedback": { "average": null, "count": 0, "category_averages": [] },
  "guide_items": [
    {
      "id": "...", "category": "ATTRACTION", "sort_order": 0,
      "title_bn": "...", "title_en": "...", "body_bn": "...", "body_en": "...",
      "provenance": {
        "source_type": "TEAM_RESEARCH", "source_ref": "https://example.org/source",
        "publisher": "Abhijatri content team",
        "effective_on": "2026-10-01", "verified_on": "2026-10-15", "next_review_on": "2027-01-15",
        "licence": "CC-BY-4.0"
      }
    }
  ],
  "advisories": [
    {
      "id": "...", "severity": "CAUTION",
      "title_bn": "...", "title_en": "...", "text_bn": "...", "text_en": "...",
      "effective_on": "2026-10-01", "valid_until": "2026-12-01",
      "state": "CURRENT",
      "provenance": { "source_type": "OFFICIAL", "source_ref": "...", "publisher": "...",
                      "effective_on": "2026-10-01", "verified_on": "2026-10-15",
                      "next_review_on": null, "licence": "..." }
    }
  ],
  "contacts": [
    {
      "id": "...", "kind": "TOURIST_POLICE",
      "name_bn": "...", "name_en": "...", "phone": "+880 341-62000",
      "address_bn": null, "address_en": null, "latitude": null, "longitude": null,
      "provenance": { "...": "same shape as above" }
    }
  ],
  "content_licence": "CC-BY-4.0",
  "content_verified_on": "2026-10-15",
  "as_of": "2026-10-19",
  "stale_after_days": 30,
  "last_updated": "2026-10-19T06:00:00Z"
}
```

Rules:

- Only published guide items, advisories and contacts appear. `guide_items` are ordered by category, then `sort_order`; `advisories` by severity (most severe first), then `valid_until`; `contacts` by kind, then name.
- **Advisory state** is computed on read from the Asia/Dhaka date `as_of`, never stored:

| `state` | Meaning |
|---|---|
| `CURRENT` | In effect (`effective_on <= as_of <= valid_until`) and verified within `stale_after_days`. |
| `STALE` | In effect, but last verified more than `stale_after_days` ago. The client shows it distinctly with its `verified_on` date. |
| `EXPIRED` | `as_of > valid_until`. Returned only with `include_expired=true`; never presented as current. |
| `NOT_YET_EFFECTIVE` | `as_of < effective_on`. Never returned by this route. |

- Every advisory and contact carries `provenance` (PF 17). `researcher` and `reviewer` names stay internal and are never returned.
- Contacts are public institution and emergency numbers only; no personal contacts are stored.
- `phone` matches `^\+?[0-9][0-9 -]{2,30}$` (for example `999`).
- Both public destination routes send `Cache-Control: public, max-age=60` and a weak `ETag`; a matching `If-None-Match` returns `304` with no body. They are CORS simple requests (no custom headers, no credentials). Because the payload carries both languages, it does not vary by `Accept-Language`.
- `category_averages` (in both rating objects, list and profile) has the same shape and rules as `guest_category_averages` in 5.8: only counted categories, Section 8 order, each with its count. Guest and Community category averages are never merged.
- `community_rating` also carries `score` and `seeded_selection` (added 20 Oct 2026).
  - `score` is the Bayesian Community Rating `(sum + 5 × 3.5) / (count + 5)` (RV 6.1). It is `null` until `count >= 5`.
  - `seeded_selection` is `true` while the score is `null`. The client then shows "Seeded Destination Selection" instead of a score (RV 6.4).
  - Clients display these values and never compute the rating themselves.

### 5.14 `POST /guest-visits`

Counts one visitor-day (Guest-Identity-and-Visits 4.2). Nothing identifies the guest; the guest tag, name and scope secret never reach this route.

```http
POST /api/v1/guest-visits
Content-Type: application/json

{ "first_visit": true }
```

Response `204 No Content`, `Cache-Control: no-store`.

- **The body is exactly one boolean.** Any other field (name, tag, secret, device id) returns `422 UNKNOWN_FIELD`; a missing `first_visit` returns `422 REQUIRED`.
- **What is stored:** one `HINCRBY` on the Redis hash `abj:{APP_ENV}:visits:{YYYY-MM-DD}` (field `guest_new` or `guest_returning`, TTL 8 days). Finished days are rolled up into `visit_daily_stats` (four integers per day). No server row per visit or per guest exists.
- **Once per Asia/Dhaka day per browser.** The client sends nothing when `abhijatri_last_visit_on` is today. `first_visit` is `true` only when the browser has never been counted.
- **Best effort.** If Redis is slow or down the route still returns `204`; the miss is counted as `visits_dropped` and shown on the ops dashboard. `VISIT_COUNTER_ENABLED=false` stops counting.
- **Limits.** Burst `RATE_LIMIT_GUEST_VISIT` (default `20/minute`), then the durable `GUEST_VISITS_PER_NETWORK_PER_HOUR` (default 60) returning `429 RATE_LIMITED` with `Retry-After`.
- The response carries no number, so traffic volume is not public.

**Client flow** (`frontend/src/api/guests.ts`, `recordDailyVisit`): on every app load, if this browser was not counted today, send `{ "first_visit": <no abhijatri_first_visit_on yet> }`, then store today in `abhijatri_last_visit_on` (and `abhijatri_first_visit_on` the first time).

### 5.15 `GET /review-parameters`

This route returns the review form and the rating rules, so the client renders them from the server and never hard-codes them. `POST /reviews/guest` validates against the same constants (`backend/app/review_parameters.py`). A test fails if the published limits and the validation schema ever disagree. The response is public, with a short TTL.

```json
{
  "version": "2026-10-20",
  "overall_rating": { "required": true, "min": 1, "max": 5 },
  "categories": [
    {
      "code": "CLEANLINESS",
      "name": { "bn": "পরিচ্ছন্নতা", "en": "Cleanliness" },
      "prompt": { "bn": "...", "en": "How clean were the area, stay and toilets?" },
      "required": false, "min": 1, "max": 5
    }
  ],
  "note": { "field": "body", "required": true, "min_length": 20, "max_length": 6000 },
  "title": { "field": "title", "required": true, "min_length": 3, "max_length": 160 },
  "display_name": { "field": "guest_display_name", "required": true, "min_length": 1, "max_length": 80 },
  "traveller_types": [{ "value": "SOLO", "label": { "bn": "একা", "en": "Solo" } }],
  "comfort_tiers": [{ "value": "ECONOMY", "label": { "bn": "সাশ্রয়ী", "en": "Economy" } }],
  "languages": [{ "value": "BN", "label": { "bn": "বাংলা", "en": "Bangla" } }],
  "rating_rules": {
    "guest_feedback": "...", "community_rating": "...", "category_averages": "...",
    "community_prior_mean": 3.5, "community_prior_weight": 5, "community_min_reviews": 5
  }
}
```

**How the rating is calculated** (RV 3.1, A2 and 6):
- A review has one required overall rating from 1 to 5, any of the seven optional category ratings (1 to 5; missing means not applicable), and a required note (`body`).
- **Guest Feedback** is the mean overall rating of published Guest reviews.
- **Community Rating** is the Bayesian `score` over eligible Verified Member reviews (5.12). It is shown only from five reviews.
- **Category averages** are computed per audience and never merged.
- The overall rating is never derived from the category ratings.

### 5.16 Operations API: `/ops/*` (System Monitoring Dashboard)

Private, read-only API for the ops dashboard (`Docs/System-Monitoring-Dashboard.md` 3 to 6).

- **Credential:** `Authorization: Bearer <OPS_DASHBOARD_TOKEN>` only (never a URL, cookie or log). When the variable is unset every `/ops` route is `404`. A wrong or missing token is `401 AUTH_REQUIRED`; after 10 failures per network per hour the network gets `429 RATE_LIMITED`.
- **Caching:** every response is `no-store`. Burst limit 60 requests per minute.
- **Content:** aggregates and system state only. No names, guest tags, secrets, receipts, IP addresses, emails or review bodies.

| Route | Returns |
|---|---|
| `GET /ops/panels` | `{ "panels": [{ id, title {bn,en}, version, refresh_seconds, permission, sources, owner }] }` |
| `GET /ops/panels/{panel_id}?days=7\|30\|90` | One panel (shape below); unknown id is `404` |
| `GET /ops/overview?days=7\|30\|90` | `{ generated_at, days, panels: [...] }`. First rolls up any missing finished day (best effort). |
| `POST /ops/jobs/visit-rollup` | `{ "rolled_up": ["2026-10-21"] }`. Idempotent; `503` when Redis is not reachable. |
| `POST /ops/jobs/rating-reconciliation` | `{ destinations_checked, drifts, clean }`. Detect-only nightly reconciliation (Review.md 6.3); never changes a total; drift alerts superadmins. |

Panel shape (dashboard doc 6.2): `{ id, version, title, status: ok|degraded|unavailable, generated_at, refresh_seconds, sources: [{name, fresh_at}], blocks: [...], notes: [{bn,en}] }`. Block types are `stat` (`value`, optional `limit`, `level`, `hint`), `series` (`points: [{date, value}]`, `null` = no data), `table` (`columns`, `rows`) and `status` (`value`, `level`). A missing number is `null`, never `0`.

Panels: `visitors`, `content`, `reviews`, `traffic`, `health`, `members`.

### 5.17 Authentication: `/auth/*` (R04, implemented 27 October 2026)

All responses are `no-store`. Identity is Supabase Auth, proxied by this API; no body ever contains a token. A write from a browser must carry an allowed `Origin`. Cookie-authenticated writes also need `X-CSRF-Token` from `GET /auth/csrf`.

| Route | Request body | Response |
|---|---|---|
| `POST /auth/register` | `{ email, password, display_name, turnstile_token? }`; password at least 10 characters with a letter and a digit; display name 1 to 80 characters, not reserved | `202 { "status": "verification_sent" }`, identical for new and existing addresses. `409 RESERVED_DISPLAY_NAME`, `422 VALIDATION_FAILED` |
| `POST /auth/verify-email` | `{ token_hash }` from the emailed link | `200 { "status": "verified" }`; no session is created. `422 TOKEN_INVALID_OR_EXPIRED` |
| `POST /auth/resend-verification` | `{ email }` | `202`, identical for any address |
| `POST /auth/login` | `{ email, password }` | `200` session payload (below) and the two cookies. `401 INVALID_CREDENTIALS`, `403 EMAIL_NOT_VERIFIED`, `403 ACCOUNT_DISABLED`, `429` |
| `POST /auth/logout` | none; needs `X-CSRF-Token` | `204`; cookies cleared and the Auth session revoked |
| `POST /auth/password-reset/request` | `{ email, turnstile_token? }` | `202 { "status": "reset_sent" }`, identical for any address |
| `POST /auth/password-reset/confirm` | `{ token_hash, new_password }` | `200 { "status": "password_changed" }`; every session of the account ends. The password is checked before the one-time link is spent |
| `GET /auth/csrf` | none | `{ "csrf_token": "..." }` bound to the session |
| `GET /auth/session` | none | `{ "authenticated": false }` or the session payload. Counts the member's visit day once per Dhaka day |
| `POST /auth/mfa/enroll` | none (CSRF) | `{ factor_id, secret, uri, qr_code }` for an authenticator app |
| `POST /auth/mfa/verify` | `{ factor_id, code }` (6 digits, CSRF) | `{ aal: "aal2", auth_time, csrf_token }` and new cookies |
| `POST /auth/reauth` | `{ password, code? }` (CSRF); `code` required when TOTP is enrolled | `{ aal, auth_time, csrf_token }` and new cookies |

Session payload: `{ authenticated: true, user: { id, email, display_name, email_verified }, role: null | "moderator" | "superadmin", aal: "aal1" | "aal2", mfa_factors: [{ id, type }], auth_time }`. Cookies: `__Host-abhijatri_session` (access token, lifetime of the token) and `__Host-abhijatri_refresh` (30 days), both `HttpOnly`, `Secure`, `SameSite=Lax`, `Path=/`.

### 5.18 Staff API: `/admin/*` (Moderation spec 8, Gantt R10 and R11; implemented 27 October 2026)

Needs a member session that holds an active staff role (`user_roles`, read from the database on every request) and passed TOTP (`aal2`). Everyone else gets `404`; a role that is too low gets `403`. All responses are `no-store`; writes need `X-CSRF-Token`. Decisions accept an `Idempotency-Key` (8 to 100 characters of letters, digits, `-`, `_`): the same key and payload returns the first result, the same key with another payload is `409 IDEMPOTENCY_KEY_REUSED`.

| Route | Who | Body and result |
|---|---|---|
| `GET /admin/queue?task_type=&limit=` | staff | `{ items: [{ id, task_type, subject_id, status, required_role, escalated, claimed_by, lease_expires_at, version, claimable, lease_active, lease_token (holder only), subject }], generated_at }`, oldest and highest priority first. `subject` carries the review or report content. |
| `POST /admin/tasks/{task_id}/claim` | staff | The task with `lease_token`. `409 TASK_NOT_AVAILABLE` while another live lease exists; `403` when escalated above the caller. A lease lasts 5 minutes; an expired one can be taken over. |
| `POST /admin/tasks/{task_id}/heartbeat` and `POST /admin/tasks/{task_id}/release` | holder | `{ lease_token }`. `409 LEASE_LOST` when the lease expired or moved. |
| `POST /admin/tasks/{task_id}/escalate` | holder | `{ lease_token, reason }`. The task now needs a superadmin and the holder's lease ends. |
| `POST /admin/submissions/{review_id}/moderation-actions` | staff | `{ task_id, lease_token, expected_version, decision: PUBLISH\|REJECT\|HIDE\|RESTORE, reason_code, note? }` -> `{ review_id, status, version, counted_rating, task_id }`. Order: role, lease, state and version, action row, audit row, event, one commit. `409 REVIEW_VERSION_CONFLICT`, `409 LEASE_LOST`, `422 TRANSITION_NOT_ALLOWED`, `403 SELF_MODERATION_FORBIDDEN`. |
| `POST /admin/submissions/{review_id}/conflict` | staff | `{ expected_version, conflict_declared, reason_code, note? }` |
| `POST /admin/members/{user_id}/verification/revoke` | staff | `{ reason_code }` -> `{ user_id, verification_id, reviews_uncounted }`. Ends the member's Verified status for abuse and removes every rating they contributed from the destination totals, in one transaction (Review.md 6.3). The reviews stay published. `404` when no active Verified Member record exists (also the answer to a repeat), `403` for your own account. Audited as `verification.revoke_for_abuse`; the member is notified. |
| `POST /admin/ratings/reconcile` | superadmin | `{ repair?: false }` -> `{ destinations_checked, repaired, drifts: [{ destination_id, kind: community\|guest\|category\|review, key, stored, expected, repairable }] }`. Recomputes every destination's totals from the review rows. `repair: false` never changes a total; `repair: true` overwrites drifting totals under row locks with one `ratings.reconcile_repair` audit event each. `review` drifts are reported only. |
| `GET /admin/rating-evidence` | staff | `{ threshold, verified_members: { active, ever_approved }, verification_turnaround_hours: { decisions, median, maximum }, destinations: [{ destination_id, name_en, eligible_reviews, mode: top_rated\|seeded }] }` (Review.md 6.4 semester evidence). |
| `POST /admin/bulk/moderation-actions` | staff | `{ items: [{ review_id, ...decision body }] }` (at most 25). Each item is atomic; the answer lists `{ review_id, ok, result \| error }` per item plus `succeeded` and `failed`. |
| `POST /admin/reports/{report_id}/transition` | staff | `{ to: in_review\|actioned\|dismissed, expected_version, reason_code, note?, task_id, lease_token }`. Allowed: `open` -> `in_review`, `actioned`, `dismissed`; `in_review` -> `actioned`, `dismissed`. Anything else is `422 TRANSITION_NOT_ALLOWED`. |
| `GET /admin/audit-events?action=&target_type=&target_id=&actor_user_id=&before=&limit=` | staff | Newest first, `{ items, next_before }` |
| `GET /admin/audit-events/{event_id}` | staff | One event; `id` is globally unique |
| `GET /admin/staff` | superadmin | Active staff and roles |
| `GET /admin/users?q=` | superadmin | `{ items: [{ user_id, display_name, email, status, role }] }`: accounts whose email contains `q` (3 or more characters, at most 10 rows), to pick someone for a role |
| `POST /admin/staff/{user_id}/role` | superadmin, password confirmed within 10 minutes | `{ role: moderator\|superadmin\|null, reason }`. Serialised on a guard row; `409 LAST_SUPERADMIN` when it would remove the last superadmin; `403 REAUTH_REQUIRED` when the confirmation is old. |
| `GET /admin/monitoring/summary` | staff | `{ queue_depth, oldest_open_task_age_seconds, escalated_open, expired_claims, open_reports, outbox_pending, denied_last_24h, generated_at }` |
| `POST /reviews/{review_id}/reports` | member (CSRF) | `{ reason_code: spam\|offensive\|false_information\|privacy\|conflict_of_interest\|other, details? }` -> `201 { report_id, state, version }`. Only published reviews can be reported (`404` otherwise); `409 DUPLICATE_OPEN_REPORT`; `403` for your own review. |

Denied attempts by staff (`403`) are written to the audit log as `denied.<action>`.

### 5.19 Verification, enforcement, appeals and notifications (implemented 27 October 2026)

Member routes need a session (writes: CSRF). Staff routes follow 5.18 (404 for non-staff, 403 for a lower role, lease and version checks, audit and outbox in one transaction).

| Route | Who | Body and result |
|---|---|---|
| `GET /verifications/mine` | member | `{ verified_member, case: { id, state, version, statement, decision_note, evidence: [{id, status, content_type}] } \| null }` |
| `POST /verifications` | member | `{ statement? }` -> `201` case. `409 VERIFICATION_ALREADY_OPEN`, `409 ALREADY_VERIFIED`, `403 ACCOUNT_RESTRICTED` |
| `POST /verifications/{case_id}/evidence` | applicant | `{ content_type: image/jpeg\|image/png\|application/pdf, size_bytes <= 5 MB }` -> `{ evidence_id, upload_url }`; the browser `PUT`s the file to `upload_url` (one-time, private bucket). At most 3 files |
| `POST /verifications/{case_id}/evidence/{evidence_id}/complete` | applicant | Confirms the file is in Storage -> `{ id, status: "uploaded" }`; `422` if it is not there |
| `POST /verifications/{case_id}/respond` | applicant | `{ statement }` while `needs_clarification` -> back to `in_review` and the queue |
| `POST /verifications/{case_id}/withdraw` | applicant | Withdraws an open case |
| `POST /admin/verification-cases/{case_id}/transition` | staff holding the task | `{ to: in_review\|needs_clarification\|approved\|rejected\|escalated, expected_version, reason_code, note?, task_id, lease_token }`. Approval needs an uploaded file (`422 EVIDENCE_REQUIRED`); a question needs `note`; escalated cases are decided by a superadmin. Nobody decides their own case |
| `POST /admin/verification-cases/{case_id}/evidence/{evidence_id}/url` | the staff member holding the case, or a superadmin | `{ url, expires_in: 60 }`; every view is audited as `evidence.viewed` |
| `GET /admin/enforcement-cases?state=` | staff | Cases with their review or account and sanctions |
| `POST /admin/enforcement-cases` | staff | `{ review_id \| user_id, reason_code, note?, emergency, counts_toward_rating, sanction?: { kind: warning\|posting_restriction\|suspension, ends_at? , review_on? } }` -> `201`. A review is taken down (hidden); an emergency gets a superadmin follow-up within 24 h; a suspension needs a superadmin and disables the account while active |
| `POST /admin/enforcement-cases/{case_id}/actions` | staff (emergency: superadmin) | `{ action: remove\|restore\|close\|reverse_sanction, expected_version, reason_code, note?, counts_toward_rating?, sanction_id? }` |
| `GET /appeals/mine` | member | `{ appeals: [...], appealable: [{ target_type, target_id, label, decided_at, deadline_at, open, appeal_state }] }` |
| `POST /appeals` | member with standing | `{ target_type: moderation_action\|enforcement_case\|verification_case, target_id, reason }` -> `201`. Deadline: end of the 30th day after the decision, Asia/Dhaka (`409 APPEAL_WINDOW_CLOSED`); one appeal per decision (`409 DUPLICATE_APPEAL`, also after a decision; a withdrawn appeal may be filed again) |
| `POST /appeals/{appeal_id}/withdraw` | appellant | While `received` or `in_review` |
| `POST /admin/appeals/{appeal_id}/decision` | staff holding the task, not the original decider | `{ outcome: upheld\|overturned, expected_version, note, task_id, lease_token }`; `403 APPEAL_REVIEWER_NOT_INDEPENDENT`. Overturning restores a hidden review, sends a rejected review back to the queue, grants a rejected verification, or reverses an enforcement and its sanctions. The original decision is kept |
| Notifications | member | Moved to section 5.21 (Notification system v1.1). |

### 5.20 Member reviews with photos and videos (implemented 27 October 2026)

Owner decisions, 27 Oct 2026: any signed-in member (confirmed email) may attach media, not only Verified Members; video follows Review.md amendment A4 **without transcoding**. Guests stay text-only. Member routes need a session and the CSRF token.

| Route | Who | Body and result |
|---|---|---|
| `POST /reviews/member` | member (CSRF), 20/hour | The 5.2 body without `guest_scope_secret`, `guest_display_name` and `turnstile_token`. The author and public name come from the session. `201 { review_id, status, version, duplicate_recovered }`; the same `client_draft_id` and receipt return `200` with `duplicate_recovered: true`. `409 MEMBER_REVIEW_EXISTS` for a second active review of the same destination and visit month |
| `POST /reviews/{review_id}/media-intents` | the author, while the review is `PENDING`, 30/hour | `{ content_type: image/jpeg\|image/png\|image/webp\|video/mp4, size_bytes, alt_text (1-250), caption? (<=300), ownership_declared: true }` -> `201 { media_id, kind, upload_url, max_bytes }`. The browser `PUT`s the file to `upload_url` (one-time, private bucket `review-media`, `quarantine/`). At most 5 images (8 MiB each) and 1 video (50 MiB); field errors `TYPE`, `TOO_LARGE`, `TOO_MANY`. Someone else's review is `404`; after the moderator's decision `422 TRANSITION_NOT_ALLOWED` |
| `POST /reviews/{review_id}/media/{media_id}/complete` | the author | The server reads the object: images must really be JPEG, PNG or WebP of at most 20 megapixels and are re-encoded to WebP (long edge <= 2048 px) with no EXIF/GPS; videos must be MP4 with H.264 video, AAC audio and at most 60 s, and their metadata boxes and extra tracks are blanked in place (no transcoding). `200 { id, kind, state: "pending", content_type, width, height, duration_ms, size_bytes }`. A bad file is deleted and answers `422` with field `file` and code `BROKEN`, `TYPE`, `TOO_MANY_PIXELS`, `TOO_LARGE`, `TOO_LONG`, `VIDEO_CODEC` or `NOT_UPLOADED` |
| `POST /reviews/{review_id}/media/{media_id}/remove` | the author, while `PENDING` | `204`; deletes the objects and frees the place |
| `POST /admin/submissions/{review_id}/media/{media_id}/url` | staff | `{ url, expires_in: 300 }` for the checked copy, to look before deciding |
| `GET /admin/media?state=pending\|approved\|rejected&limit=` | staff | Recent media with `review_id`, `review_status`, `destination_id`, `decided_at` |
| `POST /admin/media/{media_id}/decision` | staff | `{ decision: approve\|reject, reason_code }`: corrects a decision made with the review (`422 TRANSITION_NOT_ALLOWED` for pending or removed media). Audited as `media.approve` / `media.reject` with `from` and `to` |

Moderation: the queue item of a review lists its pending media (`subject.media`). `POST /admin/submissions/{review_id}/moderation-actions` accepts `rejected_media_ids` (PUBLISH only): those are rejected and the rest approved; REJECT rejects all. The decision, the media states and the audit record (`metadata.media`) commit together. The public feed (5.8) adds `author_display_name` for member reviews and `media: [{ id, kind, content_type, url, alt_text, caption, width, height, duration_ms }]` with approved media only; `url` is a signed link valid for one hour. Uploads not completed within 24 hours are purged by the retention job.

### 5.21 Notification system v1.1 (implemented 28 October 2026)

Implements `Docs/Notification-Documentation.md`. Member routes need a session (writes: CSRF). Superadmin routes follow 5.18 (404 for non-staff, 403 for moderators, TOTP) and every write is audited. Responses never contain an email address, subject or message body of an email; deliveries show only a prefix of the address HMAC.

**Member inbox**

| Route | Body and result |
|---|---|
| `GET /notifications?limit=1..50&cursor=&archived=false&unread_only=false` | `{ items: [{ id, kind, category, priority, critical, audience, title {bn,en}, body {bn,en}, link, created_at, read, archived }], next_cursor, unread }`, newest first. `422 INVALID_CURSOR`. Staff notices (`audience: staff`) appear only while the person holds a staff role. |
| `GET /notifications/unread-count` | `{ unread }` (archived items are not counted) |
| `PATCH /notifications/{notification_id}` | `{ read?: bool, archived?: bool }` on your own item only (`404` otherwise; any other field `422`) → the item plus `unread` |
| `POST /notifications/mark-all-read` | `{ unread: 0 }` |
| `GET /notification-preferences` | `{ standard_email_mode: immediate\|digest\|off, digest_timezone, digest_local_time: "HH:MM", always_immediate: ["critical","high"] }`; default `digest`, `Asia/Dhaka`, `08:00` |
| `PUT /notification-preferences` | Same three fields; the zone must be an IANA name. Critical and high-priority notices are always emailed at once and cannot be switched off. |
| `GET /notifications/stream` | Server-Sent Events: `unread` on connect, then `notification` events. Best effort only: the inbox above is the source of truth, and the page refetches after a reconnect. |

**Superadmin monitoring and templates**

| Route | Body and result |
|---|---|
| `GET /admin/notification-deliveries?status=&limit=` | `{ items: [{ id, notification_id, digest_id, kind, channel, status, attempt_count, next_attempt_at, provider, destination_ref, last_error_code, created_at, updated_at }], counts }` |
| `GET /admin/notification-deliveries/{delivery_id}` | The delivery plus `provider_message_id`, `last_error_summary` (redacted) and `attempts: [{ attempt_number, outcome, started_at, finished_at, error_class, error_code, redacted_error_summary }]` |
| `POST /admin/notification-deliveries/{delivery_id}/retry` | `{ reason }`; only `ambiguous` or `failed_permanently` (`422 TRANSITION_NOT_ALLOWED` otherwise). Audited `notification.delivery_retried`. |
| `GET /admin/notification-outbox?status=pending\|processing\|processed\|retry\|dead_letter&limit=` | `{ items: [{ id, event_type, aggregate_type, aggregate_id, status, attempts, next_attempt_at, last_error_code, created_at, processed_at }], counts, oldest_unprocessed_at }` |
| `GET /admin/notification-suppressions?active=true` | Suppressions with an HMAC prefix, never the address |
| `POST /admin/notification-suppressions` | `{ email, channel: "email", reason_code }` → `201`; `422 ALREADY_SUPPRESSED` field code. Audited. |
| `DELETE /admin/notification-suppressions/{suppression_id}` | `{ removal_reason }` → the removed row. Audited. |
| `GET /admin/notification-templates` | Every template key with its allowed variables, audience, live priority/email/enabled and active versions |
| `GET /admin/notification-templates/{template_key}/versions` | All versions of every channel and language |
| `POST /admin/notification-templates/{template_key}/versions` | `{ channel: in_app\|email, locale: bn\|en, subject_template?, title_template?, body_template }` → `201` draft with the next version number. Only the key's allowed `{variables}` (`UNKNOWN_VARIABLE`, `BAD_PLACEHOLDER`). Audited. |
| `POST /admin/notification-templates/{template_key}/versions/{version}/activate` | `{ channel, locale }`: the version becomes active and the previous active one is retired (one active per key/channel/locale; a retired version cannot come back, `422`). Audited. |
| `PATCH /admin/notification-rules/{template_key}` | `{ priority?, email?, enabled? }` for an existing catalogue rule only (`404` otherwise). Audited. |
| `POST /admin/tasks/{task_id}/assign` | Superadmin: `{ user_id: uuid \| null }`. Notifies the assignee (task or appeal assigned) and the previous assignee (unassigned). Audited. |

**Provider webhook (no session; provider authentication instead)**

`POST /webhooks/notifications/{provider}` (`resend` or `brevo`): Resend uses the Svix signature (`svix-id`, `svix-timestamp`, `svix-signature`, secret `RESEND_WEBHOOK_SECRET`); Brevo sends `Authorization: Bearer <BREVO_WEBHOOK_TOKEN>`. A timestamp outside 5 minutes, a wrong signature or a non-JSON body is refused (`403`/`422`) and counted for the anomaly alert; a provider without a configured secret is `404`. Each `(provider, provider_event_id)` is processed once (`{ status: "processed" | "duplicate" }`). Delivered marks the delivery `delivered`; a hard bounce marks it `bounced` and suppresses the address; a complaint suppresses it.

**Behaviour**

- Producers write `outbox_events` in the business transaction (`app/notify/events.py`, unique `dedupe_key`, captured staff recipients and the recipient policy). The worker claims with `FOR UPDATE SKIP LOCKED` and a lease, creates one notification per event, recipient and kind, and retries a failing event with backoff until `dead_letter` (6 tries).
- The catalogue (`app/notify/registry.py`) maps events to the kinds of spec section 3. Staff captured at event time are re-checked against their current role; the person whose role is revoked is still told (as a member notice).
- Email: critical and high-priority items at once, others by preference (immediate, daily digest at the person's local time, or off). The current verified address is read at send time; unverified or suppressed addresses are `skipped`. Retries after about 1 min, 5 min, 30 min and 2 h with jitter, then `failed_permanently`; a timeout is `ambiguous` and never resent automatically; a worker that dies mid-send leaves `ambiguous` (lease reconciliation). Every try has an attempt row.
- Alerts (deduplicated per window, also logged at ERROR): lease expiring (holder), queue overdue (moderators, daily), escalation, repeated denials, delivery failures (5/hour), outbox backlog (older than 10 minutes), webhook anomalies (5/hour).
- Retention: per-row `expires_at` (90 days, critical 24 months); items linked to an open appeal are kept until it closes; processed outbox rows go after 30 days unless still referenced.

### 5.22 Review reporting, moderation actions and the audit log (R11, implemented 1 November 2026)

**Report reasons** (one list, `app/report_reasons.py`): `spam`, `harassment`, `false_information`, `privacy`, `impersonation`, `safety_misinformation`, `copyright`, `conflict_of_interest`, `other`. The older `offensive` is accepted and stored as `harassment`. `removal_request` exists only for the anonymous removal route below. `privacy`, `safety_misinformation` and `conflict_of_interest` reports from a **member** take the review's rating out of the totals while the report is open; the review text stays public (Review.md 5.4, 6.1). Anonymous reports never touch a rating.

| Route | Who | Body and result |
|---|---|---|
| `POST /reviews/{review_id}/reports` | member (CSRF) | `{ reason_code, details? }` (details at most 1000) -> `201 { report_id, state, version }`. `404` unpublished or unknown, `403` your own review or `ACCOUNT_RESTRICTED`, `409 DUPLICATE_OPEN_REPORT`, `422` unknown reason, `429` over 20 reports an hour or 5 for one review a day. Audited `report.create`. |
| `GET /reports/mine?limit=&cursor=` | member | `{ items: [{ id, review_id, reason_code, state, created_at }], next_cursor }`. Only your own; no staff notes or contact. |
| `POST /public/review-reports` | anyone | `{ review_id, reason_code, details?, contact?, turnstile_token }` -> `202 { received: true }`. Origin check, Turnstile, 5 an hour and 20 a day per network. The answer is the same whether or not the review exists, is published, or the visitor already reported it. `contact` is an email or a phone number, optional, staff-only, erased 30 days after the report closes. Audited `report.create_anonymous` (no address, contact or text in the row). |
| `POST /public/removal-requests` | anyone | `{ review_id, statement (10 to 1000), contact (required), turnstile_token }` -> `202 { received: true }`. The author lost the receipt; a moderator checks ownership out of band. Queue priority 2. Audited `removal_request.create`. |
| `POST /admin/reports/{report_id}/hide-pending` | staff | `{ expected_version, reason_code (group hide), counts_toward_rating?: false, task_id, lease_token }` -> `{ report_id, state: in_review, version, case_id, review_status: HIDDEN, review_version, counted_rating }`. Hides a reported review until a decision is recorded, as a takedown case; a moderator's choice, never automatic. `counts_toward_rating: true` keeps the review's counted rating while it is hidden. `422 TRANSITION_NOT_ALLOWED` when the review is not published or the report is closed. Audited `report.hide_pending` and `enforcement.opened`. |
| `POST /admin/reviews/{review_id}/reopen` | superadmin | `{ expected_version, reason_code (group reopen), note? }` -> `{ review_id, status: PENDING, version }`. A rejected review goes back to the queue within 30 days of the rejection; `409 REOPEN_WINDOW_CLOSED` after that or once its text was purged. Audited `review.reopen`; the author is told. |
| `GET /admin/reviews?status=REJECTED\|HIDDEN&limit=&after=` | staff | `{ items: [{ review_id, destination_id, status, version, author, title, overall_rating, counted_rating, decided_at, reason_code, purged, recoverable_until }], next_cursor }`. Newest decision first. A purged review shows `title: "[removed]"` and no deadline. |
| `GET /admin/reason-codes` | staff | `{ groups: { <group>: { strict, reasons: [{ code, bn, en }] } } }`. Groups publish, reject, hide, restore, request_changes, reopen, report_resolution are strict (anything else is `422 VALIDATION_FAILED`, field `reason_code`); enforcement is guidance only. |
| `GET /admin/audit-events` | staff | Filters `action`, `target_type`, `target_id`, `actor_user_id`, `actor_role`, `request_id`, `from` (inclusive), `to` (exclusive), `limit` 1 to 100, `cursor`. `{ items, next_cursor, next_before }`. The cursor is a keyset on time and id, so rows with the same timestamp are never skipped; `next_before` is the older form. |
| `GET /admin/audit-events/actions` | staff | `{ actions: [...], denied_prefix: "denied." }`, every action the log can hold. |
| `GET /admin/audit-events/export` | superadmin | Same filters; CSV of at most 10,000 rows with headers `X-Row-Count` and `X-Truncated`. Cells starting with `= + - @` are neutralised. The export is audited as `audit.exported`. |
| `POST /ops/jobs/retention` | ops token | Idempotent daily sweep: `{ evidence_files, cases, notifications, outbox_events, sanctions_expired, rejected_reviews, report_contacts, abandoned_media }`. Run by `.github/workflows/retention.yml`. |

**Other changes in this release.** A posting restriction or suspension now blocks `POST /reviews/member`, `PATCH /reviews/{id}/pending` (member), the media routes and reporting with `403 ACCOUNT_RESTRICTED`; withdrawing, appeals and reading stay open. A sanction ends when its time passes, on the next request that meets it (audited `sanction.expired`), not only when the retention job runs. A staff member refused for their role is audited as `denied.role` with the route and the role that was needed. A database "data exception" (for example a NUL character in a text field) answers `422 VALIDATION_FAILED` instead of `503`. `POST /admin/enforcement-cases` now defaults `counts_toward_rating` to `false`: a hidden review leaves the rating unless the moderator says otherwise.

## 6. Changes required in the current code

The routes marked "Change required" in Section 4 differ from this contract as follows. Each item is a code defect, not a reason to change this contract.

| Route | Current behaviour | Required | Source |
|---|---|---|---|
| All | ~~`{"detail": ...}` errors and FastAPI's default 422 body~~ Done 19 Oct (WP2): every error uses the Section 2 body, `app/errors.py` | Section 2 format | PF 12.3 |
| All writes | `Idempotency-Key` allowed by CORS but ignored | Section 3 | PF 12.4 |
| `POST /reviews/guest` | ~~Server generates `receipt_token`, returns it, and issues a new one on every duplicate retry~~ Done 19 Oct (WP3): client `receipt_secret`, nothing returned, never reissued, match `200` / mismatch `409`. Order-of-checks steps 3 to 6 (idempotency, Turnstile, counters, limits) pending WP4/WP5 | Client `receipt_secret`, nothing returned, never reissued, Section 5.2 order of checks | PF 13.1 to 13.3, 14.4 |
| `POST /reviews/guest` | ~~No Turnstile; limits keyed on remote address only~~ Done 19 Oct (WP5): server-side Turnstile, durable per-scope and per-network limits, pending ceilings, emergency switch | Turnstile plus Section 7 limits | PF 14.1, 14.3 |
| Receipt and scope digests | ~~One pepper, no `key_id`, no context labels~~ Done 19 Oct (WP3): versioned keyring (`RECEIPT_KEYS`, `RECEIPT_KEY_CURRENT`), labels, `key_id`/`guest_scope_key_id`, unique `(key_id, digest)`, re-digest on use | Keyring with `key_id` and labels | PF 13.4 |
| `POST /review-receipts/exchange` | ~~Legacy name; returns no reason or deadline~~ Removed 19 Oct (WP3); `POST /review-receipts/status` (5.3) added | Remove; add `POST /review-receipts/status` (5.3) | PF Annex A.7, RV 4.2 |
| `POST /reviews/{review_id}/withdraw` | ~~Checks `expected_version` before the already-withdrawn check, so a retry returns 409~~ Done 19 Oct (WP3) | 5.4 | PF 12.4 |
| `GET /destinations/{destination_id}/reviews` | ~~Middleware sets `no-store`~~ Done 19 Oct: `Cache-Control: public, max-age=60` | Short public TTL | Security 7.1 |
| `POST /reviews/guest` | ~~Rejects `category_ratings` as an unknown field~~ Done 20 Oct: accepted, stored per revision, counted on publish, returned in 5.8, 5.12, 5.13 | Accept and store the optional `category_ratings` (5.2) | RV 3.1, amendment A2 |
| `POST /reviews/{review_id}/media-intents` | Absent | Verified Member image upload intent | RV 8, amendment A1 |
| `GET /staff/moderation/reviews` | Returns content (title, body, display name, overall and category ratings) since 20 Oct, but still a bare list capped at 100 without cursor | 5.9 | RV 9.3 |
| `GET /health/ready` | Returns `status` only | Add `build` and `db_revision` | PF 22.1 |
| CORS | ~~`allow_credentials=false`; no `X-CSRF-Token` header~~ Done 27 Oct 2026 (R04): `allow_credentials=true`, `X-CSRF-Token` allowed, origins an explicit list. `Accept-Language` is a CORS-safelisted header already | Section 1.2 | PF 16.1 |
| Client address | ~~Uvicorn runs with `--proxy-headers` and `FORWARDED_ALLOW_IPS` defaulting to `*`~~ Done 19 Oct (WP5): `--no-proxy-headers`; `app/client_address.py` reads only the configured provider-appended entry; the forged-header test on staging is still outstanding (Gate A) | Provider-appended address only | PF 14.2 |

## 7. Rate limits

Limits are configuration values. Starting values (PF 14.3):

| Action | Per credential | Per network digest | Other control |
|---|---|---|---|
| Guest review submission | 3 new drafts per guest scope per 24 h | 30 per hour, 100 per 24 h | Fresh Turnstile token per new draft |
| Guest reports | 10 per guest scope per hour | 60 per hour | Fresh Turnstile token |
| Guest removal requests | 3 per guest scope per 24 h | 20 per 24 h | Fresh Turnstile token |
| Receipt operations | 20 per receipt digest per hour | 100 per hour | Progressive delay after repeated failures |
| Pending guest reviews | 50 per destination, 500 total | n/a | Administrator alert at 80 % |
| Sign-up | n/a | 10 per hour | Fresh Turnstile token |
| Sign-in failures | 5 per email digest per 15 minutes | 100 per hour | Refused with `429` while exhausted; a wrong TOTP code or password in `/auth/reauth` also counts |
| Password-reset and resend requests | 3 per email digest per hour | 30 per hour | Fresh Turnstile token on reset |
| Email-link confirmations | n/a | 30 per hour | The one-time token is single use |

The client address is the provider-appended entry only (PF 14.2). IPv6 is truncated to /64 and stored only as a keyed digest. Public reads and staff routes have independent limits. Hitting a pending ceiling returns `503 GUEST_WRITES_PAUSED` for guest submissions only.

## 8. Enumerations

| Name | Values |
|---|---|
| `ReviewStatus` | `PENDING`, `UNDER_REVIEW`, `CHANGES_REQUESTED`, `PUBLISHED`, `HIDDEN`, `REJECTED`, `WITHDRAWN`, `DELETED` |
| `RatingEligibility` | `NOT_EVALUATED`, `ELIGIBLE`, `INELIGIBLE_GUEST`, `INELIGIBLE_UNVERIFIED`, `INELIGIBLE_DUPLICATE`, `INELIGIBLE_CONFLICT`, `INELIGIBLE_REPORTED`, `INELIGIBLE_REMOVED` |
| `ReviewLanguage` | `BN`, `EN`, `MIXED` |
| `TravellerType` | `SOLO`, `STUDENT`, `COUPLE`, `FAMILY`, `GROUP` |
| `ComfortTier` | `ECONOMY`, `STANDARD`, `PREMIUM` |
| `ReviewCategory` | `CLEANLINESS`, `ACCESSIBILITY`, `HOSPITALITY`, `FOOD`, `TRANSPORT`, `SAFETY_PERCEPTION`, `VALUE` (implemented 20 Oct 2026; also the display order of category averages) |
| `GuideCategory` | `ATTRACTION`, `ACCOMMODATION`, `FOOD`, `TRANSPORT`, `LOCAL_PRACTICE` |
| `AdvisorySeverity` | `INFO`, `CAUTION`, `WARNING`, `CRITICAL` |
| `AdvisoryState` | `CURRENT`, `STALE`, `EXPIRED`, `NOT_YET_EFFECTIVE` (Section 5.13) |
| `ContactKind` | `POLICE`, `TOURIST_POLICE`, `AMBULANCE`, `FIRE`, `HOSPITAL`, `COAST_GUARD`, `FOREST_OFFICE`, `LOCAL_GUIDE`, `OTHER` |
| `SourceType` | `OFFICIAL`, `TEAM_RESEARCH`, `OPEN_LICENCE`, `VENDOR_LICENSED`, `OTHER` |
| Moderation `decision` | `PUBLISH`, `REJECT`, `HIDE`, `RESTORE` |
| Report `reason` | Section 5.7 |
| Platform roles | `MODERATOR`, `ADMINISTRATOR`, `SUPER_ADMINISTRATOR` |

`LOCAL_DRAFT` exists only on the device and is never sent to the API.

## 9. Change process

1. Change the code, run the export script and commit the new `Docs/api/openapi-v1.json`.
2. Update this document in the same pull request. CI fails if an implemented path is missing here.
3. Record breaking or rule-changing changes in `Docs/Decisions.md`.
4. The frontend owner is notified through the pull request.
