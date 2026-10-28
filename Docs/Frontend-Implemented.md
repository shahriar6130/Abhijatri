# Frontend Implementation Record

**Status:** Current as of 19 October 2026.
**Scope of this file:** what the public PWA actually does today, which defects were found and fixed, and the evidence for each claim. It mirrors `Docs/Backend-Implemented.md`.
**Rule:** this file claims only what the repository contains and a build, test or recorded browser run demonstrates. Anything not yet built is listed under "Not implemented" here and in `Docs/Implemented.md`.
**Owner:** Abdullah Bin Sorwar Choudhury (frontend, bilingual, offline).
**Related documents:** `Docs/api/API.md` (contract), `Docs/Architecture.md` section 10 (frontend structure), `Docs/Design.md` (tokens), `Docs/Decisions.md` (decisions), `Docs/Implemented.md` (project-wide status).

---

## 1. Gantt position on 19 October 2026

| ID | Task | Window | State |
|---|---|---|---|
| F03 | Bilingual information architecture and component plan | 12 to 14 Oct | **Plan written 20 Oct, awaiting approval:** `Docs/UI-Architecture.md` (language rules, sitemap, flows, component map, fonts, audit). Follow-ups U1 to U6 listed there. |
| R03 | Bilingual destination list and detail screens | 15 to 22 Oct | **Implemented** against the R02 API, with loading, error and empty states (section 2). |
| R05 | Account, verification and session screens | 18 to 23 Oct | **Implemented 27 Oct** with R04: `/login`, `/register`, `/verify-email`, `/forgot-password`, `/reset-password`, server-backed session, `/account/verification`, `/account/appeals`, `/account/notifications` (28 Oct). See `Docs/R04-R05-Checklist.md`. |
| R12 | Installable PWA shell, cached public destination views | 19 to 25 Oct | Not started. No manifest, service worker or IndexedDB yet. |
| R09 | Review form, list, filters, author controls | 20 to 27 Oct | **Guest and member paths implemented**; members add photos and one video (27 Oct). Filters not started. |
| R13, R15 | Offline pack, offline drafts | 23 to 31 Oct | Not started. |

## 2. R03: Destination list and detail screens

| Item | Location |
|---|---|
| API module | `frontend/src/api/destinations.ts` (`listDestinations`, `listAllDestinations`, `getDestination`) |
| List page | `frontend/src/pages/DestinationsPage.tsx` |
| Detail page | `frontend/src/pages/DestinationDetailPage.tsx` |
| Overview | `frontend/src/pages/OverviewPage.tsx` (live counts from the same list) |
| Shared states | `frontend/src/components/common/StatusViews.tsx` (`LoadingState`, `ErrorState`, `EmptyState`, `describeError`) |
| Loader hook | `frontend/src/hooks/useApiResource.ts` (abort on change or unmount, `reload` for retry) |
| Display components | `frontend/src/components/destination/` (`RatingSummary`, `AdvisoryCard`, `ProvenanceNote`) |

Behaviour:

- Both languages arrive in one payload, so switching language never refetches and the page keeps its place ("English switch preserves context", Gantt R03).
- Every state is explicit: loading, network failure (offline message and retry), server error (server message in the interface language plus the request reference), not found (unknown or malformed id), empty list, and no filter match.
- Advisories appear before attractions. Each shows severity, state (`CURRENT`, `STALE` flagged as "not recently verified", `EXPIRED` labelled and never shown as current), validity date, source link and verification date. The page states the Dhaka `as_of` date and the staleness threshold.
- Guide items are grouped by category with per-item source and verification date (Platform Foundation 17).
- Contacts are `tel:` links with 44 px targets and their source.
- **Ratings follow Review.md 6.** Community Rating and Guest Feedback are separate pills, each with its count. Below five eligible Verified Member reviews the card says "Editorial seeded selection" instead of a score. The Bayesian formula (C = 3.5, m = 5) is applied only above that threshold.
- No images. The R02 API has no licensed image field, and the previous hotlinked Unsplash photos were unlicensed and did not show the named places (PF 17, PF 16.3). Text-first also suits the asset budget.

## 3a. Landing page and sign-in entry (20 October 2026)

| Item | Location |
|---|---|
| Landing page at `/` | `frontend/src/pages/LandingPage.tsx` |
| Sign-in screen at `/login` (R05) | `frontend/src/pages/SignInPage.tsx` |
| Public shell (brand, preferences, footer; no sidebar) | `frontend/src/components/layout/PublicLayout.tsx` |
| Shared language and theme switches | `frontend/src/components/layout/PreferenceToggles.tsx` (also used by `Navbar.tsx`) |
| Routes | `frontend/src/App.tsx`: `/` landing, `/login` sign-in, the app from `/overview` |

Behaviour:

- Two paths: **Continue as guest** (to `/overview`) and **Sign in** (to `/login`). Each card lists what that path allows. Guest: guides, dated advisories, emergency numbers, text-only reviews. Member: account-owned reviews, Community Rating eligibility for Verified Members, photos for Verified Members. Member items are marked "Coming soon".
- The landing page is an **entry, not a gate**. Every app route, including shared links such as `/destinations/<id>`, opens directly without choosing a path, because a Guest needs no registration (Execution.md rule 1).
- When the API answers, the landing page links straight to each published destination. If it does not, that strip is omitted and the page still works.
- **Sign-in is shown but disabled.** The form (email, password with correct `autocomplete`) sits in a disabled `fieldset` with a status notice. Nothing is sent, because the account service (R04) does not exist. It connects to `POST /api/v1/auth/login` with the CSRF flow of PF 16.2 when R04 lands.
- The sidebar logo returns to the landing page, the Overview link moved to `/overview`, and a session card shows "Browsing as a guest" with a Sign in link.
- Browser run (Edge, 20 Oct 2026): landing in Bangla and English, guest path to `/overview`, sidebar Sign in to `/login` with disabled inputs, logo back to `/`, `/destinations` opened directly, dark theme, no horizontal overflow at 390 px, no page errors. Build: initial JS 86.8 KB gzip.

## 3b. Review form: category ratings, note and Verified Member photos (20 October 2026)

Implements Review.md amendments A1 and A2 on the frontend.

| Item | Location |
|---|---|
| Category ratings (7, optional, 1 to 5 or "Not applicable") with one-line prompts | `frontend/src/components/reviews/CategoryRatings.tsx`, labels in `reviewLabels.ts` |
| Free-text note (the review body), required for Guests and Members | `frontend/src/components/reviews/GuestReviewForm.tsx` |
| Photo section: locked notice for Guests; picker for Verified Members | `frontend/src/components/reviews/ReviewPhotos.tsx` |
| Photo rules (JPEG/PNG/WebP, 8 MiB, 20 MP, five per review, alt text and ownership declaration) | `frontend/src/utils/reviewPhotos.ts` |
| Request builder | `buildGuestReviewPayload`, `cleanCategoryRatings`, `REVIEW_CATEGORIES` in `frontend/src/api/reviews.ts` |
| Who is using the app (guest only until R04) | `frontend/src/context/SessionContext.tsx`; the sidebar session card reads it |
| Unit tests (Vitest, `npm test`) | `frontend/src/api/reviews.test.ts`, `frontend/src/utils/reviewPhotos.test.ts` |

Behaviour:

- **Category ratings are collected but not yet sent.** The API rejects unknown fields, so `category_ratings` is added to the request only when `VITE_REVIEW_CATEGORY_RATINGS=true`. Until the review service accepts it (R07), the form says so. Sending it early would break every submission.
- **Guests are text-only.** They see "Photos are for Verified Members" with a sign-in link, and no file input exists for them.
- **Verified Members get the photo picker**, which checks type, size, count and decoded resolution before anything is attached. These checks are only fast feedback; the server and media worker re-check everything (Security.md 8). Upload through media intents comes with R07 and the media pipeline.
- `SessionContext` only shapes the interface. It cannot be set from the browser, and the API remains the authorization boundary.

Evidence (20 Oct 2026):

| Check | Result |
|---|---|
| `npm test` | 15 passed: receipt format and uniqueness; the seven categories; rating clean-up; payload mapping with NFC name and trimming; no `category_ratings` while disabled and exactly the 13 accepted fields; rated categories only when enabled; photo type, size, count, pixel limit and metadata |
| `npm run build` | clean; initial JS 90.4 KB gzip (budget 200 KB) |
| Browser run (Edge, local API on embedded PostgreSQL) | categories rated and one reset to "Not applicable"; Guest photo lock shown with no file input; submission returned "Review submitted"; the captured request had the 13 accepted fields and no `category_ratings` |
| Not exercised in a browser | The Verified Member photo picker, because no session can be verified until R04; its rules are covered by unit tests |

## 3c. Guest entry and welcome; review form driven by the API; Turnstile (20 October 2026)

| Item | Location |
|---|---|
| Guest entry page `/guest`. The guest enters a name, which stays on this device. The page shows "Welcome, <name>! You are Guest #N", with "Not you? Change name", then a guide to what a review asks for (from the API). The landing page's "Continue as guest" now opens it. It is an entry point, never a gate: every app route still opens directly. | `frontend/src/pages/GuestEntryPage.tsx`, route in `App.tsx`, link in `LandingPage.tsx` |
| Guest name storage (`localStorage` `abhijatri_guest_name`, NFC, at most 80 code points, tolerant of blocked storage). Guest footprint: `recordDailyVisit()` posts `{}` at most once per Dhaka day per browser and keeps the first `visit_number` as "Guest #N". Nothing about the guest is sent (updated 20 Oct, count-only rule). | `frontend/src/api/guests.ts` |
| Session: the guest variant now carries `displayName` and `guestNumber`; `setGuestName`, `clearGuestName` and `signOut` | `frontend/src/context/SessionContext.tsx` |
| Sidebar card: "Welcome, <name> · Guest #N" | `frontend/src/components/layout/Sidebar.tsx` |
| **Guest sign-out** (20 Oct): a "Sign out" button in the sidebar card (named guests only) and on `/guest`. It forgets the name, guest number and last-visit day and opens `/`; the next guest gets a new, higher number, so numbers only increase. The review scope stays (Decisions.md, "Guest sign-out ends that guest"). | `frontend/src/api/guests.ts` (`signOutGuest`), `SessionContext.tsx`, `Sidebar.tsx`, `GuestEntryPage.tsx` |
| The review form reads `GET /review-parameters`. It uses the category names and prompts and the note, title and name limits from the API, falling back to the local labels if the call fails. The note is marked **required**. The display name is pre-filled from the guest name. | `frontend/src/api/reviewParameters.ts`, `GuestReviewForm.tsx`, `CategoryRatings.tsx` |
| **Cloudflare Turnstile** on Guest submission: explicit render, action `guest-review`, token sent as `turnstile_token`, and the widget is remounted after every attempt. Nothing renders when `VITE_TURNSTILE_SITE_KEY` is unset (local dev). This fixes the production `403 CHALLENGE_FAILED`. | `frontend/src/components/reviews/TurnstileWidget.tsx` |
| Category averages (destination page: Community and Guest; review feed: Guest) and per-review category chips | `frontend/src/components/destination/CategoryAverages.tsx`, `DestinationDetailPage.tsx`, `ReviewFeedSection.tsx` |
| Community Rating uses the API's `score` and `seeded_selection` (the local formula is only a fallback for older API builds) | `RatingSummary.tsx` |

**Category ratings are now sent.** Set `VITE_REVIEW_CATEGORY_RATINGS=true`; `.env.example` now uses it.

Evidence (20 Oct 2026):

| Check | Result |
|---|---|
| `npm test` | 27 passed (15 existing + 6 photo + 6 new). The new guest tests cover NFC trimming, the 80-code-point cap in Bangla, the storage round trip, blocked storage, and that the request body has only `guest_scope_secret` and never the name. |
| `tsc --noEmit`, `npm run build` | clean; JS 93.8 KB gzip |
| `npm test` after guest sign-out (20 Oct) | 32 passed (3 new: sign-out clears name, number and last visit but keeps the scope; the next guest gets a higher number on the same day; blocked storage). `npm run build` clean. |
| Local end to end (API + PostgreSQL 17 + Vite) | Same device twice → Guest #1 both times. A `name` field gets 422. Parameters: 7 categories, note required, minimum 20. A short note gets 422. A review with 3 categories gets 201 and appears in the moderator queue with its categories; publishing it puts the category averages in the list, profile and feed. `guest_visits` holds no name. The pages `/`, `/guest`, `/reviews` and the destination page serve 200. |
| Not run | A click-through in a real browser (the Chrome extension was not connected); a real Turnstile token (needs the production site key) |

**Deployment settings:**
- Vercel: `VITE_TURNSTILE_SITE_KEY` (the Cloudflare site key) and `VITE_REVIEW_CATEGORY_RATINGS=true`, then redeploy.
- Railway: `TURNSTILE_HOSTNAME=abhijatri.vercel.app`.

## 3. R09 (Guest path): review submission, receipt, status and withdrawal

| Item | Location |
|---|---|
| API module | `frontend/src/api/reviews.ts` |
| Page | `frontend/src/pages/ReviewsPage.tsx` |
| Form | `frontend/src/components/reviews/GuestReviewForm.tsx` |
| Receipt shown once | `frontend/src/components/reviews/ReceiptPanel.tsx` |
| Status and withdrawal | `frontend/src/components/reviews/ReceiptStatusPanel.tsx` |
| Public feed on the detail page | `frontend/src/components/reviews/ReviewFeedSection.tsx` |
| Labels | `frontend/src/components/reviews/reviewLabels.ts` |

Contract points met (API.md 5.1 to 5.4, 5.8; PF 13):

- **Receipt.** `generateReceipt()` makes `abr1_` plus 32 bytes from `crypto.getRandomValues`, unpadded base64url (48 characters). The server never issues one.
- **Retry safety.** One `client_draft_id` and receipt per draft. A failed or lost submission is retried with the same pair, so the server returns the stored review (`duplicate_recovered: true`) instead of a duplicate. A fresh pair is created only after success or `DRAFT_ALREADY_SUBMITTED`.
- **All required fields:** destination UUID, display name (1 to 80), language, traveller type, comfort tier, visit month (`YYYY-MM-01`, not after the current Asia/Dhaka month), title (3 to 160), body (20 to 6000, counted in code points like the server), rating 1 to 5, consent version `2026-10-01`. Client checks mirror the server; server `field_errors` are mapped back onto the matching inputs.
- **Receipt custody.** The receipt is shown once after acknowledgement, with copy and save-as-file, and a "saved it" confirmation before closing. It is held only in memory and never written to storage, a URL or a log (PF 13.3, 13.5).
- **Status and withdrawal** use `POST /review-receipts/status` and `POST /reviews/{id}/withdraw` with the receipt in the body and the `expected_version` from the status response. Withdrawal asks for confirmation.
- **Feed.** Published reviews, newest first, cursor "show more", Guest label, plain text only (React escapes it; no user HTML is rendered).
- The submission notice states moderation, the public display name and Guest label, the separate Guest Feedback, and that a lost receipt cannot be recovered.
- Inputs have associated labels, `aria-invalid` and `aria-describedby` for errors, a radio-group star rating with labelled 44 px targets, and focus moves to the receipt heading after submission.

## 4. Destination content seed (supports R01 and R03)

R01 belongs to Shahriar Islam. To give R03 real data to show, sourced seed content was added. **It still needs the R01 content review.** Every record has `reviewer = NULL` until that review happens.

| Item | Location |
|---|---|
| Content | `backend/scripts/destination_seed_content.py` |
| Loader | `backend/scripts/seed_destinations.py` (idempotent; matches by English name so the existing smoke-test record keeps its id and reviews) |
| Tests | `backend/tests/test_seed_content.py` (52 checks: semester scope, column lengths, phone format, advisory window, provenance) |

Content: Cox's Bazar, Sajek Valley, Sylhet, Sundarbans and Bandarban, each with region, summary, seasonality, restrictions, coordinates, 3 to 5 guide items, 1 to 2 advisories and national contacts (999, Tourist Police 01320-222222, Shastho Batayon 16263, and the 1090 disaster line for coastal and flood-prone places). Every record cites a source a reviewer can open; all were checked on 19 October 2026. Local office numbers that could not be confirmed were left out rather than guessed. Prices are excluded (they belong to E02 to E06).

The Sajek advisory "Road blockade eased until 21 October" is time-bound and expires on 22 October 2026. That is intended and demonstrates expiry.

## 5. Defects found and fixed

| # | Defect | Cause | Fix | Evidence |
|---|---|---|---|---|
| D1 | Guest review submission always failed, then showed a fake receipt (before the merge) or a raw error (after). | Sent slug ids (`sajek-valley`) where the API requires UUIDs; omitted `guest_display_name`, `language`, `visit_month`, `title`, `receipt_secret`, `consent_version`; sent a non-existent `travel_date` (rejected as `UNKNOWN_FIELD`); expected a server `receipt_token` the API no longer returns. | Rebuilt the flow on the contract (section 3). | Browser run, section 7. |
| D2 | API errors were never parsed. | `client.ts` expected `{code, message, details}`; the API returns `{error: {code, message, request_id, field_errors}}`. | `ApiError` now carries `code`, `requestId`, `fieldErrors`; network failures become `NETWORK_ERROR`. | `npm run build`; error states seen in the browser run. |
| D3 | Public GETs triggered a CORS preflight. | `Content-Type: application/json` was sent on every request. | Sent only with a body, so public reads stay CORS simple requests (PF 16.1). | Code review of `client.ts`. |
| D4 | Error messages ignored the interface language. | No `Accept-Language` header. | Sent from the current `<html lang>`. | Bangla and English messages seen in the browser run. |
| D5 | The local frontend could not reach the local backend (every request blocked by CORS). | `CORS_ALLOWED_ORIGINS` in the local `backend/.env` was `http://localhost:5173/`; browsers send the origin without a trailing slash, so it never matched. | `Settings.cors_origins` strips trailing slashes (`backend/app/config.py`). | `tests/test_config.py::test_cors_origins_ignore_trailing_slashes`; header `access-control-allow-origin: http://localhost:5173` observed. |
| D6 | Destination pages showed invented ratings ("4.85 Bayesian Score", "342 reviews", "Bayesian Verified"). | Hardcoded mock data. | Pages read the API; ratings follow section 2. | Browser run. |
| D7 | The interface claimed offline features that do not exist ("PWA Offline Ready", "IndexedDB Cache: offline packs and drafts stored locally", a pack download that only called `alert()`). | Mock UI. | Claims removed from the navbar, sidebar and detail page until R12 and R13 deliver them. | `Navbar.tsx`, `Sidebar.tsx`, `DestinationDetailPage.tsx`. |
| D8 | Mock data looked like an API module. | `SEEDED_DESTINATIONS` lived in `src/api/destinations.ts`. | Moved to `src/data/prototypeDestinations.ts` as `PROTOTYPE_DESTINATIONS`, used only by the planner, offline-packs and saved-trips prototypes. | `grep` shows no API page imports it. |
| D9 | Untyped, unused date helper. | `src/utils/formatDate.js` in a TypeScript project, imported nowhere. | Replaced by `src/utils/format.ts` (Asia/Dhaka dates, Bangla digits). | Build. |
| D10 | System Status reported the Railway API as "Unreachable" although it was up. | `isAllowedBackendUrl` (`src/api/health.ts`) accepts only `localhost`, `api.abhijatri.example` or the `VITE_API_BASE_URL` host, so the Railway URL was refused before any request was sent. | Extra hosts can be allowed with `VITE_ALLOWED_BACKEND_HOSTS` (comma-separated hostnames; documented in `frontend/.env.example`). The allow-list itself is kept. | Browser run on 19 Oct 2026: `https://abhijatri-backend.up.railway.app/` showed "Live & Connected", database ready, 238 ms. |
| D11 | Every non-OK health result showed the same "Unreachable" heading and hid the reason. | `HealthCheckPage` never rendered `healthResult.error`. | A refused URL now has status `blocked` ("URL not allowed (not tested)") with a bilingual explanation; other failures show their error text. | Browser run: `https://evil.example.com` showed the blocked message and sent no request. |
| D12 | A review's declared `language` followed the interface language, not the text: a Bangla note written in the English interface was sent as `EN`, and vice versa. The note text itself was always sent verbatim (never translated). | `GuestReviewForm` set `language` once from the interface when the form opened. | `detectReviewLanguage` (`src/api/reviews.ts`) labels the title and note by script: mostly Bengali `BN`, mostly Latin `EN`, at least 20 % of each `MIXED`. The dropdown follows it with a "Detected from your writing" hint until the reviewer picks a value, which then sticks (Banglish in Latin letters needs that override). | 6 Vitest tests; browser run 20 Oct 2026: English interface with Bangla text sent `BN`, Bangla interface with English text sent `EN`, a manual `MIXED` stayed `MIXED`; the body matched the typed text in every case. |
| D13 | After a failed submit the page stayed where the Submit button is, so errors higher up the long form went unseen. | No scroll or focus handling on failure. | Every failed submit (client checks or server response) scrolls the topmost error to the centre of the screen (instant when reduced motion is requested) and focuses its field; a star rating focuses its first star; a form-level error with no field focuses the message itself. | Browser run 20 Oct 2026, submitting from the bottom of the page: empty form focused Destination; missing rating focused "1 star"; server `409 RESERVED_DISPLAY_NAME` focused Display name; server `503 GUEST_WRITES_PAUSED` focused the alert. Each was in view below the header. |
| D14 | Large cards (the review form, detail panels) jittered when the cursor rested near their edge. | `.tonal-card:hover` lifted every card by 2 px; the lift moved the edge out from under the cursor, hover ended, the card dropped back, and the cycle repeated. Found because the test could not click a "stable" Submit button. | The lift now applies only to cards that are links (`a.tonal-card`). | Two consecutive browser runs clicked Submit without instability. |

## 5a. QA and F03 audit fixes (28 October 2026)

Sources: `QA_UI_UX.md`, `QA_FRONTEND.md` (28 Oct) and `Docs/UI-Architecture.md` section 8.

| Item | Fix |
|---|---|
| QA UI/UX 1 (High): offline screen claimed "100% offline", "Airplane Mode Ready" | `OfflinePacksPage` replaced by `FeatureUnavailable`: says nothing is stored yet, what packs will do (R12, R13), and links to the guides |
| QA UI/UX 2 and Frontend 1 (High): planner called the missing `/api/v1/estimates` | `PlannerPage` replaced by a placeholder; it makes no API call |
| QA UI/UX 3, 4: planner range and tier controls, saved-trip delete icon | Removed with the prototypes; rebuilt accessibly with E08 and E09 |
| QA Frontend 2: nine npm advisories | Already resolved by the Vite 8 / Vitest 5 upgrade: `npm audit` reports 0 in `frontend`, `ops` and `staff` |
| QA Frontend 3: prototype slugs bypass live data | `src/data/prototypeDestinations.ts` and the prototype types deleted; no page uses slug ids |
| Sidebar | "Soon" tag on the three unavailable items; consistent names ("System status" / "সিস্টেম স্ট্যাটাস") |
| U1, U16 | English font and tracking apply only to text that is itself English; Bangla headings and `tracking-*` utilities never tighten Bangla (`global.css`) |
| U3 | Each published review carries its own `lang` (detected from its script) |
| U4, U5, U9, U10, U11 | Paired menu-button and status-pill names, `aria-expanded`, 44 px targets, paired brand subtitle; unwired search removed; language switch named by its visible word |
| U6 | System status page fully bilingual; time in Dhaka with the interface locale |
| U12 | `utils/safeStorage.ts`: blocked or full storage no longer blanks the app |
| U13, U14 | Whole bilingual sentences for counts; Review.md term "Seeded Destination Selection"; star labels with locale digits and the scale |
| U17 | `<html lang>` set before any request, so the first `Accept-Language` is right |

Evidence (28 Oct 2026): `npm test` 64 passed (8 files; 3 new for `safeStorage`); `npm run build` clean. Browser run in Edge with the API stubbed: storage blocked still renders; planner makes no `/estimates` request; no "Airplane Mode Ready"; three "Soon" tags; Bangla `h1` letter-spacing `normal`; a Bangla review in English mode `normal` (was -0.93 px); reviews tagged `bn` and `en`; menu and status names in Bangla; language button 44 px; no horizontal overflow at 390 px.

Open: U2 (self-hosted fonts, waits for decision Q2), U15 (review labels from `GET /review-parameters`), QA Frontend 4 (no browser E2E tests in CI).

## 6. Defects found, reported to their owners, not fixed here

| # | Finding | Owner | Detail |
|---|---|---|---|
| B1 | `counted_rating` is returned as the rating value for Guest reviews. | Backend (Muhtasim) | API.md 5.10 says it is `null` for Guest reviews. The aggregates are correct (only Guest Feedback moves); the service keeps the value to subtract it later. Either the contract text or the response needs to change. |
| B2 | `tests/test_config.py::test_unset_environment_fails_closed` fails unless `DATABASE_URL` is set in the shell. | Backend (Muhtasim) | The test does not clear `DATABASE_URL`, and production now requires an explicit one. CI passes only because CI sets the variable. |
| B4 | The Railway deployment (`https://abhijatri-backend.up.railway.app`) runs backend code from before the `backend-dev` merge. | Railway owner (Muhtasim or Shahriar) | Checked 19 Oct 2026: `/health` and `/health/ready` return `200` and CORS allows `http://localhost:5173`, but `GET /destinations` is `404`, `POST /review-receipts/exchange` (removed) still exists, `POST /review-receipts/status` is `404`, errors use the old `{"detail": ...}` shape, and `GET /destinations/{id}/reviews` returns `500` for every valid id. Redeploy from current code. If it shares the Supabase database migrated to `0005` on 19 Oct, its old receipt routes will also fail (`0004` renamed `review_receipts.token_hash` to `digest`). The current frontend cannot use this deployment until then. |
| B3 | The local `backend/.env` lists `https://abhijatri-backend.up.railway.app/` as an allowed CORS origin. | Whoever owns that `.env` | That is the API's own address, not a browser origin. The architecture also names Render, not Railway; the deployment target needs one answer. |

## 7. Verification evidence (19 October 2026)

All runs were local against an embedded PostgreSQL 16 server (the project targets 17; the embedded build was used because Docker is not installed on this machine).

**Shared Supabase database, 19 October 2026** (the project in the local `backend/.env`, `APP_ENV=development`): it was at `0002_enable_rls` with no destinations or reviews. With the team's approval, `alembic upgrade head` applied `0003` to `0005`, then `seed_destinations.py` loaded 5 destinations, 21 guide items, 6 advisories, 18 contacts and 5 rating rows. `GET /destinations` and the Sajek profile returned `200` from that database. This was run from a developer machine, not the protected migration workflow (PF 22); staging and production must still migrate only through that workflow.

| Check | Result |
|---|---|
| `alembic upgrade head` on an empty database | 0001 to 0005 applied |
| `seed_destination.py`, then `seed_destinations.py` twice | Five destinations; the second run reused every id (idempotent) |
| Backend unit tests (`-m "not integration"`, with `DATABASE_URL` set as in CI) | 180 passed |
| Backend integration tests (`-m integration`) | 54 passed |
| `ruff check .` | clean |
| `npm run build` (strict `tsc` and Vite) | clean; initial JS 84 KB gzip (budget 200 KB), CSS 6.3 KB gzip |
| API lifecycle by script | submit `201`, same-draft retry `200` with `duplicate_recovered: true`, unknown field `422 UNKNOWN_FIELD`, status `200`, staff publish `200`, public feed shows the review, Guest Feedback `5.0 (1)`, Community Rating unchanged |
| Browser run (Microsoft Edge through Playwright, against Vite and the local API) | Overview, list and Sajek detail rendered in Bangla and English; "Write a review" preselected Sajek; empty-form validation shown; review submitted through the UI; receipt matched `abr1_` plus 43 characters; status "Waiting for moderation"; withdrawal reached "Withdrawn"; unknown destination showed "Destination not found"; no horizontal overflow at 390 px; only console error was that deliberate 404 |

## 8. Not implemented

| Item | Task |
|---|---|
| Cloudflare Turnstile widget. Production requires `turnstile_token`; local development has it disabled. | R09 follow-up. Needs the site key and the CSP entry in PF 16.3. |
| Guest scope secret in IndexedDB. It is in `localStorage` until the draft store exists. | R15 |
| Offline drafts, installable PWA, service worker, destination packs | R12, R13, R15 |
| Member review path; working sign-in, registration and verification screens | R05, R07, R09 (after R04) |
| Review filters, edit-pending, appeals, reports | R09, R07, R11 |
| Staff (admin) build | Gate A item "public and staff skeletons building in CI" |
| Self-hosted fonts (CSP `style-src 'self'`, 40 KiB Bangla font budget) | F03 or R12 |
| Frontend lint in CI (unit tests now run through `npm test`) | PF 27 item 2 |
| Sending `category_ratings`; uploading photos through media intents | R07 and the media pipeline (Review.md A1, A2) |
| Planner, offline packs and saved trips (placeholders since 28 Oct 2026) | E06–E08, R12–R13, E09 |
| Public deployment. `frontend/vercel.json` is ready; deploying and adding the Vercel origin to the API's `CORS_ALLOWED_ORIGINS` is with Shahriar Islam (`Architecture.md` section 5). | Interim Vercel deploy |
