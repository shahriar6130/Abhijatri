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
| Member session | Member endpoints | Cookie `__Host-abhijatri_session` (`SameSite=Lax`) plus `X-CSRF-Token` on writes. |
| Staff session | `/staff/*` | Cookie `__Host-abhijatri_staff_session` (`SameSite=Strict`) plus `X-CSRF-Token` on writes. Member sessions never authorise staff routes and staff sessions never authorise member routes. |

Both cookies are host-only on `api.<owned-domain>`, `Secure`, `HttpOnly`, `Path=/`, with no `Domain` attribute (PF 5.3). No receipt cookie exists.

Until the staff authentication adapter lands (R04), staff routes accept the development-only `X-Test-Staff-Id` header when `APP_ENV` is `development` or `test`, and return `501 STAFF_AUTH_NOT_CONFIGURED` in production.

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
| 403 | `FORBIDDEN` | Authenticated but not permitted. |
| 403 | `SELF_MODERATION_FORBIDDEN` | A moderator acts on their own review. |
| 403 | `CSRF_INVALID` | Missing or wrong `X-CSRF-Token`. |
| 403 | `CHALLENGE_FAILED` | Turnstile token missing, expired, reused or invalid. |
| 404 | `NOT_FOUND` | Route, destination or review does not exist. |
| 404 | `RECEIPT_NOT_FOUND` | Receipt does not match the review. Same response as a missing review, so existence is not leaked. |
| 409 | `REVIEW_VERSION_CONFLICT` | `expected_version` is stale. |
| 409 | `INVALID_TRANSITION` | The decision is not allowed from the current state. |
| 409 | `DRAFT_ALREADY_SUBMITTED` | Duplicate draft with a different receipt (Section 5.2). |
| 409 | `RESERVED_DISPLAY_NAME` | Display name is reserved (for example `Admin`, `Moderator`). |
| 409 | `IDEMPOTENCY_KEY_REUSED` | Same `Idempotency-Key` with a different request body. |
| 409 | `DUPLICATE_OPEN_REPORT` | The same scope already has an open report on this review. |
| 409 | `APPEAL_WINDOW_CLOSED` | Appeal sent after the 30-day window. |
| 413 | `PAYLOAD_TOO_LARGE` | Request body exceeds the configured limit. |
| 422 | `VALIDATION_FAILED` | Schema validation failed; see `field_errors`. |
| 422 | `INVALID_CURSOR` | `after` cannot be decoded. |
| 422 | `INVALID_RECEIPT_FORMAT` | Receipt is not `abr1_` plus 43 base64url characters, or is a known weak value. |
| 429 | `RATE_LIMITED` | A limit in Section 7 was hit. `Retry-After` is set. |
| 503 | `GUEST_WRITES_PAUSED` | Pending ceiling reached or emergency switch on (PF 14.3, 14.6). Public reads continue. |
| 500 | `INTERNAL_ERROR` | Unexpected failure. |
| 501 | `STAFF_AUTH_NOT_CONFIGURED` | Staff route in production before R04. |
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
| `GET /auth/csrf` | member or staff session | no-store | Planned (R04) |

`/health` returns `{ "status": "ok" }`. `/health/ready` checks the database and returns `503 SERVICE_UNAVAILABLE` if it is down. It must also report the deployed build and the database migration revision, because the deploy workflow polls it for both (PF 22.1):

```json
{ "status": "ok", "build": "82ecb52", "db_revision": "0002" }
```

### 4.2 Guest reviews and receipts

| Method and path | Credential | Cache | Status |
|---|---|---|---|
| `POST /reviews/guest` | guest scope + receipt + Turnstile | no-store | Change required |
| `POST /review-receipts/status` | receipt | no-store | Planned (R07). Replaces the legacy `POST /review-receipts/exchange`, which is removed in the same change. |
| `POST /reviews/{review_id}/withdraw` | receipt | no-store | Change required |
| `PATCH /reviews/{review_id}/pending` | receipt or owner | no-store | Planned (R07) |
| `POST /review-receipts/appeals` | receipt | no-store | Planned (R07) |

### 4.3 Public reads

| Method and path | Credential | Cache | Status |
|---|---|---|---|
| `GET /destinations/{destination_id}/reviews` | none | Public, short TTL | Change required |
| `GET /destinations` | none | Public, short TTL | Planned (R02) |
| `GET /destinations/{destination_id}` | none | Public, short TTL | Planned (R02) |
| `GET /destinations/{destination_id}/pack/manifest` | none | Public, versioned | Planned (R14) |

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
| `POST /auth/register`, `/auth/verify-email`, `/auth/login`, `/auth/logout`, `/auth/password-reset/request`, `/auth/password-reset/confirm` | none or member | no-store | Planned (R04). Shapes are set by `Features/Identity-Access-Verification.md`. |
| `POST /reviews/member` | member | no-store | Planned (R07) |
| `GET /reviews/{review_id}` | owner or staff | no-store | Planned (R07) |
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

`POST /reviews/{review_id}/media-intents` is listed in RV 9.2 but starts only if the media pipeline is approved (Execution step 10).

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
  "consent_version": "2026-10-01"
}
```

Field rules: `guest_display_name` 1 to 80 characters; `title` 3 to 160; `body` 20 to 6000, plain text; `overall_rating` 1 to 5; `visit_month` is the first day of a month and not in the future in the display time zone. Unknown fields return 422.

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
  "appeal_deadline": "2026-11-17T08:30:00Z"
}
```

`decision_reason` is the public-safe reason code and `appeal_deadline` is 30 days after rejection. Both are `null` unless the review was rejected (RV 4.2). A wrong receipt returns `404 RECEIPT_NOT_FOUND`.

### 5.4 `POST /reviews/{review_id}/withdraw`

```json
{ "receipt_secret": "abr1_...", "expected_version": 2 }
```

Response `200`: the same body as 5.3. Withdrawal removes the review from public view and its rating contribution in one transaction.

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

Response `200`: `{ "review_id": "...", "status": "PENDING", "version": 3 }`. A member owner sends no `receipt_secret` and uses their session instead. Any other state returns `409 INVALID_TRANSITION`.

### 5.6 `POST /review-receipts/appeals`

```json
{ "review_id": "...", "receipt_secret": "abr1_...", "statement": "Plain text, 20 to 2000 characters." }
```

Response `201`: `{ "appeal_id": "...", "status": "OPEN" }`. Only for a `REJECTED` review within its appeal window; otherwise `409 APPEAL_WINDOW_CLOSED`.

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
      "guest_display_name": "Sadia Rahman",
      "status": "PUBLISHED",
      "overall_rating": 4,
      "published_at": "2026-10-15T08:30:00Z",
      "title": "Good family trip",
      "body": "..."
    }
  ],
  "next_cursor": "MjAyNi0xMC0xNVQwODozMDowMCswMDowMHwuLi4",
  "guest_rating_average": 4.0,
  "guest_rating_count": 1
}
```

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

## 6. Changes required in the current code

The routes marked "Change required" in Section 4 differ from this contract as follows. Each item is a code defect, not a reason to change this contract.

| Route | Current behaviour | Required | Source |
|---|---|---|---|
| All | `{"detail": ...}` errors and FastAPI's default 422 body | Section 2 format | PF 12.3 |
| All writes | `Idempotency-Key` allowed by CORS but ignored | Section 3 | PF 12.4 |
| `POST /reviews/guest` | Server generates `receipt_token`, returns it, and issues a new one on every duplicate retry | Client `receipt_secret`, nothing returned, never reissued, Section 5.2 order of checks | PF 13.1 to 13.3, 14.4 |
| `POST /reviews/guest` | No Turnstile; limits keyed on remote address only | Turnstile plus Section 7 limits | PF 14.1, 14.3 |
| Receipt and scope digests | One pepper, no `key_id`, no context labels | Keyring with `key_id` and labels | PF 13.4 |
| `POST /review-receipts/exchange` | Legacy name; returns no reason or deadline | Remove; add `POST /review-receipts/status` (5.3) | PF Annex A.7, RV 4.2 |
| `POST /reviews/{review_id}/withdraw` | Checks `expected_version` before the already-withdrawn check, so a retry returns 409 | 5.4 | PF 12.4 |
| `GET /destinations/{destination_id}/reviews` | Middleware sets `no-store` | Short public TTL | Security 7.1 |
| `GET /staff/moderation/reviews` | Returns only id, status, version, rating; bare list capped at 100 | 5.9 | RV 9.3 |
| `GET /health/ready` | Returns `status` only | Add `build` and `db_revision` | PF 22.1 |
| CORS | `allow_credentials=false`; no `X-CSRF-Token` or `Accept-Language` header | Section 1.2, with the R04 authentication milestone | PF 16.1 |
| Client address | Uvicorn runs with `--proxy-headers` and `FORWARDED_ALLOW_IPS` defaulting to `*` | Provider-appended address only | PF 14.2 |

## 7. Rate limits

Limits are configuration values. Starting values (PF 14.3):

| Action | Per credential | Per network digest | Other control |
|---|---|---|---|
| Guest review submission | 3 new drafts per guest scope per 24 h | 30 per hour, 100 per 24 h | Fresh Turnstile token per new draft |
| Guest reports | 10 per guest scope per hour | 60 per hour | Fresh Turnstile token |
| Guest removal requests | 3 per guest scope per 24 h | 20 per 24 h | Fresh Turnstile token |
| Receipt operations | 20 per receipt digest per hour | 100 per hour | Progressive delay after repeated failures |
| Pending guest reviews | 50 per destination, 500 total | n/a | Administrator alert at 80 % |

The client address is the provider-appended entry only (PF 14.2). IPv6 is truncated to /64 and stored only as a keyed digest. Public reads and staff routes have independent limits. Hitting a pending ceiling returns `503 GUEST_WRITES_PAUSED` for guest submissions only.

## 8. Enumerations

| Name | Values |
|---|---|
| `ReviewStatus` | `PENDING`, `UNDER_REVIEW`, `CHANGES_REQUESTED`, `PUBLISHED`, `HIDDEN`, `REJECTED`, `WITHDRAWN`, `DELETED` |
| `RatingEligibility` | `NOT_EVALUATED`, `ELIGIBLE`, `INELIGIBLE_GUEST`, `INELIGIBLE_UNVERIFIED`, `INELIGIBLE_DUPLICATE`, `INELIGIBLE_CONFLICT`, `INELIGIBLE_REPORTED`, `INELIGIBLE_REMOVED` |
| `ReviewLanguage` | `BN`, `EN`, `MIXED` |
| `TravellerType` | `SOLO`, `STUDENT`, `COUPLE`, `FAMILY`, `GROUP` |
| `ComfortTier` | `ECONOMY`, `STANDARD`, `PREMIUM` |
| Moderation `decision` | `PUBLISH`, `REJECT`, `HIDE`, `RESTORE` |
| Report `reason` | Section 5.7 |
| Platform roles | `MODERATOR`, `ADMINISTRATOR`, `SUPER_ADMINISTRATOR` |

`LOCAL_DRAFT` exists only on the device and is never sent to the API.

## 9. Change process

1. Change the code, run the export script and commit the new `Docs/api/openapi-v1.json`.
2. Update this document in the same pull request. CI fails if an implemented path is missing here.
3. Record breaking or rule-changing changes in `Docs/Decisions.md`.
4. The frontend owner is notified through the pull request.
