# Implemented status

Claims here are limited to what is in the repository and evidenced by a test, migration check, or CI run. Last updated 19 October 2026 (R01/R03/R09 frontend integration).

| Area | Status | Evidence |
|---|---|---|
| Review schema, constraints, enums | Implemented | `migrations/versions/0001_review_vertical_slice.py`; `alembic upgrade head`, `check`, `downgrade base` clean on PostgreSQL 17. |
| Guest submission, permanent draft dedup, receipts | Implemented | `tests/test_review_postgres.py::test_guest_vertical_slice_and_retry_deduplication`. |
| Moderation, publish/hide/restore/withdraw with locked rating deltas | Implemented | Concurrency and property tests in `tests/test_review_postgres.py`. |
| Conflict flag transitions | Implemented | `test_conflict_flag_uses_locked_rating_delta`. |
| Public feed with stable cursor | Implemented | Vertical-slice test; `tests/test_review_unit.py`. |
| Production config guard, CORS allow-list, docs toggle, readiness probe | Implemented | `tests/test_config.py`; `app/main.py`. |
| CI (lint, unit, integration, migrations, audit, secret scan, image build) | Defined | `.github/workflows/ci.yml`; first green run to be confirmed on the PR. |
| Render deployment blueprint | Defined, not yet applied | `render.yaml`; requires dashboard setup and the Supabase URL. |
| Pending-review edit endpoint (`PATCH /reviews/{id}/pending`) | Implemented 29 Oct 2026 (R07) | `app/api.py::edit_unpublished_review`; `tests/test_review_crud.py`. |
| Member reviews, accounts, verification, reports, appeals, review edit/read/history | Implemented (see the R04, R07 and R11 entries and `Docs/Backend-Implemented.md` 5.13 to 5.18) | The older "not implemented" label here was out of date. |
| Production authentication, staff MFA, CSRF | Not implemented | Security.md deploy gates; staff API returns 501 in production. Rate limiting is implemented (WP5 row below). |
| ERD (`Docs/Schema.md`) and API contract (`Docs/api/API.md`, `Docs/api/openapi-v1.json`) | Implemented, review pending | Contract and schema drift tests; sign-off in `Docs/Reviews/F02-review.md`. |
| Row-level security on all public tables | Implemented | `migrations/versions/0002_enable_rls.py`; `tests/test_rls.py`. |
| Destination profile, bilingual guide items, dated advisories (Current/Stale/Expired), public contacts, provenance; `GET /destinations`, `GET /destinations/{destination_id}` with public cache and ETag (R02) | Implemented | `migrations/versions/0003_destination_content.py`; `tests/test_destination_unit.py`, `test_destination_http.py`, `test_destination_postgres.py`; 70 backend tests pass on PostgreSQL 17 on 19 Oct 2026. Sourced seed content for the five destinations exists (see the R01/R03 section below); its R01 content review is pending. |
| Public review feed cache header | Implemented | `tests/test_destination_postgres.py::test_review_feed_has_a_short_public_ttl`. |
| Standard error body, bilingual messages, field-error codes (WP2) | Implemented | `tests/test_errors.py`. |
| Client-generated receipts, versioned HMAC keyring with rotation, `POST /review-receipts/status`, idempotent withdraw (WP3) | Implemented | `tests/test_receipts.py`; migration `0004_receipt_keyring`. |
| Trusted client address, durable rate limits, progressive receipt block, pending ceilings, emergency switch, server-side Turnstile (WP5) | Implemented, **staging proof outstanding** | `tests/test_client_address.py`, `test_turnstile.py`, `test_abuse.py`; migration `0005_rate_limit_buckets`. The forged-header test against the real Render edge and a live Turnstile key have not been run. Historical: 181 backend tests passed on PostgreSQL 17 on 19 Oct 2026; see the current CI run for present status. |
| `Idempotency-Key` replay (WP4), edit-pending, appeals, reports (WP6, WP7), CSRF and credentialed CORS (WP9), authentication (WP10), pack manifest (WP11) | Not implemented | `Docs/api/API.md` section 4. |
| Redis, CDN, media pipeline, offline pack API | Deferred | Decisions.md scope control; Gantt R14. |

## R02: Destination, advisory and contact data services (19 October 2026)

Full account: [`Docs/Backend-Implemented.md`](Backend-Implemented.md), section 1. This entry is a summary; the evidence below comes from a local run on PostgreSQL 17 on 19 October 2026 (181 backend tests passed, `ruff` and strict `mypy` clean, migrations applied and reversed cleanly). A first CI run on the pull request is still to be confirmed.

| Item | Status | Evidence |
|---|---|---|
| `GET /api/v1/destinations`: paged list of published destinations with both-language names, region, summary, coordinates, rating summaries, active-advisory count | Implemented | `tests/test_destination_postgres.py`; contract `Docs/api/API.md` 5.12 |
| `GET /api/v1/destinations/{destination_id}`: bilingual profile with seasonality, restrictions, guide items, advisories, contacts and per-record provenance | Implemented | `tests/test_destination_postgres.py`; contract 5.13 |
| Advisory states `CURRENT`, `STALE`, `EXPIRED`, `NOT_YET_EFFECTIVE`, evaluated on the Asia/Dhaka date; expired items hidden unless `include_expired=true` | Implemented | `tests/test_destination_unit.py` (boundaries, Dhaka versus UTC date), `test_destination_postgres.py` |
| Schema: profile columns on `destinations`; tables `destination_guide_items`, `destination_advisories`, `destination_contacts`; provenance columns, check constraints, indexes; row-level security on the new tables | Implemented | Migration `0003_destination_content`; `tests/test_rls.py`; `tests/test_docs_schema.py`; database rejection of bad coordinates, phone numbers and advisory windows is tested |
| Public caching: `Cache-Control: public, max-age=60` and weak ETag with `304` on the two routes; the review feed also has the short public TTL; all other routes stay `no-store` | Implemented | `tests/test_destination_postgres.py` |
| Privacy: no personal data; researcher and reviewer names not returned; non-published records return the same `404` as missing ones | Implemented | `tests/test_destination_postgres.py`, `tests/test_destination_http.py` |
| Settings `ADVISORY_STALE_AFTER_DAYS` (30) and `PUBLIC_CACHE_MAX_AGE_SECONDS` (60) | Implemented | `backend/.env.example`; `Docs/Architecture.md` |
| Real destination content for five destinations with sources and licences | Implemented, **R01 content review pending** | `backend/scripts/seed_destinations.py`; `tests/test_seed_content.py`; `Docs/Frontend-Implemented.md` section 4. |
| Frontend using the endpoints | Implemented | R03; `Docs/Frontend-Implemented.md` section 2. |
| Staff create, edit and publish of destination content | Not implemented | R10 and R11, after real staff authentication. |
| Advisory staleness threshold of 30 days | Open | Working default; the team must confirm the value. |

Shared backend work built with R02 (error contract, client-generated receipts with a versioned keyring, durable rate limits, Turnstile validation) is described in `Docs/Backend-Implemented.md`, section 2.

## R01/R03/R09: Destination content, destination screens and Guest review flow (19 October 2026)

Full account: [`Docs/Frontend-Implemented.md`](Frontend-Implemented.md). Evidence is a local run on 19 October 2026 against an embedded PostgreSQL 16 server: 180 backend unit and 54 integration tests passed, `npm run build` clean, and the browser flows below were driven in Microsoft Edge. No shared database was written to.

| Item | Status | Evidence |
|---|---|---|
| Sourced bilingual content for Cox's Bazar, Sajek Valley, Sylhet, Sundarbans and Bandarban (profile, guide items, advisories, contacts, per-record provenance) and an idempotent loader | Implemented, **R01 content review by the content owner pending** (`reviewer` is empty on every record) | `backend/scripts/destination_seed_content.py`, `seed_destinations.py`; `tests/test_seed_content.py` (52 checks); two seed runs reused every id |
| Destination list, detail and overview screens on `GET /destinations` and `GET /destinations/{id}`, with loading, error, not-found and empty states; advisories with state and source; separate Community Rating and Guest Feedback with counts (R03) | Implemented | Browser run; `frontend/src/pages/DestinationsPage.tsx`, `DestinationDetailPage.tsx`, `OverviewPage.tsx` |
| Guest review submission with client-generated receipt, retry-safe draft identity, field-error mapping, receipt shown once, status and withdrawal; published feed with cursor paging (R09, Guest path) | Implemented | Browser run: submit, receipt `abr1_` plus 43 characters, status, withdraw; API script: retry returned `duplicate_recovered: true` |
| Frontend error contract (`{error:{code,message,request_id,field_errors}}`), `Accept-Language`, no preflight on public GETs | Implemented | `frontend/src/api/client.ts` |
| CORS origins with a trailing slash never matched the browser origin | Fixed | `backend/app/config.py`; `tests/test_config.py::test_cors_origins_ignore_trailing_slashes` |
| False offline claims and invented ratings removed from the interface | Fixed | `Docs/Frontend-Implemented.md` section 5 |
| System Status refused deployed API hosts and labelled them "Unreachable" without a reason | Fixed | `VITE_ALLOWED_BACKEND_HOSTS`; `Docs/Frontend-Implemented.md` D10, D11 |
| Railway API deployment serves pre-merge code (no destinations API, old error shape, review feed `500`) | Open, backend owner | `Docs/Frontend-Implemented.md` B4 |
| Bilingual information architecture and component plan (F03) | Draft, awaiting approval | `Docs/UI-Architecture.md`; audit of unpaired strings and font scoping in its section 7 |
| QA 28 Oct fixes: honest placeholders for planner, offline packs and saved trips; bilingual and accessibility fixes U1, U3-U6, U9-U14, U16, U17 | Implemented (28 Oct 2026) | `Docs/Frontend-Implemented.md` section 5a; 64 Vitest tests; browser run |
| Landing page with guest and sign-in paths; sign-in screen shown but disabled until R04 | Implemented (20 Oct 2026) | `Docs/Frontend-Implemented.md` section 3a |
| Review form: seven category ratings, free-text note, Guest photo lock and Verified Member photo picker (Review.md A1, A2) | Implemented in the frontend (20 Oct 2026); category ratings not sent and photo upload not wired until R07 and the media pipeline | `Docs/Frontend-Implemented.md` section 3b; 15 Vitest tests |
| Backend for `category_ratings`: accepted and stored per revision, per-category Guest/Community aggregates moved with the overall rating, returned in the review feed, destination list and profile, and the staff queue | Implemented in the backend (20 Oct 2026); the frontend switch `VITE_REVIEW_CATEGORY_RATINGS=true` and category display are still to be done by the frontend owner | `backend/tests/test_category_ratings.py`; property test in `test_review_postgres.py`; `Docs/Backend-Implemented.md` section 5.2 |
| Guest footprint: a daily count of guest visits (`POST /guest-visits` with an empty body, `GET /guest-visits/stats` with a per-day series). The database holds only a running number and a timestamp per guest per day; the name stays on the device. | Implemented (20 Oct 2026; count-only since migration 0008) | `backend/tests/test_guest_visits.py`; `frontend/src/api/guests.test.ts`; `Docs/api/API.md` 5.14 |
| `POST /reviews/{id}/media-intents` | Not implemented | `Docs/api/API.md` section 6 |
| Guest entry page `/guest` (name kept on the device, welcome with Guest #N), sidebar welcome, review form driven by `GET /review-parameters`, required note, Turnstile on Guest submission, category averages and chips | Implemented (20 Oct 2026) | `Docs/Frontend-Implemented.md` 3c; 27 Vitest tests; local end-to-end run |
| `GET /review-parameters` and the server-side Community Rating `score` / `seeded_selection` | Implemented (20 Oct 2026) | `backend/tests/test_review_parameters.py`; API.md 5.15 |
| Verified Member video | Proposed amendment A4, not approved | `Features/Review.md` 13.1 |
| Community | Design only | `Features/Community.md` |
| Turnstile widget, member review path, review filters, offline drafts, PWA shell, staff build | Not implemented | `Docs/Frontend-Implemented.md` section 8 |
