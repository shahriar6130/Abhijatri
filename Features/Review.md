# Abhijatri Review System

**Status:** Frozen implementation specification after schema amendments; amended 20 October 2026 (section 13)  
**Scope:** Platform foundation, destination reviews, moderation, ratings, weak-network operation, and Verified Member integration  
**Primary release:** Semester MVP  
**Architecture:** React and TypeScript PWA, FastAPI modular monolith, PostgreSQL, IndexedDB, S3-compatible object storage, and optional Redis

## 1. Purpose and release boundary

Abhijatri's review system collects useful travel experience without turning the semester project into a generic comment form or an unfinished social network. A review records the traveller's context, survives weak connectivity, passes human moderation, and contributes to a rating only under published and testable rules.

The first complete vertical slice is:

> Destination page -> local review draft -> safe submission -> moderation -> publication -> rating update -> offline review snapshot

The mandatory release includes:

- Bangla-first and English destination pages.
- Profile-free Guest reviews.
- Registered accounts and Verified Member status.
- Structured ratings and travel context.
- Offline text drafts and retry-safe submission.
- Human moderation, reporting, removal, and revision history for reviews that are still pending or returned with `CHANGES_REQUESTED`.
- Separate Community Rating and Guest Feedback values.
- Database-managed staff roles and protected administration.
- Text-first, low-bandwidth review presentation.

Verified Member image upload is part of the mandatory release (amendment A1, section 13). Guests submit text only. Multiple communities, video, chat, tour groups, vendors, agencies, bookings, and payments are future specifications.

### 1.1 Resolved decisions

| Decision | Final rule |
|---|---|
| Review storage | Review text and metadata remain in PostgreSQL until removed under policy. |
| Media storage | PostgreSQL stores metadata and object keys; binary media is stored in object storage. |
| Guest identity | A Guest has no account. The review stores a display-name snapshot and is labelled **Guest**. |
| Verified badge | The public badge is **Verified Member**. It does not mean Verified Visit. |
| Main destination rating | Only eligible Verified Member reviews contribute. |
| Guest ratings | Published separately as Guest Feedback average and count. |
| Offline deduplication | Permanent uniqueness of the client draft identity prevents duplicates; expiring idempotency records only replay recent responses. |
| Rating updates | Rating sum and count are adjusted transactionally in O(1). Verification-abuse revocation and nightly reconciliation are the documented full-recompute exceptions. |
| Bangla names | Store NFC-normalised text. Use a separate confusable skeleton only for impersonation checks. |
| Offline media | Text drafts are durable locally. Media is attached or reattached when online. |
| Administration | The URL may be unlisted, but every page and API requires authenticated, server-side authorisation. |
| Future identities | Guide, Volunteer, Vendor, and Agency are not global roles. Identity, organisation, verification, and platform authority remain separate concepts. |

### 1.2 Assumed platform contracts

This feature depends on three minimal platform modules. Their internal implementation may evolve, but these contracts are stable for the review slice.

**Destinations.** A `destinations` record provides `id`, lifecycle `status`, Bangla name, English name, and timestamps. Review submission accepts only a published destination. Seed migrations provide at least one published destination for integration tests.

**Authentication.** The auth module provides registration, email verification, sign-in, sign-out, password reset, secure session resolution, and the current `user_id`. Password credentials are not stored in review tables. Staff actions additionally require an active platform role and recent authentication.

**Transactional email.** An email adapter accepts a template key, recipient, locale, and data payload. Development uses an in-memory or console adapter; production selects a provider through configuration. Review submission never fails merely because a notification email is unavailable. Failed delivery is recorded for retry through the outbox.

## 2. Actors, identity, badges, and authority

### 2.1 User levels

| Actor | Public label | Capabilities in this specification |
|---|---|---|
| Guest | Guest | Browse, create an offline text draft, submit a moderated review, and manage it with a receipt. |
| Member | No trust badge | Guest capabilities plus account-owned reviews, reports, and deletion requests. |
| Verified Member | Verified Member | Member capabilities plus Community Rating eligibility and image upload with reviews (section 8). |
| Moderator | Moderator | Review queues, reports, rating eligibility, and content decisions within granted authority. |
| Administrator | Administrator | Destinations, verification decisions, policy configuration, and staff management within granted authority. |
| Super Administrator | Not displayed on ordinary content | Initial staff bootstrap, privileged role assignment, and recovery controls. |

Email verification proves control of an inbox; it does not grant the Verified Member badge. Verified Member is a verification record approved under a documented procedure.

### 2.2 Identity model

The initial identity tables are deliberately small but do not block future user types:

- `users`: application identity and lifecycle only.
- `auth_identities`: email/password now; phone OTP or external identity providers later.
- `platform_roles`: Member, Moderator, Administrator, and Super Administrator authority.
- `user_platform_roles`: time-bounded role assignments.
- `verifications`: subject, verification type, method, status, approver, decision date, expiry, and revocation.

Badges are derived from active verification records, not boolean columns embedded in `users`.

Future Guide and Volunteer profiles belong in `profiles`. Agencies and vendors belong in `organizations` with `org_memberships` and resource-scoped authority. A person may therefore be a traveller, a guide, and agency staff without receiving inappropriate global permissions.

All protected actions call one application policy boundary:

```text
can(actor, action, resource) -> allow or deny
```

The semester implementation may use ordinary FastAPI policy functions. Keeping one call boundary permits a later policy engine without rewriting every endpoint.

### 2.3 Verification evidence

The semester demonstration uses controlled test accounts. If verification evidence is inspected, it is uploaded to private quarantine, never shown publicly, and never placed in a public cache.

- Pending evidence expires after seven days.
- Evidence is erased within 24 hours after approval or rejection.
- The permanent record contains the method, result, approver, decision time, expiry, and revocation information, not the document image.
- Real NID verification is outside the semester MVP.

## 3. Review content and submission workflows

### 3.1 Required review data

Each review contains:

- Destination.
- Original language: Bangla, English, or Banglish/mixed.
- Display name snapshot for a Guest, or `author_user_id` for a Member.
- Overall rating from 1 to 5.
- Category ratings selected from cleanliness, accessibility, hospitality, food, transport, safety perception, and value. Each category is optional (not applicable) or an integer from 1 to 5; the overall rating stays the single required score (amendment A2).
- Traveller type: solo, student, couple, family, or group.
- Comfort tier: economy, standard, or premium.
- Visit month in `YYYY-MM` form.
- Review title and body. The body is the reviewer's free-text note and is available to Guests and Members alike (amendment A2).
- Optional structured advantages and cautions.
- Consent version.
- Client draft identity.
- Moderation and rating-eligibility states.
- Creation, revision, publication, and removal timestamps.

The visit record in the MVP is the destination plus declared visit month. Exact travel dates are optional. One active Member review is allowed for a destination and visit month unless a moderator approves a legitimate repeat visit. This is a duplicate-control rule, not proof of travel.

A later agency trip code or partner QR receipt may create a separate **Verified Visit** verification. Verified Member and Verified Visit must never be presented as the same claim.

### 3.2 Guest submission

1. The Guest enters a display name and receives a local welcome message.
2. The application creates a cryptographically random Guest scope secret, client draft UUID, and receipt secret.
3. The Guest completes the structured review online or offline.
4. The interface presents the publication, moderation, and retention notice.
5. Server validation, rate limits, a honeypot or challenge, and duplicate checks run on submission.
6. The server stores the review in `PENDING` state and returns the same review for every retry of that draft identity.
7. The client keeps the receipt it generated in step 2; the server stores only its keyed digest.
8. The review enters the human moderation queue.

A Guest review never contributes to the Community Rating. If published, its overall rating contributes to the separately labelled Guest Feedback value.

### 3.3 Member and Verified Member submission

A signed-in Member owns the review through `author_user_id`. A Verified Member review can become Community Rating eligible after moderation. Verification does not bypass moderation, duplicate control, conflict-of-interest rules, or reporting.

### 3.4 Display-name safety

Display names are stored in Unicode NFC. They are length-limited by Unicode code point count, not byte count, so Bangla names are not unfairly restricted.

The system separately derives a confusable skeleton for comparison with reserved identities. It rejects names that imitate Admin, Administrator, Moderator, Official, Verified, Abhijatri Staff, verification marks, or visually confusing equivalents. Legitimate Bangla text, ZWJ, and ZWNJ sequences are not rewritten by NFKC.

Badges are rendered by trusted UI components and can never be supplied through a display-name field.

## 4. Receipt, offline identity, and duplicate prevention

### 4.1 Permanent draft uniqueness

An expiring idempotency table cannot prevent a duplicate submitted weeks later. Duplicate prevention therefore lives on the review record:

- Authenticated partial uniqueness: `(author_user_id, client_draft_id)`.
- Guest partial uniqueness: `(guest_scope_hash, client_draft_id)`.

`guest_scope_hash` is derived from the locally generated Guest scope secret. The raw secret is never stored. On a uniqueness conflict, the API returns the previously created review and receipt state instead of inserting another review.

An `idempotency_keys` table may retain recent request responses for 72 hours. It improves network retries but is not the source of permanent uniqueness.

### 4.2 Guest receipt

The client generates the receipt before first submission using 32 random bytes from the browser cryptographic API. Its format is `abr1_` followed by 43 unpadded base64url characters. The server validates the format and stores only `(key_id, HMAC-SHA-256 digest)` under a versioned keyring. Receipt and Guest-scope inputs use different fixed HMAC context labels.

- Receipts are never reissued.
- The receipt is sent in the JSON body of a rate-limited POST for each operation.
- It is never placed in a URL, URL fragment, cookie, log, or analytics event.
- It remains valid while the review content or appeal record exists.
- It is revoked when the review is finally erased.
- A rejected review remains visible through the receipt during the 30-day appeal period, including the public-safe decision reason and appeal deadline.

The receipt permits status checks, withdrawal, appeal, and a revision only while the review is `PENDING` or `CHANGES_REQUESTED`. Submitting a revision means editing the unpublished review through `PATCH /api/v1/reviews/{review_id}/pending`; it never means editing published content. The receipt cannot access another review or identify other users. A lost receipt is handled through the moderated removal-request process in 5.4.

## 5. Lifecycle, revisions, moderation, and reports

### 5.1 Content states

```text
LOCAL_DRAFT
PENDING
UNDER_REVIEW
CHANGES_REQUESTED
PUBLISHED
HIDDEN
REJECTED
WITHDRAWN
DELETED
```

Rating eligibility is independent:

```text
NOT_EVALUATED
ELIGIBLE
INELIGIBLE_GUEST
INELIGIBLE_UNVERIFIED
INELIGIBLE_DUPLICATE
INELIGIBLE_CONFLICT
INELIGIBLE_REPORTED
INELIGIBLE_REMOVED
```

### 5.2 Revisions

- A pending review can be edited before a moderation decision, and each submitted version is retained as a `review_revision`.
- The revision moderation result is stored on `review_revisions`; `reviews.current_revision_id` identifies the version currently being moderated or displayed.
- Published-review editing is deferred to v1.1. In the MVP, an author withdraws the published review and submits a new review.
- Withdrawal removes the public review and rating eligibility immediately.
- Revision rows are append-only during normal operation, but the authorised retention job may tombstone personal content. Internal moderation notes must not copy unnecessary personal content and are subject to the same erasure policy.

### 5.3 Human-first Bangla moderation

Automated checks assist but do not make final decisions. They may flag duplicated text, phone numbers, external links, reserved names, impossible visit dates, repeated characters, suspicious submission velocity, or disallowed markup.

Moderators review Bangla, English, and Banglish content using a common checklist. Personal phone numbers and unnecessary identifying information are redacted or returned for correction. Reviews naming an individual, alleging serious misconduct, exposing private information, or raising a copyright issue enter an escalated notice-and-review case.

### 5.4 Reports

Supported reasons are spam, harassment, false information, private information, impersonation, safety misinformation, copyright concern, conflict of interest, and other. Members submit account-owned reports. Non-members can submit a rate-limited anonymous report or lost-receipt removal request with contact information optional unless follow-up is required. Duplicate open reports are controlled by account or anonymous submission scope.

A report does not automatically remove a review. A severe privacy or safety report may temporarily hide it pending a recorded decision.

Every moderation action records actor, reason code, internal note, previous state, new state, and timestamp. The application database role cannot update or delete historical audit rows.

## 6. Ratings, rankings, and cold start

### 6.1 Community Rating

Only published and eligible Verified Member reviews contribute to the primary destination rating. A review is eligible only when:

- Its current moderation state is `PUBLISHED`.
- Its rating state is `ELIGIBLE`.
- Its visit month is valid and not in the future.
- It is not a detected duplicate.
- It is not withdrawn, hidden, or deleted.
- It is not under a serious unresolved report.
- The author does not control or represent the reviewed destination resource.
- Required structured fields are complete.

For the MVP, conflict of interest is a moderator-declared flag because vendor and resource-ownership tables do not yet exist. Changing this flag on a published review is a rating transition: the operation locks the review and destination aggregate rows, checks the expected review version, removes any previous `counted_rating`, recalculates eligibility, and applies the new delta in the same transaction. Project-team accounts are excluded from semester rating evidence. Automated ownership checks replace this flag when the organisation module is introduced.

For each destination the database stores `rating_sum` and `rating_count`. The review stores nullable `counted_rating` and an integer `version`. Every transition locks the review and aggregate rows with `SELECT ... FOR UPDATE`, verifies the expected version, and applies `new_counted_rating - old_counted_rating` exactly once. No ordinary moderation request scans all destination reviews.

With fixed semester prior mean `C = 3.5` and confidence weight `m = 5`, the read-time Bayesian score is:

```text
Community Rating = (rating_sum + m * C) / (rating_count + m)
```

The interface always displays the eligible review count with the score.

### 6.2 Guest Feedback

Published Guest reviews maintain a separate `guest_rating_sum` and `guest_rating_count`. The interface shows only their star average and count. It does not claim to infer sentiment from Bangla or Banglish text.

### 6.3 Transactional consistency

Publication, hiding, withdrawal, deletion, eligibility changes, aggregate deltas, audit events, and an outbox event occur in one PostgreSQL transaction. After commit, a worker invalidates Redis or CDN representations. Public queries also filter by current review state, so stale cached aggregates cannot make removed content visible.

A nightly reconciliation job recomputes expected sums and counts from published source rows and alerts on drift. It repairs only through an explicit, audited maintenance operation.

Verified Member eligibility is evaluated and frozen when a review is published. Ordinary verification expiry does not retroactively remove the rating. When verification is revoked for abuse, an authorised moderator operation locks the affected destination aggregates, removes that author's counted contributions, updates each review's `counted_rating`, and records the recomputation. This abuse-revocation operation is a documented exception to the no-full-scan rule.

### 6.4 Cold-start behavior

Top Rated is unavailable until a destination has at least five eligible Verified Member reviews. Before that threshold, Abhijatri presents a first-class **Seeded Destination Selection** based on researched destination content and labels it explicitly as editorial, not community ranking.

Semester evidence must include:

- The number of approved Verified Members.
- Median and maximum verification turnaround time.
- Eligible review count per destination.
- Which destinations use Seeded Selection rather than Top Rated.

Near-you ranking is a later integration. It may use Community Rating only after eligibility and advisory-freshness gates pass.

## 7. Weak-network and offline behaviour

Offline support is a platform capability, but the review module owns the following contract.

### 7.1 Public review snapshots

Downloaded destination packs may contain a bounded snapshot of recent published reviews, rating counts, and advisory status. The UI displays the snapshot timestamp. Authenticated account responses, staff data, receipt operations, and private community data are excluded from public service-worker caches.

### 7.2 Local text drafts

Guest, Member, and Verified Member text drafts are stored in IndexedDB with:

- Client draft UUID.
- Guest scope reference or signed-in author reference.
- Destination and structured review fields.
- Consent version.
- Local revision number.
- Created and updated timestamps.
- Submission state and idempotency key.

The application requests persistent browser storage when supported and clearly reports whether it was granted. IndexedDB is not encrypted by default, so the interface provides delete controls and does not put private community conversations in offline storage during the MVP.

### 7.3 Reconnection

The product does not depend on background sync. When connectivity returns, it shows pending drafts and asks the user to submit or retry. It revalidates consent, destination status, and review fields, then submits using the permanent draft identity. A draft remains local until the server acknowledges the stored review.

If an authenticated session expired, the draft remains local and submission waits for sign-in. Published reviews are not editable in the MVP. A local change to published content must be saved as a separate draft, and the author must withdraw the published review before submitting the replacement.

### 7.4 Adaptive media presentation

Normal connections receive responsive, lazy-loaded thumbnails. Low-data mode does not automatically fetch full media. If media is unavailable locally, its card shows title, type, processed size, and an explicit action:

```text
Sunset from Sajek Valley
Image - 184 KB
[Load image]
```

Offline packs show cached thumbnails where available. Otherwise they show the title and `Open when online`. Video never autoplays.

The MVP guarantees offline text drafts only. If a Verified Member selects an image while offline, the draft retains its intended caption and filename where possible but asks the user to attach or confirm the file when online.

## 8. Verified Member image pipeline

Image upload is part of the mandatory release (amendment A1). It is built after Verified Member approval (step 7) because only Verified Members may upload. Guests cannot attach images.

- Verified Members only.
- Maximum five images per review.
- JPEG, PNG, and WebP only; SVG, GIF, archives, and video are rejected.
- Maximum upload size: 8 MiB per image.
- Maximum decoded resolution: 20 megapixels.
- Browser metadata and MIME type are treated as untrusted.
- Upload uses a presigned POST policy with content-length conditions.
- Objects enter a private quarantine prefix under random keys.
- Workers validate the signature, decode with resource limits, remove EXIF/GPS metadata, re-encode, and create thumbnails.
- Moderators approve processed media before publication.
- Unattached quarantine objects expire after 24 hours.
- Deletion revokes public metadata, removes objects according to policy, and purges CDN entries.

Every media record includes title, alt text, caption, media type, dimensions, processed size, ownership declaration, object key, review revision, and moderation state.

## 9. Data and API design

### 9.1 Core tables

| Table | Responsibility |
|---|---|
| `users`, `auth_identities` | Account identity and authentication methods. |
| `platform_roles`, `user_platform_roles` | Global staff authority. |
| `verifications` | Verified Member and future subject verifications. |
| `reviews` | Stable review identity, author reference, current states, current revision, visit month, permanent draft uniqueness, conflict flag, `counted_rating`, and optimistic `version`. |
| `review_revisions` | Append-only submitted versions and revision moderation state; content can be tombstoned only by the retention job. |
| `review_category_ratings` | Category-level scores for a revision. |
| `review_receipts` | Hashed Guest receipt secret, expiry state, and review scope. |
| `review_media` | Processed-object metadata and moderation state. |
| `review_reports` | User reports with duplicate-open-report control. |
| `moderation_cases`, `moderation_actions` | Queue, decisions, escalation, and history. |
| `destination_rating_stats` | O(1) Community and Guest sum/count aggregates. |
| `idempotency_keys` | Short-lived recent response replay. |
| `outbox_events` | Transactional cache, search, and media follow-up events. |
| `audit_events` | Append-only privileged activity record. |

Community tables are not required by this feature. A later Community specification may add `communities`, `community_memberships`, `community_posts`, and `community_comments` without changing review ownership or global authority.

### 9.2 API surface

```text
GET    /api/v1/destinations/{destination_id}/reviews
POST   /api/v1/reviews/guest
POST   /api/v1/reviews/member
GET    /api/v1/reviews/{review_id}
PATCH  /api/v1/reviews/{review_id}/pending
POST   /api/v1/reviews/{review_id}/withdraw
POST   /api/v1/review-receipts/status
POST   /api/v1/review-receipts/appeals
POST   /api/v1/reviews/{review_id}/reports
POST   /api/v1/public/review-reports
POST   /api/v1/public/removal-requests
POST   /api/v1/reviews/{review_id}/media-intents
POST   /api/v1/verifications
GET    /api/v1/staff/moderation/reviews
POST   /api/v1/staff/moderation/reviews/{review_id}/decisions
PUT    /api/v1/staff/moderation/reviews/{review_id}/conflict
GET    /api/v1/staff/verifications
POST   /api/v1/staff/verifications/{verification_id}/decisions
POST   /api/v1/staff/users/{user_id}/roles
```

All write APIs use server-side validation. Receipt exchange, authentication, and staff APIs are separately rate-limited. State-changing cookie-authenticated requests require CSRF protection.

Staff pages may use `admin.abhijatri.example`, but the hostname is not treated as a security boundary. Staff authentication, MFA, a short session lifetime, recent reauthentication for role changes, `can()` checks on every request, and audit records are mandatory. The first Super Administrator is created by a one-time bootstrap command, never public registration.

### 9.3 Query and pagination rules

Published review pagination uses the stable tuple `(published_at, id)`, with a default page of 20 and maximum of 50. A review approved after several days therefore appears at the correct position and in recent offline snapshots. `created_at` remains audit data. Every alternative order has its own complete cursor; cursors are not reused across sort modes.

Initial indexes include:

- Published review feed: destination, publication state, publication time, and ID.
- Member history: author user, creation time, and ID.
- Moderation queue: moderation state, queue priority, submission time, and ID.
- Open reports: review and report status.
- Verification queue: verification status and creation time.

Partitioning is not enabled merely for appearance. It is introduced after measured table and index growth justify it.

## 10. Security, privacy, retention, and recovery

- Review bodies are plain text; user HTML is never trusted or rendered.
- SQL is parameterised through the data-access layer.
- Public and staff rate limits are independent.
- Private data is excluded from service-worker caches and public CDN responses.
- Exact user coordinates are outside this feature and never enter review URLs or logs.
- Logs exclude receipt secrets, evidence files, review request bodies, and unnecessary personal data.
- Published content supports withdrawal, reporting, and account-deletion workflows.
- Security headers, TLS, secure HttpOnly cookies, SameSite policy, CSRF protection, and staff MFA are deployment requirements.

Retention defaults:

| Record | Default |
|---|---|
| Published review | Retain until withdrawal, deletion, or policy action. |
| Inactive pending review | 30 days, then erase after notice where applicable. |
| Rejected review body and revision content | 30-day appeal period, then tombstone the content even though revisions are otherwise append-only. |
| Receipt | Valid through the content or appeal lifetime; erase with final content erasure. |
| Verification evidence | Seven days pending; erase within 24 hours after decision. |
| Orphaned quarantine media | 24 hours. |
| Idempotency response | 72 hours. |
| Backup containing removed content | Rotate out within 35 days. |

A non-content deletion ledger is reapplied after restoration so erased reviews are not accidentally republished. Actual production retention must be reviewed against current Bangladeshi law and institutional policy before launch.

## 11. Performance and operational model

The semester release is a modular monolith. FastAPI instances are stateless apart from PostgreSQL and shared stores. Media processing and outbox consumption run as workers. Redis is an optimisation, not a source of truth; the application remains correct when Redis is unavailable.

Performance principles:

- Never scan all reviews during a moderation decision.
- Fetch bounded pages and selected columns.
- Cache public aggregates and first review pages only after measurement.
- Invalidate caches from committed outbox events.
- Serve processed media through object storage and a CDN.
- Monitor submission rate, moderation backlog, verification turnaround, failed media processing, duplicate conflicts, cache hit rate, and rating-delta failures.

The portfolio may state that the design supports horizontal growth. It must not claim millions of concurrent users without measured evidence. An optional data-volume benchmark may seed one million synthetic review rows; semester acceptance is based on correctness and documented load tests on the actual demonstration environment.

## 12. Implementation sequence and acceptance

### 12.1 Build order

1. Create identity, role, verification, review, revision, aggregate, audit, and outbox migrations.
2. Implement `can(actor, action, resource)` and bootstrap the first Super Administrator.
3. Build the structured form and IndexedDB text draft.
4. Complete Guest submission, permanent deduplication, receipt-scoped POST operations, and the no-reissue rule.
5. Build moderation, revisions, reports, and transactional aggregate deltas.
6. Publish Community Rating, Guest Feedback, counts, and Seeded Destination fallback.
7. Add Member ownership, Verified Member approval, badges, and conflict checks.
8. Complete offline snapshots, reconnection, low-data presentation, and accessibility.
9. Add protected staff user management and role assignment.
10. Add the Verified Member image pipeline (section 8). It is mandatory (amendment A1) and depends on step 7.

### 12.2 Mandatory acceptance cases

- A Guest submits a Bangla review without an account and receives a Guest label and receipt.
- Retrying the same offline draft after more than 72 hours returns the existing review, not a duplicate.
- A Member cannot impersonate a staff or Verified Member badge through the display name.
- Bangla names preserve valid NFC text and conjunct behavior.
- A pending review is invisible publicly and contributes to no aggregate.
- Publishing a Guest review adjusts Guest Feedback only.
- Publishing an eligible Verified Member review adjusts Community Rating sum and count exactly once.
- Hiding, withdrawing, or deleting an eligible review subtracts its rating in the same transaction.
- A rejected Guest can read the decision and appeal deadline during the 30-day window.
- A published review cannot be edited in the MVP; withdrawal followed by a new submission is required.
- Hidden, rejected, withdrawn, and deleted reviews never appear in public queries or ratings.
- An airplane-mode text draft survives reload and submits safely after reconnection.
- Failure after the server commits but before the client receives the response is recovered through permanent draft uniqueness.
- Public offline caches contain no account, receipt, private-community, or staff response.
- Low-data mode shows an image title, size, and explicit load link instead of fetching full media.
- Ordinary users cannot render a staff page or call a staff API even if they know its URL.
- Every moderation and role-assignment action creates an append-only audit event.
- Top Rated is not shown below five eligible Verified Member reviews; Seeded Destination Selection is shown instead.

### 12.3 Image-pipeline acceptance

These cases are mandatory (amendment A1):

- Only a Verified Member can create an image upload intent.
- Invalid signatures, SVG, excessive size, excessive pixel count, and abandoned uploads are rejected or purged.
- A Guest submission cannot carry or reference an image.
- An image is public only after moderator approval, with EXIF and GPS metadata removed.

### 12.4 Explicit exclusions

The Review MVP does not include video, automated Bangla sentiment analysis, real NID verification, Verified Visit proof, arbitrary private groups, live chat, vendor responses, guide or agency onboarding, booking, payment, or machine-learning moderation. These are separate future features and must not delay the accepted vertical slice.

## 13. Amendments

Approved by Shahriar Islam (scope owner) on 20 October 2026, requested by the frontend owner, and recorded in `Docs/Decisions.md` (2026-10-20). Each amendment replaces the earlier text in the sections named.

| ID | Change | Sections |
|---|---|---|
| A1 | Verified Member image upload moves from a conditional post-core extension into the mandatory release. Limits in section 8 are unchanged (five images, JPEG/PNG/WebP, 8 MiB, 20 megapixels, quarantine, re-encode, moderation). Guests remain text-only. | 1, 2.1, 8, 12.1 step 10, 12.3 |
| A2 | The review form is the seven section 3.1 category ratings (each optional, 1 to 5) plus the required overall rating and a free-text note (the body), for Guests and Members. No other question set is used. The request field is `category_ratings` (`Docs/api/API.md` 5.2). | 3.1 |
| A3 | Verified Member status stays a manually approved verification record (section 2.3). No NID, birth-registration number or national verification API is used; section 12.4 still excludes real NID verification. | 2.3 (confirmed, unchanged) |

### 13.1 Proposed amendment (not approved; nothing is built from it)

Requested by the project owner on 20 October 2026. It waits for the scope owner's decision. Until it is approved, section 12.4 ("The Review MVP does not include video") stands.

| ID | Proposed change | Sections |
|---|---|---|
| A4 (**approved by the owner 27 Oct 2026 without transcoding**, and for any signed-in member; see Decisions.md) | **Verified Member video, after the image pipeline (section 8) is live.** Verified Members only; at most one video per review. MP4 (H.264/AAC) only, at most 60 seconds and 50 MiB. Upload uses the same presigned quarantine flow as images. A worker validates the container, strips metadata, transcodes to one low-bitrate rendition, and creates a poster image. Moderators approve before publication. Video never autoplays. In low-data mode the card shows the title, duration and size with an explicit "Load video" action (section 7.4). Video is never included in offline packs. Guests remain text-only. | 1, 8, 7.4, 12.1, 12.3, 12.4 |
