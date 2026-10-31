# Abhijatri Implementation Decisions

This log records build-time decisions without reopening the frozen Review specification.

## 2026-10-31 (Hidden reviews and the rating)

| Decision | Rule | Reason |
|---|---|---|
| Hidden reviews and the rating (owner) | A hidden review is removed from the rating by default (Review.md line 476 stands). A takedown opened with `counts_toward_rating: true` keeps the review's counted rating, for a genuine review hidden only for a privacy problem. Plain `HIDE` from the queue always removes it. Wiring the flag into the rating delta path is Moderation spec P-00. | The owner's 22 Oct draft wanted every hidden review counted. Counting abusive or fake ratings that nobody can see would distort the score. |

## 2026-10-28 (Unavailable features and bilingual fixes)

| Decision | Rule | Reason |
|---|---|---|
| Features without a backend | Planner, offline packs and saved trips show `FeatureUnavailable` (what it will do, its Gantt task, what works today) and stay in navigation with a "Soon" tag. No invented data, no calls to missing APIs. | QA_UI_UX 1 and 2; "no fake live claims" (Gantt C08). |
| Language-scoped typography | English font and tracking apply only to text that is itself English; Bangla is never tracked. | UI-Architecture U1, U16; measured -0.93 px on Bangla. |
| Guarded preference storage | Language and theme preferences use `utils/safeStorage.ts`; a blocked store falls back to defaults for the session. | UI-Architecture U12 (blocked storage blanked the app). |

## 2026-10-28 (Notification system v1.1)

Implements `Docs/Notification-Documentation.md` in full (owner request, 28 Oct 2026). Details: API.md 5.21, Schema.md, the spec's own section 15.

| Decision | Rule | Reason |
|---|---|---|
| Reuse the shared outbox | `outbox_events` gains the spec 7.1 fields (`dedupe_key`, `aggregate_type`, `aggregate_version`, `recipient_policy`, `occurred_at`, `lease_owner`, `last_error_code`, statuses `processed`/`retry`/`dead_letter`) instead of a second `notification_outbox`. | Spec 7 says to reuse existing tables; the outbox already commits with every decision. |
| Bilingual rows | A notification stores Bangla and English text side by side; templates are versioned per language. | The UI switches language without a refetch. |
| Catalogue in code | Events, recipient resolvers, routes and allowed template variables live in `app/notify/registry.py`; the database can only tune priority, email and on/off (`notification_rules`) and add template versions. | Spec 3 and 7.7: a controlled registry, no executable rules from the database. |
| Staff notices | Staff recipients are captured when the event happens and re-checked for their current role; staff items are hidden once the role is gone; the role-revoked notice itself is a member notice so it still arrives. | Spec 5. |
| Email modes | Critical and high-priority notices are emailed at once and cannot be switched off; standard ones follow the person's preference (immediate, daily digest at their local time, default 08:00 Asia/Dhaka, or off). | Spec 2, 6.5, 7.8. |
| Retries | About 1 min, 5 min, 30 min and 2 h with ±10 % jitter, then `failed_permanently`; a timeout or a worker lost mid-send is `ambiguous` and is only resent by a superadmin after checking. | Spec 8: no blind resends, no exactly-once claim. |
| Addresses | Deliveries and suppressions keep an HMAC of the address (`crypto.EMAIL_DESTINATION_LABEL`), never the address; monitoring views show a prefix of it. | Spec 7.3, 7.9. |
| Provider webhooks | Resend (Svix signature) and Brevo (bearer token), 5-minute replay window, stored once per provider event id; switched off (404) until a secret is configured. | Spec 9. |
| Supabase access | No table is readable from the browser: RLS on everywhere and no grants to `anon`/`authenticated`; the API checks ownership. | Stricter than spec 10's "members read their own rows"; the browser talks only to the API (PF 8.1). |
| Task assignment | Superadmins can assign a task (`POST /admin/tasks/{id}/assign`) so the "task assigned/unassigned/appeal assigned" notices have a workflow. | Spec 3 moderator events. |
| Not emitted | `verification.expired` and `account.removal_requested` have no workflow in v1. | Spec 3 marks the second "only if this workflow exists". |
| Gmail API provider (owner) | `EMAIL_PROVIDER=gmail` sends through the Gmail API over HTTPS with an OAuth refresh token (scope `gmail.send` only), from the authorising Gmail address; about 500 recipients a day. One-time token: `python -m app.jobs.gmail_authorize`. | Railway blocks outbound SMTP below the Pro plan and the Brevo account is under review (28 Oct 2026). |

## 2026-10-27 (Member accounts on Supabase Auth, staff roles, moderation API)

Implements Gantt R04 and R05 and the first phases of `Docs/Moderation-Dashboard-Specification.md`. Owner choices of 27 Oct 2026 are marked "owner".

| Decision | Rule | Reason |
|---|---|---|
| Identity provider (owner) | Supabase Auth (GoTrue) provides registration, email verification, sign-in, reset and TOTP. **This deviates from Platform Foundation 8.1** ("first-party auth, no Supabase Auth"); the moderation specification (3.1, 4.1) asks for it. The browser still never calls Supabase: the API proxies it, so no Supabase key reaches a browser (PF 3). | The owner chose the specification's design. Local development runs the real stack with the Supabase CLI (Auth, Postgres, Storage, mail inbox). |
| Sessions | The access and refresh tokens live only in `__Host-abhijatri_session` and `__Host-abhijatri_refresh` (`HttpOnly`, `Secure`, `SameSite=Lax`). The API refreshes an expired access token once per request. CSRF is a synchronizer token (`GET /auth/csrf`) on every cookie write, plus an exact `Origin` check. | PF 8.5 and 16.2, adapted to Supabase tokens. |
| One session cookie for members and staff | Staff are members with an active row in `user_roles`; the single cookie pair serves both. Authorisation reads the role from the database on every request. Staff also need TOTP (`aal2`). | The specification says members, moderators and superadmins share one authentication system (2.1). It replaces the two-cookie design in the earlier API.md draft. |
| Roles | `user_roles` (`moderator` or `superadmin`, one active role per user by a partial unique index) replaces `platform_roles` and `user_platform_roles` for authorisation. The "Administrator" role is dropped for v1. A single guard row serialises superadmin changes; the last superadmin cannot be removed. | Specification 2.2 and 6.1. |
| Staff API prefix and denial convention | `/api/v1/admin/*` replaces `/staff/*`. A non-staff caller gets `404`, a staff member of a lower role `403`, a stale version or lost lease `409`, an invalid transition `422` (new code `TRANSITION_NOT_ALLOWED`; the older review routes keep `409 INVALID_TRANSITION`). | Specification 2.4, 8.1 and 9. |
| Claim leases | A task claim lasts 5 minutes and is renewed by heartbeat. An expired lease can be taken over; the previous holder's next write is `409 LEASE_LOST`. A report task may hide or restore the review it names. | Specification 5. |
| Audit | `audit_events` is append-only (triggers refuse UPDATE, DELETE and TRUNCATE), not partitioned (so lookup by `id` is exact), and written in the same transaction as the change. Denied attempts are recorded as `denied.<action>`. | Specification 6.6 and 8.1. |
| Dev inbox | Verification and reset emails go to the local Mailpit inbox (http://127.0.0.1:54324). | Nothing leaves the machine while developing. |
| Production cookies | A same-site domain (PF 5.5) is still required: cookies set by the Railway API are not sent from a Vercel page on another site. Local development works because every port of `localhost` is the same site. | Browser rules; not fixable in code. |
| Verification evidence | Files go to the private Storage bucket `verification-evidence` through a one-time signed upload URL; staff see them through a 60-second link issued only to the person holding the case (or a superadmin), each view audited. Files are deleted 24 hours after approval and 30 days after rejection, never while an appeal is open. | Specification 3.3 and 10; Security 3.7. |
| Appeals | One appeal per decision (a withdrawn one may be filed again); deadline is the end of the 30th day after the decision in Asia/Dhaka; the original decider cannot decide it. An overturned rejection sends the review back to the queue rather than publishing it directly. | Specification 6.5. |
| Account emails sent by the API (owner) | `AUTH_EMAIL_DELIVERY=app`: verification, resend and reset tokens come from Supabase Auth's admin `generate_link`, which sends nothing; the API mails them through `EMAIL_PROVIDER` (Brevo in real use, 300/day free; Mailpit locally) after the response, so known and unknown addresses answer in the same time. A resend never changes the password. Supabase's own email rate limit no longer applies; this API's limits do (API.md section 7). | Owner, 27 Oct 2026: the built-in mailer allowed 2 emails an hour. |
| Live notifications | Server-Sent Events from the API (`GET /notifications/stream`) instead of Supabase Realtime, so the browser still talks only to the API and Realtime stays off. New items arrive in about 2 to 4 seconds. | Specification 3.4 (Realtime is a convenience) and PF 3. |
| Email | One outbox relay for moderation and notifications; critical notices are emailed at once, others in a daily digest at 08:00 Asia/Dhaka (accounts have no time zone of their own yet). Local inbox: Mailpit; production: Resend with idempotency keys. | Specification 6.7 and 11. |

## 2026-10-22 (Guest tag, Redis visit counters, ops dashboard token)

Implements `Docs/Guest-Identity-and-Visits.md` and `Docs/System-Monitoring-Dashboard.md` (phase 1). Owner choices of 22 Oct 2026 are marked "owner".

| Decision | Rule | Reason |
|---|---|---|
| Guest tag replaces Guest #N | Each browser's tag is `CrockfordBase32(SHA-256("abhijatri:guest-tag:v1
" + scope secret))[50 bits]`, shown `XXXXX-XXXXX`. The browser computes it for the badge; the server computes it in `POST /reviews/guest` and stores it in `reviews.guest_tag`. A client-sent tag is a 422. "Guest #N" and its storage keys are retired. | Unique, unguessable, needs no server list of guests, and nobody can post under another tag (Guest doc D1 to D3). |
| Unique identifier (owner) | The **guest tag** is the unique guest identifier. Typed guest display names may repeat. | Making names unique would need a server list of guest names, which the count-only rule forbids. |
| Guest session (owner) | The typed name is remembered for **30 days after the last visit**, then asked again. The tag, scope secret, receipts and visit dates stay, so the guest is not counted as new. Sign-out forgets the name only. | "Session cache for about one month" without inflating New Guest. |
| Visit counting | A visit is one visitor per Asia/Dhaka day; "new" is the first ever day. Counters live in Upstash Redis (`abj:{env}:visits:{date}`, 8-day TTL); finished days roll up into `visit_daily_stats` (numbers only). `guest_visits` is dropped; its totals moved to `guest_total_legacy`. `GET /guest-visits/stats` is removed from the public API. | Amends the Redis deferral (PF 32, "Scope control") for counters only. Old visits = A − B holds by construction. |
| Verified counts (owner) | `users.first_visit_on` / `last_visit_on` and the counting SQL exist now; they are wired to `GET /auth/session` with R04. Until then Verified is 0 and the dashboard says "member sign-in not built". | No sign-in exists yet; no fake numbers (Dashboard R5). |
| Ops dashboard (owner) | A separate `ops/` Vite app (own Vercel project, `noindex`). The API checks `OPS_DASHBOARD_TOKEN` (`Authorization: Bearer`, constant-time, ≥ 32 chars, 10 failures per network per hour then 429; unset = every `/ops` route 404). The browser keeps it in `sessionStorage`. Panels show aggregates only. | A private URL is not protection (Security 4.1). The token is not an identity and reads aggregates only, so it does not conflict with PF 25. Replaced by staff sign-in with MFA in phase 2 (R04, R11). |
| Guest name not public (owner) | On destination pages a guest review shows only "Anonymous guest · tag". `GET /destinations/{id}/reviews` returns `author_type` instead of `guest_display_name`; the name is kept for moderators (queue) and the guest's own welcome. The review form says the name is seen only by moderators. | The owner wants guests fully anonymous in public; the tag still links one guest's reviews. |
| Processor | Upstash (Redis, ap-southeast-1) holds aggregate counters only: no tag, secret, IP, user id or user agent. | Security 3.8 processor register. |

## 2026-10-20 (Production schema changes only through Alembic)

| Decision | Rule | Reason |
|---|---|---|
| No manual schema edits | Never create, alter or drop tables in the Supabase dashboard or SQL editor for the production database. Every schema change is an Alembic migration that runs on deploy (PF 22). `alembic_version` must never be touched. | On 20 Oct 2026, 14 tables, including `alembic_version`, were deleted by hand. The API returned 503 and every new deploy crash-looped. Recovery is recorded in `Docs/Backend-Implemented.md` 4.1. |
| What "nothing about guests in the DB" means | Only **guest** data is limited: originally `guest_visits(id, visited_at)`, now only daily aggregate counters (`visit_daily_stats`). The other tables (destinations, guides, advisories, contacts, reviews, receipts, ratings, rate limits, roles, audit) are the application itself and are required. | The scope owner's count-only rule applies to guest visitors, not to the platform's data. |

## 2026-10-20 (Guest sign-out ends that guest; numbers only increase)

A guest who had entered a name could not sign out: the sidebar showed only "Sign in", and the name could be cleared only through "Change name" on `/guest`. Member auth (R04) is on hold while the main features, RBAC and scalability come first, so this fix is guest-only and client-side.

| Decision | Rule | Reason |
|---|---|---|
| What sign-out does | "Sign out" (sidebar session card and `/guest`) forgets the guest's name, guest number and last-visit day, then opens `/`. It is shown only to a named guest. | A guest has no server session; all of this lives only on the device. |
| ~~Guest numbers only increase~~ **Superseded 21 Oct 2026** by the guest tag | The next guest on that browser registers a new visit (`POST /guest-visits`) and gets the next running number, even on the same day. A guest never sees an older number after someone signs out. | Muhtasim, 20 Oct 2026: "the guest number should increase always." `guest_visits.id` is an identity column, so the server number is monotonic. This refines "at most one visit per browser per day": a sign-out starts a new guest, which is a new visit. |
| What it keeps | `abhijatri_guest_scope` stays. "Change name" still keeps the number (same guest correcting a name). | The scope secret keeps duplicate-draft recovery and receipts working. |
| Members later | `SessionContext.signOut` is the one sign-out entry point; when R04 lands, the member branch also posts `/auth/logout`. | One control for both kinds of visitor. |

## 2026-10-20 (Guest footprint is a count only)

Scope owner (Shahriar Islam), 20 Oct 2026: "Guest er shudhu count rakhlei hobe … daily kotojon ashe. Ke ashe jana lagbe na." Only the number of guests per day is needed, not who they are. Community members, by contrast, must be identified (`Features/Community.md`).

| Decision | Rule | Reason |
|---|---|---|
| Guest storage **(superseded 21 Oct 2026: `guest_visits` is dropped; counters are in Upstash and `visit_daily_stats`)** | `guest_visits` holds only `id` (a running number) and `visited_at`. `POST /guest-visits` takes an empty body. No name, device id, hash, address or user reference is stored. Migration `0008` dropped the per-device digest table (and its single test row). | The scope owner's rule above. It **supersedes** the earlier "Guest counter digest" decision and the choice to keep one anonymous row per device. |
| Daily counting | Each browser reports at most one visit per Asia/Dhaka day and remembers the date locally. Stats group `visited_at` by Dhaka date. | "How many come each day" without identifying anyone. |
| ~~Guest #N~~ **Superseded 21 Oct 2026** by the guest tag | The number of the browser's first visit, kept on the device and reused. A new browser, incognito window or cleared storage is a new guest. | A friendly welcome with no server-side identity. |
| Abuse control | Per-network durable limit (60 per hour) and burst limit stay. The counters in `rate_limit_buckets` are keyed by a network digest and purged within 2 days; they are not guest data. | PF 14.5; stops scripts from inflating the count. |

## 2026-10-20 (Guest entry page, server-defined review parameters, Turnstile on the client)

| Decision | Rule | Reason |
|---|---|---|
| Guest entry | `/guest` asks for a name, which stays in `localStorage` only, then welcomes the guest by name with the device's guest tag (was the server's `Guest #N` until 21 Oct 2026). It is an entry point, never a gate; deep links still open directly. | Owner request; Execution.md rule 1; Review.md 3.2 step 1 ("local welcome message"). |
| Review parameters from the server | `backend/app/review_parameters.py` is the single source. `GuestReviewCreate` imports its limits and `GET /review-parameters` publishes them. A parity test fails if the two drift. The client renders from the API and falls back to its local labels offline. | The owner wants the parameters and rating rules in the backend; the frontend cannot drift from the validation. |
| Rating calculation | Unchanged from A2: an overall rating (required) plus the seven optional categories and a required note. The overall rating is never derived from the categories. The Community Rating Bayesian score (C = 3.5, m = 5, shown from 5 reviews) is now computed by the API (`community_rating.score`, `seeded_selection`). | Review.md 3.1, A2, 6.1 and 6.4; one implementation instead of one per client. |
| Turnstile on the client | The Guest review form renders Cloudflare Turnstile (action `guest-review`) when `VITE_TURNSTILE_SITE_KEY` is set, and remounts it after every attempt. | Production requires Turnstile (PF 14.1), and the live site was failing every submission with `403 CHALLENGE_FAILED`. |
| Video | **Built 27 Oct 2026** (owner): amendment A4 without transcoding. One MP4 per review (H.264 video, AAC audio, at most 60 s and 50 MiB). The server parses the MP4, rejects other codecs (`VIDEO_CODEC`, e.g. HEVC), and blanks metadata boxes and non-audio/video tracks in place as `free` boxes, so location and device data are removed without re-encoding or moving byte offsets. No poster image or low-bitrate rendition; the player uses `preload="none"` and never autoplays. | Owner, 27 Oct 2026: “I should now upload photo and video”. Transcoding needs ffmpeg and much more memory and CPU. |
| Who may attach media | **Any signed-in member** with a confirmed email, not only Verified Members (changes Review.md 8 and 12.3 “Only a Verified Member can create an image upload intent”). Guests stay text-only. Every file is still checked by the server and approved by a moderator before it is public. | Owner, 27 Oct 2026. |
| Media storage | Private bucket `review-media`: uploads go to `quarantine/` through a one-time signed URL; the server re-reads the object, re-encodes photos to WebP (long edge 2048 px, no EXIF/GPS) or strips the video, writes `processed/` and deletes the quarantine copy. The public feed shows approved media through signed links valid for one hour; staff get five-minute links. Abandoned uploads are purged after 24 hours by the retention job. | Review.md 8; keeps the bucket private and the Supabase key on the server. |
| Community | Design only: `Features/Community.md`. | Owner request: design now, so the build is faster later. |

## 2026-10-20 (Backend: category ratings and guest welcome counter)

| Decision | Rule | Reason |
|---|---|---|
| Category ratings storage | One `review_category_ratings` row per rated category per revision; "not applicable" is an absent row, never a zero. `{}` is treated as omitted. | Review.md 3.1 and A2; an absent row cannot be mistaken for a score. |
| Category aggregates | `destination_category_stats` per destination, category and audience (`GUEST` or `COMMUNITY`). It moves only inside `_remove_counted_rating` and `_add_published_rating`, so it always changes together with the overall rating and in the same transaction. Rows are locked in category order after the destination aggregate. | Review.md 6.1 to 6.3 (O(1) deltas, Guest and Community never merged); one code path means the two aggregates cannot drift. A property test compares both with a full recompute after random transitions. |
| Category averages in responses | Added as new fields (`category_ratings`, `category_averages`, `guest_category_averages`); no existing field changed. Only categories with a counted rating appear, in the Review.md order. | The current frontend keeps working unchanged; empty categories carry no claim. |
| Guest name | The name a guest types on the landing page stays on the device. `POST /guest-visits` took an empty body (see "Guest footprint is a count only"); since 21 Oct 2026 it takes exactly `{ "first_visit": bool }`. | Review.md 1.1 (a Guest has no account) and 3.2 step 1 (a local welcome message); no personal data on the server. |
| Guest counter digest | ~~`guest_visits.scope_hash` uses its own HMAC label `abhijatri:guest-visit:v1`, not the review scope label.~~ **Superseded the same day** by "Guest footprint is a count only": no digest is stored any more. | A visit row cannot be linked to the Guest's reviews. |
| Guest counter limits | In-memory burst `20/minute` plus a durable 60 per network per hour. The number is stable per device, so repeated calls are harmless. | PF 14.3 and 14.5 pattern for unauthenticated writes. |
| Frontend unchanged | This change touches no frontend file. `VITE_REVIEW_CATEGORY_RATINGS` remains the frontend's switch (and kill switch) for sending categories. | Requested by the project owner; the frontend owner wires the welcome view and category display. |

## 2026-10-20 (Landing page and sign-in entry)

| Decision | Rule | Reason |
|---|---|---|
| Landing page | `/` is a public landing page offering "Continue as guest" and "Sign in"; the app starts at `/overview`. It never gates app routes: deep links open directly. | A Guest browses without registration (Execution.md rule 1); shared destination links must keep working. |
| Sign-in before R04 | The sign-in form is shown disabled with a notice; nothing is submitted and no session is faked. | No account service exists; a working-looking login would be a false claim. |

**Scope requests raised on 20 Oct 2026, resolved the same day by the scope owner (Shahriar Islam).** Applied as dated amendments in `Features/Review.md` section 13.

| Request | Decision | Amendment |
|---|---|---|
| Verified Member status through NID or birth-registration number, ideally checked against a national verification API. | **Not adopted.** Verified Member stays a manually approved verification record; no NID, birth-registration number or national API is collected or called. | Review.md A3 (2.3 confirmed) |
| Reviews answer 15 fixed rated questions plus a free-text note. | **Replaced** by the seven frozen category ratings (each optional, 1 to 5) plus the required overall rating and a free-text note, for Guests and Members. The frontend builds it now; the backend adds `category_ratings` (API.md 5.2) with R07. | Review.md A2 (3.1) |
| Photos for Verified Members only, in semester scope. | **Adopted.** Verified Member image upload moves from conditional post-core into the mandatory release, with the section 8 limits unchanged. Guests remain text-only. | Review.md A1 (1, 2.1, 8, 12.1, 12.3); Security.md 8; Schema.md `review_media`; API.md media intents |

## 2026-10-20 (Review form: categories, note, photos)

| Decision | Rule | Reason |
|---|---|---|
| Category ratings in the form | The form shows the seven categories with a one-line prompt each; "Not applicable" is the default. The overall rating stays the only required score. | Review.md 3.1 and A2. Prompts make a rating mean the same thing to every reviewer. |
| Sending category ratings | `category_ratings` is sent only when `VITE_REVIEW_CATEGORY_RATINGS=true`. Until then the form says the server does not store them yet. | The API forbids unknown fields; sending early would make every submission fail with `422 UNKNOWN_FIELD`. |
| Photos in the form | Guests see a locked notice and no file input. Verified Members get a picker (JPEG/PNG/WebP, 8 MiB, 20 MP, five photos, alt text and ownership declaration required). Upload uses media intents once they exist. | Review.md 8 and A1; PF 20 alternatives for images. |
| Session state | `SessionContext` says who is using the app. It is guest-only until R04 and can only be filled from the server. It shapes the interface and is never an authorization boundary. | Review.md 1.1 ("every page and API requires server-side authorisation"). |
| Frontend unit tests | Vitest runs with `npm test`; CI already runs it when the script exists. | PF 27 item 5. |
| Review language | The declared `language` is detected from the script of the title and note (Bengali, Latin, or at least 20 % of each for `MIXED`), never from the interface language. A reviewer's explicit choice overrides detection. Review text is never translated. | Gantt R09 "Reviews remain in submitted language"; Review.md 3.1 original language. |

## 2026-10-19 (Frontend integration: R03, R09 Guest path, R01 seed content)

| Decision | Rule | Reason |
|---|---|---|
| Real data only on integrated screens | Overview, Destinations, destination detail and Reviews read the API. Prototype data moves to `frontend/src/data/prototypeDestinations.ts` and is used only by the planner, offline-packs and saved-trips screens until E08, R13 and E09. | Proposal "no fake live claims"; Review.md 6 forbids showing ratings that do not exist. |
| Rating display | Community Rating and Guest Feedback are separate and always show a count. Below five eligible Verified Member reviews the interface shows "Editorial seeded selection" instead of a score. | Review.md 6.1, 6.2, 6.4. |
| No destination images | Destination screens are text-first until the API carries licensed images. The hotlinked Unsplash photos are removed. | PF 17 licensing, PF 16.3 `img-src`, asset budget. |
| Offline claims | Interface text claiming PWA, IndexedDB or pack downloads is removed until R12 and R13 deliver them. | Same as above. |
| Guest scope secret storage | Kept in `localStorage` (key `abhijatri_guest_scope`) until the IndexedDB draft store (R15) exists, then moved there. The receipt is never stored; it is held in memory and shown once. | PF 18.1 names IndexedDB; PF 13.5 forbids keeping submitted-review receipts. |
| Draft identity on retry | One `client_draft_id` and receipt per draft, reused on every retry; replaced only after success or `DRAFT_ALREADY_SUBMITTED`. | Review.md 4.1, API.md 5.2 order of checks. |
| Turnstile widget | Deferred to an R09 follow-up. Development runs with `TURNSTILE_ENABLED=false`; production submission needs the widget before release. | Needs the site key and the CSP origin in PF 16.3. |
| Seed content ownership | The five-destination content was researched and sourced by Abdullah to unblock R03. It stays R01 work owned by Shahriar Islam and is accepted only after that review sets `reviewer`. | Gantt R01 ownership; R01 acceptance "pass review". |
| CORS origin normalisation | Trailing slashes are stripped from `CORS_ALLOWED_ORIGINS`. | A trailing slash never matches a browser `Origin`, which blocked the local frontend. |
| Vercel for the public frontend (interim) | The public PWA is deployed to Vercel by Shahriar Islam using `frontend/vercel.json`; steps are in `Architecture.md` section 5. This amends the Render static-site plan of PF 4 for the interim only. Before R04 cookies or Gate B, the frontend and API must share an owned domain (PF 5.2, 5.3); the staff build is not deployed here. | The shared deployment account is available to Shahriar; Guest features need no cookies, so `vercel.app` is acceptable until authentication lands. |

## 2026-10-19 (WP2 error contract, WP3 receipts and keyring)

| Decision | Rule | Reason |
|---|---|---|
| Error body | Every error is `{"error": {"code", "message", "request_id", "field_errors"}}` from `app/errors.py`. Codes, statuses and Bangla/English messages live in one catalogue. `Accept-Language` selects the message; Bangla is the default. | API.md section 2, PF 12.3. |
| Field errors | Only `{field, code}` pairs are returned; submitted values are never echoed. | A rejected request can contain a receipt or Guest secret (PF 13.4). |
| Request id | `X-Request-ID` is a UUID and equals `error.request_id`. | API.md section 2. |
| Receipt origin | The client generates the receipt (`abr1_` plus 32 random bytes, base64url). The server validates the exact format, rejects non-canonical and low-entropy values, stores only a keyed digest, and never issues or returns one. | PF 13.1 to 13.2; removes the receipt-minting weakness of the Guest scope. |
| Keyring | One versioned ring (`RECEIPT_KEYS`, `RECEIPT_KEY_CURRENT`) serves receipt, Guest-scope and network digests, separated by context labels. Lookups try every retained key; a successful receipt use re-digests under the current key. Without `RECEIPT_KEYS` the pepper is key `v1`. | PF 13.4. |
| Duplicate draft | Same Guest scope and `client_draft_id`: same receipt returns `200` with `duplicate_recovered: true`; a different receipt returns `409 DRAFT_ALREADY_SUBMITTED` and no review id. A receipt already bound to another review is refused the same way. | PF 13.3. |
| Legacy data | Receipts and Guest-scope digests created before migration `0004` are marked `legacy`; the receipts are revoked. Pending drafts from the old scheme cannot be recovered. | The old digests used an unlabelled pepper and cannot be verified under the new scheme. Pre-release data only. |
| Rejection details | `decision_reason` is the moderator `reason_code` of the latest rejection and `appeal_deadline` is 30 days after it. Moderator notes are never returned. Moderators must therefore use catalogue codes (full catalogue planned with R10). | API.md 5.3. |
| Withdrawal order | An already `WITHDRAWN`/`DELETED` review returns `200` before the `expected_version` check. | A retry after a lost response must succeed (API.md 5.4). |

## 2026-10-19 (WP5 abuse controls)

| Decision | Rule | Reason |
|---|---|---|
| Client address | Uvicorn runs with `--no-proxy-headers`. `app/client_address.py` reads one configured header (`CLIENT_ADDRESS_HEADER`) at one position (default right-most). A missing or malformed value falls back to the socket peer, never to another client-controlled header. IPv6 is truncated to /64. Only a keyed digest is stored. Production refuses to start without the header setting. | PF 14.2. The header name is **unproven** until the staging forged-header test records it in `Architecture.md`. |
| Counters | `rate_limit_buckets` holds fixed-window counters keyed by (rule, keyed digest, window start). Every increment commits in its own transaction before the business operation, so a later failure never erases the attempt. Windows older than two days are purged at most once a minute per process. Fixed windows allow up to twice the limit across a window boundary; this is accepted for the MVP. | PF 14.5. |
| Limits | New Guest drafts: 3 per scope per 24 h; 30 per network per hour; 100 per network per 24 h. Receipt operations: 20 per receipt per hour; 100 per network per hour. All are settings with these defaults. | API.md section 7. |
| Progressive block | Failed receipt lookups are counted per receipt and per network in two tiers (5 per 15 minutes, then 20 per 24 hours). While either tier is exhausted, receipt operations are refused with `429` and `Retry-After` before any lookup, so the right receipt from a guessing network is also refused but other networks are unaffected. A request sleeping in a worker is not used as a delay. | "Progressive delay after repeated failures" without tying up workers. |
| Order of checks | 1 schema and receipt format, 2 recoverable draft (free: no challenge, no counter), 3 idempotency replay (**pending WP4**), then the emergency switch, 4 Turnstile, 5 counters, 6 limits and pending ceilings, 7 business transaction. The emergency switch sits before Turnstile so a paused system does not spend a visitor's challenge. | PF 14.4. |
| Turnstile | Server-side validation of success, hostname and action; one retry of the siteverify call with the same `idempotency_key`; an unreachable Cloudflare returns `503`, never a pass and never `CHALLENGE_FAILED`. Disabled only in development and test; production refuses to start without it. | PF 14.1. |
| Pending ceilings | Pending Guest reviews are `PENDING`, `UNDER_REVIEW` and `CHANGES_REQUESTED`. Ceilings 50 per destination and 500 total return `503 GUEST_WRITES_PAUSED` for new Guest submissions only; a warning is logged from 80 percent. | PF 14.3. |
| Emergency switch | `GUEST_WRITES_PAUSED=true` stops new Guest submissions. Reads, receipt status, withdrawal and recovery of an existing draft continue. Changing it needs a deploy; the administrator toggle with an audit event arrives with `audit_events` (R11). | PF 14.6. |
| In-memory pre-filter | slowapi remains as a per-address burst filter (5 and 10 per minute by default), now keyed by the trusted address. It is an optimisation, not the limiter. | PF 14.5. |

## 2026-10-19 (R02: destination, advisory and contact services)

| Decision | Rule | Reason |
|---|---|---|
| Endpoint set | Exactly the two R02 routes in `Docs/api/API.md` 4.3: `GET /destinations` and `GET /destinations/{destination_id}`. Advisories and contacts are embedded in the profile; they have no routes of their own. | Keeps the code identical to the approved contract and gives the PWA and the offline pack a single fetch. |
| Contract file | `Docs/api/API.md` is the single API contract. `tests/test_openapi_contract.py` reads it. | The earlier `Docs/API.md` was moved; two copies would drift. |
| Read-only scope | No staff write endpoints for destination content. Content enters through seed and migration scripts until R10 and R11 provide real staff authentication. | The staff header is a development stub that returns 501 in production. |
| Language | Every response carries both Bangla and English fields. | Offline packs need both, and the client chooses the language (FR02). |
| Advisory state | `EXPIRED` when the Asia/Dhaka date is after `valid_until`; `STALE` when last verified more than `ADVISORY_STALE_AFTER_DAYS` (default 30) ago; `NOT_YET_EFFECTIVE` before `effective_on`. State is computed on read and never stored. Expired items appear only with `include_expired=true`. | Expired information must never be presented as current (PF 17). |
| Provenance | Guide items, advisories and contacts store source type, reference, publisher, effective and verification dates, next review date, licence, researcher and reviewer. Researcher and reviewer names are not returned publicly. | PF 17; avoids exposing team members' names in a public payload. |
| Public caching | The two destination routes and the review feed send `Cache-Control: public, max-age=60` (`PUBLIC_CACHE_MAX_AGE_SECONDS`); the destination routes add a weak `ETag` and answer `If-None-Match` with 304. Every other route stays `no-store`. | Security 7.1 route allowlist with a short explicit TTL. |
| Row-level security | Migration `0003_destination_content` enables RLS on its three new tables itself. | `0002` only covered tables that existed at the time. |

## 2026-10-16 (Platform Foundation revision 3)

| Decision | Rule | Reason |
|---|---|---|
| Foundation adopted | `Docs/Platform-Foundation.md` revision 3 is the approved shared-platform specification, together with the same-commit amendments to Security, Review, Architecture and API documentation. `Features/Execution.md` controls dependency sequence only and cannot amend the Foundation or an approved feature specification. | Separates shared platform authority from implementation ordering. |
| Schema changes | Supersedes the 15 October rule. Production and staging migrations run only from the protected GitHub workflow; containers never run `alembic upgrade head`; the runtime has no migrator credential. | Migrations must precede deployment and use a separate identity. |
| Deploy trigger | Supersedes the 15 October rule. Render auto-deploy is Off. CI migrates, deploys and verifies the API, then builds the public static site, then builds the staff site, all from the tested commit. | Prevents migration races and stale prerendered content. |
| Environments | `abhijatri-dev` becomes `abhijatri-staging`; production remains separate. | Matches the four-environment foundation contract. |
| Guest receipts | The client generates one 256-bit receipt before submission. Receipts are never reissued and never create a cookie session. | Makes lost-response recovery idempotent without allowing a Guest scope to mint replacement receipts. |
| HMAC domain separation | Receipt and Guest-scope digests share a versioned keyring but use distinct fixed context labels and store `key_id`. | Prevents cross-credential substitution and supports rotation. |
| Abuse controls | Guest writes require Turnstile and enforce both per-credential and higher network-digest hard ceilings plus queue caps. The application does not claim it can force Turnstile interactivity. | A Guest scope is free to regenerate, while managed Turnstile interaction is controlled by Cloudflare. |
| Trusted client address | Gate A must prove the provider-derived client address cannot be spoofed. If it cannot, Gate B requires a provider or edge with a documented non-bypassable address contract. | A guessed forwarding-header rule is not a security boundary. |
| Completion date | Planned development freezes on 3 January 2027. Work after that date is testing, defect correction and approved low-risk enhancement only. | Removes the earlier 2 or 3 January ambiguity. |
| Argon2id parameters | Record the selected `time_cost`, `memory_cost` and `parallelism` when the authentication schema lands, and review them again before Gate B. | Makes the password-cost decision measurable and testable rather than leaving it implicit. |

## 2026-10-14

| Decision | Rule | Reason |
|---|---|---|
| Published review editing | Deferred to v1.1. The MVP uses withdraw and resubmit. | Prevents rating and revision races in the first vertical slice. |
| Feed cursor | Order by `(published_at, id)` descending. | Stable pagination when moderation publishes older submissions later. |
| Rating transitions | Lock the review and destination aggregate rows, check `version`, and apply `counted_rating` deltas once. | Prevents double counting under retries and concurrent moderation. |
| Member rating eligibility | Only an active, non-revoked `VERIFIED_MEMBER` verification is eligible. Team and conflict-declared reviews are excluded. | Keeps the Community Rating claim truthful. |
| Visit month clock | Reject future months using `DEFAULT_DISPLAY_TIMEZONE` (default `Asia/Dhaka`); all timestamps are stored and computed in UTC. | Makes the rule deterministic for a Bangladesh-first platform. |
| Moderator self-review | Denied in the service layer. | Prevents an obvious conflict of interest. |
| Infrastructure order | PostgreSQL correctness first. Redis, CDN, and media processing remain deferred. | Keeps the first release testable and within semester scope. |
| Pending-review revisions | A Guest receipt may edit only a `PENDING` or `CHANGES_REQUESTED` review through `PATCH /api/v1/reviews/{review_id}/pending`. | Published-review editing remains deferred to v1.1. |
| Conflict changes | Setting or clearing `conflict_declared` is a locked rating transition with an expected-version check and the same `counted_rating` delta mechanism used by publish, hide, and withdraw. | Prevents a moderator flag change from leaving Community Rating stale. |
| Rejected rating value | A rejected review has `counted_rating = NULL`. If it was never published, its aggregate delta is zero. | Makes rejection behavior explicit and testable. |
| Restore transition | Restore applies only to a `HIDDEN` review and returns it to `PUBLISHED` after recalculating its current eligibility through the locked delta path. | Gives the aggregate property test and moderation workflow a precise restore meaning. |
| Active duplicate states | For one Member review per destination and visit month, active means `PENDING`, `UNDER_REVIEW`, `CHANGES_REQUESTED`, `PUBLISHED`, or `HIDDEN`. `REJECTED`, `WITHDRAWN`, and `DELETED` do not block a replacement. A recorded moderator override permits a legitimate repeat visit. | Prevents duplicate active submissions without permanently blocking corrected or later submissions. |

## 2026-10-15 (F06: repositories, CI, shared environments)

| Decision | Rule | Reason |
|---|---|---|
| System flow | React PWA -> HTTPS -> FastAPI (Render, Docker) -> SQLAlchemy/Psycopg -> Supabase-managed PostgreSQL. The browser never holds a Supabase key or calls Supabase directly. | Keeps authorisation, moderation and rating integrity in one server-side boundary. |
| Supabase connection | Backend uses the Supavisor **session** pooler URI (port 5432, `sslmode=require`). Transaction mode (6543) is not used. | Render is IPv4 and the direct host is IPv6-only; row locks and `SELECT ... FOR UPDATE` need session-stable connections. |
| Schema changes | Alembic only. Migrations run at container start (`alembic upgrade head`). Optional `MIGRATION_DATABASE_URL` allows a separate migrator role later. | Render `preDeployCommand` is paid-only; the migrator role is a Security 4.4 deploy gate. |
| Production config guard | Startup fails closed on default or short pepper, wildcard CORS, or non-TLS remote database. | Prevents silent insecure deployment. |
| Environments | `abhijatri-dev` (shared team) and `abhijatri-prod` (demo) Supabase projects; CI uses a throw-away PostgreSQL service container and never touches Supabase. | Security 9.1 environment separation. |
| Staff API on Render | Moderation endpoints return 501 in production until the real authentication adapter (R04) replaces the test header. | Security 2.2; the header must never be accepted publicly. |
| Deploy trigger | Render auto-deploys only after CI checks pass on `main` (`autoDeployTrigger: checksPass`). | Broken builds cannot reach the demo environment. |
| Free-tier risk | Supabase free projects pause when idle; use a paid plan or keep-alive before test and demo windows. | Avoids a dead demo. |
| Test fix | `test_concurrent_publish_counts_once` rebuilt its engine from `str(url)`, which masks the password; it now uses `render_as_string(hide_password=False)`. | The concurrency gate could not run against a password-protected database. |

**Evidence:** first real PostgreSQL execution on 15 October 2026 passed all 20 tests, including the aggregate property test, concurrent moderation test, and Guest vertical slice; `alembic upgrade head`, `alembic check`, and `alembic downgrade base` are clean. Gates 2-4 below are therefore met locally and are re-verified on every CI run.

## 2026-10-15 (F02: schema and API contract)

| Decision | Rule | Reason |
|---|---|---|
| ERD and contract location | `Docs/Schema.md` (Mermaid ERD, implemented vs planned) and `Docs/api/API.md` plus `Docs/api/openapi-v1.json`. | One reviewed source for Abdullah and Irfan. |
| Contract drift | `tests/test_openapi_contract.py` fails when `app.openapi()` differs from the committed snapshot or a route is missing from `Docs/api/API.md`; `tests/test_docs_schema.py` does the same for tables. | Keeps documents honest without manual review. |
| Pending-review edit | `PATCH /reviews/{id}/pending` was planned (R07) and is **implemented 29 Oct 2026** (Backend-Implemented.md 5.18). | The documentation-only slice deferred it; R07 builds it with revisions and tests. |
| Versioning | Additive changes stay in `/api/v1`; breaking changes need `/api/v2`. | Frontend can rely on stability. |

## 2026-10-15 (F06 follow-up)

| Decision | Rule | Reason |
|---|---|---|
| Supabase exposure | Migration `0002_enable_rls` enables RLS with no policies on all public tables and revokes `anon`/`authenticated` grants; Data API is also disabled in the dashboard. | Tables created through Alembic are otherwise reachable with the public anon key. |
| CI dependency audit | `pip-audit` runs on a hashed `uv export` (without `--no-hashes`). | `--disable-pip` requires hashed requirements; first run failed on this. |
| Moderation decisions | `/decisions` accepts `PUBLISH`, `REJECT`, `HIDE`, `RESTORE`; conflict changes use `PUT .../conflict`. | Matches implemented transitions; documented in `Docs/api/API.md`. |

## Decisions scheduled during implementation

These choices are intentionally made at the named implementation step and then recorded in this log. They are not permission to weaken the frozen security or correctness rules.

| When | Decision to record | Required guardrail | Status |
|---|---|---|---|
| Step 4 | Exact submission and receipt rate limits, the anti-abuse challenge, and the maximum number of pending reviews per Guest scope. | Limits must combine Guest scope, account where present, and cautiously weighted IP signals because mobile-carrier CGNAT makes IP-only blocking unsafe. | Open until Step 4 load and abuse tests. |
| Step 5 | Final duplicate-index implementation and rejection transition behavior. | Rejection leaves `counted_rating` null; active states are the states recorded above; all aggregate changes use row locks and version checks. | Rules fixed; implementation and PostgreSQL tests in progress. |
| Step 7 | Moderator self-review and visit-month timezone. | A moderator cannot moderate their own review; future visit months are evaluated in `Asia/Dhaka`. | Decided and implemented in the service and validation layers. |
| Step 8 | Maximum age and refresh behavior for offline review snapshots. | The UI must display snapshot age, attempt refresh on reconnection, and stop presenting an over-age snapshot as current because removed reviews can remain on a device. | Open until offline-pack testing. |
| Account deletion | Choose anonymisation or deletion for eligible review content. | Either choice must remove personal linkage as promised, subtract any `counted_rating` in the same locked transaction, emit an audit/outbox event, and preserve only the minimum lawful deletion ledger. | Open before account-deletion implementation. |

## First-week execution gates

Work may proceed beyond the first review slice only after these gates have evidence.

| Order | Gate | Required evidence | Current status |
|---:|---|---|---|
| 1 | Database invariants | PostgreSQL migrations contain permanent draft uniqueness, the active Member duplicate index, enum-backed state values, rating checks from 1 to 5, aggregate non-negative checks, and foreign keys. | Implemented; migration SQL generation passes. |
| 2 | Aggregate property test | Random sequences of publish, hide, withdraw, and restore produce the same sums and counts as a full recomputation on real PostgreSQL. | Passed on real PostgreSQL 17 (15 Oct 2026); re-run in CI. |
| 3 | Moderation concurrency test | Two moderators acting on the same review concurrently produce one successful transition, one version conflict, and exactly one aggregate delta. | Passed on real PostgreSQL 17 (15 Oct 2026); re-run in CI. |
| 4 | Guest vertical slice | One Guest review completes submit, moderation, publication, public retrieval, and Guest Feedback aggregate update end to end. | Passed on real PostgreSQL 17 (15 Oct 2026); re-run in CI. |

## Scope control

The Review specification is frozen after the schema amendments. Necessary implementation changes are added to this decisions log rather than rewriting the architecture. Redis, CDN integration, and the image pipeline remain out of scope until implementation steps 1 through 9 and their regression tests pass.

## 2026-10-31 (R08 rating exclusion)
| Decision | Choice | Reason |
|---|---|---|
| Serious reports | Only `privacy` and `conflict_of_interest` take a published review out of the rating while the report is open. `spam`, `offensive`, `false_information` and `other` do not. | Review.md 6.1 says "serious unresolved report"; the report reasons have no severity field. One constant (`app.eligibility.SERIOUS_REPORT_REASONS`) changes the list. |
| Duplicates | A later review by the same author for the same destination and month does not count while an earlier one does. | Possible only through the moderator `duplicate_override`; keeps one voice per visit. |
| Invalid reviews | New `INELIGIBLE_INVALID` for a future visit month, no text or a rating out of range. | The existing values would have been misleading. Published text is unaffected. |
| Abuse revocation | Moderator or superadmin, reason required, not on yourself; reviews stay public but stop counting. | Review.md 6.3; staying public avoids a second decision about the text. |
| Repair | Detect-only nightly; repair only by explicit superadmin call or CLI flag, audited. | Review.md 6.3. |
