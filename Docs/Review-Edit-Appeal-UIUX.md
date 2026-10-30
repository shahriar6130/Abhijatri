# Review edit, history, guest appeal and "Request changes": UI/UX and build guide

**For:** Abdullah (public PWA `frontend/` and staff app `staff/`)
**Written:** 29 October 2026 · **Backend status:** done and verified (R07, `Docs/Backend-Implemented.md` section 5.18). **Frontend status: not built.** This file is the complete build brief, test plan and sign-off checklist.
**Contract:** `Docs/api/API.md` sections 5.3 to 5.6 and 5.5a. Specification: `Features/Review.md` 4.2, 5.1, 5.2, 9.2, 9.3.

Nothing in the backend needs to change for this work. If an API behaves differently from this file, the API (`Docs/api/openapi-v1.json`) is right and this file has a bug: tell the backend owner.

---

## 1. What you are building

| # | Screen | App | Route | Who |
|---|---|---|---|---|
| A | **My reviews** list (paged) with a detail view | `frontend/` | `/account/reviews`, `/account/reviews/:id` | Signed-in member |
| B | **Edit a review** that is not yet published | `frontend/` | `/account/reviews/:id/edit` (member), panel on the receipt page (guest) | Member, or guest with the receipt |
| C | **Guest appeal** of a rejection | `frontend/` | receipt status panel on `/reviews` | Guest with the receipt |
| D | **Withdraw** by session (member) | `frontend/` | button on A | Member |
| E | **"Request changes"** decision | `staff/` | decision form in `screens/Queue.tsx` | Moderator, superadmin |
| F | Member notice "Your review needs changes" | `frontend/` | already delivered by the notification system; make `/account` a valid link target | Member |

Not in scope: editing a **published** review (Review.md 5.2: the author withdraws and writes a new one; v1.1). Do not build an edit button for `PUBLISHED`, `HIDDEN`, `REJECTED` or `WITHDRAWN` reviews.

## 2. Review lifecycle (what the UI must reflect)

```text
 PENDING ──moderator──> PUBLISHED ──> HIDDEN ──> PUBLISHED
    │  ▲                    │
    │  └──edit (new revision)┘ (never from PUBLISHED)
    ├──moderator "Request changes"──> CHANGES_REQUESTED ──edit──> PENDING
    ├──moderator reject──> REJECTED ──appeal overturned──> PENDING
    └──author withdraw──> WITHDRAWN
```

| Status | Author sees | Author can |
|---|---|---|
| `PENDING` | "Waiting for moderation" | Edit, withdraw, add media (member) |
| `UNDER_REVIEW` | "A moderator is reading it" | Withdraw only (**edit is refused** while a moderator holds it) |
| `CHANGES_REQUESTED` | "Needs changes" + the moderator's public reason | Edit (resubmits), withdraw, add media |
| `PUBLISHED` | "Published" | Withdraw (then write a new review) |
| `HIDDEN` | "Hidden by a moderator" | Member: appeal (existing `/account/appeals`) |
| `REJECTED` | "Not published" + reason + appeal deadline | Appeal (member: existing page; guest: new form) |
| `WITHDRAWN` | "Withdrawn" | Nothing |

An edit is **not** an in-place change. The server keeps every version (`revisions[]`), marks the old one `SUPERSEDED`, returns the review to `PENDING` and puts it back in the moderation queue. Tell the author this before they save (see copy in section 9).

## 3. API cheat sheet

All paths are under `/api/v1`. Errors are always `{ error: { code, message, request_id, field_errors } }`; branch on `code`. Member calls send cookies (`credentials: 'include'`) and, for writes, `X-CSRF-Token` (reuse `call(..., { session: true })` in `src/api/auth.ts`; it already refreshes the token on `CSRF_INVALID`). Guest calls send **no cookies** and put the receipt in the JSON body only, never in a URL, header, log, analytics event or error text.

| Action | Call | Success | Errors the UI must handle |
|---|---|---|---|
| Own review list | `GET /reviews/mine?status=&destination_id=&after=&limit=` (member) | `{ items[], next_cursor }` | `401 AUTH_REQUIRED`, `422 INVALID_CURSOR`, `422 VALIDATION_FAILED` (bad status/limit) |
| One review | `GET /reviews/{id}` (member owner or staff) | `ReviewDetail` | `401`, `404 NOT_FOUND` (not yours or missing: identical) |
| Edit | `PATCH /reviews/{id}/pending` | `200 { review_id, status:"PENDING", version, revision }` | `404 NOT_FOUND` (member, not yours), `404 RECEIPT_NOT_FOUND` (guest), `422 INVALID_RECEIPT_FORMAT`, `409 INVALID_TRANSITION`, `409 REVIEW_VERSION_CONFLICT`, `409 MEMBER_REVIEW_EXISTS`, `422 VALIDATION_FAILED`, `429 RATE_LIMITED` |
| Withdraw (member) | `POST /reviews/{id}/withdraw` body `{ expected_version }` | `200` receipt-status shape | `404`, `409 REVIEW_VERSION_CONFLICT`, `401` |
| Withdraw (guest) | same path, body `{ expected_version, receipt_secret }` | `200` | `404 RECEIPT_NOT_FOUND`, `409 REVIEW_VERSION_CONFLICT` (already wired in `ReceiptStatusPanel`) |
| Guest appeal | `POST /review-receipts/appeals` body `{ review_id, receipt_secret, statement }` | `201 { appeal_id, status:"OPEN", deadline_at }` | `404 RECEIPT_NOT_FOUND`, `409 APPEAL_WINDOW_CLOSED`, `409 DUPLICATE_APPEAL`, `422`, `429` |
| Receipt status | `POST /review-receipts/status` | adds **`appeal_state`**: `null`, `received`, `in_review`, `upheld`, `overturned` | as today |
| Moderator decision | `POST /admin/submissions/{id}/moderation-actions` with `decision: "REQUEST_CHANGES"` | `200 { status:"CHANGES_REQUESTED", ... }` | as today (`REVIEW_VERSION_CONFLICT`, `LEASE_LOST`, `TRANSITION_NOT_ALLOWED`) |

### PATCH body (all content fields optional; at least one required)

```json
{
  "expected_version": 2,
  "receipt_secret": "abr1_...",          // guest only; omit for a member
  "title": "...", "body": "...", "overall_rating": 4,
  "visit_month": "2026-09-01",
  "language": "BN", "traveller_type": "FAMILY", "comfort_tier": "STANDARD",
  "category_ratings": { "FOOD": 4 },     // replaces the whole set; {} clears it
  "consent_version": "2026-10-01"
}
```

Rules the form must mirror (the server enforces them too): omitted field = keep current value; **never send `null`** for a content field (422); send `category_ratings` only if the user changed it (otherwise the old set stays); `visit_month` is the first day of a month, not in the future; the destination cannot be changed; unknown fields return 422. Send only **changed** fields: compare against the loaded `ReviewDetail`.

### Pagination (`GET /reviews/mine`)

Newest first. Default 20, max 50. Keep the opaque `next_cursor` and pass it back as `after`. Never build or parse a cursor. A cursor from the public destination feed returns `422 INVALID_CURSOR`. When the filter (`status`, `destination_id`) changes, **throw away the cursor** and start from page 1.

## 4. Screen A: My reviews (`/account/reviews`)

Replaces the "My reviews" placeholder promised in `Docs/UI-Architecture.md`. Add a link to it in the account menu / sidebar next to Appeals and Notifications. Auth guard: same pattern as `AppealsPage` (signed-out message with a Sign in link; never a blank page).

Layout (mobile first, one column; two-column list + detail from `lg`):

```text
My reviews                                   [Filter: All statuses ▾] [Destination ▾]
┌───────────────────────────────────────────────────────────────┐
│ Sajek · Sep 2026                         ● Needs changes       │
│ Clouds over the hills            ★★★★☆                         │
│ Reason: remove-phone-number                  [Edit] [Withdraw] │
└───────────────────────────────────────────────────────────────┘
│ Cox's Bazar · Aug 2026                   ● Published           │
│ ...                                                  [Withdraw]│
                       [ Load more ]      (or "That is all your reviews.")
```

Card content: destination name (look up from the destinations API; fall back to the id's first 8 chars, never blank), visit month, title, overall rating, **status chip** (text + icon, colour is not the only signal), `appeal_deadline` when `REJECTED`, `published_at` when published. Buttons follow the table in section 2. A card with an **open appeal** shows "Appeal sent" instead of the Appeal button (read `appeal_state` from the detail call, or from `/appeals/mine`).

States to build (each has a test in section 8):
1. **Loading**: skeleton cards, `aria-busy="true"`, no layout jump.
2. **Empty**: "You have not written a review yet." + link to the destinations page.
3. **Error**: inline notice with the localized `message`, a **Retry** button, and the `request_id` in small text for support.
4. **Offline**: this data is private, so it is **never cached by the service worker**. Show "You are offline. Your reviews load when you reconnect." Do not show stale data.
5. **Load more**: button, disabled while loading, announces "N more reviews loaded" in a polite live region. Ties on time are handled by the server: never sort or de-duplicate client-side.
6. **Session expired** (`401`): show the sign-in prompt, keep the filter in the URL query so it survives sign-in.

Detail view (`/account/reviews/:id`): full content, category ratings, status timeline from `revisions[]` ("Version 2 · waiting", "Version 1 · replaced"), media with their states (`pending`, `approved`, `rejected`), and the action buttons. A `404` shows "This review was not found." (do not say whether it exists).

## 5. Screen B: Edit a pending review

Reuse the existing review form components (`ReviewsPage` / `components/reviews/*`): same fields, same validation limits from `GET /review-parameters` (title, note length, rating range, category list). Differences:

- **Pre-filled** from `GET /reviews/{id}` (members) or from the values the guest typed into the receipt panel (guests cannot read a review back, see below).
- **Destination, display name, draft id and receipt are read-only/hidden.** The destination is shown as plain text.
- Banner at the top: *"Saving creates a new version and sends your review back to the moderators. It stays hidden until they approve it."*
- **Save** is disabled until at least one field differs from the loaded values. Send only the changed fields plus `expected_version` (the `version` you loaded).
- On `200`: show a success notice with the new version number, navigate to the detail view, and refresh the list.
- Media (members): the existing photo/video picker keeps working for `PENDING` and `CHANGES_REQUESTED` (the backend now allows both).

Error handling:

| Code | What the user sees | What the app does |
|---|---|---|
| `REVIEW_VERSION_CONFLICT` | "This review changed while you were editing (a moderator may have acted). Reload to see the latest version." | Offer **Reload**; keep the user's unsaved text in the form so they can copy it. Never auto-overwrite. |
| `INVALID_TRANSITION` | "This review can no longer be edited because it is {status}." | Reload the detail, disable Save. |
| `MEMBER_REVIEW_EXISTS` | "You already have a review of this destination for that month." | Highlight the visit-month field. |
| `NOT_FOUND` / `RECEIPT_NOT_FOUND` | "We could not find that review" / "That receipt does not match this review." | Do not reveal which. Guest: count toward nothing client-side; the server applies the progressive block. |
| `INVALID_RECEIPT_FORMAT` | "A receipt starts with abr1_ and has 48 characters." | Field error on the receipt input. |
| `VALIDATION_FAILED` | Field errors from `field_errors` under each field | Focus the first invalid field. |
| `RATE_LIMITED` | "Too many tries. Wait a moment." | Disable the button for the `Retry-After` seconds if present. |

**Guest edit (no account):** a guest cannot read a review back (no guest `GET`), so the guest edit lives in the receipt status panel on `/reviews`: after "Check status" shows `PENDING` or `CHANGES_REQUESTED`, show an **Edit** button that opens the same form blank-filled from what the guest still holds locally (their IndexedDB draft if it exists) or empty with a note "Only fill in what you want to change." Because only changed fields are sent, an empty form is valid for a partial edit. The receipt comes from the panel's receipt input (already validated with `isReceiptFormat`). For a `CHANGES_REQUESTED` review, show the moderator's `decision_reason` above the form.

## 6. Screen C: Guest appeal

Placed inside `ReceiptStatusPanel` when `status === 'REJECTED'`:

```text
Not published
Reason: {decision_reason}
You can appeal until {appeal_deadline, local date + "end of day, Bangladesh time"}.
[ Appeal this decision ]
   Your statement (20 to 2000 characters, plain text)  [ textarea, counter ]
   Do not include phone numbers or private details.
   [ Send appeal ]   [ Cancel ]
```

- Before the deadline: show the form. After it (`appeal_deadline < now`) or on `APPEAL_WINDOW_CLOSED`: "The appeal period has ended."
- `201`: replace the form with "Appeal sent. A different moderator will review it. Check this page again to see the result." (`deadline_at` is the appeal-window end, not a decision date).
- `DUPLICATE_APPEAL`: "You already appealed this decision." and show `appeal_state`.
- `appeal_state` display: `received` "Appeal received", `in_review` "Being reviewed", `upheld` "Your appeal was reviewed and the decision stands.", `overturned` "Your appeal was accepted. The review is back in the queue." (status will read `PENDING` again).
- Counter turns into an error state below 20 or above 2000; Send is disabled outside the range; trim leading/trailing whitespace before counting.
- The statement is not stored on the device. The receipt is never put in a URL.

Members keep using `/account/appeals` (unchanged).

## 7. Screen E: staff "Request changes" (`staff/`)

1. `staff/src/logic.ts::decisionsFor`: `PENDING` and `UNDER_REVIEW` return `['PUBLISH', 'REJECT', 'REQUEST_CHANGES']`. Add `'REQUEST_CHANGES'` to the `Decision` type in `staff/src/types.ts`. `CHANGES_REQUESTED` returns `[]` (it is the author's turn). Update `logic.test.ts`.
2. `staff/src/screens/Queue.tsx` decision form: label *"Ask for changes"*, help text *"The author is told what to change and can edit. The review stays hidden until they resubmit and you approve."* The **reason code is required** (2 to 60 characters) and is shown to the author, so say so under the field: *"The author can read this reason. Do not include private details."* The internal note stays internal.
3. No media decision is needed for this choice (`rejected_media_ids` must stay empty; the server returns 422 otherwise).
4. After success the item leaves the queue (the task completes). The subject status shows "Changes requested".
5. Audit tab: the new action appears as `review.request_changes`; check its label is not blank.

## 8. Build checklist (files)

`frontend/`
- [ ] `src/types/index.ts`: add `appeal_state: AppealState | null` to `ReceiptStatus`; add `ReviewDetail`, `ReviewSummary`, `MyReviews`, `ReviewEditInput`, `ReviewEdited`, `GuestAppealInput`, `GuestAppealCreated` (copy field names from `Docs/api/openapi-v1.json`).
- [ ] `src/api/reviews.ts`: `getMyReviews`, `getReview`, `editPendingReview` (member and guest variants), `withdrawMemberReview`, `appealRejectedReview`. Member calls use `call(..., { session: true })`; guest calls use `apiRequest` with **no** `credentials`. Add `src/api/reviews.test.ts` cases (section 10).
- [ ] `src/pages/MyReviewsPage.tsx`, `ReviewDetailPage.tsx`, `ReviewEditPage.tsx`; routes in `src/App.tsx` under the signed-in `AppLayout`; nav links in `Sidebar.tsx`/`Navbar.tsx`.
- [ ] `src/components/reviews/ReceiptStatusPanel.tsx`: guest Edit and Appeal sections, `appeal_state` text, `CHANGES_REQUESTED` branch.
- [ ] Bilingual strings via `t('বাংলা', 'English')` for every new label, error and notice. Bangla first, no English-only text.
- [ ] Service worker: confirm `/api/v1/reviews/*` and `/api/v1/review-receipts/*` are **not** cached (`Docs/Architecture.md` section on caching).

`staff/`
- [ ] `src/types.ts`, `src/logic.ts`, `src/logic.test.ts`, `screens/Queue.tsx` (section 7).

## 9. Copy (Bangla / English)

| Key | Bangla | English |
|---|---|---|
| edit.warning | সংরক্ষণ করলে নতুন একটি সংস্করণ তৈরি হবে এবং রিভিউটি আবার মডারেটরের কাছে যাবে। অনুমোদনের আগে এটি দেখা যাবে না। | Saving creates a new version and sends your review back to the moderators. It stays hidden until they approve it. |
| edit.conflict | আপনি সম্পাদনা করার সময় রিভিউটি বদলে গেছে। সর্বশেষ সংস্করণ দেখতে রিলোড করুন। | This review changed while you were editing. Reload to see the latest version. |
| edit.locked | রিভিউটির বর্তমান অবস্থায় আর সম্পাদনা করা যাবে না। | This review can no longer be edited in its current state. |
| changes.title | আপনার রিভিউতে পরিবর্তন দরকার | Your review needs changes |
| appeal.sent | আপিল পাঠানো হয়েছে। অন্য একজন মডারেটর এটি দেখবেন। | Appeal sent. A different moderator will review it. |
| appeal.closed | আপিলের সময় শেষ হয়ে গেছে। | The appeal period has ended. |
| appeal.duplicate | এই সিদ্ধান্তের বিরুদ্ধে আপনি ইতিমধ্যে আপিল করেছেন। | You already appealed this decision. |
| list.empty | আপনি এখনও কোনো রিভিউ লেখেননি। | You have not written a review yet. |
| list.offline | আপনি অফলাইনে আছেন। অনলাইনে ফিরলে রিভিউ দেখা যাবে। | You are offline. Your reviews load when you reconnect. |

## 10. Automated tests (Vitest, `npm test` in `frontend/` and `staff/`)

Mock `fetch`; no network. Name tests exactly as below so the checklist can tick them.

`frontend/src/api/reviews.test.ts`
1. `editPendingReview` (member) sends `PATCH /api/v1/reviews/{id}/pending` with `credentials: 'include'` and `X-CSRF-Token`, **no** `receipt_secret`.
2. `editPendingReview` (guest) sends `receipt_secret` in the body, **no** cookies, and the receipt appears in no URL.
3. Only changed fields are sent; unchanged fields and `null` are never in the body.
4. `category_ratings: {}` is sent when the user clears all categories; omitted when untouched.
5. `getMyReviews` builds `?status=&destination_id=&after=&limit=` and drops empty params.
6. A `422 INVALID_CURSOR` resets the cursor and reloads page 1.
7. `appealRejectedReview` posts `{review_id, receipt_secret, statement}`; maps `APPEAL_WINDOW_CLOSED` and `DUPLICATE_APPEAL` to their messages.
8. `withdrawMemberReview` sends only `expected_version`.
9. A `CSRF_INVALID` response refreshes the token once and retries.
10. Error `message` never contains the receipt (assert on a thrown `ApiError`).

Component tests (`@testing-library/react`, as used by the existing page tests)
11. `MyReviewsPage`: loading skeleton, empty state, error with Retry and `request_id`, one page, "Load more" appends without duplicates, filter change drops the cursor, signed-out prompt, offline notice.
12. Buttons by status: Edit only for `PENDING`/`CHANGES_REQUESTED`; none for `UNDER_REVIEW` (Withdraw only), `PUBLISHED` (Withdraw only), `WITHDRAWN` (none), `REJECTED` (Appeal).
13. `ReviewEditPage`: Save disabled until a field changes; sends only the diff; shows each error row of section 5 with the right message; `REVIEW_VERSION_CONFLICT` keeps the typed text.
14. `ReceiptStatusPanel`: Edit shown for `PENDING`/`CHANGES_REQUESTED`; appeal form for `REJECTED` before the deadline; closed message after it; counter bounds 20 to 2000; `appeal_state` texts; no appeal UI when `appeal_deadline` is `null`.
15. Accessibility: every control has a label, errors use `role="alert"`, status chips have text, focus moves to the first invalid field, Load more announces through `aria-live="polite"`.

`staff/src/logic.test.ts`
16. `decisionsFor('PENDING')` and `decisionsFor('UNDER_REVIEW')` include `REQUEST_CHANGES`; `CHANGES_REQUESTED`, `WITHDRAWN`, `REJECTED` return `[]`.
17. The decision form requires a reason of 2 to 60 characters for `REQUEST_CHANGES` and sends no `rejected_media_ids`.

Build gates: `npm run build` passes in both apps with no TypeScript errors; counts of passing tests increase by at least the numbers above.

## 11. Manual test cases

Run against a local backend (`uv run uvicorn app.main:app`) with a seeded destination, two member accounts (**Nila**, **Omar**), one moderator with TOTP, and a second moderator. Record Pass/Fail and the `request_id` of any failure.

### 11.1 Member edit
| ID | Steps | Expected |
|---|---|---|
| M1 | Nila submits a review. Open My reviews. | One card, status "Waiting", buttons Edit and Withdraw. |
| M2 | Edit: change the title only, Save. | Success notice "version 2". Card shows the new title, still "Waiting". The moderator queue shows the review with the new title. |
| M3 | Edit: clear all category ratings, Save. | Detail view shows no category ratings. History shows two versions. |
| M4 | Open Edit, change nothing. | Save disabled. |
| M5 | Edit with a note of 5 characters. | Field error under the note, nothing sent. |
| M6 | Open Edit in two tabs; save in tab 1; save in tab 2. | Tab 2: conflict message, typed text still there, Reload loads version 3. |
| M7 | Moderator publishes the review; Nila reopens the Edit URL directly. | "can no longer be edited", Save disabled, no Edit button on the card. |
| M8 | Nila has reviews for Sep and Aug at one destination; edit Aug's visit month to Sep. | `MEMBER_REVIEW_EXISTS` message on the month field; nothing changed. |
| M9 | Omar opens `/account/reviews/{Nila's id}` and `/edit`. | "not found", identical to a made-up id. |
| M10 | Sign out in another tab, press Save. | Sign-in prompt, form text kept. |

### 11.2 Request changes round trip
| ID | Steps | Expected |
|---|---|---|
| R1 | Moderator claims a pending review, picks "Ask for changes", reason `remove-phone-number`, Submit. | Review leaves the queue; audit shows `review.request_changes`. |
| R2 | Author opens My reviews (and the notification bell). | Notification "Your review needs changes"; card status "Needs changes" with the reason; Edit and Withdraw available. |
| R3 | Author edits and saves. | Status back to "Waiting"; review is in the queue again with the new text. |
| R4 | Moderator publishes it. | Public destination page shows the edited text; the old version is not visible anywhere public. |
| R5 | Moderator opens "Ask for changes" on a published review. | Option not offered. |
| R6 | Submit with an empty reason. | Blocked client-side; server `422` shown as a field error if forced. |

### 11.3 Guest edit and appeal
| ID | Steps | Expected |
|---|---|---|
| G1 | Submit a guest review, keep the receipt. On `/reviews` check status. | "Waiting"; Edit and Withdraw offered. |
| G2 | Edit with the right receipt (change the note). | Success; version +1; in queue. |
| G3 | Edit with a wrong receipt (valid format). | "receipt does not match"; no detail about the review. Repeat 6 times quickly: progressive delay/`RATE_LIMITED` message appears. |
| G4 | Edit with a malformed receipt (`abc`). | Format hint; no request sent. |
| G5 | Moderator rejects the review (reason `spam`). Check status. | "Not published", reason, appeal deadline in local date, Appeal form. |
| G6 | Statement of 10 characters. | Send disabled; counter in error state. |
| G7 | Statement of 40 characters, Send. | "Appeal sent". Re-check status: "Appeal received". |
| G8 | Send a second appeal. | "You already appealed this decision." |
| G9 | The moderator who rejected it opens the appeal. | Cannot decide it ("someone else must decide"). A second moderator claims and chooses *overturned*. |
| G10 | Guest checks status. | "Your appeal was accepted"; status "Waiting" again. |
| G11 | Reject another guest review, then change `created_at` of the rejection in the database to 32 days ago (test database only), try to appeal. | "The appeal period has ended." |
| G12 | Open DevTools Network during G2 to G7. | Receipt only in request bodies; none in URLs, headers, localStorage, console or error text. |

### 11.4 History and pagination
| ID | Steps | Expected |
|---|---|---|
| H1 | Give Nila 45 reviews (seed script), open My reviews. | 20 cards, then "Load more" twice (20, 5); then the end message. No duplicates; newest first. |
| H2 | Filter status = Published, then Withdrawn. | List resets to page 1 each time; counts match the database. |
| H3 | Edit a review on page 1 while page 2 is loaded; press Load more. | No duplicate or missing cards. |
| H4 | Paste a cursor from the public destination feed into `?after=`. | Graceful "Could not load this page", list reloads from the start. |
| H5 | Omar's list. | Only Omar's reviews. |

### 11.5 Withdraw
| ID | Steps | Expected |
|---|---|---|
| W1 | Nila withdraws a pending review. | Confirmation dialog first; status "Withdrawn"; leaves the moderator queue; no Edit button. |
| W2 | Withdraw a published review, check the destination page and rating. | Review disappears; the average updates (count -1) after refresh. |
| W3 | Double-click Withdraw / retry after a dropped response. | One withdrawal; second request still shows "Withdrawn", no error. |

### 11.6 Cross-cutting
| ID | Steps | Expected |
|---|---|---|
| X1 | Switch the interface to Bangla/English on every new screen. | No untranslated text; layout does not break with long Bangla strings. |
| X2 | Keyboard only: Tab through list, edit form, appeal form; Esc closes dialogs. | Logical order, visible focus, no keyboard trap. |
| X3 | Screen reader (NVDA/TalkBack): list, errors, Load more. | Status chips, errors and "N more loaded" are announced. |
| X4 | 360 px wide phone, then 1280 px desktop. | No horizontal scroll; tap targets at least 44 px. |
| X5 | Throttle to "Slow 3G", then offline. | Spinners/skeletons, then the offline notice; no stale private data when offline. |
| X6 | Reload while offline after visiting My reviews online. | Private pages are not served from the cache. |
| X7 | Dark mode. | Status chips, notices and counters stay readable. |

## 12. Final verification checklist (sign-off)

### Backend and database (done 29 October 2026)
- [x] R07 endpoints implemented: edit, owner read, member history, member withdraw, guest appeal, request changes
- [x] Migration `0018_review_crud` written, upgrade → downgrade → upgrade proven on PostgreSQL 17
- [x] Backend suite: 502 passed, 1 skipped (includes 16 new `tests/test_review_crud.py`); ruff and strict mypy clean
- [x] OpenAPI snapshot regenerated; every route documented in `API.md`
- [x] `Docs/Backend-Implemented.md` section 5.18 records the work and open items
- [x] Migration `0018` applied to the online Supabase project (`Abhijatri`, 29 October 2026): `alembic_version = 0018_review_crud`; `moderation_decision` has `REQUEST_CHANGES`; `revision_status` has `SUPERSEDED`; `appeals.appellant_user_id` nullable; `appeals.reason` length 2000; `ck_appeals_guest_target` and `ix_reviews_member_history` exist; RLS still on for `appeals`; the Supabase security advisor shows no new finding (only the existing informational "RLS enabled, no policy" notices that are intentional because the API connects as the owner)
- [ ] **Backend owner:** redeploy the Railway API so the running service has the new routes (the code is not deployed by the migration)
- [ ] **Backend owner:** after deploy, smoke test on the live API: `GET /api/v1/reviews/mine` returns `401` when signed out (proves the route exists); `POST /api/v1/review-receipts/appeals` with a random receipt returns `404 RECEIPT_NOT_FOUND`

### Frontend (built and tested 30 October 2026; see `Docs/Review-Frontend-Manual-Test-Cases.docx`)
- [x] Section 8 file checklist complete; `frontend/` and `staff/` build with no errors (public app: `MyReviewsPage`, `ReviewDetailPage`, `ReviewEditPage`, `ReviewEditForm`, `StatusChip`, guest edit and appeal in `ReceiptStatusPanel`, public list filters; staff: "Ask for changes")
- [x] Section 10 automated tests: 31 new public-app tests and 2 new staff tests written and passing (public 95, staff 26, ops 19). Component-level tests (item 11 to 15) are covered by the browser run instead, because the repo has no component-test library
- [x] Browser run on the local stack: 59 of 59 checks pass (member edit, conflict, request changes round trip, publish, public filters, paging of 43+ reviews, withdraw, offline, 360 px, Bangla, labels, guest edit, rejection, appeal)
- [x] Receipt never appears in a URL, header, storage or error text (checks GU2, GU6, GU10)
- [x] No Edit button on a published, rejected or withdrawn item (P1, P2, GU8)
- [x] `Docs/Frontend-Implemented.md` updated with what was built and the test counts
- [ ] Manual cases (96) run by a person on real devices: section 4 of the manual test-case document
- [x] Online run (real Supabase database, signed-in superadmin, 30 Oct 2026): 14 checks pass; publish, guest appeal and a member request-changes round trip were skipped on purpose (they would leave public or open data, or need a second account) and pass on the local stack. Details: manual test-case document, section 3a and K
- [x] Staff queue and inbox refresh within seconds (5 s and 10 s, and on focus); unit-tested
- [ ] Private review pages not cached by a service worker (X5, X6): there is no service worker yet, so this holds trivially; re-check when R12 adds one
- [ ] Tester (project owner) signs off: name ______ date ______

## 13. Backend facts that may surprise you

- `UNDER_REVIEW` means a moderator has claimed the task. Edits are refused then; the author sees "A moderator is reading it". If they get `INVALID_TRANSITION`, reload and show the new status.
- The server returns **`404`** for "not yours" and "does not exist" alike. Do not try to tell them apart.
- `appeal_deadline` is the end of the 30th day in Bangladesh time (UTC+6), returned in UTC. Show it in local time and say "end of day, Bangladesh time".
- A guest appeal has no inbox notification (guests have no account); the only place to see the outcome is the receipt status (`appeal_state`).
- The public feed (`GET /destinations/{id}/reviews`) always shows the **current published** version only; superseded versions are never public.
- Edits are rate limited like other receipt operations (guest) and by the global limiter (member); show `RATE_LIMITED` calmly.
