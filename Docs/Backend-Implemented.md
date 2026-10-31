# Backend Implementation Record

**Status:** Current as of 20 October 2026 (category ratings and the guest welcome counter added; section 5).
**Scope of this file:** what the backend actually does today, how it was built, and the evidence for each claim. The headline section is **R02**, the destination, advisory and contact data services. The sections after it record the shared backend work that was built alongside R02 because the approved API contract (`Docs/api/API.md`) required it.
**Rule:** this file claims only what the repository contains and a test or migration check demonstrates. Anything not yet built is listed under "Not implemented" and in `Docs/Implemented.md`.
**Related documents:** `Docs/api/API.md` (contract), `Docs/Schema.md` (tables), `Docs/Architecture.md` (environment variables), `Docs/Decisions.md` (decisions and reasons), `Docs/Implemented.md` (project-wide status).

---

## 1. R02: Destination, advisory and contact data services

### 1.1 Task and requirements

| Item | Value |
|---|---|
| Gantt task | R02, "Build destination, advisory and contact data services" |
| Owner | Muhtasim; 5 points; 15 to 21 October 2026 |
| Depends on | F02 (architecture, schema, API contract) and R01 (seeded destination content) |
| Unblocks | R03 (bilingual destination list and detail screens) and R14 (offline destination pack) |

Requirements the implementation answers:

| Source | Requirement | How it is met |
|---|---|---|
| Proposal FR01, O2 | A bilingual destination profile with attractions, accommodation, food, transport, local practices, contacts, coordinates, seasonality and restrictions. | `destinations` profile columns plus `destination_guide_items` and `destination_contacts`; one payload carries Bangla and English for every text field. |
| Proposal, "Advisory freshness" | Every advisory stores source, verification date, effective date and validity date. Current, stale and expired states are shown distinctly. Expired information is never presented as current. | `destination_advisories` columns; `state` computed on read; expired items hidden unless requested. |
| Platform Foundation 17 | Provenance on every maintained record: source type, reference, publisher, effective date, verification date, next review date, language, licence, researcher, reviewer. | A shared provenance mixin on all three content tables. |
| Platform Foundation 11.2 | Advisory validity and seasonal rules use the `Asia/Dhaka` calendar. | `today_in_display_tz()` evaluates every date rule on the Dhaka date. |
| Security 7.1 | Public destination pages are cacheable with a short explicit TTL; everything else is `no-store`. | `Cache-Control: public, max-age=60` plus a weak ETag on the public routes only. |
| Execution.md, row 2 | Provenance, administrative maintenance, bilingual content. | Provenance and bilingual content done; administrative maintenance is deliberately deferred (section 1.10). |

### 1.2 What was delivered

| Deliverable | Location |
|---|---|
| Models, enums, provenance mixin | `backend/app/models.py` |
| Migration | `backend/migrations/versions/0003_destination_content.py` |
| Read services | `backend/app/destination_services.py` |
| HTTP routes | `backend/app/destination_api.py` (included from `backend/app/main.py`) |
| Response schemas | `backend/app/schemas.py` |
| Settings | `backend/app/config.py`, `backend/.env.example` |
| Contract text | `Docs/api/API.md` sections 4.3, 5.12, 5.13 and 8 |
| Schema text | `Docs/Schema.md` |
| OpenAPI snapshot | `Docs/api/openapi-v1.json` |
| Tests | `backend/tests/test_destination_unit.py`, `test_destination_http.py`, `test_destination_postgres.py` |

### 1.3 Endpoints

The contract lists exactly two R02 routes, so exactly two exist. Advisories and contacts are part of the profile payload and have no routes of their own. A request for `/destinations/{id}/advisories` or `/contacts` returns `404`, and a test asserts that.

| Method and path | Purpose | Credential | Cache |
|---|---|---|---|
| `GET /api/v1/destinations` | Paged list of published destinations | none | `public, max-age=60`, weak ETag |
| `GET /api/v1/destinations/{destination_id}` | Full bilingual profile with guide items, advisories, contacts and provenance | none | `public, max-age=60`, weak ETag |

**`GET /destinations`**

| Parameter | Rule |
|---|---|
| `limit` | 1 to 50, default 20 |
| `after` | Opaque cursor, at most 300 characters |

- Only `PUBLISHED` destinations appear. Drafts and archived records are invisible.
- Order is `name_en`, then `id`. The cursor encodes the last `(name_en, id)` pair, so the next page is a tuple comparison in PostgreSQL and is stable when records are added.
- Each item carries: both names, region, summary, coordinates, `community_rating` and `guest_feedback` summaries, `active_advisory_count` and `last_updated`.
- `community_rating.average` is `null` until Verified Member ratings exist; Guest Feedback is a separate object and is never merged into it.
- `active_advisory_count` counts published advisories that are in effect and not expired on the Dhaka date.
- An undecodable cursor returns `422 {"error": {"code": "INVALID_CURSOR", ...}}`.

**`GET /destinations/{destination_id}`**

| Parameter | Rule |
|---|---|
| `include_expired` | Boolean, default `false`. Adds expired advisories, each marked `EXPIRED`. |

The response contains: identity and both-language names; region, summary, seasonality and restrictions in both languages; coordinates; rating summaries; `guide_items`; `advisories`; `contacts`; `content_licence`; `content_verified_on`; `as_of` (the Dhaka date used for all state decisions); `stale_after_days`; and `last_updated`.

- A draft, archived or unknown destination returns the same `404 NOT_FOUND`, so existence is not leaked.
- A malformed identifier returns `422 VALIDATION_FAILED` with a field error.
- `guide_items` are ordered by category, then `sort_order`, then title. `advisories` are ordered most severe first, then by `valid_until`. `contacts` are ordered by kind, then name.
- Only items with `is_published = true` are ever returned.

**Caching behaviour.** A weak ETag is the SHA-256 of the serialised response body. A request with a matching `If-None-Match` receives `304` with no body and the same `Cache-Control` and `ETag`. The ETag changes whenever any returned field changes, including `as_of`, so an advisory that becomes stale or expires at midnight in Dhaka is never served from a cache as still current. Error responses stay `no-store`.

The public review feed `GET /destinations/{destination_id}/reviews` now sends the same short public `Cache-Control` (contract section 6, item B8). Every other route keeps `Cache-Control: no-store`.

### 1.4 Data model (migration `0003_destination_content`)

**Changes to `destinations`.** All new columns are nullable, so the existing seed record, the review slice and the review tests keep working before R01 content exists.

| Column | Type | Notes |
|---|---|---|
| `region_bn`, `region_en` | `varchar(160)` | |
| `summary_bn`, `summary_en` | `text` | |
| `seasonality_bn`, `seasonality_en` | `text` | |
| `restrictions_bn`, `restrictions_en` | `text` | |
| `latitude`, `longitude` | `numeric(9,6)` | Range checks `ck_destination_latitude_range` (-90 to 90) and `ck_destination_longitude_range` (-180 to 180); `ck_destination_coordinates_pair` requires both or neither. |
| `content_licence` | `varchar(160)` | |
| `content_verified_on` | `date` | |

A partial index `ix_destinations_published_name (name_en, id) WHERE status = 'PUBLISHED'` serves the list query.

**New tables.** Each table has a UUID primary key, a foreign key to `destinations` with `ON DELETE CASCADE` (these rows are owned children), an `is_published` flag that defaults to `false`, and an `updated_at` timestamp.

| Table | Content columns | Constraints and indexes |
|---|---|---|
| `destination_guide_items` | `category` (`ATTRACTION`, `ACCOMMODATION`, `FOOD`, `TRANSPORT`, `LOCAL_PRACTICE`), `title_bn/en`, `body_bn/en`, `sort_order` | Index `ix_guide_items_destination_category (destination_id, category, sort_order)` |
| `destination_advisories` | `severity` (`INFO`, `CAUTION`, `WARNING`, `CRITICAL`), `title_bn/en`, `text_bn/en`, `valid_until`, plus `effective_on` from the provenance set | `ck_advisory_validity_window` (`valid_until >= effective_on`); index `ix_advisories_destination_valid_until (destination_id, valid_until)` |
| `destination_contacts` | `kind` (`POLICE`, `TOURIST_POLICE`, `AMBULANCE`, `FIRE`, `HOSPITAL`, `COAST_GUARD`, `FOREST_OFFICE`, `LOCAL_GUIDE`, `OTHER`), `name_bn/en`, `phone`, `address_bn/en`, `latitude`, `longitude` | `ck_contact_phone_format` (`^\+?[0-9][0-9 -]{2,30}$`, so `999` and `+880 341-62000` pass and free text fails); the same coordinate checks as `destinations`; index `ix_contacts_destination_kind` |

**Provenance columns** (the same nine on each content table, from `ProvenanceMixin` in `models.py`):

| Column | Meaning |
|---|---|
| `source_type` | Enum `OFFICIAL`, `TEAM_RESEARCH`, `OPEN_LICENCE`, `VENDOR_LICENSED`, `OTHER` |
| `source_ref` | URL or reference to the source |
| `publisher` | Who published the source |
| `effective_on` | Date the information takes effect |
| `verified_on` | Date a team member last checked it |
| `next_review_on` | Optional date the record must be re-checked |
| `licence` | Licence or permission under which it is republished |
| `researcher`, `reviewer` | Internal names; **never returned by the public API** |

**Row-level security.** Migration `0002` enabled RLS only on the tables that existed when it ran. `0003` therefore enables RLS on its three new tables itself and revokes the Supabase `anon` and `authenticated` grants, using the same pattern. `tests/test_rls.py` fails if any public table lacks RLS.

**Reversibility.** `downgrade()` drops the indexes, tables, check constraints, columns and enum types. The sequence upgrade, `alembic check`, downgrade and upgrade was run clean on PostgreSQL 17.

### 1.5 Advisory freshness logic

`advisory_state()` in `destination_services.py` is a pure function of five dates. `today` is the Dhaka date; it is injectable so every boundary is testable.

| State | Rule | Returned by the profile |
|---|---|---|
| `NOT_YET_EFFECTIVE` | `today < effective_on` | Never |
| `EXPIRED` | `today > valid_until` | Only with `include_expired=true` |
| `STALE` | in effect, but `today - verified_on > ADVISORY_STALE_AFTER_DAYS` | Yes, flagged |
| `CURRENT` | in effect and verified within the threshold | Yes |

Design points:

- **Expired wins over stale.** An old, expired advisory is `EXPIRED`, never `STALE`, so it cannot be mistaken for something merely out of date.
- **The last day is inclusive.** An advisory valid until today is still `CURRENT` today.
- **A future verification date does not make an advisory stale.**
- **The date is the Dhaka date.** At 20:30 UTC on 19 October it is already 20 October in Dhaka, and a test proves the service uses 20 October. Using the UTC date would show an expired advisory as current for six hours each day.
- **State is never stored.** It is derived on every read, so no job has to run for an advisory to expire.
- `as_of` and `stale_after_days` are returned so the client can label advisories and the offline pack can record the evaluation date.

### 1.6 Service layer

`backend/app/destination_services.py` keeps the review code in `services.py` untouched.

| Function | Responsibility |
|---|---|
| `today_in_display_tz(now=None)` | Current date in `DEFAULT_DISPLAY_TIMEZONE` (default `Asia/Dhaka`) |
| `advisory_state(...)` | The classification in section 1.5 |
| `list_published_destinations(session, limit, after, today)` | Page of destinations with ratings and active-advisory counts. Ratings are fetched in one query and advisory counts in one grouped query per page, so there is no per-row query. |
| `get_destination_profile(session, id, include_expired, today)` | Loads the destination, published guide items, advisories (filtered in SQL by `effective_on <= today` and, unless requested, `valid_until >= today`) and contacts; raises `DestinationNotFound` for anything not `PUBLISHED`. |
| `encode_destination_cursor` / `decode_destination_cursor` | Opaque, URL-safe cursor. The last separator splits the value, so a name containing `|` round-trips. Malformed values raise `InvalidCursor`. |

The rating summary reuses `destination_rating_stats`, the same aggregate the review feed uses, with the same average calculation. `last_updated` is the newest `updated_at` among the destination and the rows returned.

### 1.7 API layer

`backend/app/destination_api.py` holds only the two routes and the cache helpers.

- It raises the standard `ApiError` codes (`NOT_FOUND`, `INVALID_CURSOR`); the shared handlers turn them into the contract error body.
- `public_cache_headers()` is reused by the review feed so there is one definition of the public TTL.
- A `304` response carries the cache headers, as HTTP requires.
- Routes are `GET` only. `POST` and `DELETE` return `405 METHOD_NOT_ALLOWED`.

### 1.8 Configuration added

| Variable | Default | Effect |
|---|---|---|
| `ADVISORY_STALE_AFTER_DAYS` | `30` (1 to 365) | Verification age after which an in-effect advisory is `STALE` |
| `PUBLIC_CACHE_MAX_AGE_SECONDS` | `60` (0 to 3600) | `max-age` on the public destination routes and the review feed |

Both are documented in `backend/.env.example` and `Docs/Architecture.md`.

### 1.9 Privacy and safety properties

- No personal data is stored or returned. Contacts are public institutions and emergency numbers; private contacts stay on the device (proposal privacy rule).
- `researcher` and `reviewer` names are internal and not in any response schema.
- Non-published records return the same `404` as missing ones.
- The new tables are unreachable through the Supabase Data API (RLS enabled, no policies).
- Database check constraints reject impossible coordinates, free-text phone numbers and inverted advisory windows even if data is loaded outside the application.

### 1.10 Decisions taken for R02

Recorded in `Docs/Decisions.md` (entry of 19 October 2026).

| Decision | Reason |
|---|---|
| Exactly the two contract routes | The approved contract (section 4.3) lists two. Advisories and contacts travel inside the profile, giving the PWA and the offline pack one fetch. |
| Read-only scope; no staff write endpoints | Staff authentication is still the development header and returns `501` in production. Content is loaded by script or migration until R10 and R11. |
| Both languages in every payload | Offline packs need both, and the client chooses the language (FR02). Content therefore does not vary by `Accept-Language`. |
| Stale threshold of 30 days | A working default. **The team must confirm the value**; Platform Foundation 18.4 uses seven days as the default maximum age for safety-sensitive offline snapshots, which is a related but separate rule. |
| Public caching limited to three routes | Security 7.1 allows an exact route allowlist with a short TTL only. |

### 1.11 Tests and evidence

| File | Type | What it proves |
|---|---|---|
| `tests/test_destination_unit.py` | Unit, no database | State boundaries (last valid day, day after, not yet effective, stale threshold at 30 and 31 days, future verification, expired beats stale); Dhaka date versus UTC date; cursor round-trip and rejection of malformed cursors; ETag stability and sensitivity; `If-None-Match` parsing |
| `tests/test_destination_http.py` | HTTP, stubbed session | `404` and its body for unknown destinations, `no-store` on errors, `422` for bad identifiers and list parameters, no routes for advisories or contacts, read-only methods |
| `tests/test_destination_postgres.py` | Integration, PostgreSQL 17 | List filtering and stable two-page pagination; Bangla text and ratings in list items; advisory counts; draft and archived records return `404`; full profile content, ordering and provenance; researcher and reviewer absent; unpublished items hidden; expired, stale, future and unpublished advisories; severity ordering; destination-scoped contacts; cache headers, ETag and `304` on both routes; ETag changes with content; the review feed has the public TTL while health stays `no-store`; the database rejects bad coordinates, phone numbers and advisory windows |

Verification run on 19 October 2026 against PostgreSQL 17 in a throwaway container:

| Check | Result |
|---|---|
| `ruff check .` | clean |
| `mypy` (strict) | clean |
| `alembic upgrade head`, `alembic check`, downgrade and upgrade again | clean; "No new upgrade operations detected" |
| Full backend suite | 181 passed (the whole backend, including the R02 tests above) |
| Live check with `uvicorn` and `curl` | list returned `200` with `Cache-Control` and `ETag`; matching `If-None-Match` returned `304`; unknown identifier returned `404` |

To reproduce: start PostgreSQL 17, create a database whose name ends in `_test`, set `TEST_DATABASE_URL`, then run `uv run pytest -q` from `backend/`.

### 1.12 Not implemented for R02

| Item | Status |
|---|---|
| Real destination content (five bilingual destinations with sources and licences) | Seeded by `scripts/seed_destinations.py` on 19 October 2026 (section 2.5); R01 content review pending. |
| Frontend use of the endpoints | Done on 19 October 2026 (R03); see `Docs/Frontend-Implemented.md`. |
| Staff create, edit, publish and delete of destination content, translations and advisories | R10 and R11, after real staff authentication. |
| Confirmed advisory staleness threshold | Open decision for the team (section 1.10). |
| `last_updated` using verification dates | It uses row `updated_at` values only. |
| Pack manifest `GET /destinations/{id}/pack/manifest` | R14. |

---

## 2. Shared backend work built alongside R02

These items are not part of the R02 task, but the approved contract required them and R02 routes depend on them. Each is recorded with its evidence.

### 2.1 Standard error contract (contract section 2)

`backend/app/errors.py` is the single source for error bodies: `{"error": {"code", "message", "request_id", "field_errors"}}`.

- One catalogue maps every contract code to its HTTP status, a Bangla message and an English message. Bangla is the default; `Accept-Language` selects English, with quality values honoured.
- Handlers cover domain errors, framework `404` and `405`, validation failures, rate limits (with `Retry-After`), database outages, pool exhaustion, timeouts, oversized bodies and unexpected failures.
- `field_errors` carry only the field path and a stable code (`REQUIRED`, `TOO_SHORT`, `TOO_LARGE`, `INVALID_UUID`, `UNKNOWN_FIELD`, `FUTURE_MONTH` and so on). Submitted values are never echoed, because a rejected request can contain a receipt or Guest secret.
- `X-Request-ID` is a UUID and equals `error.request_id`.
- Evidence: `tests/test_errors.py`.

### 2.2 Client-generated receipts and the keyring (contract sections 5.1 to 5.4)

Migration `0004_receipt_keyring`, `backend/app/crypto.py`, `backend/app/services.py`.

- The client generates the receipt (`abr1_` plus 43 base64url characters). The server checks the exact format, rejects non-canonical and low-entropy values, stores only a keyed digest, and never issues, returns or reissues a receipt.
- Receipt, Guest-scope and network digests are HMAC-SHA-256 under a versioned key ring (`RECEIPT_KEYS`, `RECEIPT_KEY_CURRENT`; the pepper is key `v1` when no ring is set), separated by context labels. Lookups try every retained key; a successful receipt use re-digests under the current key.
- A repeated draft with the same receipt returns `200` and `duplicate_recovered: true`; with a different receipt it returns `409 DRAFT_ALREADY_SUBMITTED` without the review identifier.
- `POST /review-receipts/status` replaces `/review-receipts/exchange` and reports `decision_reason` and `appeal_deadline` for rejected reviews. Withdrawal succeeds on retry even with a stale version.
- Receipts and Guest-scope digests created before the migration are marked `legacy` (receipts revoked); pre-release data only.
- Evidence: `tests/test_receipts.py`.

### 2.3 Abuse controls (contract section 7, Platform Foundation 14)

Migration `0005_rate_limit_buckets`; `app/client_address.py`, `app/abuse.py`, `app/turnstile.py`.

- The client address is read from one configured provider header and position; no other forwarding header is read; IPv6 is reduced to /64; only a keyed digest is stored. Uvicorn runs with `--no-proxy-headers`.
- Durable fixed-window counters commit in their own transaction before the business operation: 3 new drafts per scope per day, 30 per network per hour and 100 per day, 20 receipt operations per receipt per hour and 100 per network per hour.
- Failed receipt lookups feed a two-tier progressive block (5 per 15 minutes, 20 per 24 hours) that answers `429` with `Retry-After` before any lookup.
- Pending ceilings of 50 per destination and 500 total return `503 GUEST_WRITES_PAUSED` for new Guest submissions; a warning is logged from 80 percent. `GUEST_WRITES_PAUSED=true` is the emergency switch; reads, receipt status and recovery of an existing draft continue.
- Turnstile is validated on the server (success, hostname, action, one retry with the same idempotency key; an unreachable Cloudflare returns `503`, never a pass).
- The submission order follows contract section 5.2 except step 3 (`Idempotency-Key` replay).
- Evidence: `tests/test_client_address.py`, `tests/test_turnstile.py`, `tests/test_abuse.py`.

### 2.4 Housekeeping

- The API contract moved to `Docs/api/API.md`. `tests/test_openapi_contract.py` reads it, and references in `Decisions.md`, `Implemented.md`, `Reviews/F02-review.md` and `README.md` were updated.
- `httpx` became a runtime dependency (Turnstile); `uv.lock` was refreshed.

### 2.5 Destination seed content and CORS origin fix (19 October 2026, frontend integration)

| Item | Detail | Evidence |
|---|---|---|
| `scripts/seed_destinations.py` | Loads the five semester destinations from `scripts/destination_seed_content.py`: profile fields, guide items, advisories and contacts with full provenance. Idempotent: a destination is matched by `name_en` (so the `seed_destination.py` smoke record keeps its id and reviews), children are replaced with stable UUIDv5 ids, the rating aggregate row is created if missing and never reset. Refuses production without `--force`. `reviewer` stays empty until the R01 content review. | Two runs on a fresh database reused every id |
| `tests/test_seed_content.py` | Checks the content against the database constraints (lengths, phone format, coordinate ranges, advisory window) and PF 17 provenance, with no database. | 52 passed |
| `Settings.cors_origins` | Strips trailing slashes. Browsers send `Origin` without a path, so `http://localhost:5173/` in `CORS_ALLOWED_ORIGINS` silently blocked every request from the local frontend. | `tests/test_config.py::test_cors_origins_ignore_trailing_slashes` |

Run after migrating: `uv run python scripts/seed_destinations.py`.

Findings for the backend owner, recorded in `Docs/Frontend-Implemented.md` section 6: Guest reviews return `counted_rating` as the rating although API.md 5.10 says `null` (aggregates are correct); `test_unset_environment_fails_closed` depends on `DATABASE_URL` being set in the shell.

---

## 3. Not implemented in the backend

| Area | Contract reference | Planned work |
|---|---|---|
| `Idempotency-Key` replay | section 3 | WP4 |
| Reports and removal requests | 4.4, 5.7 | WP7 (R11) |
| Paged staff moderation queue; `build` and `db_revision` in `/health/ready` | 5.9, 4.1 | WP8 |
| Credentialed CORS, CSRF token endpoint | 1.2, `GET /auth/csrf` | WP9 |
| Registration, sign-in, sessions, staff MFA, verifications, role grants | 4.5, 4.6 | WP10 (R04, R11); needs `Features/Identity-Access-Verification.md` |
| Destination pack manifest | 4.3 | WP11 (R14) |

## 4. Open items that need evidence outside this repository

| Item | Why it is open |
|---|---|
| Forged-header test on the real Render edge | The trusted-address header cannot be proven locally. Production refuses to start without `CLIENT_ADDRESS_HEADER`. Platform Foundation 14.2 requires the result to be recorded in `Architecture.md` (Gate A). |
| Live Turnstile key | Tests use a mocked Cloudflare endpoint. |
| First green CI run on the pull request | All results above are from a local run. |
| Docker image build of the changed `Dockerfile` | Not confirmed locally. |

### 4.1 Incident, 20 October 2026: production tables deleted in Supabase

| Item | Detail |
|---|---|
| What happened | 14 tables were dropped by hand in the Supabase dashboard (guide items, advisories, contacts, rating and category stats, category ratings, receipts, rate-limit buckets, moderation actions, outbox, platform roles, user roles, verifications and `alembic_version`). Left behind: `destinations`, `users`, `reviews`, `review_revisions`, an old-format `guest_visits`, and 16 enum types. |
| Effect | `GET /destinations` returned `503 SERVICE_UNAVAILABLE`, so the review page showed "The service is temporarily unavailable". The PR #17 deploy crash-looped: without `alembic_version`, `alembic upgrade head` restarted at 0001 and failed on the leftover `destination_status` type. |
| Recovery | (1) A one-off script run through `railway run` with the service's own `DATABASE_URL` dropped every remaining table and enum in `public`; the schema itself was kept, so Supabase grants and extensions stayed. (2) Railway redeploy, so `alembic upgrade head` rebuilt 0001→0008. (3) `scripts/seed_destinations.py --force` restored the 5 destinations with their guides, advisories and contacts. |
| Data lost | Test data only: 3 pending guest reviews (their receipts table was already gone) and 3 old-format guest-visit rows. No users existed and no review had been published. |
| Prevention | `Docs/Decisions.md`, "Production schema changes only through Alembic". |

---

## 5. Backend work required after the 20 October 2026 frontend release

**Status:** 5.2 (category ratings) and 5.3 (guest welcome counter) **were implemented on 20 October 2026**; evidence is in 5.8. Everything in 5.4 and 5.5 is still planned and not built. This section was written on 20 October 2026 after PR #14 (commits `abfd084` to `a989755`).
**Why:** that release changed only the frontend and the docs. Review.md amendments A1 to A3 (section 13) and the new landing page needed backend support. **No frontend file was changed by this backend work.** Every response change only adds fields, so the current frontend keeps working. The frontend owner switches on `VITE_REVIEW_CATEGORY_RATINGS=true` and builds the welcome view.

### 5.1 What the frontend already sends or expects

| Frontend feature | File | Backend dependency | Backend state today |
|---|---|---|---|
| Seven category ratings (each 1 to 5 or not applicable) | `frontend/src/components/reviews/CategoryRatings.tsx`, `src/api/reviews.ts` (`REVIEW_CATEGORIES`, `cleanCategoryRatings`) | `category_ratings` in `POST /reviews/guest` (API.md 5.2) | **Implemented 20 Oct** (5.2); the frontend flag can now be turned on |
| Overall rating (required), title, note (`body`) | `GuestReviewForm.tsx` | Existing fields | Done |
| Review language detected from the script | `src/api/reviews.ts:detectReviewLanguage` | Existing `language` field | Done |
| Photo picker for Verified Members; guests locked | `ReviewPhotos.tsx`, `src/utils/reviewPhotos.ts` | `POST /reviews/{id}/media-intents` (amendment A1) | Absent |
| Session card and photo lock | `src/context/SessionContext.tsx` | `GET /auth/session` | Absent; every visitor is a guest |
| Sign-in page (R05) | `src/pages/SignInPage.tsx` | `POST /auth/login` and the other R04 routes | Absent |
| Landing page "Continue as guest" | `src/pages/LandingPage.tsx` | Guest welcome and counter (5.3) | **Backend implemented 20 Oct** (5.3); the frontend has no name input or welcome view yet |

### 5.2 Category ratings: the seven fixed questions (priority 1) — implemented 20 Oct 2026

Source: Review.md 3.1 and amendment A2; API.md 5.2 and section 6 ("Rejects `category_ratings`").

**Categories (enum `review_category`, display order):** `CLEANLINESS`, `ACCESSIBILITY`, `HOSPITALITY`, `FOOD`, `TRANSPORT`, `SAFETY_PERCEPTION`, `VALUE`. Each one is optional. A missing key means not applicable. `overall_rating` stays the only required score.

**Migration `0006_review_category_ratings`**

| Object | Definition |
|---|---|
| Enum | `review_category` with the seven values |
| Table `review_category_ratings` | `revision_id uuid` FK `review_revisions.id ON DELETE CASCADE`; `category review_category`; `rating smallint`; primary key `(revision_id, category)`; check `ck_category_rating_range` (`rating BETWEEN 1 AND 5`) |
| Table `destination_category_stats` | `destination_id` FK `destinations.id ON DELETE CASCADE`; `category`; `audience` (`GUEST` or `COMMUNITY`); `rating_sum int`, `rating_count int` (both non-negative checks); primary key `(destination_id, category, audience)` |
| RLS | Enable on both new tables and revoke the `anon` and `authenticated` grants, the same pattern as `0003` (`tests/test_rls.py`) |
| Downgrade | Drop tables, then enum |

**Code changes**

| File | Change |
|---|---|
| `app/models.py` | `ReviewCategory` enum, `ReviewCategoryRating` and `DestinationCategoryStats` models |
| `app/schemas.py` | `GuestReviewCreate.category_ratings: dict[ReviewCategory, int] \| None = None`, each value 1 to 5, at most 7 keys; an unknown key returns `422 INVALID_VALUE` on `category_ratings.<key>`. Add `category_ratings` to `PublicReview`, and `category_averages: list[{category, average, count}]` to `GuestFeedbackSummary` and `CommunityRatingSummary` |
| `app/services.py` `submit_guest_review` | Insert one `review_category_ratings` row per rated category for the new revision, in the same transaction as the review |
| `app/services.py` `moderate_review`, `withdraw_review`, `set_review_conflict` | Lock the `destination_category_stats` rows with the existing aggregate (`SELECT ... FOR UPDATE`) and apply the per-category deltas in the same transaction as the overall delta: Guest reviews go to `GUEST`, eligible Verified Member reviews to `COMMUNITY` (Review.md 6.1 to 6.3) |
| `app/api.py` `public_reviews` | Return each review's `category_ratings` (one extra query per page, not one per row) |
| `app/destination_services.py` | Add `category_averages` to list and profile rating summaries (one grouped query per page) |
| `scripts/export_openapi.py` | Regenerate `Docs/api/openapi-v1.json` |

**Endpoints affected**

| Endpoint | Change |
|---|---|
| `POST /api/v1/reviews/guest` | Accept and store `category_ratings` |
| `GET /api/v1/destinations/{id}/reviews` | Each item gains `category_ratings` |
| `GET /api/v1/destinations` and `GET /api/v1/destinations/{id}` | `guest_feedback.category_averages` (and `community_rating.category_averages`) |
| `GET /api/v1/staff/moderation/reviews` | Show title, body and category ratings so moderators see the full review (also part of API.md 5.9) |
| `PATCH /api/v1/reviews/{id}/pending` (R07) | A new revision carries its own category rows |

**Tests to add:** schema unit tests (range, unknown key, empty object, 7-key limit); PostgreSQL tests for rows per revision, deltas on publish, hide and withdraw, and no change for pending reviews; an HTTP test that `category_ratings` is accepted; the OpenAPI contract test.
**Frontend switch afterwards:** `VITE_REVIEW_CATEGORY_RATINGS=true` in `frontend/.env` and on Vercel.

### 5.3 Guest welcome and anonymous guest counter (new) — backend implemented 20 Oct 2026 (superseded by 5.11)

**Rule:** a Guest has no account (Review.md 1.1). The name the Guest types on the landing page stays in the browser (`localStorage` key `abhijatri_guest_name`) and is used for the welcome message and to pre-fill the review display name. **The server never receives or stores it.** The server counts distinct guest devices by the keyed digest of the existing `guest_scope_secret` (`src/api/reviews.ts:getGuestScopeSecret`), so a reload keeps the same number and no personal data is stored.

**Migration `0007_guest_visits`**

| Column | Type | Notes |
|---|---|---|
| `scope_hash` | `bytea(32)` primary key | HMAC under the existing keyring with the guest-scope label (`app/crypto.py`, `abuse.scope_key`) |
| `key_id` | `varchar(16)` | Keyring version |
| `guest_number` | `bigint` identity, unique | Shown as "Guest #N" |
| `first_seen_at`, `last_seen_at` | `timestamptz` | For counts per day; no address stored |

RLS enabled, with grants revoked.

**Endpoints**

| Method and path | Request | Response | Credential | Cache | Limits |
|---|---|---|---|---|---|
| `POST /api/v1/guest-visits` | `{ "guest_scope_secret": "<43 to 200 chars>" }` (strict model, no name field) | `200 { "guest_number": 128, "total_guests": 128 }`. It is an upsert: an existing digest returns its old number and updates `last_seen_at` | none (no cookie, no CSRF) | `no-store` | `limiter` plus a durable per-network counter (`abuse.enforce`), e.g. 10 per minute |
| `GET /api/v1/guest-visits/stats` | none | `{ "total_guests": 128, "guests_today": 9 }` | none | `public_cache_headers()` | `60/minute` |

**Frontend afterwards:** a name input on `LandingPage.tsx`; a new `src/api/guests.ts`; `SessionContext` guest variant `{ kind: 'guest'; displayName?: string; guestNumber?: number }`; the sidebar shows "Welcome, <name>, Guest #N"; `GuestReviewForm` pre-fills the display name.
**Docs afterwards:** API.md 4.1 rows and a shape section; Schema.md `guest_visits`; Decisions.md ("guest name local-only; server counts scope digests").
**Tests:** the same secret twice returns the same number; two secrets give consecutive numbers; the request rejects a `name` field (`422 UNKNOWN_FIELD`); the stats route has the public TTL; RLS.

### 5.4 Remaining endpoints from the contract (not built)

| Milestone | Method and path | Purpose | Contract |
|---|---|---|---|
| R04 | `POST /auth/register`, `/auth/verify-email`, `/auth/login`, `/auth/logout`, `/auth/password-reset/request`, `/auth/password-reset/confirm` | Member accounts; needs `auth_identities`, password hashing and a secure HttpOnly session cookie | 4.5 |
| R04 | `GET /auth/session` | Fills `SessionContext` (`member`, `verifiedMember`, `displayName`) | used by the frontend; add to 4.5 |
| R04 | `GET /auth/csrf` | Synchronizer token for cookie writes | 1.2, 4.1 |
| R04 | `POST /verifications` | Member requests Verified Member status; manual approval only, no NID (amendment A3) | 4.5 |
| R07 | `POST /reviews/member` | Account-owned review with the same body plus `category_ratings` | 4.5 |
| R07 | `GET /reviews/{review_id}` | Owner or staff view | 4.5 |
| R07 | `PATCH /reviews/{review_id}/pending` | Edit while `PENDING` or `CHANGES_REQUESTED`; new revision | 4.2, 5.5 |
| R07 | `POST /review-receipts/appeals` | Appeal a rejection within 30 days | 4.2, 5.6 |
| R07 + A1 | `POST /reviews/{review_id}/media-intents` | Verified Member photo upload: presigned POST into quarantine, at most 5 images, JPEG/PNG/WebP, 8 MiB, 20 MP, re-encode, EXIF removed, moderator approval | 4.6 note, Review.md 8 |
| R11 | `POST /reviews/{review_id}/reports`, `POST /public/review-reports`, `POST /public/removal-requests` | Reports and lost-receipt removal | 4.4, 5.7 |
| R11 | `GET /staff/verifications`, `POST /staff/verifications/{id}/decisions` | Verified Member approval queue | 4.6 |
| R11 | `POST /staff/users/{user_id}/roles` | Role assignment (super administrator, recent reauthentication) | 4.6 |
| R14 | `GET /destinations/{id}/pack/manifest` | Offline pack | 4.3 |

### 5.5 Existing endpoints that still need updates (API.md section 6)

| Endpoint | Required change |
|---|---|
| All writes | `Idempotency-Key` replay (WP4, order-of-checks step 3) |
| `GET /health/ready` | Add `build` and `db_revision` |
| `GET /staff/moderation/reviews` | Full 5.9 shape and pagination, not a bare list capped at 100 |
| CORS | `allow_credentials=true`, `X-CSRF-Token` and `Accept-Language` headers (with R04) |
| Staff authentication | Replace the `X-Test-Staff-Id` development header (`app/api.py:require_staff`) with real sessions and MFA (R04, R11) |

### 5.6 Recommended order

1. 5.2 category ratings: unblocks the form the frontend already ships.
2. 5.3 guest welcome and counter: small and independent.
3. R04 authentication and `GET /auth/session`: unblocks sign-in, Member reviews and Verified Members.
4. R07 Member reviews, pending edits, appeals and media intents.
5. R11 reports, verification and roles; R14 pack manifest; the 5.5 updates alongside.

### 5.7 Verification for each step

- `uv run alembic upgrade head`, `alembic check`, then downgrade and upgrade again.
- `uv run ruff check .`, `uv run mypy app`, and `uv run pytest -q` with `TEST_DATABASE_URL` set to a `_test` database.
- `uv run python scripts/export_openapi.py`; `tests/test_openapi_contract.py` passes.
- Frontend: `npm test` and `npm run build`. Then a manual flow:
  - Enable the flag and submit a guest review with three categories (expect `201`).
  - Publish it through the staff route; the destination page shows the category averages.
  - Enter a name on `/`; the sidebar shows the welcome and the guest number, and a reload keeps the same number.
  - Confirm `guest_visits` contains no name.

### 5.8 What was built on 20 October 2026 (5.2 and 5.3)

**Files**

| Area | Files |
|---|---|
| Models | `backend/app/models.py`: `ReviewCategory`, `RatingAudience`, `ReviewCategoryRating`, `DestinationCategoryStats`, `GuestVisit` |
| Migrations | `0006_review_category_ratings` (two enums, two tables, RLS, grants revoked); `0007_guest_visits` (table, identity `guest_number`, RLS, grants revoked) |
| Schemas | `backend/app/schemas.py`: `GuestReviewCreate.category_ratings` (enum keys, 1 to 5, at most 7, `{}` is the same as omitted); `CategoryAverage`; `category_averages` on both rating summaries; `PublicReview.category_ratings`; `ReviewFeed.guest_category_averages`; `ModerationQueueItem`; `GuestVisitRequest`, `GuestVisitResponse`, `GuestVisitStats` |
| Review services | `backend/app/services.py`: rows written in `submit_guest_review`. `_apply_category_delta` runs inside `_remove_counted_rating` and `_add_published_rating`, so publish, reject, hide, restore, withdraw and the conflict flag all move the category aggregate exactly when they move the overall rating. Also `revision_category_ratings`, `category_averages` (one grouped query) and `full_guest_category_recompute` (reconciliation) |
| Guest counter | `backend/app/guest_services.py` (`register_guest_visit`, `guest_visit_stats`); `crypto.GUEST_VISIT_LABEL`; `abuse.guest_visit_checks`; `limits.guest_visit_limit` |
| Routes | `backend/app/api.py`: `POST /guest-visits`, `GET /guest-visits/stats`; the review feed and staff queue return category data. `backend/app/destination_services.py`: list and profile return `category_averages` |
| Configuration | `RATE_LIMIT_GUEST_VISIT` (default `20/minute`), `GUEST_VISITS_PER_NETWORK_PER_HOUR` (default `60`); both in `backend/.env.example` |
| Contract and schema docs | `Docs/api/API.md` 4.1, 5.2, 5.8, 5.9, 5.12, 5.13, new 5.14, sections 6 and 8; `Docs/api/openapi-v1.json` regenerated; `Docs/Schema.md`; `Docs/Decisions.md`; `Docs/Implemented.md` |

**Design points**

- The category aggregate has no code path of its own. It is updated only where the overall rating is counted or uncounted, under the same transaction, with the lock order review → destination aggregate → category rows (sorted). The two aggregates therefore cannot drift.
- Guest and Community category averages are separate (`audience`), as the overall ratings are (Review.md 6.1, 6.2).
- Pending, rejected, hidden and withdrawn reviews contribute nothing.
- The guest's name never reaches the server; `POST /guest-visits` rejects any field except `guest_scope_secret`. The visit digest uses its own HMAC label, so it cannot be linked to the Guest's reviews.

**Frontend handoff (not done here; the frontend was deliberately left unchanged)**

1. Set `VITE_REVIEW_CATEGORY_RATINGS=true` locally and on Vercel.
2. Optionally show `guest_feedback.category_averages`, `guest_category_averages` and each review's `category_ratings`.
3. Welcome flow:
   - The guest enters a name on the landing page and it is saved locally.
   - Call `POST /api/v1/guest-visits` with `getGuestScopeSecret()`.
   - Open the welcome view "Welcome, <name> · Guest #N".
   - On failure, show the name without a number.

**Verification run on 20 October 2026** (PostgreSQL 17 in a throwaway container, CI environment variables)

| Check | Result |
|---|---|
| `ruff check .` | clean |
| `mypy` (strict) | clean |
| `alembic upgrade head`, `alembic check`, `downgrade -2`, `upgrade head`, `downgrade base` | clean; "No new upgrade operations detected" |
| Unit tests (`pytest -m "not integration"`) | 195 passed |
| Integration tests (`pytest -m integration`) | 63 passed, including `tests/test_category_ratings.py`, `tests/test_guest_visits.py`, the updated property test in `tests/test_review_postgres.py` and `tests/test_rls.py` over the new tables |
| Frontend | No file changed. `npm test` was not run because `node_modules` is not installed in this checkout. |

### 5.9 Review parameters and server-side Community score (20 October 2026)

| Item | Detail |
|---|---|
| Single source | `backend/app/review_parameters.py`: the rating range, the seven categories with bilingual names and prompts, note/title/name limits, choice labels, and the Bayesian constants (C = 3.5, m = 5, threshold 5). `GuestReviewCreate` imports these limits. |
| Route | `GET /api/v1/review-parameters` (API.md 5.15), public with a short TTL, `60/minute`. |
| Community score | `community_rating.score` (Bayesian, `null` below five eligible reviews) and `seeded_selection` in the destination list and profile, computed in `destination_services._ratings` with no extra query. |
| Tests | `tests/test_review_parameters.py`: category order and labels; note required with minimum 20; published limits equal to the validation schema (a parity test); the Bayesian score at counts 0, 4, 5 and 10. |
| Run | ruff and mypy clean; 203 unit and 63 integration tests passed on PostgreSQL 17; OpenAPI regenerated. The local end-to-end run is recorded in `Docs/Frontend-Implemented.md` 3c. |

Still blocked in production until Phase B (R04 with staff sign-in): **publishing reviews**, because moderation routes return `501` in production.

### 5.10 Guest footprint reduced to a count (20 October 2026; supersedes the storage design in 5.3)

The scope owner ruled that only the number of guests per day is needed, never who they are (`Docs/Decisions.md`, "Guest footprint is a count only").

| Item | Detail |
|---|---|
| Migration `0008_guest_visits_count_only` | Drops the `0007` table (per-device HMAC digest, key id, number, first/last seen; it held 1 test row) and recreates `guest_visits` with **only** `id` (identity) and `visited_at`, plus index `ix_guest_visits_visited_at`, RLS and revoked grants. The downgrade restores the `0007` shape. |
| `app/guest_services.py` | `record_guest_visit` inserts one row and returns its number. `guest_visit_stats(days)` returns the total, today's count and the per-day series on Asia/Dhaka dates (one grouped query, zero days filled). No hashing, lookups or updates. |
| API | `POST /guest-visits` takes `{}` (any field gives 422) and returns `{visit_number, visits_today}`. `GET /guest-visits/stats?days=1..90` returns `{total_visits, visits_today, daily}`. The burst and durable per-network limits are unchanged. `crypto.GUEST_VISIT_LABEL` was removed. |
| Frontend | `recordDailyVisit()` reports at most once per Dhaka day per browser and keeps the first `visit_number` as "Guest #N" (`abhijatri_guest_number`, `abhijatri_guest_last_visit` in `localStorage`). |
| Tests | `tests/test_guest_visits.py`: the table columns are exactly `{id, visited_at}`; any request field (name, old scope secret, device id) gives 422; each visit adds one row with the next number; a 20:30 UTC visit counts for the next Dhaka day; `daily` fills zero days; the `days` bounds are checked; HTTP shapes; rate limit 429. Frontend: `guests.test.ts`, where the body is exactly `{}`, a browser is counted once per day, and a later day keeps the first number. |
| Run | ruff and mypy clean; `alembic upgrade head`, `check`, `downgrade -1` and `upgrade` clean; backend unit and integration suites green; frontend 29 tests, `tsc` and build clean. |

### 5.11 Guest identity, visit counting and the System Monitoring Dashboard (22 October 2026; supersedes 5.3 and 5.10)

Implements `Docs/Guest-Identity-and-Visits.md` and `Docs/System-Monitoring-Dashboard.md` phase 1. Owner choices of 22 Oct 2026 are in `Docs/Decisions.md`:

- The guest tag is the unique guest identifier; typed names may repeat.
- The guest name is a 30-day session.
- Verified stays 0 until R04.
- The dashboard is a separate `ops/` app.

#### What was built

| Area | Detail |
|---|---|
| Guest tag | `app/guest_tag.py`: `CrockfordBase32(SHA-256("abhijatri:guest-tag:v1\n" + scope secret))[50 bits]`, shown `XXXXX-XXXXX`. The spec test vector gives `1C669-J0TDY` in Python and TypeScript. `submit_guest_review` stores it in `reviews.guest_tag` (no dash). The client cannot send one: `guest_tag` in the body is a `422 UNKNOWN_FIELD`. |
| Review feed | `GET /destinations/{id}/reviews` and the moderation queue return `guest_tag` ("1C669-J0TDY", or `null` for member reviews and older guest reviews). The destination page shows the name, then **"Anonymous guest · 1C669-J0TDY"** (বেনামী অতিথি). |
| Visit counting | `app/visits.py`. `POST /guest-visits` takes exactly `{ "first_visit": bool }` and returns `204` with `no-store`. One `HINCRBY` and `EXPIRE` (8 days) in a single `MULTI` on `abj:{APP_ENV}:visits:{Dhaka date}` (fields `guest_new`, `guest_returning`, `member_new`, `member_returning`). If Redis is down or unset, the route still returns 204, `visits_dropped` goes up, and a warning without request data is logged. `VISIT_COUNTER_ENABLED=false` stops counting. The burst and durable per-network limits are unchanged. `GET /guest-visits/stats` is removed. |
| Metrics | `visits.metrics()` is the one implementation of doc 5: Guest, Verified, New Guest, New Verified, A = total, B = new, Old = A − B. A hypothesis test checks that A − B always equals the returning visits. |
| Roll-up | `visits.rollup()` takes a per-day `SET NX EX 300` lock and upserts the absolute values of each finished day (last 7) into `visit_daily_stats`. Running it twice gives the same row. A missing hash never zeroes a row. Triggered nightly by `.github/workflows/visit-rollup.yml` (00:15 Dhaka) and by every dashboard open. |
| Member visits | `users.first_visit_on` / `last_visit_on` and `visits.record_member_visit()` (the doc 4.3 `UPDATE … RETURNING`). Wired into `GET /auth/session` with R04. |
| Migration `0009_guest_tag_visit_stats` | Adds `reviews.guest_tag char(10)` with `ck_review_guest_tag` (guest reviews only, Crockford pattern). Adds `users.first_visit_on` and `last_visit_on`. Creates `visit_daily_stats` (RLS on, Supabase roles revoked). Copies the old `guest_visits` totals per Dhaka day into `guest_total_legacy`, then drops `guest_visits`. The downgrade reverses it. The revision id stays under Alembic's 32-character limit. |
| Ops API | `app/ops/`, under `/api/v1/ops`. Routes: `GET /panels`, `GET /panels/{id}?days=7\|30\|90`, `GET /overview?days=`, `POST /jobs/visit-rollup`. **Access:** `OPS_DASHBOARD_TOKEN` as `Authorization: Bearer`, compared in constant time. Unset means every route is 404. A wrong token is 401; after 10 failures per network per hour the network gets 429. **Limits:** responses are `no-store`, with a burst limit of 60 per minute. |
| Panels | `visitors`, `content`, `reviews`, `traffic`, `health`, `members` (`app/ops/providers/`). Each runs with a 2-second budget, and one failing panel shows `unavailable` without affecting the others. A missing number is `null`, never 0. Adding a panel takes one new provider file (doc 6.4). |
| Event counters | `app/ops/events.py`: an `EVENT_NAMES` allowlist plus `route_5xx:<route template>`, counted in memory and flushed every `METRICS_FLUSH_SECONDS` to `abj:{env}:events:{date}`. Middleware counts 2xx, 4xx and 5xx, 429, `CHALLENGE_FAILED` and 5xx per route template (never raw paths). |
| Logging | `RedactIdentifiers` in `app/main.py` replaces guest tags and `abr1_` receipts in every log line. |
| Config | Production start-up fails unless `REDIS_URL` is a `rediss://` URL, and when `OPS_DASHBOARD_TOKEN` is set but shorter than 32 characters. CORS allows the `Authorization` header. |
| Frontend | `src/api/guests.ts` changes: <ul><li>WebCrypto `guestTag()`.</li><li>The scope secret is created on the first visit.</li><li>New keys `abhijatri_first_visit_on` and `abhijatri_last_visit_on`.</li><li>The retired `abhijatri_guest_number` and `abhijatri_guest_last_visit` are read once (the browser counts as returning), then removed.</li><li>The 30-day name session uses `abhijatri_guest_name_seen_on`.</li><li>Sign-out forgets the name only.</li><li>"Start as a new guest" makes a new secret, and so a new tag, without resetting the visit dates.</li></ul> Other files: `SessionContext` counts a visit on every app load, with or without a name. The sidebar card and `/guest` show "Welcome, Sadia · Guest 1C669-J0TDY" plus the doc 3.3 notice. If storage is blocked, the tab keeps one tag. |
| Ops app | `ops/`: Vite, React and TypeScript on port 5174. **Login:** a token prompt that keeps the token in `sessionStorage`. **Content:** a generic renderer for the four block types (stat, series with gaps for missing days, table, status), the 7/30/90 selector, per-panel refresh, the "Run roll-up" button and Bangla/English. **Hosting:** `vercel.json` sets `X-Robots-Tag: noindex`, a strict CSP and `no-store`. |
| Local stack | `compose.yaml` gains a `redis` service on `127.0.0.1:6379`. The new variables are documented in `backend/.env.example`, `ops/.env.example` and `render.yaml`. |
| CI | Two additions: a new `ops` job (`npm ci`, build, test), and a check that the public `frontend/dist` contains no ops route or token name. |

#### Verification (22 Oct 2026)

| Check | Result |
|---|---|
| Backend | ruff and mypy clean. 225 unit tests and 76 integration tests passed on PostgreSQL 17. `alembic upgrade head`, `check` (no drift) and `downgrade base` are clean. Three legacy `guest_visits` rows migrated to the correct Dhaka days (`2026-10-19: 1`, `2026-10-20: 2`). OpenAPI snapshot regenerated. |
| Frontend | `tsc`, build and 38 vitest tests pass, including the tag parity vector, the once-per-day flag, the 30-day name, the retired-key migration and sign-out keeping the tag. |
| Ops app | `tsc`, build and 4 tests pass. |
| End to end (real Redis, real Postgres, running API) | 15 of 15 checks passed: <ul><li>Two visits return 204, and an extra field returns 422.</li><li>A guest review stores the server-derived tag.</li><li>After publishing, the destination feed returns `guest_display_name: "Rahim"` and the matching `guest_tag`.</li><li>A wrong ops token returns 401.</li><li>All six panels return `ok`.</li><li>Visitors today shows Guest 2, New Guest 1, A 2, B 1, Old 1, Verified 0.</li><li>No tag, secret or receipt appears in the dashboard output.</li><li>The roll-up route works.</li></ul> Redis held only `abj:development:visits:<date>` (`guest_new 1`, `guest_returning 1`) and the events hash. |

#### Run everything on localhost (no Vercel, no Render)

1. Start Postgres and Redis (from the repository root):
   ```powershell
   docker compose up -d postgres redis
   ```
2. Configure the backend. In `backend/.env` (copy of `.env.example`) set at least:
   ```ini
   APP_ENV=development
   REDIS_URL=redis://localhost:6379/0
   OPS_DASHBOARD_TOKEN=<python -c "import secrets;print(secrets.token_urlsafe(48))">
   CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:5174
   ALLOW_TEST_STAFF_HEADER=true        # only to publish reviews locally with X-Test-Staff-Id
   ```
3. Migrate, seed and start the API:
   ```powershell
   cd backend
   uv run alembic upgrade head
   uv run python scripts/seed_destinations.py
   uv run uvicorn app.main:app --reload            # http://localhost:8000
   ```
4. Start the public app: `cd frontend; npm run dev`, then open http://localhost:5173. The sidebar shows "Guest XXXXX-XXXXX". Write a review from a destination page.
5. Publish the review. Guest reviews are `PENDING` until a moderator publishes them, and staff sign-in waits for R04. Locally, use the development staff header:
   1. Create a user with the `MODERATOR` role in `user_platform_roles`.
   2. Call `POST /api/v1/staff/moderation/reviews/{id}/decisions` with `X-Test-Staff-Id: <that user id>` and `{"expected_version": 1, "decision": "PUBLISH", "reason_code": "OK"}`.

   The destination page then shows "Anonymous guest · XXXXX-XXXXX".
6. Start the dashboard: `cd ops; npm install; npm run dev`, open http://localhost:5174 and paste the `OPS_DASHBOARD_TOKEN`.

#### Deploying: Upstash, Render, Vercel, GitHub

Secrets (the Redis URL and the ops token) go only into the host dashboards or GitHub secrets: never into git, chat or an MCP prompt. Use the MCP route for non-secret steps and status checks, and paste secret values into the web consoles yourself.

**1. Upstash Redis (manual; once per environment)**

1. Sign in at https://console.upstash.com and choose **Redis → Create database**.
2. Fill in the form:
   - Name: `abhijatri-prod`
   - Type: **Regional**
   - Region: **AP-Southeast-1 (Singapore)**, same as the API
   - TLS: on (the default)
3. Open the database and copy the **`rediss://default:<password>@<name>.upstash.io:6379`** URL (Connect → Redis URL). Use a separate database for staging.
4. Check the free-plan command limit in the console (about 100,000 to 150,000 commands a month at 1,000 visitors a day; dashboard doc 8).

**2. Render API (manual)**

1. Open https://dashboard.render.com and select the **abhijatri-api** service, then **Environment**.
2. Add or update these variables:
   - `REDIS_URL` = the Upstash `rediss://…` URL.
   - `OPS_DASHBOARD_TOKEN` = a new value from `python -c "import secrets;print(secrets.token_urlsafe(48))"`. Store it in the password manager of two owners.
   - `CORS_ALLOWED_ORIGINS` = `https://<public-app>.vercel.app,https://<ops-app>.vercel.app`. Add the ops origin after step 4 has created it.
   - `VISIT_COUNTER_ENABLED` = `true`.
3. Click **Save, rebuild and deploy**. The Docker command runs `alembic upgrade head` on start, so migration `0009` is applied automatically. If the service is managed by the Blueprint, **Blueprints → Sync** asks for the new `sync: false` keys from `render.yaml`.
4. Verify:
   - `GET https://<api>/api/v1/health/ready` returns 200.
   - `curl -X POST https://<api>/api/v1/guest-visits -H "Content-Type: application/json" -d '{"first_visit":false}'` returns 204.
   - `curl https://<api>/api/v1/ops/panels -H "Authorization: Bearer <token>"` returns 200.

   If the service does not start, the logs name the missing variable (the production guard).

**2b. Render through MCP (optional)**

1. Create an API key: Render Dashboard → Account Settings → API Keys.
2. Connect Render's hosted MCP server in Claude Code:
   ```powershell
   claude mcp add --transport http render https://mcp.render.com/mcp --header "Authorization: Bearer <RENDER_API_KEY>"
   ```
3. Run `/mcp` to confirm it is connected, then ask, for example: "select my Render workspace", "list services", "show the latest deploy and logs of abhijatri-api", "set VISIT_COUNTER_ENABLED=true on abhijatri-api".
4. Set `REDIS_URL` and `OPS_DASHBOARD_TOKEN` in the dashboard (step 2), not through the chat.

This session had no Render MCP connected, so these steps were written, not run.

**3. Public app on Vercel**

No new variable is needed. Redeploy after merging, because Vite reads `VITE_*` values at build time. The existing `VITE_API_BASE_URL` must point to the Render API.

**4. Ops dashboard on Vercel (manual)**

1. Go to https://vercel.com/new, choose **Import Git Repository**, and pick `shahriar6130/Abhijatri`.
2. Set **Project name** to something unlisted, such as `abhijatri-ops-<random>`, and **Root Directory** to **`ops`**. Vercel detects Vite (build `npm run build`, output `dist`).
3. Under **Environment Variables** add `VITE_API_BASE_URL` = `https://<api>.onrender.com` (no trailing slash).
4. Click **Deploy**, and note the `https://abhijatri-ops-<random>.vercel.app` origin.
5. Tighten the CSP: in `ops/vercel.json`, change `connect-src` from the `*.onrender.com` / `*.up.railway.app` wildcards to the exact API origin, then commit and redeploy.
6. Add the ops origin to the API's `CORS_ALLOWED_ORIGINS` (step 2), then open the dashboard and paste the token.
7. Optional: Project → Settings → **Deployment Protection** → Vercel Authentication, as a second lock in front of the token, if your plan offers it for production.
8. Do not add a link to the ops URL anywhere in the public app (rule R1).

**4b. Vercel through MCP**

1. Connect the Vercel MCP if it is not already connected (it is in this Claude session):
   ```powershell
   claude mcp add --transport http vercel https://mcp.vercel.com
   ```
2. Run `/mcp` and complete the Vercel sign-in.
3. Ask Claude to create a Git-connected project from `shahriar6130/Abhijatri` with root directory `ops`, add the environment variable `VITE_API_BASE_URL=https://<api>`, and deploy production. Behind the scenes this uses the project, environment-variable and deployment tools.
4. Ask for the deployment status and build logs to confirm.

`VITE_API_BASE_URL` is not a secret. The ops token is never stored in Vercel: each person types it into the dashboard.

**5. GitHub (nightly roll-up)**

1. Open Repository → **Settings → Secrets and variables → Actions → New repository secret** and add:
   - `OPS_API_URL` = `https://<api>.onrender.com`
   - `OPS_DASHBOARD_TOKEN` = the same token as on Render.
2. Actions → **Nightly visit roll-up** → **Run workflow** once to test. The job skips itself when the secrets are missing, and it wakes a sleeping free Render instance.

**6. Rotation and the kill switches**

- **Token:** change `OPS_DASHBOARD_TOKEN` on Render and in GitHub, then redeploy. Rotate when a team member leaves and at least each semester.
- **Counting:** `VISIT_COUNTER_ENABLED=false` stops counting without a deploy of code.

#### Known limits

- **Verified numbers:** they are 0 until member sign-in (R04) calls `record_member_visit` from `GET /auth/session`. The dashboard says "member sign-in not built".
- **Range totals:** these are visitor-days, not distinct people (doc 5). A person who browses as a guest and signs in on the same day counts in both.
- **Unflushed event counts:** up to `METRICS_FLUSH_SECONDS` of counts can be lost if a free Render instance sleeps or restarts. Visit counters are written immediately and are not affected.
- **Phase 2:** the token is replaced by staff sign-in with MFA and `ops.read` (dashboard doc 3.2), with R04 and R11.

#### Deployment record (22 Oct 2026)

The live API runs on **Railway**, not Render: project `sincere-warmth`, service `abhijatri-api`, region asia-southeast1. It builds `backend/Dockerfile` from the **`main`** branch, root `./backend`. The Dockerfile start command runs `alembic upgrade head`, so migration `0009` is applied when the new code first deploys.

| Item | State |
|---|---|
| Ops dashboard | Vercel project `abhijatri-ops-44afee` (account `syedmuhtasimapon-8894`), https://abhijatri-ops-44afee.vercel.app. Deployed from `ops/` with the Vercel CLI and not linked to GitHub, so updates are `vercel deploy --prod` from `ops/`. `VITE_API_BASE_URL=https://abhijatri-backend.up.railway.app` is set for Production. The headers `noindex`, CSP and `no-store` were verified live. |
| Railway variables set (no restart) | `OPS_DASHBOARD_TOKEN` (64 characters, generated locally and never printed), `CORS_ALLOWED_ORIGINS=https://abhijatri.vercel.app,https://abhijatri-ops-44afee.vercel.app`, `VISIT_COUNTER_ENABLED=true`. |
| **Blocking before `backend-dev` reaches `main`** | `REDIS_URL` (Upstash `rediss://`) is **not set**. Railway runs `APP_ENV=production`, and the new code refuses to start there without it. Set it first: `railway variable set REDIS_URL --stdin --skip-deploys` from `backend/`, then paste the URL. |
| Public app | Vercel project `abhijatri` (https://abhijatri.vercel.app) belongs to the `choturmatra30` account. Its owner redeploys it after the merge. |
| Nightly roll-up | Add the GitHub secrets `OPS_API_URL=https://abhijatri-backend.up.railway.app` and `OPS_DASHBOARD_TOKEN` (the same token). |


### 5.12 Security audit follow-up (22 October 2026)

The full record is in `Docs/Security-Audit-2026-10-21.md`. In code:
- **F-06 and F-09:** `app/main.py` adds the security headers, including a restrictive API CSP, to every response, including early 413 and 504 errors.
- **F-03:** the config tests are hermetic.
- **Audit §6 tests:** added as `tests/test_audit_additions.py`.
- **F-02 and F-04:** React Router 7.18.4, Vite 8.3.5, Vitest 5.0.5 and plugin-react 6.1.2 in `frontend/` and `ops/`.
- **F-01 guard:** a CI step, `.github/scripts/check_committed_secrets.py`, fails on credential URLs and on binary documents that are not allowlisted.

Still open, owner actions:
- **F-01:** rotate the Supabase password, update Railway `DATABASE_URL`, and remove the audit PDF from `backend-dev` history.
- **F-04 remainder:** the Tailwind 4 migration.
- **F-08:** the `ruff format` team decision.


### 5.13 Verification, ops dashboard completion and deployment (27 October 2026)

**Scope.** A full check of `Guest-Identity-and-Visits.md` and `System-Monitoring-Dashboard.md` against the code, the gaps closed, the local and live setup checked, and the dashboard deployed. Nothing was committed or pushed by the assistant; the owner pushes git.

**Audit result.** Both documents match the code. Static audits (backend, frontend, ops app) found no missing feature; they found the gaps below, all closed.

**Fixes in code**
- **Tests ignored the developer's `.env`.** `.env` enabled the staff test header and set the ops token, so 6 tests failed on a developer machine. `tests/conftest.py` now disables `.env`, defaults `APP_ENV` to `development`, and points the app's own engine at `TEST_DATABASE_URL` when it is set, so tests never touch the dev database.
- **Unhandled errors were not counted as 5xx.** `app/main.py`: the counting middleware now counts a raised exception as a 500 (and `route_5xx:<template>`), then re-raises. Before, the Traffic panel would have missed real failures.
- **`reviews.submitted` was allowlisted but never counted.** `app/api.py` now counts it after a guest review commits.
- **Stale comment** about Redis being deferred in `app/config.py` replaced.
- **Frontend:** the guest review form notice now says the review is shown as "Anonymous guest" and that reviews from one browser share a guest tag (EN and BN); `recordDailyVisit` shares one in-flight request, so React StrictMode or two tabs send one visit.
- **Ops app:** panel layout now comes from `GET /ops/panels` (`getCatalogue`, `orderByCatalogue`); table headers are bilingual.
- **CI:** the public-build check fails if `frontend/dist` is empty and also looks for `abhijatri-ops`.

**Tests added (all green)**
- Backend: 5xx by route template, 60/minute limit, `no-store` on 200/401/404/429, CORS preflight with the `Authorization` header (ops origin allowed, others not), real counts in the content and traffic panels, health panel without secrets, log redaction filter (`test_log_redaction.py`), `reviews.submitted` counted.
- Frontend: overlapping visit calls send one request; the review payload never sends a guest tag.
- Ops app: API client (header only, `sessionStorage` only, error mapping), block rendering in both languages, catalogue ordering.

**Results.** Backend 341 passed, 0 skipped (with `TEST_DATABASE_URL` set to the local `abhijatri_test` database on port 5434); ruff and mypy clean. Frontend 40 tests and build pass. Ops app 19 tests and build pass.

**Local environment.** Postgres and Redis run from `compose.yaml` (`POSTGRES_PORT=5434`). Supabase is used only in production. The development database is at migration `0009_guest_tag_visit_stats`. All six panels returned `ok` on the local API.

**Deployment state (27 October 2026)**
- **Railway** (`sincere-warmth`, service `abhijatri-api`, production): deploy `a337d5c` on `main` is live at `https://abhijatri-backend.up.railway.app`. It has `OPS_DASHBOARD_TOKEN`, `REDIS_URL` and `CORS_ALLOWED_ORIGINS`. The ops routes answer `401` without a token, and the CORS preflight accepts `https://abhijatri-ops-44afee.vercel.app`. **This deploy predates the fixes above; they go live when `backend-dev` is merged to `main`.**
- **Vercel** (account `syedmuhtasimapon-8894`, project `abhijatri-ops-44afee`, root `ops/`): `VITE_API_BASE_URL` set for Production to the Railway address, and `ops/` redeployed to production. The served bundle contains the Railway address and no localhost fallback; the response carries `X-Robots-Tag: noindex, nofollow, noarchive` and the strict CSP. The Vercel MCP connector was first signed in as a different account and was re-authorized as `syedmuhtasimapon-8894`.
- The full test steps are in `Docs/System-Monitoring-Dashboard.md` section 12.

**Open items (owner actions)**
- Merge `backend-dev` to `main` so Railway redeploys the fixes.
- Add the public frontend's Vercel origin to Railway `CORS_ALLOWED_ORIGINS` once it is known.
- Add GitHub secrets `OPS_API_URL` and `OPS_DASHBOARD_TOKEN` for the nightly roll-up workflow.
- Check the live dashboard with the production token (the assistant never reads or prints it).
- Still open from earlier: `visit_daily_stats` counters are nullable everywhere although only legacy days may be `NULL`; no frontend component tests; member visits wait for R04.
Step 3: GitHub secrets for the nightly roll-up

  1. Open the repo on GitHub: https://github.com/shahriar6130/Abhijatri. You
     need admin or owner rights to add secrets. If the repo belongs to your
     teammate, ask them to do this.
  2. Go to Settings → Secrets and variables → Actions → New repository secret.
  3. Add the first secret: Name OPS_API_URL, Secret
     https://abhijatri-backend.up.railway.app (no trailing slash needed). Click
     Add secret.
  4. Add the second secret: Name OPS_DASHBOARD_TOKEN, Secret the same ops token
     that is set on Railway. The Railway and local tokens may differ. Don't
     paste the token into chat or commit it.
  5. Test it: go to Actions → Nightly visit roll-up → Run workflow, pick the
     branch, and run. A green run with "rolled_up" in the log means it works. A
     green run that prints "secrets are not set; skipping" means a secret name
     is wrong, so check the spelling.
  6. After that it runs by itself at 00:15 Dhaka.
**Update, 27 October 2026 (later): live Redis fixed.** The Upstash password saved in Railway `REDIS_URL` was rejected ("invalid username-password pair"), so the Health panel showed Redis down and Visitors and Traffic were degraded. The Upstash MCP server was added (`claude mcp add --scope user upstash https://mcp.upstash.com/mcp`, authorized in `/mcp`), the correct `rediss://` URL for the database `Abhijatri` (`first-monarch-177806.upstash.io`, ap-southeast-1) was tested with a PING, and `REDIS_URL` was set on Railway. After the redeploy (deploy `cd66c42d`, commit `a337d5c`, SUCCESS) all six panels returned `ok`, Redis `up` at 1.9 ms, and the counter flush is running. Visit counters start at 0 on the live site. Two things to remember: the dashboard must be opened at the fixed address `https://abhijatri-ops-44afee.vercel.app` (per-deployment Vercel addresses are not in `CORS_ALLOWED_ORIGINS`), and it needs Railway's `OPS_DASHBOARD_TOKEN`, which differs from the one in `backend/.env`.


### 5.14 Accounts (R04), staff roles and the moderation API (27 October 2026)

Full decisions are in `Docs/Decisions.md` (27 Oct 2026). Supabase Auth is the identity provider, run locally with the Supabase CLI; the API proxies it and keeps the tokens in HttpOnly cookies.

**Built and tested**
- **Member accounts (R04, R05):** `/api/v1/auth/*`: register, verify email, resend, sign in, sign out, password reset, `csrf`, `session` (also counts the member's visit day), TOTP enrol and verify, `reauth`. Same answers for known and unknown addresses; durable throttles for sign-in failures, sign-up, resets and link confirmations; reserved and look-alike display names refused. Code: `backend/app/auth/*`. Public pages: `/login`, `/register`, `/verify-email`, `/forgot-password`, `/reset-password`; `SessionContext` is server-backed; members can report a review.
- **Roles:** `user_roles`, guard row, last-superadmin protection, `python -m app.jobs.bootstrap_admin`. Migration `0010_auth_roles`.
- **Moderation foundation:** append-only `audit_events`, `idempotency_keys` (`0011_audit_idempotency`); `moderation_tasks` with claim leases, `reports`, task and request ids on `moderation_actions` (`0012_tasks_reports`).
- **Staff API `/api/v1/admin/*`:** queue, claim, heartbeat, release, escalate; decisions with version, lease, idempotency key and an atomic audit and outbox row; bulk decisions with per-item results; reports and their transitions; audit listing and lookup; staff list, user search and role changes (password re-confirmation); monitoring summary. Code: `backend/app/admin/*`.
- **Staff dashboard:** new `staff/` app (port 5175): sign-in with TOTP enrolment (QR and secret), queue with live lease countdown and heartbeat, review and report decisions, escalation, audit viewer, staff roles with a re-confirmation dialog, monitoring tiles, English and Bangla.
- **Tests:** backend 410 passing against real PostgreSQL (including simultaneous-claim and last-superadmin races, append-only audit, idempotency replay, stale tab after escalation); frontend 55, staff 22, ops 19. `backend/scripts/e2e_smoke.py` runs about 35 steps against the real local Supabase stack, including real TOTP. The UI was also driven in Chrome: sign-up, verification, sign-in, session survival, sign-out, report, claim, publish, hide, role grant, TOTP enrolment and the QR code.
- **Bugs the tests found and fixed:** a refreshed access token was not used for the follow-up Auth call; the role guard row was missing in a database built from the models, so the race protection did nothing there; the staff app fetched a CSRF token before sign-in; the enrolment QR was not drawable until re-encoded.

**Not built yet (specification phases 3 to 5)**
- Verification cases and evidence storage (a private bucket with short-lived signed URLs), enforcement cases and sanctions, appeals with their independence rule.
- The notification outbox worker, the Resend adapter, daily digests and retention jobs.
- A `moderation` panel on the monitoring dashboard; staff screens for the items above.
- Production sign-in needs the owned same-site domain (PF 5.5).

### 5.15 Verification, enforcement, appeals, notifications and retention (27 October 2026)

**Built and tested** (specification phases 3 to 5):
- **Verification cases** (`app/admin/cases.py`, migration `0013`): request, private evidence upload via signed URL to the Storage bucket `verification-evidence`, staff transitions with the table of spec 7.1, escalation to a superadmin, clarification round trip, approval writes `verifications` (`VERIFIED_MEMBER`, `APPROVED`) and the session reports `verified_member`.
- **Enforcement and sanctions:** review takedowns (emergency path with a 24-hour superadmin follow-up task), removal and restore with a separate `counts_toward_rating`, account cases, warnings, posting restrictions and suspensions (a suspension disables the account), reversal and automatic expiry.
- **Appeals:** standing check, 30-day deadline in Dhaka time, one appeal per decision, independent reviewer, overturn effects for each target type, original decisions preserved.
- **Notifications** (`app/notify/*`, migration `0014`): the shared outbox gained status, lease, retries and errors; an in-process relay (`FOR UPDATE SKIP LOCKED`) fans events out into unique notifications; critical notices emailed at once (Mailpit locally, Resend in production), others in a daily digest; `ambiguous` sends are never resent blindly; live delivery to the browser over Server-Sent Events.
- **Retention** (`python -m app.jobs.retention`): evidence and rejected cases, notifications (90 days, critical 24 months), sanction expiry; open appeals are re-checked under a lock before anything is deleted.
- **Screens:** public app notification bell (live), `/account/verification`, `/account/appeals`, Verified Member badge; staff app queue views and forms for verification, appeals and emergency follow-ups, an Enforcement tab, and new monitoring tiles.
- **Tests:** backend 427 passing on real PostgreSQL; `scripts/e2e_cases.py` against the real local stack (live notification measured at 2.5 s, approval email received, evidence round trip through Storage, independent-reviewer refusal).

**Still open**
- ~~Member review submission itself is Gantt R07 (not built)~~ Built 27 Oct 2026, see 5.16.
- Provider webhooks (bounces, complaints) and their de-duplication: Resend webhooks are not wired yet.
- Production: hosted Supabase Auth settings, `RESEND_API_KEY` and a verified sending domain, the same-site domain for cookies, and migrations `0010` to `0014` on the production database.

### 5.16 Member reviews with photos and video (27 October 2026)

Owner decisions: any signed-in member may attach media (not only Verified Members); video per Review.md A4 **without transcoding**. API in API.md 5.20; decisions in Decisions.md.

**Built and tested**
- `POST /reviews/member` (`app/services.py::submit_member_review`): the review is owned by the account (`author_user_id`), uses the same draft id and receipt recovery as guests, needs the session and CSRF token instead of Turnstile, and allows one active review per member, destination and visit month (`409 MEMBER_REVIEW_EXISTS`).
- Media (`app/media.py`, migration `0016_review_media`, private bucket `review-media`): upload intent → browser PUT to a signed URL → `complete`, where the server reads the real file. Photos: JPEG/PNG/WebP only, at most 8 MiB and 20 megapixels, re-encoded to WebP without EXIF/GPS (Pillow). Video: MP4 with H.264 + AAC, at most 50 MiB and 60 s; metadata boxes and extra tracks are blanked in place. Bad files are deleted at once with a field code (`BROKEN`, `TYPE`, `TOO_LARGE`, `TOO_MANY_PIXELS`, `TOO_LONG`, `VIDEO_CODEC`, `NOT_UPLOADED`).
- Moderation: the queue shows pending media; `rejected_media_ids` on a PUBLISH decision rejects single items; REJECT rejects all; states and the audit record commit with the decision. Staff preview through five-minute links.
- Corrections (added after a photo was rejected by a mis-ticked box): `GET /admin/media` and `POST /admin/media/{media_id}/decision` let staff approve or reject a decided photo or video, audited as `media.approve` / `media.reject`; the staff decision form now shows a ticked "Publish" box per file instead of a "must not be published" box; staff Media tab.
- Public feed: `author_display_name` for member reviews and approved `media` with one-hour signed links. Retention purges uploads not completed within 24 hours.
- Screens: the review form (members post under their account name, choose up to 5 photos and 1 video with description and ownership tick, see upload progress and any refused file on the receipt), a gallery on review cards, and media preview plus per-item rejection in the staff queue.
- Tests: `tests/test_media.py` (17: EXIF/GPS removal, scaling, SVG/GIF/oversized/truncated images, MP4 metadata stripping with unchanged offsets, too long, HEVC, non-MP4, the full submit → upload → moderate → feed flow, upload rules, rejection, abandoned purge). Backend 454 passing; frontend 56 and staff 23 vitest passing; both apps build.

**Still open**
- ~~Migration `0016_review_media` on the online database~~ Applied 27 Oct 2026 (owner approved); a photo and a video were uploaded through online Storage and a GIF posing as JPEG was refused (`TYPE`).
- No video poster image or low-bitrate rendition (no transcoding by decision); approved media of a later hidden or removed review stay stored until the review is deleted.

### 5.17 Notification system v1.1 (28 October 2026)

Implements `Docs/Notification-Documentation.md` in full; its section 14 is ticked with the evidence for each item.

**Built and tested**
- Migration `0017_notification_system`: outbox fields and statuses, notification priority/audience/template/delivery mode/archive/expiry, and the tables `notification_deliveries`, `notification_delivery_attempts`, `notification_provider_events`, `notification_templates`, `notification_rules`, `notification_preferences`, `notification_suppressions`, `notification_digests`. Existing email state and attempt history are carried over (checked on a copy with old rows); RLS on, no browser-role grants.
- `app/notify/`: `registry.py` (catalogue: every spec 3 event), `events.py` (producers, dedupe, captured staff), `messages.py` (resolvers, role re-check, templates), `worker.py` (relay with lease owner, retry, dead letter, start-up defaults), `delivery.py` (deliveries, attempts, retry schedule, suppressions, current verified address, crash reconciliation, per-person digest), `alerts.py` (lease expiring, queue overdue, escalation, repeated denials, failure/backlog/webhook thresholds, deduplicated), `webhooks.py` (Resend and Brevo), `admin_routes.py` (superadmin monitoring, retry, suppressions, templates, rules).
- New events: review decisions carry the decision and author; staff role changes, escalations, assignments (new `POST /admin/tasks/{id}/assign`), password changes (security notice), clarification questions.
- Member API: cursor inbox, unread count, PATCH read/archive, mark-all-read, preferences; SSE kept as a hint.
- Retention: per-row expiry with open-appeal preservation; processed outbox rows after 30 days.
- Ops dashboard: new Notifications panel (independent of the worker); the Members panel now reads `user_roles` and shows sign-in as live.
- Screens: public `/account/notifications` (inbox, filters, archive, email preferences) and a bell that refetches after a reconnect; staff Inbox tab, superadmin Notifications tab (outbox, deliveries with attempts and retry, suppressions, templates and rules), Assign control in the queue.
- Tests: `tests/test_notifications.py` (26) plus updated `test_cases.py`, `test_rls.py` (grants), `test_ops.py`. Backend 481 passing; public app 59 and staff 24 vitest passing; both apps build.

**Still open**
- ~~Apply `0017` online~~ Applied 28 Oct 2026 (owner approved): old rows carried over, RLS on, no browser grants; live check on the online project created a member receipt (email off by preference) and a superadmin staff notice.
- Configure `RESEND_WEBHOOK_SECRET` or `BREVO_WEBHOOK_TOKEN` and point the provider's webhook at `/api/v1/webhooks/notifications/{provider}` once a real email provider is live.

### 5.18 R07: structured review CRUD, ownership and pagination (29 October 2026)

Completes Gantt R07 against `Features/Review.md` 4.2, 5.1, 5.2, 9.2, 9.3 and `Docs/api/API.md` 5.4 to 5.6. Before this entry, create (guest and member), the public feed, guest withdraw and member appeals existed; the rows below were the gaps.

**Built and tested**
- **Edit while unpublished.** `PATCH /reviews/{id}/pending` (`app/services.py::edit_pending_review`, route in `app/api.py`). Allowed only in `PENDING` or `CHANGES_REQUESTED` (`INVALID_TRANSITION` otherwise, `REVIEW_VERSION_CONFLICT` on a stale version). Every content field is optional and omitted fields carry over; a sent `category_ratings` replaces the set and `{}` clears it; `null` and an empty body are refused (422). The edit is a new append-only revision (`sequence + 1`), the old one becomes `SUPERSEDED`, the review returns to `PENDING`, version rises, the moderation task is re-queued and `review.edited` is written to the outbox. Nothing is counted before publication, so no aggregate moves. A changed `visit_month` that collides with the member's one-review-per-destination-and-month index returns `MEMBER_REVIEW_EXISTS`. A guest proves ownership with the receipt (same receipt limits and progressive block as withdraw); a member uses session and CSRF, and another person's review answers `404`.
- **Owner and staff read.** `GET /reviews/{id}` returns the current revision, state, rejection reason, appeal deadline and state, revision history and media states, `no-store`. Moderators also see the guest name, author id and conflict flag; authors see them as `null`. Strangers get `404`, anonymous `401`, and a moderator without TOTP gets `MFA_REQUIRED`, as on the staff routes.
- **Member history.** `GET /reviews/mine` lists the member's own reviews newest first by `(created_at, id)`, with optional `status` and `destination_id` filters, default 20 and maximum 50 per page, and an opaque cursor that carries a listing prefix so a public-feed cursor is refused (`INVALID_CURSOR`). Migration `0018_review_crud` adds the partial index `ix_reviews_member_history`.
- **Member withdraw.** `POST /reviews/{id}/withdraw` accepts a missing `receipt_secret` and then uses session, CSRF and ownership; the idempotent, version-checked `withdraw_review` is shared with the guest path.
- **Guest appeal.** `POST /review-receipts/appeals` (`app/admin/cases.py::create_guest_appeal`): `REJECTED` review only, one appeal per decision (`DUPLICATE_APPEAL`), within the 30-day window (`APPEAL_WINDOW_CLOSED`, which is also the answer when there is nothing to appeal). The appeal joins the normal staff queue and needs an independent reviewer; an overturn returns the review to `PENDING`. `appeals.appellant_user_id` is now nullable (check `ck_appeals_guest_target`) and `appeals.reason` holds 2000 characters. The receipt status gains `appeal_state`.
- **Request changes.** Moderators can decide `REQUEST_CHANGES` (`PENDING`/`UNDER_REVIEW` to `CHANGES_REQUESTED`), so the second editable state is reachable. It is audited (`review.request_changes`), emits `review.state_changed`, notifies the author (`content.changes_requested`, link `/account`) and shows the public-safe reason on the receipt status.
- **Consistency fix.** `rejection_details` used `created_at + 30 days` while appeals used the end of the 30th day in Asia/Dhaka. Both now call `services.appeal_deadline`, so the receipt shows the real deadline.
- Media upload intents are also allowed in `CHANGES_REQUESTED`.
- Migration `0018_review_crud`: enum values `moderation_decision.REQUEST_CHANGES` and `revision_status.SUPERSEDED` (committed outside the transaction), the history index, the nullable appellant, the longer reason. The downgrade removes the guest appeals and restores the old column limits; PostgreSQL cannot drop the two enum values, so they remain defined but unused.
- Tests: `tests/test_review_crud.py` (16 PostgreSQL tests: member and guest edit, validation and credentials, the five refused states, month collision, request-changes round trip, owner/staff/stranger reads, history paging with a timestamp tie, member and guest withdraw, guest appeal through to an overturn, late appeal). Existing `tests/test_receipts.py` now expects `appeal_state`. OpenAPI snapshot regenerated.

**Still open**
- The public and staff screens are not wired (guide: `Docs/Review-Edit-Appeal-UIUX.md`): the account "My reviews" list, the edit form for a pending review, the guest appeal form on the receipt page, and a moderator "Request changes" button in the staff queue. The API for all of them is ready.
- Published reviews are still not editable (Review.md 5.2: withdraw and submit again until v1.1).
- `Idempotency-Key` replay on the new writes is part of WP4.
- ~~Apply `0018` online~~ Applied 29 Oct 2026 (owner approved) to the Supabase project `Abhijatri`: `alembic_version` is `0018_review_crud`, both enum values, the history index, the nullable appellant, the 2000-character reason and `ck_appeals_guest_target` verified by query; RLS on `appeals` unchanged; no new security advisor finding. The Railway API still has to be redeployed to serve the new routes.
- Frontend build brief, automated tests, manual cases and sign-off checklist: `Docs/Review-Edit-Appeal-UIUX.md`.



### 5.19 Notification and moderation check, merge repair and the complete workflow (30 October 2026)

Source: `Docs/Reviews/Notification-Moderation-Implementation-Check.md` (review of the notification and moderation specifications against the code; reported 291 passing and 4 failing backend tests).

**Findings and fixes**
- The four failing tests (`test_config.py::test_production_accepts_valid_configuration`, `test_production_accepts_a_long_ops_token`, `test_unset_environment_fails_closed`, `test_smtp_provider.py::test_production_requires_the_smtp_password`) failed because the production fixtures had no TLS `REDIS_URL`, which production settings require (`app/config.py`). The fixtures in the repaired `tests/test_config.py` supply `rediss://...` and a hermetic environment fixture removes any ambient variable, so the SMTP test now reaches its own rule.
- **A more serious fault was found while checking: unresolved merge-conflict markers were committed to `main`** (commit `82ba53b`, "Resolve merge conflicts", which reached `main` through the merge of 29 October). `backend/app/main.py` (two hunks) and `backend/tests/test_config.py` contained `<<<<<<< Updated upstream` blocks, so the API could not be imported and the test file could not be collected. Repaired by keeping the "Updated upstream" side in both files; in `test_config.py` that side is identical to the clean file on `origin/backend-dev`. A search of the repository finds no other marker.
- The earlier rate-limit purge fix (`app/abuse.py`, 29 October) is retained.
- No behaviour of the notification or moderation code was changed.

**Evidence (30 October 2026, PostgreSQL 17 container)**
- Backend: 502 passed, 1 skipped; ruff and strict mypy clean.
- Public app 64, staff app 24, ops app 19 Vitest tests pass; all three apps build.
- Not run: the live end-to-end scripts (`scripts/e2e_smoke.py`, `scripts/e2e_cases.py`). They need the local Supabase stack, Redis and Mailpit, and the current `backend/.env` points at the online project, so running them would create accounts in the production database. Browser (Chrome) checks of the staff and public screens need a signed-in session on a working stack and were also not run.

**The complete workflow (as the code and tests behave)**

1. *Submission.* A Guest (`POST /reviews/guest`, receipt generated by the client) or a signed-in member (`POST /reviews/member`) creates a `PENDING` review with a first revision. In the same transaction the service writes the review, its receipt digest, category ratings, a `review.submitted` outbox event and a `review_moderation` task (`app/services.py::_add_content`, `app/admin/tasks.py::ensure_task`).
2. *Queue.* Moderators and superadmins see open tasks in `GET /admin/queue`. A task is claimed with `POST /admin/tasks/{id}/claim`, which returns a lease token valid for 300 seconds (`LEASE_SECONDS`); `heartbeat` extends it, `release` frees it, `assign` and `escalate` move it. An expired lease can be taken over and the old holder gets `LEASE_LOST`.
3. *Decision.* `POST /admin/submissions/{id}/moderation-actions` needs the task id, the lease token and the review's `expected_version`. Allowed moves (`services.moderate_review`): `PENDING`/`UNDER_REVIEW` to `PUBLISHED` (counts the rating once and moves the Guest or Community aggregate, per category too), `REJECTED`, or `CHANGES_REQUESTED` (`REQUEST_CHANGES`, no rating change); `PUBLISHED` to `HIDDEN` (rating removed); `HIDDEN` to `PUBLISHED` (`RESTORE`). A moderator cannot act on their own review (`SELF_MODERATION_FORBIDDEN`). Each decision writes a `moderation_actions` row, an audit event (`review.<decision>`), media decisions for the same review, and a `review.state_changed` outbox event, all in one transaction. A stale version returns `REVIEW_VERSION_CONFLICT`; an impossible move returns `TRANSITION_NOT_ALLOWED`; `Idempotency-Key` replays the stored answer.
4. *Author response (R07, 5.18).* While `PENDING` or `CHANGES_REQUESTED` the author edits (`PATCH /reviews/{id}/pending`: a new revision, the review returns to `PENDING`, the task is re-queued) or withdraws (`POST /reviews/{id}/withdraw`, guest by receipt, member by session). A `REJECTED` or `HIDDEN` review can be appealed: members through `POST /appeals`, Guests (rejections only) through `POST /review-receipts/appeals`; one appeal per decision, within the end of the 30th day in Asia/Dhaka.
5. *Appeals.* An appeal creates an `appeal` task (priority 1) and an `appeal.received` event. A staff member other than the original decider claims it and decides `upheld` or `overturned` (`POST /admin/appeals/{id}/decision`); an overturned rejection returns the review to `PENDING` (a fresh independent review) and an overturned hide restores it. The decision writes an audit event and `appeal.decided`.
6. *Verification, enforcement and sanctions.* Members file a verification case with evidence (`/verifications`, files in private storage, erased within 24 hours of a decision); staff move it through its transition table. Enforcement cases (takedown, removal, restore) and sanctions (warning, posting restriction, suspension) follow their own tables, each audited and each emitting events.
7. *Outbox relay.* `app/notify/worker.py` claims due outbox events with `FOR UPDATE SKIP LOCKED` and a lease, and in one short transaction turns each into notifications by the rules in `app/notify/registry.py` (`ON CONFLICT DO NOTHING` on event, recipient and kind, so reprocessing never duplicates). A failed event is retried with backoff and after 6 tries becomes `dead_letter`, visible to superadmins and the ops dashboard. Staff recipients are re-checked against current roles when the notification is created; a Guest appeal has no recipient because a Guest has no account.
8. *Inbox and email.* Members read the inbox (`GET /notifications`, unread count, mark read or archive, mark all read, live hint over SSE) and set email preferences (immediate, daily digest, off; critical notices are always emailed). Each email is a delivery row with an attempt history; transient failures retry after 60 s, 5 min, 30 min and 2 h (`RETRY_DELAYS`), then fail permanently; an ambiguous send is never repeated blindly. Provider webhooks (bounces, complaints) are verified and add suppressions. Digests are built per person at their local time.
9. *Retention.* `python -m app.jobs.retention` purges notifications after 90 days (critical after 24 months, open appeals kept), processed outbox rows after 30 days, expired evidence and rejected cases, and old rate-limit buckets.
10. *Monitoring.* The ops dashboard (token protected) shows the queue, outbox backlog, dead letters and delivery failures; the notification alert thresholds (`notification.delivery_failure_threshold_reached`, `outbox_backlog_threshold_reached`, `provider_webhook_anomaly`) reach superadmins.

**Test map** (PostgreSQL integration unless noted): intake, queue, leases, decisions, idempotency, reports and the audit log: `tests/test_admin.py`; verification, enforcement, appeals, retention and notification triggers: `tests/test_cases.py`; relay, inbox, preferences, email retries, digests, webhooks, alerts and catalogue consistency: `tests/test_notifications.py`; R07 edit, history, withdraw, guest appeal and request changes: `tests/test_review_crud.py`; configuration rules: `tests/test_config.py`, `tests/test_smtp_provider.py` (unit).

**Still open**
- Run `scripts/e2e_smoke.py` and `scripts/e2e_cases.py` against the local stack (not against the online project) and record the result; do the same Chrome walk-through of the staff queue and the member inbox.
- Staff app: add the "Ask for changes" decision (`Docs/Review-Edit-Appeal-UIUX.md` section 7).
- Add a CI check that fails on conflict markers (for example `git grep -n -E '^(<<<<<<<|>>>>>>>) '`), so a half-resolved merge cannot reach `main` again.


### 5.20 Access control, notification latency and deploy on push: answers and evidence (30 October 2026)

Questions from the project owner, answered from the code and from a live run against the online Supabase project (API on this machine, signed-in superadmin in Chrome, test data withdrawn or rejected, nothing published).

**1. How is URL access controlled? From the database? What if the staff URL leaks?**
- **The URL is not the protection.** The staff app (`staff/`) is a static page that holds no data and no secret. Anyone may open it; they see a sign-in form. All authority is on the API, per request, and the browser's routes are only a convenience (Architecture.md 7, Security.md).
- **Yes, from the database.** Every `/api/v1/admin/*` request goes through `staff_principal` (`app/auth/sessions.py`): the signed token proves *who* (Supabase Auth), and the role is read from `user_roles` in the database on that request (`active_role`). A revoked role stops working at once, with no redeploy.
- **What a stranger gets:** no session gives `401 AUTH_REQUIRED`; a signed-in member without a staff role gets `404` (the route's existence is not disclosed); a staff member with the wrong role gets `403`; staff without TOTP (AAL2) get `MFA_REQUIRED`; writes also need the CSRF token and an allowed `Origin`. Superadmin sessions expire after inactivity and role changes need a recent password check. Every denial is audited.
- **Evidence (online run):** `/admin/queue`, `/admin/audit-events`, `/admin/notification-outbox`, `/admin/staff`, `/reviews/mine`, `/reviews/{id}`, `/appeals/mine`, `/notifications`, `/ops/overview` and a staff task claim all answered `401 AUTH_REQUIRED` without a session. Unit tests: `tests/test_admin.py` (members get 404, staff without TOTP refused, last superadmin protected), run on every push in CI.
- **Ops dashboard** is separate: a bearer token, read-only panels. The public build is checked in CI to contain no staff or ops code (`/api/v1/admin`, `/api/v1/ops`, token names).
- **Development only:** `ALLOW_TEST_STAFF_HEADER` exists for tests; the production configuration guard refuses it (`STAFF_AUTH_NOT_CONFIGURED`).

**2. Do notifications, the moderation dashboard and the queue work without delay?**
- **Server:** a new review and its moderation task are written in one transaction, so the queue holds it the moment it is committed (online run: visible on the first queue read). The outbox relay runs inside the API and polls every 2 s (`NOTIFY_POLL_SECONDS`); five recent online events were processed on the first attempt 0.5 to 2.4 s after creation. Member browsers get a stream that checks every 2 s, so a notice reaches an open page in about 4 s at most. Email retries after 1 min, 5 min, 30 min and 2 h; after 6 failed relays an event becomes a visible dead letter.
- **Defect found and fixed:** the staff queue refreshed only every 30 s and the staff inbox every 30 s, so a moderator's screen could be 30 s behind. Now the queue refreshes every 5 s and the inbox every 10 s while the tab is visible, and immediately when the tab or window is focused (`keepFresh` in `staff/src/logic.ts`, unit-tested with fake timers).
- **Speed from a developer machine:** against the online database the local API is slower (0.7 to 2 s for a list, 2 to 7 s for a moderator decision) because each of its many queries pays the 54 to 78 ms internet round trip; the deployed API next to the database answers in 0.28 s. One guest create from this machine hit the 15 s request limit (`504`) yet was created; a retry with the same draft id returns the existing review (that is what the permanent draft id is for).

**3. Does it keep working after every `git push`?**
- **CI** runs on every pull request and every push to `main`: lint, strict types, unit tests, migrations apply and match the models, PostgreSQL integration tests, dependency audit, secret scan, Docker image, and the three front-end builds and tests. The latest run on `main` (merge #30, 30 Oct) is green.
- **Deploy:** each push to `main` creates a production deployment on Railway (`sincere-warmth / production`); the latest, 30 Oct 09:10 UTC, succeeded 31 s after the push. The container runs `alembic upgrade head` before starting, so schema changes apply on their own; migration 0018 is already on the online database, so that step is a no-op. The `/api/v1/health` check gates the switch: the broken merge of 29 Oct failed its deploy and the previous version kept serving.
- **Not done by choice:** the front-ends (public, staff, ops) are not deployed to Vercel for this phase; the staff dashboard runs locally against the real database.
- **Recommendation:** in the Railway service settings turn on "wait for CI" so a push whose CI fails is never deployed (a deployment was created for the broken 29 Oct commit even though CI was red; only its health check stopped it).

**Evidence of the review author controls online:** guest round trip (edit, Ask for changes, edit, Reject) ended at version 5 with both decisions in the audit log; member paging with a page size of 1, cursor rules, filters, edit, stale edit, cleared categories, self-moderation refused, withdraw and its retry, edit after withdraw refused. Full list: `Docs/Review-Frontend-Manual-Test-Cases.docx` section 3a.

**Author names on published reviews (30 Oct 2026).** An older account had its sign-in email as its display name, and the public review feed showed it. `public_author_name` (`app/auth/validation.py`) now withholds any name containing `@` (the page shows "Member"), and sign-up refuses such a name with `VALIDATION_FAILED` on `display_name` (`INVALID_VALUE`); the sign-up form says so in English and Bangla. Staff screens still show emails on purpose. Tests: `test_validators` in `tests/test_auth.py`, `displayNameProblem` in `authValidation.test.ts`.

### 5.21 R08: Bayesian score and rating exclusion logic (31 October 2026)

**What already existed.** The score (`review_parameters.community_score`: prior mean 3.5, weight 5, hidden below 5 eligible reviews), the O(1) totals with row locks, and the publish, reject, hide, restore, withdraw and conflict-flag transitions were built earlier. R08 adds what Review.md 6.1 to 6.4 still required.

**One eligibility rule set (`app/eligibility.py`).** `evaluate_eligibility` is the only place that decides whether a published review counts; `services._add_published_rating` calls it. The first failing check names the reason:

| Order | Rule | Result |
|---|---|---|
| 1 | Not published | `INELIGIBLE_REMOVED` (`INELIGIBLE_REPORTED` while hidden) |
| 2 | Conflict of interest declared | `INELIGIBLE_CONFLICT` (also for a Guest review) |
| 3 | Guest review | `INELIGIBLE_GUEST`: counts in Guest Feedback only |
| 4 | Team account, or no active Verified Member record (none, expired, revoked, not approved) | `INELIGIBLE_UNVERIFIED` |
| 5 | Visit month in the future, no text, or rating out of range | `INELIGIBLE_INVALID` (new) |
| 6 | Same author already has a counted review of this destination and month (only possible with `duplicate_override`; the earlier one keeps the count) | `INELIGIBLE_DUPLICATE` |
| 7 | An open or in-review report with a serious reason (`privacy`, `conflict_of_interest`) | `INELIGIBLE_REPORTED` |
| 8 | Otherwise | `ELIGIBLE` |

Eligibility is frozen at publication: ordinary verification expiry never uncounts a review (Review.md 6.3).

**`recheck_rating` (`app/services.py`).** Locks the review, then the destination totals; removes the old contribution, re-evaluates, adds the new one. It changes nothing, not even the version, when the answer is unchanged. Serious reports use it: `create_report` uncounts the review and closing the report (`actioned` or `dismissed`) restores it. A report alone never hides the text.

**Verification revoked for abuse (`app/rating_integrity.py`).** `POST /admin/members/{user_id}/verification/revoke` (moderator or superadmin, reason required, never your own account) sets `revoked_at` and `revocation_reason`, then re-checks every counted published review of that author, locking destinations in id order. The reviews stay public; they stop feeding the Community Rating. Audited as `verification.revoke_for_abuse` with the review count; the member gets the new `verification.revoked` notice. A repeat answers `404`. This is the documented exception to the no-full-scan rule and touches one author's reviews only.

**Reconciliation.** `reconcile` recomputes the community, guest and per-category totals of every destination from the review rows and compares them with the stored totals. Detecting never writes. `repair=true` locks each drifting destination, overwrites the totals, bumps the totals version and writes one `ratings.reconcile_repair` audit event with before and after. A review row that contradicts itself (counted while not published, or published and eligible but not counted) is reported, never repaired. Entry points: `python -m app.jobs.reconcile_ratings [--repair]` (exit status 1 on drift), `POST /ops/jobs/rating-reconciliation` (ops token, detect-only), `POST /admin/ratings/reconcile` (superadmin, `{repair}`), and the workflow `.github/workflows/rating-reconciliation.yml` (00:45 Dhaka, calls the ops route). Drift raises one `ratings.drift_detected` notice a day to superadmins. Each run writes a `ratings.reconcile_run` audit event.

**Semester evidence.** `GET /admin/rating-evidence`: active and ever-approved Verified Members, median and maximum approval turnaround in hours, and for each published destination the eligible count and `top_rated` or `seeded`.

**Migration `0019_rating_integrity`.** Adds `INELIGIBLE_INVALID` to `rating_eligibility`. The downgrade maps rows using it to `INELIGIBLE_REMOVED` (PostgreSQL cannot drop an enum value).

**Evidence (31 October 2026).** `tests/test_rating_exclusion.py` (33 tests: formula table, every rule, public feed and totals after hide, reject, withdraw, delete, report and restore, a random-transition property test that reconciles after every step) and `tests/test_rating_integrity.py` (revocation, race with a publish, atomic failure, drift detection, repair, nightly job, evidence, access rules, CSRF, TOTP, ops route). Removing the duplicate or serious-report rule makes three of them fail. Full suite: 287 unit and 272 integration tests, migration round trip and `alembic check` clean. Online project: totals of all five destinations equal a full recomputation and no review row contradicts itself (read-only check). **Migration 0019 is not yet applied online**: it is applied by the container on the next deploy (`alembic upgrade head` at start).

**Not built.** A ranked Top Rated list (discovery, H02); a staff button for revocation (the API is ready); a delete workflow (the `DELETED` state is excluded by the rules and tested).

### 5.22 R11: review reporting, moderation actions and the audit log (1 November 2026)

Inspection found the R10/R11 core already built (35 staff routes, queue, leases, decisions, appeals, audit). R11 therefore closed twelve gaps against `Features/Review.md` 5.4 and the Moderation spec, two of them real defects:

| # | Gap or defect | Fix | Where |
|---|---|---|---|
| F1 | 6 report reasons, spec has 9 | Nine reasons plus `removal_request`; `offensive` stored as `harassment`; one list for API, database check, priority, rating rule and labels | `app/report_reasons.py`, migration `0020` |
| F2 | No anonymous report or lost-receipt removal request | `POST /public/review-reports`, `POST /public/removal-requests`: Origin, Turnstile, durable limits, uniform `202`, keyed digest of the network, contact erased after 30 days | `app/public_reports.py`, `admin/actions.py` |
| F3 | No quick action on a severe report | `POST /admin/reports/{id}/hide-pending`: a moderator hides a reported review as a takedown case; never automatic | `actions.hide_pending_decision` |
| F4 | `counts_toward_rating` stored but never read | A takedown can keep the counted rating; changing the flag moves the totals under the usual locks; R08 reconciliation counts "published, or hidden while kept" | `services.set_hidden_rating_kept`, `moderate_review(keep_rating)` |
| F5 | **A posting restriction did not stop review writes** (only verification) | `ensure_not_restricted` on member review create, edit, media and report | `member_routes.py`, `api.py` |
| F6 | **An expired sanction kept blocking until the unscheduled job ran** | A sanction is in force only until its end time; a request that meets an expired one ends it and audits `sanction.expired`; daily workflow added | `cases.expire_due_sanctions`, `auth/sessions.py`, `retention.yml` |
| F7 | Report creation wrote no audit row and had no limit | Audit `report.create`; 20 an hour and 5 per review a day per member | `actions.create_report` |
| F8 | `moderation_actions` could be changed | `UPDATE`, `DELETE`, `TRUNCATE` refused by trigger, like `audit_events` | migration `0020`, `models.py` |
| F9 | Audit paging skipped rows with equal timestamps; no range, request id, catalogue or export | Keyset cursor on time and id; filters; `GET /admin/audit-events/actions`; capped, neutralised, audited CSV export | `admin/audit.py` |
| F10 | No Rejected or Hidden lists, no reopen, rejected text kept forever | Lists with `recoverable_until`; superadmin reopen within 30 days; retention redacts text and media after 30 days unless appealed | `review_lists.py`, `retention.py` |
| F11 | Free-text reason codes | Server catalogue; strict groups refuse other codes | `app/reasons.py` |
| F12 | Retention had no schedule | `POST /ops/jobs/retention` and `.github/workflows/retention.yml` | `ops/routes.py` |

**Found while testing.** (a) A staff member refused for their **role** was never audited (the 403 comes from the dependency before the route), against Moderation spec 9; it is now `denied.role` with the route, and repeated denials raise the security alert. (b) A NUL character in a text field made PostgreSQL refuse the value and the API answered `503`; a database data exception now answers `422 VALIDATION_FAILED`. (c) A rating already suspended by an open serious report could not be kept by a takedown; the moderator's explicit choice now wins. (d) R08 tests that built "next month" from the machine's UTC date failed for six hours a day, because the app counts months in Dhaka time; they now use the Dhaka date.

**Rules.** Serious reasons from a member (`privacy`, `safety_misinformation`, `conflict_of_interest`) take the rating out while the report is open; anonymous reports never do. A report never hides a review. `POST /admin/enforcement-cases` now defaults `counts_toward_rating` to `false`. `AUDIT_ACTIONS` (`app/audit_actions.py`) lists every audit action; the test suite fails if code writes one that is not listed, and a test fails if a new state-changing route has no stated audit trail.

**Evidence (1 November 2026).** New tests: `test_reports.py` (59), `test_moderation_actions.py` (45), `test_audit_log.py` (31), `test_restrictions.py` (28), plus updates to the R08, admin, ops and media suites. Mutation checks: removing the restriction check, the member rate limit, the anonymous-source rule or the `moderation_actions` trigger makes tests fail. Backend: 289 unit and 438 integration tests, `alembic upgrade`, `check`, `downgrade` clean. Front end: 109 public and 45 staff tests.

**Deployment.** Migration `0020_reports_mod_audit` adds `reports.source`, `reporter_scope_hash`, `contact`, `severity` (and makes `reporter_user_id` nullable), `reviews.purged_at`, enum value `REOPEN`, indexes and the `moderation_actions` trigger. The container applies it with `alembic upgrade head` before it starts. **Do not start this code against the online database before that migration has run**: every review query reads `reviews.purged_at`. The workflows `retention.yml` and `rating-reconciliation.yml` need the `OPS_API_URL` and `OPS_DASHBOARD_TOKEN` repository secrets.

**Not built.** P-02 (moderators must be Verified Members), P-04 (moderators see each other), P-05 (reopen a rejected verification); a hash chain over the audit log; automatic hiding (declined on purpose, abuse risk).
