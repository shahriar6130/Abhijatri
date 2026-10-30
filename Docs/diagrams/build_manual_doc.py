"""Builds Docs/Review-Frontend-Manual-Test-Cases.docx: how to run the apps, results of the automated browser run,
and the full manual test cases for the review form, list, filters and author controls (Gantt R09)."""

import json
from pathlib import Path

from docx_helpers import Doc

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "Review-Frontend-Manual-Test-Cases.docx"
RESULTS = json.loads((HERE / "e2e" / "last-results.json").read_text(encoding="utf-8"))
GREEN, AMBER, RED = "E3F3EA", "FFF4D6", "F9DFD8"

# (id, title, steps, expected)
M = {}

M["A. Sign-in and navigation"] = [
    ("A1", "Member signs in", "Open `/login`. Enter the member email and password. Press Sign in.", "You land inside the app. The sidebar shows your name and the links **My reviews**, Appeals, Notifications and email."),
    ("A2", "Wrong password", "Sign in with a wrong password.", "A clear error appears; no sign-in; the password field is cleared or kept hidden."),
    ("A3", "My reviews link", "Click **My reviews** in the sidebar.", "The page `/account/reviews` opens with the heading \"My reviews\"."),
    ("A4", "Notification link target", "Open `/account` directly.", "You are sent to `/account/reviews` (the target of the new \"Your review needs changes\" notice)."),
    ("A5", "Signed out", "Sign out. Open `/account/reviews`.", "A sign-in prompt appears (not a blank page). `GET /api/v1/reviews/mine` returns 401 in the Network tab."),
    ("A6", "Sign out and back", "Sign out, sign in again, open My reviews.", "The list is the same as before; no stale data from the previous session is shown while signed out."),
]
M["B. Create a review (the form)"] = [
    ("B1", "Member form", "Open `/reviews`. Pick a destination, a visit month, 4 stars, a title (3+ chars), a note (20+ chars), tick the notice, press Submit.", "A receipt page appears with the review ID. For a member, \"Published as\" shows your account name (no guest name field, no security check)."),
    ("B2", "Validation", "Submit with an empty title, a 5-character note and no rating.", "Each problem is shown under its field; focus moves to the first problem; nothing is sent."),
    ("B3", "Future month", "Choose next month as the visit month.", "\"The visit month cannot be in the future\" appears."),
    ("B4", "Category ratings", "Rate Food 4 and Safety 5; leave the rest \"Not applicable\". Submit. Open the review in My reviews.", "No \"not stored by the server yet\" notice is shown. The detail page lists Food 4/5 and Feeling of safety 5/5."),
    ("B5", "Duplicate month", "As the same member, submit another review of the same destination and visit month.", "A clear message: you already have a review of this destination for that month. No second review."),
    ("B6", "Guest form", "Sign out. Open `/reviews`. Enter a display name and submit a review.", "A receipt page shows the review ID and the receipt (starts with `abr1_`) **once**, with Copy and Download buttons."),
    ("B7", "Receipt custody", "After B6 open DevTools > Application > Local storage and Session storage; look at the address bar.", "The receipt appears nowhere (not in storage, not in the URL)."),
]
M["C. My reviews: list, filters, paging"] = [
    ("C1", "Card content", "Open My reviews after creating a review.", "Each card shows destination, visit month, title, stars, created date, a status chip (icon **and** words) and its buttons."),
    ("C2", "Buttons by status", "Look at cards in different states.", "Pending / Changes requested: View, Edit, Withdraw. Published: View, Withdraw (no Edit). Rejected: View, Appeal (no Edit). Withdrawn: View only."),
    ("C3", "Status filter", "Choose Status = Published, then Waiting for moderation, then All.", "Only cards of that status appear; the address bar updates (`?status=`); the list restarts from the newest each time."),
    ("C4", "Destination filter", "Choose a destination.", "Only that destination's reviews appear (`?destination=`)."),
    ("C5", "Clear filters", "Set both filters, press Clear filters.", "Both reset and the full list returns."),
    ("C6", "Shareable filters", "Set a filter, copy the URL, open it in a new tab.", "The same filter is applied."),
    ("C7", "No match", "Choose a status you have no review in.", "\"No reviews match these filters\" with a link to browse destinations."),
    ("C8", "Empty account", "Sign in with an account that has no reviews.", "\"You have not written a review yet\" with a link to destinations."),
    ("C9", "Paging", "With more than 20 reviews, scroll to the bottom; press **Show more reviews** until it disappears.", "Each press adds the next reviews, newest first, with **no duplicates and no gaps**. At the end: \"That is all your reviews.\" A screen reader announces \"N more reviews loaded\"."),
    ("C10", "Paging with a filter", "Apply a filter, then Show more.", "More reviews of that filter only."),
    ("C11", "Order", "Compare the order with the created dates.", "Newest first. Reviews created at the same moment keep a stable order across pages."),
    ("C12", "Loading and error", "Throttle the network (DevTools > Network > Slow 3G), reload. Then stop the API and reload.", "A loading indicator first. With the API down: an error with a **Retry** button and a request id; Retry works when the API is back."),
    ("C13", "Offline", "Open My reviews, switch DevTools to Offline, change a filter.", "An offline notice and an error with Retry; the old list is not presented as current. Back online, Retry reloads."),
]
M["D. Review detail"] = [
    ("D1", "Open detail", "Press View on a card.", "Title, status chip, destination, visit month and version, rating, note, traveller type, comfort tier, language and category chips are shown."),
    ("D2", "Version history", "Edit a review once, then open its detail.", "The history lists every version newest first, e.g. \"Version 2 · PENDING\" and \"Version 1 · SUPERSEDED\"."),
    ("D3", "Photos and video", "Open a review that has media.", "Each file is listed with its state (pending, approved, rejected)."),
    ("D4", "Unknown id", "Open `/account/reviews/<random UUID>`.", "\"This review was not found.\" with a link back. The same text for another person's review (existence is not disclosed)."),
    ("D5", "Changes requested", "Open a review a moderator sent back.", "An amber notice says so and shows the moderator's reason; Edit is offered."),
    ("D6", "Rejected", "Open a rejected review.", "A red notice shows the reason and the appeal deadline with an Appeal link; no Edit."),
    ("D7", "Published", "Open a published review.", "No Edit; a line explains \"A published review cannot be edited. Withdraw it and write a new one.\""),
]
M["E. Edit a review (member)"] = [
    ("E1", "Prefilled form", "On a pending review press Edit.", "All fields are filled with the current values. A banner explains that saving creates a new version and sends the review back to moderators."),
    ("E2", "Save needs a change", "Open Edit and change nothing.", "Save is disabled; a hint says it turns on when something changes."),
    ("E3", "Only changed fields are sent", "Change only the title. Open DevTools > Network and Save.", "The `PATCH /reviews/{id}/pending` body contains only `expected_version` and `title`."),
    ("E4", "Result", "After saving.", "You return to the detail page with \"Saved as version 2 … waiting for moderation again\"; history shows two versions."),
    ("E5", "Validation", "Make the note 5 characters; Save.", "An inline error under the note; nothing is sent; focus moves to the field."),
    ("E6", "Clear categories", "Set all categories to Not applicable; Save.", "The detail page shows no category chips (the body had `category_ratings: {}`)."),
    ("E7", "Version conflict", "Open Edit in two tabs. Save in tab 1. Then Save in tab 2.", "Tab 2 shows \"This review changed while you were editing. Reload…\"; the text you typed stays; **Reload** loads the other tab's version."),
    ("E8", "Month collision", "With two reviews of one destination, edit one to the other's visit month.", "The visit month field shows \"You already have a review of this destination for that month\"; nothing changes."),
    ("E9", "Locked state", "Open the edit URL of a published review.", "\"This review can no longer be edited in its current state.\" The form is not shown."),
    ("E10", "Cancel", "Change a field, press Cancel.", "You return to the detail page; nothing was saved."),
    ("E11", "Another member", "Sign in as a different member and open the first member's edit URL.", "\"This review was not found.\""),
    ("E12", "Session expired", "Delete the session cookie in DevTools, press Save.", "A sign-in prompt or error; your typed text is not lost silently."),
]
M["F. Request changes (staff app) and the author's response"] = [
    ("F1", "Option offered", "In the staff app claim a pending review.", "The decision buttons are **Publish, Reject, Ask for changes**."),
    ("F2", "Reason list", "Choose Ask for changes.", "A reason list appears (remove personal information, add more detail, fix language or spelling, check destination or month) and a note says the author can read the reason."),
    ("F3", "Submit", "Submit the decision.", "\"Done: CHANGES_REQUESTED\". The item leaves the queue."),
    ("F4", "Author sees it", "As the author open My reviews and the review's detail.", "Chip \"Changes requested\"; the detail page shows the reason; Edit and Withdraw are available. The notification bell has a new item \"Your review needs changes\" linking to My reviews."),
    ("F5", "Resubmit", "Author edits and saves.", "The review is \"Waiting for moderation\" again and is back in the staff queue with the new text."),
    ("F6", "Not offered again", "In the staff app, open a review that is already CHANGES_REQUESTED or PUBLISHED.", "\"Ask for changes\" is not offered (published: only Hide; changes requested: no decision)."),
    ("F7", "Publish", "Moderator publishes the resubmitted review.", "The author's card shows Published without an Edit button. The review appears on the destination page."),
]
M["G. Withdraw (member)"] = [
    ("G1", "Confirm first", "Press Withdraw on a card or detail page.", "\"Withdrawing removes the review. Are you sure?\" with Yes and Cancel."),
    ("G2", "Cancel", "Press Cancel.", "Nothing changes."),
    ("G3", "Confirm", "Press Yes, withdraw.", "\"Review withdrawn.\" The chip becomes Withdrawn and Edit disappears. A published review disappears from the destination page and the rating count drops by one."),
    ("G4", "Retry safety", "Press Yes twice quickly, or repeat the request from DevTools.", "No error and no second change (a repeat answers success)."),
    ("G5", "Stale version", "Withdraw in tab 1, edit nothing; in tab 2 (still showing the old state) press Withdraw.", "The list or page reloads with the current state; no crash."),
]
M["H. Guest: receipt, edit, withdraw, appeal"] = [
    ("H1", "Check status", "On `/reviews` scroll to \"Check a review with its receipt\". Enter the review ID and receipt. Press Check status.", "\"Waiting for moderation\"; Edit and Withdraw are offered. A wrong receipt gives \"The receipt does not match\" (no detail about the review)."),
    ("H2", "Bad format", "Enter a receipt of `abc`.", "A format message; no request is sent."),
    ("H3", "Edit form", "Press Edit review.", "The form starts **empty** and says \"Fill in only what you want to change\"; Save is disabled."),
    ("H4", "Edit sends only what you touched", "Type a new title only; Save. Check the Network tab.", "The PATCH body has `receipt_secret`, `expected_version` and `title` only; **no cookie header and no CSRF token**; the receipt is not in the URL."),
    ("H5", "Edit result", "After saving.", "\"Saved. Your review is waiting for moderation again.\""),
    ("H6", "Rejected", "Moderator rejects it (reason spam). Press Check status.", "\"Rejected\", the reason, the appeal deadline (\"end of day, Bangladesh time\") and **Appeal this decision**. No Edit."),
    ("H7", "Appeal length", "Press Appeal; type 10 characters.", "Send appeal is disabled and the counter says \"at least 20\"."),
    ("H8", "Send appeal", "Type 20 to 2000 characters; Send appeal.", "\"Appeal sent. A different moderator will review it.\" Network: body has `review_id`, `receipt_secret`, `statement`; the URL has no receipt."),
    ("H9", "Status after appeal", "Press Check status.", "\"Appeal received\"; no second appeal offered."),
    ("H10", "Appeal outcome", "A second moderator overturns it (the original decider cannot).", "Check status shows \"Your appeal was accepted. The review is waiting again.\" and status Waiting for moderation."),
    ("H11", "Late appeal", "(Test database only) set the rejection date 32 days back; Check status.", "\"The appeal period has ended.\" No appeal form."),
    ("H12", "Guest withdraw", "Press Withdraw review, confirm.", "Status Withdrawn."),
]
M["I. Public review list filters (destination page)"] = [
    ("I1", "Filter bar", "Open a destination that has reviews.", "A filter bar appears (Rating, Author, Sort by, With photos or video) and says \"Showing X of the N loaded reviews\"."),
    ("I2", "Rating", "Choose 5 stars, then 1 star.", "Only reviews of that exact rating are shown; with none, \"No loaded review matches these filters\"."),
    ("I3", "Author", "Choose Members, then Guests.", "Only that kind of author is shown (guests appear as \"Anonymous guest · tag\")."),
    ("I4", "Photos", "Tick With photos or video.", "Only reviews with approved media."),
    ("I5", "Sort", "Choose Highest rating, then Lowest rating, then Newest.", "The order changes accordingly; equal ratings keep newest-first."),
    ("I6", "Combine and clear", "Combine two filters, press Clear filters.", "All filters reset."),
    ("I7", "Honest scope", "With more reviews than one page, read the line under the bar.", "It says the filters apply to loaded reviews and to press Show more to load more."),
    ("I8", "Counts unaffected", "Apply filters and compare the Guest Feedback line above.", "The rating summary is unchanged (filters only change which loaded reviews are listed)."),
]
M["J. Language, accessibility, layout, security"] = [
    ("J1", "Bangla", "Press the language button (Bangla) on My reviews, detail, edit and the receipt panel.", "All labels, buttons, errors and notices are Bangla; no English fragments except codes (statuses from the server such as a reason code)."),
    ("J2", "Keyboard only", "Use Tab, Shift+Tab, Enter, Space, Esc through My reviews, the edit form and the appeal form.", "Logical order, visible focus, every control reachable, no keyboard trap."),
    ("J3", "Screen reader", "With NVDA (Windows) or TalkBack (Android) read the list and the edit form.", "Status chips are read as words; errors are announced; the star rating is a radio group with \"N stars\"; \"N more reviews loaded\" is announced."),
    ("J4", "Phone width", "Set the window to 360 px wide.", "No horizontal scroll; the top bar fits (the brand word is hidden below 420 px, the logo stays); buttons are at least 44 px tall."),
    ("J5", "Desktop width", "Set 1280 px.", "The list is centred, readable, with no overlap."),
    ("J6", "Dark theme", "Switch to the night theme.", "Chips, notices, counters and form errors stay readable."),
    ("J7", "Zoom", "Zoom the browser to 200 percent.", "Content reflows; nothing is cut off."),
    ("J8", "CSRF", "In the console run a member write without the token (e.g. fetch the PATCH without `X-CSRF-Token`).", "403 `CSRF_INVALID`; nothing is changed."),
    ("J9", "No private data cached", "Open My reviews, go offline, reload (DevTools > Application > Service workers if present).", "Private pages are not served from a cache."),
    ("J10", "Console clean", "Watch the browser console while using every screen.", "No red errors."),
    ("J11", "Many tabs", "Open six tabs of the app at once (development only, API on http://localhost:8000).", "Observation: each tab holds a live notification stream; Chrome's limit of 6 connections per host over HTTP/1.1 can make requests wait. This does not happen through the production proxy (HTTP/2)."),
]
M["K. Online project (real Supabase database): run on 30 October 2026"] = [
    ("K1", "API against the online database", "From `backend/`: `uv run uvicorn app.main:app --port 8000` (the repo's `.env` points at the online project). `cd frontend; npm run dev`, `cd staff; npm run dev`.", "`/api/v1/health/ready` returns ok. **Done: pass.**"),
    ("K2", "Signed-in session", "Open http://localhost:5173/account/reviews and http://localhost:5174 in the Chrome that has the extension.", "Both load with the existing superadmin session (TOTP verified). **Done: pass.** The supplied member password was refused, so the member-author view was tested as this account."),
    ("K3", "Guest round trip online", "Guest review, edit, Ask for changes, edit, Reject.", "Ends REJECTED at version 5 with reason spam; audit log has `review.request_changes` and `review.reject`. **Done: pass.**"),
    ("K4", "Member author controls online", "Create 3 reviews, page with limit 1, filters, detail, edit, stale edit, clear categories, self-moderation, withdraw, retry.", "All results as in section 3a. **Done: pass.**"),
    ("K5", "Anonymous access control online", "Call 9 protected routes and a staff claim without a cookie.", "All answer 401 AUTH_REQUIRED. **Done: pass.**"),
    ("K6", "Guest appeal online", "Reject a guest review, appeal it.", "**Not run online on purpose:** the appeal would stay open in the real staff queue and only a second staff member can close it (the person who rejected cannot). Verified on the local stack (checks GU9 to GU11) and the database change is live (migration 0018)."),
    ("K7", "Publish online", "Publish a test review.", "**Not run online on purpose:** it would make test text public on a real destination. Verified on the local stack (P1 to P3, F1 to F4)."),
    ("K8", "Member request-changes round trip online", "Moderator asks for changes on a member's review; the member edits.", "**Needs a second account:** the superadmin cannot moderate their own review (verified: `SELF_MODERATION_FORBIDDEN`). Verified on the local stack (R1 to R4)."),
]


def main() -> None:
    passed = sum(1 for r in RESULTS if r["pass"])
    doc = Doc(
        "Review Frontend: Manual Test Cases",
        "Review form, My reviews list, filters, edit, withdraw, guest appeal and the staff \"Ask for changes\" decision (Gantt R09)",
        [
            ("Project", "Abhijatri (Team ChoturMatra, CSE 3102)"),
            ("Scope", "Public app `frontend/` and staff app `staff/`: `/reviews`, `/account/reviews`, `/account/reviews/:id`, `/account/reviews/:id/edit`, the receipt panel, the destination review list, and the staff decision form"),
            ("Version", "1.0, 30 October 2026"),
            ("Built against", "API contract `Docs/api/API.md` sections 5.3 to 5.6 and 5.5a; guide `Docs/Review-Edit-Appeal-UIUX.md`"),
            ("Automated result", f"{passed} of {len(RESULTS)} local browser checks and 14 online checks passed; 95 + 28 + 19 unit tests pass"),
            ("Credentials", "None are written in this document. Use your own test accounts."),
        ],
        "Abhijatri: Review frontend test cases",
    )
    doc.contents()

    doc.h1("1. What was built")
    doc.table(
        ["Area", "What it does", "Where"],
        [
            ["My reviews", "Paged list of the signed-in member's own reviews, newest first, with status and destination filters kept in the URL, a loading, empty, error (with Retry and request id) and offline state, \"Show more\" with a screen-reader announcement", "`pages/MyReviewsPage.tsx`"],
            ["Review detail", "Content, version history, media states, rejection or change-request reason, appeal state, Edit and Withdraw", "`pages/ReviewDetailPage.tsx`"],
            ["Edit a review", "One form for members (diff against the loaded review) and guests (only touched fields); only changed fields are sent; conflict, locked-state, month-collision and validation handling", "`components/reviews/ReviewEditForm.tsx`, `pages/ReviewEditPage.tsx`, `utils/reviewAuthor.ts`"],
            ["Author controls", "Edit only while PENDING or CHANGES_REQUESTED; withdraw with confirmation; appeal a rejection (guest, by receipt)", "`ReceiptStatusPanel.tsx`, `MyReviewsPage.tsx`"],
            ["Public list filters", "Rating, author type, photos and sort on the destination review list (applied to the loaded reviews, and the page says so)", "`ReviewFeedSection.tsx`"],
            ["Staff", "\"Ask for changes\" decision with reasons", "`staff/src/logic.ts`, `screens/Queue.tsx`"],
            ["API layer", "`getMyReviews`, `getReview`, `editMemberReview`, `editGuestReview`, `withdrawMemberReview`, `appealRejectedReview`", "`api/reviews.ts`"],
            ["Other fixes found by testing", "Top bar no longer overflows at 360 px; the create form no longer says category ratings are unsupported; the CI secret check lists the new Word documents", "`Navbar.tsx`, `api/reviews.ts`, `.github/scripts/check_committed_secrets.py`"],
        ],
        [3.2, 9.4, 3.9], caption="Delivered work", size=8.4,
    )

    doc.h1("2. How to run everything")
    doc.h2("2.1 Local stack (safe, nothing online is touched)")
    doc.steps([
        "Start Docker Desktop and the local Supabase stack (`supabase start` in the repo). Check `docker ps` shows `supabase_db_Abhijatri`.",
        "In `backend/`, load the local settings and migrate: `set -a; . ./.env.local-backup; set +a` then `uv run alembic upgrade head` (must report `0018_review_crud`).",
        "Start the API in the same shell: `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`. Check `http://localhost:8000/api/v1/health/ready`.",
        "Start the public app: `cd frontend; npm run dev -- --port 5173`. Start the staff app: `cd staff; npm run dev -- --port 5174`.",
        "Create a member and a moderator in local Supabase Auth (admin API or the register page plus Mailpit at http://localhost:54324). Give the moderator the role: insert a row into `user_roles` (`role = 'moderator'`), then enrol an authenticator in the staff app (staff accounts need a TOTP code).",
        "Make sure at least two published destinations exist (`backend/scripts/seed_destinations.py`).",
    ])
    doc.h2("2.2 Against the online project")
    doc.p("Use the repo's own `backend/.env` (online Supabase). Everything you do is real data: use your own accounts, create only a few reviews and withdraw them. The online database is already at migration 0018. The moderator account is a superadmin with an authenticator, so you need a live 6-digit code.")
    doc.h2("2.3 Automated browser run (optional)")
    doc.p("`Docs/diagrams/e2e/review-author.e2e.mjs` drives Chrome through sections B to I and prints PASS or FAIL per check. It needs `npm i puppeteer-core`, the local stack above and the moderator's TOTP secret in the `TOTP_SECRET` environment variable; the four account values are command-line arguments (never stored in the file).")
    doc.code("""cd Docs/diagrams/e2e
npm i puppeteer-core
TOTP_SECRET=<base32 secret> node review-author.e2e.mjs <memberEmail> <memberPassword> <modEmail> <modPassword>""")

    doc.h1("3. Automated results (final run)")
    rows = [[r["id"], r["name"], "PASS" if r["pass"] else "FAIL"] for r in RESULTS]
    fills = {(i, 2): (GREEN if r["pass"] else RED) for i, r in enumerate(RESULTS)}
    doc.table(["ID", "Check", "Result"], rows, [1.6, 12.6, 2.3], caption=f"Browser checks ({passed} of {len(RESULTS)} passed)", size=8.2, fills=fills)
    doc.table(
        ["Suite", "Result"],
        [
            ["Public app unit tests (`frontend`)", "95 passed (64 before this work; +31 for the author rules and API calls)"],
            ["Staff app unit tests (`staff`)", "28 passed (24 before; includes the queue refresh timing)"],
            ["Ops app unit tests", "19 passed"],
            ["Builds and type check", "All three apps build; `tsc` clean; the public build contains no staff or ops code"],
        ],
        [6.5, 10.0], caption="Unit tests and builds", size=8.6,
    )

    doc.h2("3a. Online results (real Supabase database, 30 October 2026)")
    doc.p("Run through the Chrome extension in the signed-in superadmin session, against the local API with the repo's online settings. Every test review was withdrawn or rejected; none was published. A stray review from one timed-out request was found in the queue and rejected.")
    online = [
        ["ON1", "Guest review is created (201, PENDING) and is in the moderators' queue as soon as it is committed", "Pass"],
        ["ON2", "Guest edit, moderator Ask for changes, guest edit again, moderator Reject end at REJECTED, version 5, reason spam", "Pass"],
        ["ON3", "Audit log holds review.request_changes and review.reject for that review", "Pass"],
        ["ON4", "Five recent outbox events were all processed on the first attempt, 0.5 to 2.4 seconds after creation", "Pass"],
        ["ON5", "Member: 3 reviews created (201); `GET /reviews/mine?limit=1` returns 3 pages, 3 unique reviews", "Pass"],
        ["ON6", "A made-up cursor and a public-feed cursor are refused (422 INVALID_CURSOR); limit 51 is refused (422)", "Pass"],
        ["ON7", "Status filter PENDING returns only pending reviews; owner detail shows version, revisions and categories", "Pass"],
        ["ON8", "Edit title: 200, version 2, revision 2; stale version: 409 REVIEW_VERSION_CONFLICT; empty body and null title: 422", "Pass"],
        ["ON9", "Clearing categories sends {} (200, version 3); history reads SUPERSEDED > SUPERSEDED > PENDING", "Pass"],
        ["ON10", "A moderator cannot publish their own review: 403 SELF_MODERATION_FORBIDDEN", "Pass"],
        ["ON11", "Withdraw x3: 200 WITHDRAWN; retry 200 (idempotent); edit after withdraw 409 INVALID_TRANSITION; withdrawn reviews leave the queue and appear under the WITHDRAWN filter", "Pass"],
        ["ON12", "Anonymous calls to /admin/queue, /admin/audit-events, /admin/notification-outbox, /admin/staff, /reviews/mine, /reviews/{id}, /appeals/mine, /notifications, /ops/overview and a staff claim: all 401 AUTH_REQUIRED", "Pass"],
        ["ON13", "The real UI shows the withdrawn reviews with a Withdrawn chip and only a View button", "Pass"],
        ["ON14", "A guest create returned 504 REQUEST_TIMEOUT (15 s limit) from this machine yet still created the review", "Observation: see section 5"],
    ]
    doc.table(["ID", "Check", "Result"], online, [1.6, 12.4, 2.5], caption="Online checks", size=8.2, fills={(i, 2): (GREEN if r[2] == "Pass" else AMBER) for i, r in enumerate(online)})

    doc.h2("3b. Manual cases run in the signed-in Chrome (online database, 30 October 2026, second run)")
    doc.p("Every case below was driven through the real screens of the running app (local front end and API, online Supabase database) in the Chrome that holds the superadmin session. Test reviews were withdrawn afterwards; none was published, and the queue is empty.")
    run = [
        ["A4", "/account redirects to /account/reviews", "Pass"],
        ["B1, B1b", "Member form creates a review (POST /reviews/member 201) and shows the receipt panel", "Pass"],
        ["B2, B3", "Empty submit lists five field errors; a future month is refused", "Pass"],
        ["B4", "Food 4 and Safety 5 are sent and stored when rated one after another", "Pass (see finding 10)"],
        ["B5", "Same destination and month again: 409 and the message \"You already have a review of this destination for that month\"", "Pass"],
        ["C1 to C7, C10, C11", "Card content, buttons, status and destination filters, Clear filters, URL carries the filter, no-match message, order newest first", "Pass"],
        ["D1, D2, D4, D7 (withdrawn)", "Detail page, version history 3, 2, 1 (newest first), unknown id shows not found, no Edit or Withdraw on a withdrawn review", "Pass"],
        ["E1 to E8, E9, E10", "Prefilled form, Save disabled until a change, only changed fields sent, Saved as version 2, short note blocked, all categories cleared sends {}, stale save gives the conflict message, month collision shows the field message, locked review cannot be edited, Cancel saves nothing", "Pass"],
        ["G1 to G4", "Confirm, Cancel, withdraw (message \"Review withdrawn.\"), repeat withdraw is safe", "Pass"],
        ["H1 to H5, H12", "Receipt check, bad format refused, edit form, PATCH carries only receipt_secret, expected_version and title, saved message, withdraw by receipt", "Pass"],
        ["I1 to I8", "Filter bar, rating, author (guests shown as Anonymous), photos, sort, combine and clear, scope line, rating summary unchanged", "Pass"],
        ["J1", "Bangla on My reviews, detail, edit and create: no English text", "Pass"],
        ["J4", "360 px width: create page was 16 px too wide; fixed in CategoryRatings; now no horizontal scroll on the five pages", "Pass after fix"],
        ["J8", "Write without the CSRF token: 403, nothing changed", "Pass"],
        ["F1 to F7, H6 to H11, K6 to K8", "Need a second account or a moderator decision on someone else's review (the superadmin cannot moderate own reviews); not repeated here. Passed on the local stack", "Not run online"],
        ["A1 to A3, A5, A6, B6, B7, C8, E11", "Need signing out or a second account; signing out would end the session you asked me to keep", "Not run"],
        ["C9, C12, C13, D3, D5, D6, E12, J2, J3, J5, J7, J9, J10, J11", "Need DevTools throttling or offline switching, more than 20 reviews, a rejected or changes-requested review, cookie deletion, a screen reader, window resizing or zoom; a person must do these", "Not run"],
    ]
    doc.table(["Cases", "Checked", "Result"], run, [3.2, 10.6, 2.7], caption="Second manual run", size=8.2, fills={(i, 2): (GREEN if r[2].startswith("Pass") else AMBER) for i, r in enumerate(run)})

    doc.h1("4. Manual test cases")
    doc.p("Fill the Result column with Pass, Fail or Blocked and note the request id of any failure. Cases are grouped so each section can be run on its own. IDs in the automated table are not the same as these IDs; the automated run covers most of B to I.")
    total = 0
    for title, cases in M.items():
        doc.h2(title)
        rows = [[cid, name, steps, expected, ""] for cid, name, steps, expected in cases]
        total += len(rows)
        doc.table(["ID", "Case", "Steps", "Expected result", "Result"], rows, [1.0, 2.6, 5.8, 5.9, 1.2], size=8.0)
    doc.p(f"Total: {total} manual cases.", bold=True)

    doc.h1("5. Findings from testing")
    doc.table(
        ["#", "Finding", "Type", "Status"],
        [
            ["1", "At 360 px the shared top bar was 405 px wide, so every page scrolled sideways", "Layout defect (existing)", "Fixed: brand word hidden below 420 px; re-tested (case J4)"],
            ["2", "The create form said \"category ratings are not stored by the server yet\" although the server accepts them", "Stale text", "Fixed: sent by default; set `VITE_REVIEW_CATEGORY_RATINGS=false` to disable"],
            ["3", "The repo's secret check would fail on the new Word documents", "CI", "Fixed: documents scanned for credentials and listed in `ALLOWED_DOCUMENTS`"],
            ["4", "`POST /reviews/member` is limited to 20 per hour per address", "Observation", "Working as designed; use the database seed for bulk data"],
            ["5", "Each open tab keeps a live notification stream; six tabs can stall requests over HTTP/1.1 in development", "Observation", "Not an app fault; production uses HTTP/2. Case J11"],
            ["6", "Public list filters apply only to the reviews already loaded", "Limit", "Stated on the page. A server-side filter would need an API change (not in R07)"],
            ["7", "The staff queue and inbox refreshed only every 30 seconds, so a new review could wait that long on a moderator's screen", "Delay", "Fixed: queue every 5 s, inbox every 10 s while the tab is visible, plus an immediate refresh when the tab or window is focused; unit-tested"],
            ["8", "At 360 px the create page was 16 px wider than the screen because the category rating rows could not shrink", "Defect", "Fixed: the row now wraps on small screens (`CategoryRatings.tsx`). 320 px is still 7 px over (below the 360 px target)"],
            ["9", "A published member review on the Cox's Bazar page shows the author's email address as the name (an old review from 27 October)", "Privacy", "Fixed: the public feed withholds any author name that contains @ (the page says Member), and sign-up now refuses an email-shaped display name (API and form). Unit tests added"],
            ["10", "Two category stars clicked in the same instant (a script, not a person) keep only the last one", "Observation", "Not reproducible by a person; clicked one after another both are kept. A functional state update would remove the risk"],
            ["11", "From this machine the local API is slow against the online database (0.7 to 2 s for a list, 2 to 7 s for a decision) because each query pays the 54 to 78 ms internet round trip; the deployed API answers in 0.28 s", "Observation", "Not a code fault. Keep the API in the same region as the database (it is). A 504 here after the 15 s limit still left the review created; a retry with the same draft id returns the existing review"],
        ],
        [0.8, 8.6, 3.0, 4.1], caption="Findings", size=8.4,
    )

    doc.h1("6. What was not tested, and why")
    doc.bullets([
        "**The Claude Chrome extension** was connected only for the last part of the session. The 59 local checks used the installed Chrome driven through `puppeteer-core`; the online checks used the extension.",
        "**The online project, partly.** The supplied online member password was refused (`INVALID_CREDENTIALS`), so the member-author checks ran as the signed-in superadmin account. Publishing, the guest appeal and a member request-changes round trip were not run online (section K6 to K8); they pass on the local stack.",
        "**Screen readers, real phones, Safari and Firefox**: not run. Cases J3 and J4 need a person and a device.",
        "**Photo and video upload** from the edit screen: not added (media upload remains on the create form; the detail page shows media states).",
        "**Published-review editing**: intentionally absent (Review.md 5.2).",
    ])

    doc.h1("7. Phase completion checklist")
    doc.p("Gantt R09, \"Build review form, list, filters and author controls\" (depends on R05 and R07), and the other UI and UX tasks of the plan.")
    done, part, no = GREEN, AMBER, RED
    phases = [
        ["R09 Review form", "Structured form for guest and member, seven category ratings (now sent by default), receipt shown once, member media upload", "Done", "Checks C1, GU1, GU2, B1 to B7"],
        ["R09 Review list", "My reviews list with paging; public destination review list; status chips with text", "Done", "G1 to G6, L1 to L3, ON5 to ON7"],
        ["R09 Filters", "My reviews: status and destination (server side, in the URL). Public list: rating, author, photos, sort (on loaded reviews)", "Done (public filters are client-side)", "F1 to F4, G4 to G6, I1 to I8"],
        ["R09 Author controls", "Edit while unpublished (member and guest), withdraw with confirmation, guest appeal, version history, conflict handling", "Done", "E1 to E8, W1 to W4, GU3 to GU11, ON8 to ON11"],
        ["R09 Staff decision", "Ask for changes in the staff queue", "Done", "M1, M2, R1 to R4, ON2"],
        ["R03 Destination UI", "Bilingual destination list and detail", "Done earlier (19 Oct)", "Frontend-Implemented.md"],
        ["R05 Account UI", "Sign in, register, verify, reset, verification, appeals, notifications", "Done earlier", "Frontend-Implemented.md"],
        ["H02 Review UX", "Transparency, filtering, rating explanation", "Partly: filters and the rating rules exist; no new explanation screen", "I1 to I8"],
        ["H09 Accessibility", "Keyboard, readability, responsive, Bangla rendering", "Partly: labels, tap targets, 360 px, Bangla checked; screen reader and real-device checks open", "X1 to X4, J1 to J7"],
        ["R12, R13, R15 Offline", "Installable PWA, offline packs, offline drafts", "Not built (prototype screens only)", "SRS completion 4.4"],
        ["E08, E09 Estimator UI, saved trips", "Cost estimate screens", "Prototype only", "SRS completion 4.4"],
        ["MD03 Media frontend", "Upload, retry, status, removal", "Upload on the create form and media states on the detail page; no removal or retry screen on the edit page", "B1, D3"],
        ["Extension: community, tourmates, vendors, payment", "CM03, TM03, VB03, PY03", "Not started (extension scope)", "Gantt"],
    ]
    fills = {}
    for i, r in enumerate(phases):
        s = r[2]
        fills[(i, 2)] = done if s.startswith("Done") else (part if s.startswith("Partly") or s.startswith("Upload") or s.startswith("Prototype") else no)
    doc.table(["Task", "What it covers", "Status", "Evidence"], phases, [3.2, 6.4, 4.1, 2.8], caption="Frontend phases against the Gantt plan", size=8.2, fills=fills)

    doc.h1("8. Sign-off")
    doc.table(["Done", "Check"], [["[  ]", c] for c in [
        "Sections A to J run on the local stack; every case Pass or noted",
        "Section K reviewed (the online run is done; K6 to K8 were skipped on purpose)",
        "No red errors in the console (J10)",
        "No private text (receipt, password) in URLs, storage or logs (B7, H4, H8)",
        "Tester: ____________   Date: ____________",
    ]], [1.4, 15.1])
    doc.save(OUT)
    print("saved", OUT, f"{total} manual cases, {passed}/{len(RESULTS)} automated")


if __name__ == "__main__":
    main()
