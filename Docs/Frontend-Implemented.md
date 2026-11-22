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
| R12 | Installable PWA shell, cached public destination views | 19 to 25 Oct | **Implemented and live** (section 5i); real-phone run pending. |
| R09 | Review form, list, filters, author controls | 20 to 27 Oct | **Guest and member paths implemented**; members add photos and one video (27 Oct). Filters not started. |
| R13, R15 | Offline pack, offline drafts | 23 to 31 Oct | **R13 and R15 part 1 live** (sections 5k, 5l); **R15 part 2 built 9 Nov, not deployed** (section 5m); phone tests pending. |

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
| D15 | A signed-in member could not enter guest mode: `/guest` showed the name form, accepted a name, then showed the same empty form again with no message. | `GuestEntryPage` reads the guest name only when the session is a guest, so for a member it was always empty; and a member cannot be a guest while the session cookie exists. | A member on `/guest` now sees "You are signed in as …" with **Continue as …** or **Sign out and continue as a guest** (waits for `/auth/logout`, then shows the guest name form); the page waits for the session instead of flashing the guest form; the landing page's guest card says sign-out is needed. `signOut()` now returns a promise. | Browser run 4 Nov 2026 with a stubbed Verified Member: landing hint shown; `/guest` showed the two choices and no name form; sign-out called `/auth/logout` once, then the name form appeared; "Welcome, Rafi!" after entering a name. 123 tests pass, build clean. |

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

## 5b. UI states audit (4 November 2026)

Every public-app screen was checked for ten states: empty, loading, error, no internet, slow network, no search result, permission denied, session expired, form validation and success. Empty, loading, error, no-result, validation and success already existed on almost every screen; the four that were app-wide gaps are now handled once, centrally.

| State | Before | Now | Where |
|---|---|---|---|
| No internet | Only My reviews noticed it | App-wide banner while offline ("pages already open may still show, nothing new can load or be sent") and a short "back online" notice | `components/common/StatusBanners.tsx` (`NetworkBanner`), `hooks/useNetworkState.ts`; mounted in `AppLayout` and `PublicLayout` |
| Slow network | A stalled request spun forever; the navbar could say "Checking" forever | GET requests stop after 20 s with a `TIMEOUT` error ("the connection is too slow", Try again); every spinner and busy submit button adds "taking longer than usual" after 8 s; the health check stops after 10 s. Writes get no default deadline, because the server may still complete them; the account forms submitted before sign-in (sign-in, sign-up, resend, reset request) are the exception: they are safe to repeat, so they stop after 30 s with the same `TIMEOUT` message and the button comes back. | `api/client.ts` (`READ_TIMEOUT_MS`, `TIMEOUT_ERROR`), `api/auth.ts` (`ACCOUNT_FORM_TIMEOUT_MS`), `SlowNetworkHint` in `StatusViews.tsx`, `api/health.ts` |
| Session expired | None: after the server ended a session the app still showed the member as signed in and every request failed | A 401 `AUTH_REQUIRED` fires `AUTH_REQUIRED_EVENT`; `SessionContext` drops to the guest view and shows "Your session has expired" with "Sign in again", which returns to the same page | `api/client.ts`, `context/SessionContext.tsx`, `SessionExpiredBanner` |
| Permission denied | Same look as any error, with a pointless Try again | Its own state ("No permission", shield icon, no retry). `AUTH_REQUIRED` shows "Sign in required" with a sign-in link instead of a retry | `failureKind()` and `ErrorState` in `StatusViews.tsx` |
| Sign-in links | Account pages linked to `/login` and sign-in always went to `/overview` | `SignInLink` passes the current page, so sign-in returns there | `components/common/SignInLink.tsx`; My reviews, Review detail, Edit, Appeals, Reports, Notifications, Verification |
| Empty | Overview showed zero counts and an empty grid | "No published destinations yet" | `OverviewPage.tsx` |
| No search result | Present, but looked like an empty list and had no way out | `EmptyState variant="no-results"` (search icon); destination search names the query and offers "Clear search"; My reviews offers "Clear filters" | `DestinationsPage.tsx`, `MyReviewsPage.tsx`, `ReviewFeedSection.tsx` |
| Form validation | Appeal button silently stayed disabled under 10 characters | Live counter says how many characters are still needed | `AppealsPage.tsx` |
| Loading, error, success | Present | Loading is `aria-busy` and the spinner respects reduced motion; empty and no-result states are `role="status"` | `StatusViews.tsx` |

Evidence (4 Nov 2026): `npm test` 123 passed (13 files; 13 new in `api/client.test.ts`: read timeout, no write timeout, caller abort, network error, session-expired event, wrong credentials not treated as expiry, error classification); `tsc` clean; `npm run build` clean. Browser run in Edge with the API stubbed: overview empty state; destination no-result with Clear search restoring the list; offline banner and back-online notice (Playwright offline mode); slow hint absent at 3 s and present at 9 s with a held request; a 25 s response became "The connection is too slow" with Try again; 403 showed "No permission" with no retry; a signed-in member whose next request got 401 saw "Your session has expired", the sidebar returned to the guest view, and "Sign in again" carried `/account/reviews` to the sign-in page. No page errors.

Not covered: the staff and ops apps (separate builds owned by others) were not changed; real-device and screen-reader passes are still outstanding.

## 5c. Interactive destination selector on the landing page (4 November 2026)

| Item | Location |
|---|---|
| Generic selector (from the 21st.dev "interactive-selector", adapted) | `frontend/src/components/ui/interactive-selector.tsx` |
| Licensed photos and their credits | `frontend/src/data/destinationImages.ts`, `frontend/public/images/destinations/*.webp`, `Docs/Image-Credits.md` |
| Credit line on each photo | `frontend/src/components/common/ImageCredit.tsx` |
| Entry motion | `@keyframes selector-in` in `frontend/src/global.css` (motion-safe only) |
| Placement | `LandingPage.tsx`: replaces the destination chips under the hero |

Behaviour: the live `GET /destinations` list becomes expanding photo panels; the open panel shows the name, summary, an **Open guide** link and the photo credit. Panels are real buttons (`aria-expanded`), arrow keys, Home and End move between them and focus opens a panel. Desktop shows a wide open panel and slim tabs; phones stack the panels, with names visible on the closed ones. A destination without a licensed photo still gets a panel (dark background, map-pin icon). Images are self-hosted: about 509 KB for all five, only the open one loads eagerly.

Evidence (4 Nov 2026): `npm test` 123 passed; `npm run build` clean. Browser run in Edge at 1280 px and 390 px with five stubbed destinations: five panels; clicking Sylhet opened it with "Photo: Sumon Mallick · CC BY-SA 4.0 · resized"; ArrowRight wrapped to the first panel and Home returned to it; the Open guide link pointed at `/destinations/<id>`; the open image had its alt text; every image request went to the app's own origin; no horizontal overflow; no page errors.

## 5d. shadcn/ui, Tailwind 4 and the new theme (4 November 2026)

| Item | Location |
|---|---|
| Tailwind 4 (CSS-first config, `@tailwindcss/postcss`) | `src/global.css`, `postcss.config.js`; `tailwind.config.js` removed |
| shadcn/ui setup | `components.json`, `src/lib/utils.ts`, `@/` alias in `tsconfig.json` and `vite.config.ts` |
| Components | `src/components/ui/{button,card,input,label,textarea,badge,separator,select,dialog,sonner}.tsx` (44 px targets, wrapping buttons) |
| Theme tokens (stone + green, light and dark) and aliases for the old colour names | `src/global.css` |
| Migrated to shadcn `Button` variants | `AccountUi` (all account pages), `PreferenceToggles`, `Sidebar`, `GuestEntryPage`, `StatusViews`, `FeatureUnavailable`, `LandingPage` |

Not yet migrated: page-specific buttons, chips and inputs on destination, review and moderation pages (they already take the new colours through the aliases); dialogs and toasts are installed but not yet used.

Evidence (4 Nov 2026): `tsc -b` clean; `npm test` 123 passed; `npm run build` clean, JS 142 KB gzip (was 129 KB; budget 200 KB), CSS 13.7 KB gzip. Screenshots of landing, overview, destinations, reviews, guest and sign-in pages in light and dark at 1280 px checked by eye.

## 5e. Scroll smoothness and state gaps (5 November 2026)

| Change | Where | Why |
|---|---|---|
| Removed `backdrop-blur` from the sticky top bar, the sidebar overlay and the selector's icon and credit pills; the top bar and sidebar are now solid | `Navbar.tsx`, `Sidebar.tsx`, `ui/interactive-selector.tsx` | A blur under a sticky bar is recomputed by the GPU on every scroll frame; on a 144 Hz laptop screen running on integrated graphics that leaves too little time per frame, so scrolling stuttered. Main-thread work while scrolling was measured at about 20 ms per 120 frames, so JavaScript was not the cause. |
| Removed the page-wide `transition-colors duration-300` on `<body>` and `transition-all` on the main column | `index.html`, `AppLayout.tsx` | Theme changes animated every colour on the page for 300 ms. |
| Landing destinations: loading placeholder of the selector's exact height; `ErrorState` with retry on failure | `LandingPage.tsx` | Previously blank while loading, then the page jumped; a failure hid the section silently. |
| Review detail and edit pages use `ErrorState` for load failures | `ReviewDetailPage.tsx`, `ReviewEditPage.tsx` | They showed a generic message, unlike other pages; now offline, slow, signed-out and no-permission each get their own wording and next step. |

Evidence: `tsc -b` clean, 123 tests pass, build clean. Browser (stubbed API): landing shows the placeholder while the request is pending and the "No connection" state with "Try again" when it fails. The review detail/edit change was type-checked only.

## 5f. App-wide animated background (6 November 2026)

**Removed 22 Nov 2026 on `ui-refresh`** (section 5s): the page sits on the plain background colour.

`frontend/src/components/ui/velaris.tsx` (adapted from the 21st.dev "Velaris" WebGL gradient) is the background of the whole app. `components/layout/AppBackground.tsx` mounts it once at the app root as a fixed, full-screen layer behind everything (`aria-hidden`), so it keeps running across page changes. The layouts no longer paint their own background; the top bars and sidebar are 80 to 90 percent opaque (no blur) and cards stay solid.

| Theme | Page colour | Gradient colours |
|---|---|---|
| Light | white | pale mint: green-100, green-50, emerald-100 |
| Dark | stone-950 | deep green: green-950, a darker green-900, emerald-950 |

Changes from the original component: half resolution and at most 30 frames per second; stops while off-screen or in a hidden tab; speed 3.5 (about three times the first setting); grain cut from 0.3 to 0.04 (at half resolution each grain dot is upscaled and flickers per frame, which looked grainy); one still frame under reduced motion; edges fade to the page colour instead of black (needed for the light theme); without WebGL the solid page colour shows; colours parsed once; GL resources released; no `cn()` (it would add `tailwind-merge`, about 10 KB gzip). Light-theme muted text moved from stone-500 to stone-600 to keep 4.5:1 on the mint.

Evidence (6 Nov 2026): `tsc -b` clean, 123 tests pass, build 144.5 KB JS gzip. Browser (Edge, stubbed API): 28.5 to 29 draws per second, no page errors; landing, overview and destinations checked by eye in both themes. Contrast on the background's worst 0.5 percent of pixels (99.5th percentile, background alone): light (237,253,245): muted 7.25:1, primary 4.77:1, body 18.8:1; dark (12,58,38): muted 5.05:1, primary 5.59:1, body 12.2:1.

## 5g. System status removed from the sidebar (6 November 2026)

The "System status" (`/health`) link was a development aid and is no longer in the sidebar (`Sidebar.tsx`). The `/health` route and page still exist, reachable from the server-status pill in the top bar and by URL.

## 5h. Reviews split into two pages with a sidebar group (6 November 2026)

| Route | Page | Contents |
|---|---|---|
| `/reviews/write` | `WriteReviewPage` | Guest review form, then the receipt after submitting; `?destination=<id>` preselects the destination |
| `/reviews/receipt` | `ReviewReceiptPage` | Receipt status check and withdrawal (`ReceiptStatusPanel`), removal request (`RemovalRequestForm`) |
| `/reviews` | `ReviewsRedirect` | Redirects to `/reviews/write`, keeping the query, so older links and bookmarks still work |

Since 11 Nov 2026 the second entry is "My reviews" for a signed-in member (section 5q). Sidebar: "Reviews" is a disclosure button (`aria-expanded`, `aria-controls`) that shows the two pages beneath it; it opens by itself while either page is showing. Each page links to the other. Every "Write a review" link (overview, my reviews, guest entry, saved trips, a destination's review feed) now points at `/reviews/write`. All in `pages/ReviewsPage.tsx`, `components/layout/Sidebar.tsx`, `App.tsx`.

Evidence (6 Nov 2026): `tsc -b` clean, 123 tests pass, build clean (145 KB JS gzip). Browser at 1280 px and 390 px (mobile menu): group starts closed with no sub-links; one click shows both; "Check with receipt" opens `/reviews/receipt` and the group stays open there; `/reviews?destination=<id>` lands on `/reviews/write?destination=<id>` with that destination selected; no page errors.

## 5i. R12: installable PWA shell and offline destination pages (6 November 2026)

| Item | Location |
|---|---|
| Service worker (Workbox, injectManifest): app shell precache, public destination API cache, font cache | `frontend/src/sw.ts`, `vite.config.ts` (`VitePWA`), `tsconfig.sw.json` |
| Web app manifest and icons (192, 512, maskable 512, Apple 180) | `vite.config.ts` (`manifest`), `frontend/public/icons/` |
| Registration, "new version" prompt, first-install note, persistent-storage request | `components/common/UpdatePrompt.tsx`, `offline/savedDestinations.ts` |
| Saved-destination list read straight from the cache | `offline/savedDestinations.ts`, `offline/cacheNames.ts`, `hooks/useDestinationCatalog.ts` |
| Image policy (offline / low-data / full) | `hooks/useNetworkState.ts` (`useImagePolicy`), `ui/interactive-selector.tsx`, `reviews/ReviewMediaGallery.tsx` |
| Route code splitting | `App.tsx` (`lazy`), `Suspense` in `AppLayout.tsx` and `PublicLayout.tsx` |

**What is cached (Platform Foundation 18.1, Security.md 7.4).** Precache: the built JavaScript, CSS, `index.html`, manifest and icons (40 files, 605 KiB, under the 1 MiB shell budget). Runtime, network first with a 4-second timeout: `GET /api/v1/destinations`, `/destinations/{id}` and `/destinations/{id}/reviews` only, status 200 only, refusing any response with `no-store` or `private`, never a request with an `Authorization` header, entries expire after 7 days (PF 18.4 default). Google Fonts stylesheet and files (CORS responses only). Never cached: photos, review media, session, account, receipts, reports, notifications, staff routes.

**Offline behaviour.** Every in-app address opens the cached shell. Overview, Destinations and the landing selector list only the destinations whose page this device has saved, with a notice; with none saved they say how saving works. Opening an unsaved destination says it is not saved on this device and links to the saved ones. Any failure while the browser reports no connection, and any 502/503/504, is shown as "No connection", never "Something went wrong". Overview hides its site-wide counts offline because they cannot be known.

**Images.** No connection: no photos are requested; panels keep their icon and dark background, review media shows a "back online" note. Data Saver or 2G/3G: only the 480 px variants (`*-480.webp`, about 104 KB for all five against 509 KB), review media on request. Normal: closed panels use 480 px, the open panel picks by width. The precache excludes `images/`.

**Speed.** Pages other than landing, guest entry, overview and destinations load on first visit: initial JavaScript fell from 147.6 KB to 110.8 KB gzip; the worker precaches the rest in the background.

**Updates.** A new deploy waits until the reader presses Reload in the prompt, so a half-filled form is never lost; open tabs check for updates hourly. `sw.js` and the manifest are served `no-cache` (`vercel.json`).

**Development.** The worker is off in `npm run dev`. Test offline with `npm run preview:offline` (build plus preview on port 4173); the preview proxies `/api` to the local backend, whose public routes send `public, max-age=60`.

Evidence (6 Nov 2026), built app with its service worker in Edge, real destination data served with the backend's public headers, fake API removed before going offline:
- Offline before opening any destination: Destinations says "No destinations saved on this device"; opening Bandarban says it is not saved and links to saved destinations.
- Bandarban opened online, then Overview, then offline: Destinations and Overview show only Bandarban with the offline notice, three rounds in a row; after 70 seconds offline (past the 60-second browser cache) and in a new tab, Bandarban still lists and opens; Cox's Bazar, never opened, says it is not saved.
- A destination response sent with `no-store` was not cached and showed "No connection" offline.
- No session, account, receipt, notification, report or guest URL in any cache.
- Data Saver: only `*-480.webp` requested; normal: the open panel full size, closed panels 480 px.
- `tsc -b` and `tsc -p tsconfig.sw.json` clean, 123 tests pass, build clean.

**Open items.** Handoffs for other people: `Handoff-Backend.md` (B6, DEP2, TS1, DOC1, Q1; closed: B5, DEP1, R14, R16) and `Handoff-Testing.md` (test checklist).
1. **Installability: resolved, no defect.** Chrome's check reported "no-acceptable-icon" only on plain-HTTP `localhost` under automation. A minimal test app with a plain solid icon failed the same way there, and over HTTPS both that app and the built Abhijatri app pass with no installability errors and the icon fetched (local HTTPS server, Chrome, 6 Nov 2026). Real users are on HTTPS. To check installability locally, serve `dist/` over HTTPS, not `vite preview`.
2. **Live API caching: fine** (B5 withdrawn, section 6).
3. `navigator.storage.persist()` is requested; headless Edge refused it (expected without site engagement). The persistence-status display and the review-snapshot date now exist (R13, section 5k); draft export belongs to R15 part 2.
4. The real-phone airplane-mode acceptance test (Gantt R12) needs the HTTPS deployment.
5. **Deployed** (DEP1 closed, section 6). Emulated acceptance on the live HTTPS site passed on 7 Nov 2026 (see below); only the real-phone run remains.

**Live acceptance, emulated (7 November 2026).** On `https://abhijatri.vercel.app` with the real API and no stubbing, Chrome emulating an Android phone: no installability errors and the icon fetched; Bandarban opened online and saved (page and reviews); fully offline the app opened, Bandarban reopened with its emergency contacts, Destinations listed only Bandarban, and a new tab still opened it; no page errors. Not yet done: the same on a real phone in airplane mode (`Handoff-Testing.md` section B). In the emulation the saved notice read "The server cannot be reached" rather than "You are offline", because Playwright's offline mode may leave `navigator.onLine` true; test B4 confirms the wording on a phone.

## 5j. Persistence, load-weight and state audit in Chrome (6 November 2026)

Method: the production build with its service worker in Chrome (Claude in Chrome), through a test-only relay to the live API that restores the `public, max-age=60` header `main` sends (B5 simulated as fixed). A server outage was simulated by stopping the relay (browser still online), and a network loss by stopping the web server (requests fail at the network level).

| # | Finding | Fix | Where |
|---|---|---|---|
| A1 | During a server outage (5xx), a saved destination page said "not saved on this device": the worker passed the 502 through instead of the saved copy. | 5xx counts as a failed fetch, so the saved copy is served. | `sw.ts` (`serverErrorIsFailure`) |
| A2 | With the browser online but the server unreachable, lists showed all destinations (the list itself was cached), including ones that cannot be opened. | The list is no longer cached by the worker (old entries are deleted on activation) and is requested with `cache: 'no-cache'` (a 304 when unchanged), so offline lists come only from saved pages. | `sw.ts`, `api/destinations.ts` |
| A3 | Outage wording said "You are offline" / "No internet" while the device was online. | "The server cannot be reached" when the browser is online; "You are offline" only when it is not. | `StatusViews.tsx` (`OfflineSavedNotice`, `ErrorState`) |
| A4 | Latin digits in Bangla text: "1টি" in the saved notice, "5 তারকা" in the rating filter and star labels. | `formatNumber(n, 'bn')`. | `StatusViews.tsx`, `ReviewFeedSection.tsx`, `GuestReviewForm.tsx`, `CategoryRatings.tsx`, `ReviewEditForm.tsx` |
| A5 | When the session check failed, a signed-in member was shown as a guest, account pages asked them to sign in, and the sidebar offered "Sign in". | Session status `unreachable` (offline, timeout, 502/503/504): account pages show "Account pages need a connection" with retry, the sidebar says the sign-in cannot be checked, and the session is re-checked on reconnect and every 30 s. Session data is still never stored offline (PF 18.1). | `SessionContext.tsx`, `StatusViews.tsx` (`AccountNeedsConnection`), 7 account pages, `Sidebar.tsx` |
| A6 | The review form opened offline with no warning; anything typed could not be sent and was lost on reload. | Offline the page says sending a review needs a connection. Offline drafts remain R15. | `ReviewsPage.tsx` |
| A7 | Fonts: about 330 KB on first load (Hind Siliguri in 4 weights, about 70 KB each, plus Inter), against the PF 19.3 Bangla font budget. | Hind Siliguri 400 and 700 only (500 renders as 400, 600 as 700 by CSS font matching): about 187 KB. Still above the 40 KiB single-weight budget; a self-hosted subset is the remaining step. | `index.html` |
| A8 | The animated background runs at 30 frames per second on every page, also on low-end phones. | One still frame when device memory is under 4 GB, 4 or fewer CPU cores, or Data Saver is on. | `layout/AppBackground.tsx`, `ui/velaris.tsx` (`animate`) |
| A9 | After an invalid receipt check, focus stayed on the page. | Focus moves to the first wrong field. | `ReceiptStatusPanel.tsx` |

**Checked and fine.** Saved destination pages survived an app update and a new tab; `localStorage` holds only language, theme, the guest name with its date and the guest scope secret (as Guest-Identity-and-Visits specifies); no session, account, receipt, notification or report data in any cache; quota about 10 GB, about 1.7 MB used. Initial JavaScript 111 KB gzip, the review form's code (47 KB) loads only on its page; the open landing panel loads full size and the closed ones 480 px. Online states: no-results search, member empty "My reviews", receipt format validation, overview tiles.

**Noted, not changed.** `navigator.storage.persisted()` is `false` (the browser decides; the status display is R13). The top bar asks `/health` and `/notifications` on each full page load. Cookies named `sb-…-auth-token` on `localhost` come from another local project (cookies are shared across localhost ports); this app has no Supabase client code.

Evidence: `tsc -b` and `tsc -p tsconfig.sw.json` clean, 123 tests pass, build clean (JS 111 KB gzip, precache 40 files, 608 KiB). Each fix above was re-checked in Chrome on the rebuilt app after activating the new worker.

## 5k. R13: offline destination packs (7 November 2026)

Built to `Offline-Frontend-Guideline.md` tasks 1 to 7 (steps A, B, C), against the live R14 API (API.md 5.23).

| Step | What | Files |
|---|---|---|
| A | IndexedDB `abhijatri-offline` v1 (`packs`, `drafts`, `meta`), honest failure results (`quota`, `unavailable`), storage status; `idb` 8.0.4, `fake-indexeddb` 6.2.6 (tests) | `offline/db.ts`, `offline/storageStatus.ts`, pack types in `types/index.ts` |
| B | Manifest, pack bytes, freshness; download → SHA-256 check → format and build check → one-transaction save; one retry for a cold start or a superseded build; the old pack is kept on any failure; advisory states recomputed on the Asia/Dhaka date with the backend's rules; pack → page shapes | `api/packs.ts`, `api/client.ts` (`toApiError`), `offline/packs.ts`, `offline/packStore.ts`, `offline/advisoryState.ts`, `offline/packAdapter.ts` |
| C | Pages read packs offline (pack first, then the opened-page cache); review snapshot; offline lists merge packs and opened pages (pack wins); Save for offline button with size; Offline packs page (states, Update, Delete with confirmation, storage status); reconnect check (freshness, update, remove with notice); "Soon" removed from the sidebar | `offline/destinationSource.ts`, `offline/freshness.ts`, `offline/packManager.ts`, `hooks/useOfflinePacks.ts`, `components/offline/*`, `pages/OfflinePacksPage.tsx`, `DestinationDetailPage.tsx`, `ReviewFeedSection.tsx`, `useDestinationCatalog.ts` |

**Decisions (owner, 7 Nov 2026).** Delivered in three reviewed steps. The guest scope secret is not moved (question Q1 in `Handoff-Backend.md`). On reconnect, changed packs update automatically, one at a time. An expired pack is still shown, labelled "Out of date", and never as current guidance. Guideline section 10 default kept: packs and opened pages both exist; the pack wins.

**Rules kept.** A stored pack is removed only on a clear server answer (`410` withdrawn, `404` or freshness `WITHDRAWN`/`NOT_FOUND`), with a notice; a failed check, `429` or `503` never deletes. Pack routes are not in the service worker cache. Packs are user-selected and need no sign-in.

Evidence (7 Nov 2026):
- `tsc -b` and `tsc -p tsconfig.sw.json` clean; 174 tests pass (35 new: storage, download and verification, advisory states including the Dhaka midnight boundary, adapter, every row of guideline table 5.3, reconnect runs).
- Real Chrome, live API: all 5 packs downloaded and verified (9 to 13 KB, about 0.25 s each); a pack with one byte changed was refused as `integrity` and the old pack kept; offline advisory counts matched the live server.
- Built app with its service worker, live API, real offline (`navigator.onLine` false), guideline group P: size shown before download (P1); Downloading → Ready, listed on Offline packs (P2); offline the pack opens with its banner and emergency numbers (P3); the review snapshot shows with filters hidden (P4); the Offline packs page works offline with storage status and no Update button (P5); Delete asks for confirmation and removes only that pack (P6); offline Destinations lists only the pack; an unsaved destination says it is not saved; the reconnect check updated `last_checked_at`; no pack or private URL in Cache Storage; no page errors. Bangla mode at 390 px: Bangla digits throughout, no overflow.
- Initial JavaScript 118 KB gzip (was 111 KB); the Offline packs page loads separately (16 KB).

**Not covered by these checks:** P7 to P16 (dropped connection mid-download, staff hide and archive, device date changes, full storage, private window, sign-out, phone restart). They are in the guideline's group P for R18.

## 5l. R15 part 1: review drafts saved on the device, form works offline (7 November 2026)

`Offline-Frontend-Guideline.md` tasks 8 and 9 only. Sending queued drafts, the stored `Idempotency-Key`, the pending list, receipt custody and export (tasks 10 and 11) wait for question Q1 in `Handoff-Backend.md` (where the guest scope secret lives), because a draft must carry a copy of it (guideline 6.2).

| Item | Files |
|---|---|
| Draft store (`drafts` in IndexedDB): fields, `client_draft_id`, receipt, `consent_version`, `local_revision`, author | `offline/draftStore.ts` |
| Autosave (500 ms), restore, destination switching, delete | `hooks/useReviewDraft.ts`, `components/reviews/GuestReviewForm.tsx` |
| Review parameters kept for offline | `offline/parameters.ts`, `api/reviewParameters.ts` |
| Offline form: saved destinations only; none saved → explains to save one first | `pages/ReviewsPage.tsx` |
| Member session exposes `userId` (account id from `/auth/session`) | `context/SessionContext.tsx` |

**Owner decisions (7 Nov 2026).** One draft per destination. Offline, Send is disabled with "Your draft is saved on this device; send it when you are back online"; the security check is not rendered offline. When the sign-in cannot be confirmed (offline), only guest drafts show and a new draft is saved as `pending`; once the sign-in is known online it goes to the member signed in, or to the guest when nobody is. Member drafts show only to that member.

**Behaviour.** Text typed before choosing a destination belongs to the destination then chosen. Switching to a destination that has its own draft restores it; switching to one without starts a fresh form and the previous destination keeps its draft. A restored tick of consent counts only for the current `CONSENT_VERSION`. Photos and videos are not kept in drafts (the form says so). After the server accepts the review the draft and its receipt leave the device and the receipt is shown once, as before. Drafts are stored unencrypted; the form says so and offers Delete with a confirmation.

Evidence (7 Nov 2026): 185 tests pass (11 new: visibility rules, newest draft per destination, Bangla text and receipt kept, pending drafts going to the member or the guest, delete one, parameters). Built app, live API reads, real offline (only the review POST answered by the test, so no review was created): D1 offline form with only the saved destination, Send disabled with the saved note; D3 a reload offline restores the text (Bangla included); D4 a new tab offline restores it; back online the offline draft is the guest's and is restored; one draft per destination across switches; D16 Delete removes only that draft; sending posts the draft's own `client_draft_id` and `receipt_secret`, then no draft is left; D2 offline with nothing saved explains what to do; no page errors.

Found and fixed during the check: an offline draft was hidden from the same guest back online; switching destination moved an existing draft; a sign-in change could clear the form; a destination change could drop the last half second of typing.

## 5m. R15 part 2: sending saved drafts after reconnect, receipt custody, export (9 November 2026)

`Offline-Frontend-Guideline.md` tasks 10 and 11, plus the guest scope write-through of 4.3 (Decisions 2026-11-08). Built on `abd`; **not deployed yet**.

| Item | Files |
|---|---|
| Draft record gains the guest scope copy, a stored `Idempotency-Key` with the SHA-256 of the request it was sent with, the state (`DRAFT`, `SUBMITTING`, `NEEDS_ATTENTION`, `ACKNOWLEDGED`), the last error, `Retry-After` and the acknowledgement. Drafts saved by part 1 are filled in on read | `offline/draftStore.ts` |
| Sending one stored draft and the guideline 6.4 answer table (`classifyFailure`) | `offline/submitDraft.ts` |
| Form sends the stored draft (saved first), honours `Retry-After`, shows the last attempt's answer | `components/reviews/GuestReviewForm.tsx`, `hooks/useReviewDraft.ts`, `components/reviews/draftText.ts` |
| "Saved drafts on this device" list: Open, Delete, Clear all (each asks first), Export, draft-loss warning when persistence was refused | `components/reviews/SavedDrafts.tsx`, `pages/ReviewsPage.tsx`, `hooks/useDrafts.ts` |
| Receipt kept until "Done" or 7 days, shown again if the tab closed before "Done"; trap-2 note ("the first version was received") | `components/reviews/ReceiptPanel.tsx` |
| App-wide banner when the connection returns and a count on "Write a review" | `components/offline/PendingDraftsBanner.tsx`, `components/layout/AppLayout.tsx`, `Sidebar.tsx` |
| Sign-out with unsent member drafts: keep or delete (guideline 6.7 default) | `components/reviews/useGuardedSignOut.tsx`, `SignOutDraftsDialog.tsx`, `Sidebar.tsx`, `pages/GuestEntryPage.tsx` |
| Guest scope secret written through to IndexedDB `meta`; restored from it when `localStorage` lost it | `offline/guestScope.ts`, `api/reviews.ts`, `main.tsx` |
| Start-up: a draft left `SUBMITTING` goes back to `DRAFT`; receipts acknowledged over 7 days ago are deleted | `maintainDrafts` in `offline/draftStore.ts` |
| `Retry-After` read into `ApiError.retryAfterSeconds`; date and time display | `api/client.ts`, `utils/format.ts` |

**Owner decisions (9 Nov 2026).** A draft is sent from the review form, opened from the saved-drafts list (not a separate pending list), so guideline state `READY` is `DRAFT` here; nothing is sent by itself. The reconnect notice is an app-wide banner plus a count in the sidebar. Every acknowledged review keeps its receipt on the device until the user confirms saving it, or 7 days. Export only, no import.

**Behaviour.** The key is reused while the request is unchanged and renewed when it changes; the draft id, receipt and scope copy never change, so a retry after a lost response is recovered by the server and never makes a second review. An edit after a lost response is sent with a new key; the server keeps the first version and the receipt screen says so, with a link to edit (receipt page for guests, My reviews for members). `IDEMPOTENCY_KEY_REUSED` renews the key and keeps the identity; `DRAFT_ALREADY_SUBMITTED` keeps the text under a new identity and removes the spent one. `429` keeps the draft, says when it can be sent, and blocks Send until then. Deleting the draft that is open in the form clears the form. The export never contains the guest scope secret, the key or any acknowledged receipt; an unsent draft's receipt only when the user ticks it.

Evidence (9 Nov 2026): 227 tests pass (34 new in `offline/submitDraft.test.ts`: the answer table, D7, D9, D10, D11, D14, D17, D20, D22, scope write-through and restore). Types and build clean; first-visit JavaScript 126.8 KB gzip (122.5 before; budget 200). Built app in Chromium (Playwright) against the live API for reads, with **every review POST answered by the test, so no review was created**: lost response then retry used the same draft id, receipt and key and showed "This review was already submitted"; the receipt stayed in IndexedDB, came back after a reload, and was deleted on Done; the IndexedDB scope copy equals `localStorage`; a draft written offline showed no banner while offline, then the banner "You have 1 unsent review draft" and sidebar count 1 after reconnect, no request sent by itself, no banner on the Write page; `429` with `Retry-After: 3600` kept the draft, said "can be sent after 9 Nov 2026, 20:52", and a second Submit sent nothing; Bangla text and digits in the list; Export without receipts, scope or key; Delete from the list cleared the open form; no horizontal overflow at 390 px. **Not run in a browser:** the member sign-out dialog (no test account used; covered by unit tests), D8 and D21 on a real phone.

Found and fixed during the check: a draft written offline (sign-in unknown) was not counted by the banner or sidebar until the form was opened; the wait time showed a date without the time.

## 5n. Phase 1 update 1: guide by type, search, Google Maps link, best-rated order (11 November 2026)

First of five requested Phase 1 updates (`Handoff-Phase1-Updates.md`). Requested: places inside a destination by type (restaurant, resort), with name and Google Maps link, and sorting to find the best. The API has no separate places and no rating for a place, so this is the part the current data allows; the rest is backend item P1 in that file.

| Item | Files |
|---|---|
| Guide of a destination: type buttons with counts (All and each type present), search over title and text in both languages, "nothing matches" state. Filtered on the device, so it works from a pack or a saved page | `components/destination/GuideSections.tsx`, `pages/DestinationDetailPage.tsx` |
| Google Maps link for the destination's map point (replaces the OpenStreetMap link) and for a contact that has a map point | `pages/DestinationDetailPage.tsx`, `utils/destinationSort.ts` (`googleMapsUrl`) |
| Destination list: sort control "By name" or "Best rated first". Community Rating first (score, highest first), then Guest Feedback average, then its count; the two ratings are never combined (Review.md 6.2) and the page says so | `pages/DestinationsPage.tsx`, `utils/destinationSort.ts` (`sortDestinations`) |

Evidence (11 Nov 2026): 237 tests pass (10 new in `utils/destinationSort.test.ts`). Types and build clean. Chrome, desktop width, Bangla, live data read through a read-only local proxy (no write could reach the server): "Best rated first" moved Cox's Bazar (Guest Feedback 3.0) to the top and kept the others in name order; the Food button showed one entry; a non-matching search showed "Nothing in the guide matches"; the header link was `google.com/maps/search/?api=1&query=21.4272,92.0058`; no console errors. **Not checked:** phone width, offline, screen reader (tests T1.8 to T1.10).

## 5o. Phase 1 update 2: the overall rating is calculated from the category ratings (11 November 2026)

Second requested Phase 1 update (`Handoff-Phase1-Updates.md`; Decisions 2026-11-11; Review.md amendment A6). This replaces the form rules of sections 3b and 3c: the overall rating is no longer an input and the seven category ratings are no longer optional.

| Item | Files |
|---|---|
| `overallFromCategories`: mean of the seven ratings, rounded to a whole number; `null` until all seven are rated | `api/reviews.ts` |
| Category ratings: all required, "Not applicable" removed, 44 px targets, the calculated overall rating shown read-only with the average (announced as a status), error on the first unrated category | `components/reviews/CategoryRatings.tsx` |
| Write a review: the overall input is removed; the value sent as `overall_rating` and stored on the draft is the calculated one; submit is refused until all seven are rated | `components/reviews/GuestReviewForm.tsx` |
| Edit a review (Member and Guest): the overall input is removed; ratings may be left alone; if changed, all seven are required and `overall_rating` is sent with `category_ratings` | `components/reviews/ReviewEditForm.tsx` |
| Guest welcome page text: the overall rating is calculated; categories are all required | `pages/GuestEntryPage.tsx` |

Not changed: how a review's overall rating is shown (review cards, My reviews, moderation, receipt status) and the destination's Community Rating and Guest Feedback. Reviews submitted earlier keep the overall rating their author gave.

Evidence (11 Nov 2026): 241 tests pass (4 new in `api/reviews.test.ts`). Types and build clean. Chrome, desktop width, Bangla, the Write page with live data through a read-only local proxy (no write could reach the server): no overall input and no "Not applicable" button; seven rating groups; submit with ratings missing showed the error and marked the unrated groups; ratings 5,5,5,5,4,4,4 showed "5 out of 5 (average 4.6)", and lowering one to 4 showed "4 out of 5 (average 4.4)". **Not checked in a browser:** a real submission and its request body, the two edit forms (they need a test review), phone width, screen reader. Limit: the server does not enforce the rule yet (P2).

## 5p. Phase 1 update 3: a guest sees "Exit" instead of "Sign out" (11 November 2026)

Third requested Phase 1 update (`Handoff-Phase1-Updates.md`; Decisions 2026-11-11). Label only; the behaviour of sections 3c and 5m is unchanged.

| Item | Files |
|---|---|
| Sidebar session card: "Exit" for a named guest, "Sign out" for a member | `components/layout/Sidebar.tsx` |
| `/guest` welcome page: the "Sign out" link reads "Exit" | `pages/GuestEntryPage.tsx` |

Evidence (11 Nov 2026): types clean, 241 tests pass, build clean. Chrome, desktop width, Bangla: a named guest saw "Sign in" and "Exit" in the sidebar card and "Exit" on `/guest`; pressing Exit opened `/`, removed the name, kept the scope and the same guest tag, and left only "Sign in". **Not checked:** the member label (no test account used), English, phone width.

## 5q. Phase 1 update 4: a member finds reviews in "My reviews", not by receipt (11 November 2026)

Fourth requested Phase 1 update (`Handoff-Phase1-Updates.md`; Decisions 2026-11-11). Only the member navigation is built; guest listing, keyword search, the "reported" filter and the note minimum need the backend (P4a to P4d). This amends section 5h: the second entry of the sidebar "Reviews" group now depends on who is signed in.

| Item | Files |
|---|---|
| Sidebar "Reviews" group: a member sees "Write a review" and "My reviews" (`/account/reviews`); a guest still sees "Check with receipt". The group also opens by itself on `/account/reviews` | `components/layout/Sidebar.tsx` |
| Write page: for a member the link under the form reads "Already reviewed? Find it in My reviews" | `pages/ReviewsPage.tsx` |
| My reviews: a line at the end links to "Check with receipt" for a review written as a guest before the account existed (such a review belongs to its receipt, not to the account) | `pages/MyReviewsPage.tsx` |

Not changed: the `/reviews/receipt` page and its route; the existing status and destination filters of My reviews (they already cover published, rejected and hidden); the note minimum of 20 (read from the server, fallback 20).

Evidence (11 Nov 2026): types clean, 241 tests pass, build clean. **Not checked in a browser:** all three changes are for a signed-in member, and no test account was used.

## 5r. Phase 1 update 5: side menu with a hamburger button in the staff dashboard (11 November 2026)

Fifth requested Phase 1 update (`Handoff-Phase1-Updates.md`; Decisions 2026-11-11). This is in the separate staff app (`staff/`), which Muhtasim owns; only its shell and stylesheet were changed. Section 5b says the staff app was not changed; that was true on 4 November and this is the first frontend change to it.

| Item | Files |
|---|---|
| Hamburger button in the top bar (`aria-expanded`, `aria-controls`, label "Open menu" / "Close menu", 44 px) | `staff/src/App.tsx` |
| Side menu with the role-filtered sections; the current one has `aria-current="page"`; the top bar shows its name | `staff/src/App.tsx` |
| From 960 px: the menu starts open beside the page and the button collapses it. Below 960 px: it starts closed and opens over the page with a backdrop; it closes on a choice, Escape or a press on the backdrop; focus moves into the menu and back to the button; the page behind is `inert` | `staff/src/App.tsx` |
| Styles as classes only (the staff site's Content-Security-Policy allows no inline styles); the slide-in is skipped under reduced motion | `staff/src/styles.css` |

Evidence (11 Nov 2026): `tsc -b` clean, 46 staff tests pass, `vite build` clean. Chrome with a local stand-in for the API that returns a made-up signed-in session and empty lists (no real account, no real data): at 1536 px the menu was open with ten sections for a superadmin, choosing Inbox changed the screen and the top bar and kept the menu open, and the button closed it; at 390 px (in a frame) the menu started closed, opened as an overlay with focus on the current section, and closed on Escape, on the backdrop and on a choice, each time returning focus to the button; no sideways scrolling at either width. **Not checked:** with a real staff sign-in and real data, the moderator role (fewer sections), Bangla, a real phone, a screen reader. **Not done:** the bundle served at `/staff` was not rebuilt (P5).

## 5s. UI refresh: palette and front page (22 November 2026, branch `ui-refresh`)

Owner request; Decisions 2026-11-22. Not merged: it is on `ui-refresh`, and `git diff ui-baseline ui-refresh -- frontend` shows every change.

| Item | Files |
|---|---|
| Theme tokens: white and near-black, neutral greys, grass green accent (light #3F7A2B, dark #6FAF4F); old colour names point at them. Browser theme colour updated | `global.css`, `index.html`, `vite.config.ts` |
| Animated background removed (section 5f no longer applies) | `App.tsx`; `components/layout/AppBackground.tsx` and `components/ui/velaris.tsx` deleted |
| Colours outside the palette replaced: success notices green, information grey, warnings amber, ratings in the text colour, "Coming soon" badges grey | `AccountUi.tsx`, `StatusBanners.tsx`, `PackNotices.tsx`, `PendingDraftsBanner.tsx`, `AdvisoryCard.tsx`, `StatusChip.tsx`, `ReceiptPanel.tsx`, `ReceiptStatusPanel.tsx`, `HealthCheckPage.tsx`, `Navbar.tsx`, `Sidebar.tsx`, `FeatureUnavailable.tsx`, `RatingSummary.tsx`, `CategoryAverages.tsx`, `CategoryRatings.tsx`, `ReviewFeedSection.tsx`, `GuestEntryPage.tsx` |
| Front page: photo hero (brand, promise, five licensed photos that change by themselves every 7 s, progress shown, each photo's credit); right panel with the language and theme switches and the choice between guest and member. No API call: the photos are bundled. The shared header is hidden on `/` because the page carries its own. The Destinations page also accepts `?q=` to start with a search | `pages/LandingPage.tsx`, `components/layout/PublicLayout.tsx`, `pages/DestinationsPage.tsx`, `data/destinationImages.ts` |
| The old destination selector is no longer used and is deleted | `components/ui/interactive-selector.tsx` |
| The member list no longer says "Coming soon": accounts, Verified Member ratings and photos are live | `pages/LandingPage.tsx` |

Revised the same day (owner): no search, menu, greeting, tabs or cards; guest and member choice moved into the right panel; no controls in the hero (Decisions 2026-11-22). Evidence after the revision: types clean, 241 tests pass, build clean; main JavaScript 107.2 KB gzip (110.5 before the refresh), CSS 13.1 KB (14.1); with motion allowed the place under the photo went Cox's Bazar, Sajek Valley, Sylhet at 0, 8 and 15 s; no sideways scrolling at 1440, 1280, 390 and 360 px in both themes. Before the revision: Headless Chrome driven over the DevTools protocol, with a local stand-in that serves only the five seeded destination names and regions (the live API answered 404 "Application not found" that day): the front page at 1440 and 1280 px (light, dark, Bangla, English) and at 390 and 360 px (light and dark) had no sideways scrolling, five cards and five tabs; the Destinations page at the same sizes had no sideways scrolling. **Not checked:** the slider moving (screenshots used reduced motion), keyboard and screen reader, a real phone, the pages that need the API (destination detail, reviews, account).

## 6. Defects found, reported to their owners, not fixed here

| # | Finding | Owner | Detail |
|---|---|---|---|
| B1 | `counted_rating` is returned as the rating value for Guest reviews. | Backend (Muhtasim) | API.md 5.10 says it is `null` for Guest reviews. The aggregates are correct (only Guest Feedback moves); the service keeps the value to subtract it later. Either the contract text or the response needs to change. **Closed 6 Nov 2026: the contract was corrected (API.md 5.10); see `Handoff-Backend.md`.** |
| B2 | `tests/test_config.py::test_unset_environment_fails_closed` fails unless `DATABASE_URL` is set in the shell. | Backend (Muhtasim) | The test does not clear `DATABASE_URL`, and production now requires an explicit one. CI passes only because CI sets the variable. |
| B4 | The Railway deployment (`https://abhijatri-backend.up.railway.app`) runs backend code from before the `backend-dev` merge. | Railway owner (Muhtasim or Shahriar) | Checked 19 Oct 2026: `/health` and `/health/ready` return `200` and CORS allows `http://localhost:5173`, but `GET /destinations` is `404`, `POST /review-receipts/exchange` (removed) still exists, `POST /review-receipts/status` is `404`, errors use the old `{"detail": ...}` shape, and `GET /destinations/{id}/reviews` returns `500` for every valid id. Redeploy from current code. If it shares the Supabase database migrated to `0005` on 19 Oct, its old receipt routes will also fail (`0004` renamed `review_receipts.token_hash` to `digest`). The current frontend cannot use this deployment until then. |
| B3 | The local `backend/.env` lists `https://abhijatri-backend.up.railway.app/` as an allowed CORS origin. | Whoever owns that `.env` | That is the API's own address, not a browser origin. The architecture also names Render, not Railway; the deployment target needs one answer. |
| B5 | **Withdrawn 7 Nov 2026: not a defect.** The check used `curl -I`, a HEAD request; the API answers HEAD with `405` and `no-store`, and the status line was filtered out. With GET, the live API (through Vercel and on Railway) sends `Cache-Control: public, max-age=60` on `/destinations`, `/destinations/{id}`, `/destinations/{id}/reviews` and `/destinations/{id}/pack/manifest`. Check headers with `curl -s -D - -o /dev/null <url>`, never `curl -I`. | Railway owner (Muhtasim or Shahriar) | See the note. |
| DEP1 | **Closed 7 Nov 2026.** `abd` reached `main` through PR #38 and Vercel deployed it: `/sw.js` is served as `application/javascript` and `/manifest.webmanifest` as `application/manifest+json`. | Abdullah (pull request `abd` to `main`); whoever reviews and merges (Shahriar deploys Vercel) | See the note. |
| B6 | **Open (6 Nov 2026).** The shared Supabase database refuses connections: `FATAL: (EMAXCONNSESSION) max clients reached in session mode - max clients are limited to pool_size: 15`. The local backend then answers 503 to everything. | Backend (Muhtasim); whoever manages the Supabase project | `DATABASE_URL` uses the session-mode pooler (`aws-0-ap-southeast-1.pooler.supabase.com:5432`), capped at 15 clients for everyone together. Each backend process may hold `DB_POOL_SIZE` 5 + `DB_MAX_OVERFLOW` 2 = 7 (`app/config.py`), so Railway plus two local backends already exceed the cap. **Options:** (a) local `.env`: `DB_POOL_SIZE=2`, `DB_MAX_OVERFLOW=0`; (b) use the transaction-mode pooler (port 6543), which needs psycopg prepared statements off (`prepare_threshold=None` in the engine's `connect_args`) and a test pass; (c) give local development its own database (the test database on `127.0.0.1:54322` already exists). **Done when** two local backends and Railway run together without the error. |

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
| Guest scope secret with IndexedDB as the reader. `localStorage` stays the reader for M1; IndexedDB holds a write-through copy (section 5m, Decisions 2026-11-08). | Post-M1 |
| Offline drafts, installable PWA, service worker, destination packs | R12, R13, R15 |
| Member review path; working sign-in, registration and verification screens | R05, R07, R09 (after R04) |
| Review filters, edit-pending, appeals, reports | R09, R07, R11 |
| Staff (admin) build | Gate A item "public and staff skeletons building in CI" |
| Self-hosted fonts (CSP `style-src 'self'`, 40 KiB Bangla font budget) | F03 or R12 |
| Frontend lint in CI (unit tests now run through `npm test`) | PF 27 item 2 |
| Sending `category_ratings`; uploading photos through media intents | R07 and the media pipeline (Review.md A1, A2) |
| Planner, offline packs and saved trips (placeholders since 28 Oct 2026) | E06–E08, R12–R13, E09 |
| Public deployment. `frontend/vercel.json` is ready; deploying and adding the Vercel origin to the API's `CORS_ALLOWED_ORIGINS` is with Shahriar Islam (`Architecture.md` section 5). | Interim Vercel deploy |

## R07/R09 review author controls, list and filters (30 October 2026)

Guide: `Docs/Review-Edit-Appeal-UIUX.md`. Test cases: `Docs/Review-Frontend-Manual-Test-Cases.docx`. API: `Docs/api/API.md` 5.3 to 5.6, 5.5a.

**Built and tested**
- **My reviews** (`/account/reviews`): the member's own reviews, newest first, status and destination filters kept in the URL, "Show more reviews" with an announcement, loading, empty, error-with-Retry and offline states. A new filter restarts from page 1; an `INVALID_CURSOR` restarts the list.
- **Review detail** (`/account/reviews/:id`): content, version history, media states, the moderator's reason, appeal state, Edit and Withdraw with confirmation. An unknown or foreign id shows "not found".
- **Edit** (`/account/reviews/:id/edit` and the receipt panel): one form, two modes. Members edit the loaded review and only changed fields are sent; guests start with an empty form and only touched fields are sent, with the receipt in the body and no cookie. Handles version conflict (keeps the typed text, Reload), locked state, visit-month collision and field errors. Edit is offered only while PENDING or CHANGES_REQUESTED.
- **Guest appeal**: in the receipt status panel for a rejection before its deadline, 20 to 2000 characters with a live counter, the appeal state shown afterwards.
- **Public list filters** on the destination page: rating, author type, photos or video, sort. They apply to the reviews already loaded and the page says so.
- **Staff**: "Ask for changes" decision with four reasons and a note that the author can read the reason. The queue now refreshes every 5 s and the inbox every 10 s while visible, and on focus (it was 30 s), so a moderator sees a new review within seconds.
- Fixes found by testing: the top bar overflowed at 360 px; the create form said category ratings were unsupported (now sent by default); the CI secret check lists the new Word documents.

**Evidence (30 October 2026)**: 95 public-app, 28 staff-app and 19 ops-app unit tests pass; all three apps build; `tsc` clean; the public build has no staff or ops code. A real-Chrome run on the local stack passed 59 of 59 checks (`Docs/diagrams/e2e/review-author.e2e.mjs`, results in `last-results.json`).

**Still open**
- A person has not yet run the 92 manual cases on real devices, with a screen reader, or on Safari and Firefox.
- The online run was done as the signed-in superadmin (14 checks pass); the supplied member password was refused, and publishing, the guest appeal and a member request-changes round trip were not run online (they pass locally).
- Photo and video upload from the edit screen is not built (upload remains on the create form).
- Public list filters are client-side; a server-side filter needs an API change.
- In development over HTTP/1.1, six open tabs can stall requests because each holds a notification stream (not an issue behind the HTTP/2 production proxy).

## Three-role Chrome run: fixes (8 November 2026)

Full record: [Testing-and-Implementation-Irfan.md](Testing-and-Implementation-Irfan.md).

- Verification page: review-status screen while a case is pending (auto-refresh), data summary with Edit links on the review step.
- Tours: Safety tab rewritten (errors shown, saved details prefilled, inline SOS confirmation); suspended banner; workspace refresh every 15 s; chat refusals shown as "Not sent".
- Staff app: inline evidence viewer; report panel for tour, chat and SOS tasks (`TourReportForms.tsx`); Tour Operations uses an inline reason panel instead of `prompt()`.
- Staff 46 tests and member 192 tests pass; both builds clean.
