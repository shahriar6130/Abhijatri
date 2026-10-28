# Guest Identity and Visit Counting

**Status:** Implemented 22 October 2026 (sections 3, 4.2, 4.4 to 4.6, 5; member visits wait for R04). Proposed 21 October 2026. Replaces the pasted "Production-Grade System Architecture" draft; the issues with that draft are in `Docs/Reviews/Guest-Identity-Monitoring-review.md`.
**Companion:** `Docs/System-Monitoring-Dashboard.md` (the private dashboard that reads these numbers). Section 9 describes how the two connect.
**Owner decisions it carries forward:** guest footprint is a count only (Decisions.md, 20 Oct 2026); guests have no account (Review.md 1.1); the team chat of 21 Oct 2026 (random unique guest string, badge on the device, "anonymous guest" heading on notes, Guest / Verified / New / Total / Old = A − B, Upstash Redis instead of the database for guests, Vercel hosting).

## 1. Decisions in one table

| # | Decision | Why |
|---|---|---|
| D1 | Each browser gets a random **guest tag** such as `1C669-J0TDY`, derived from the existing guest scope secret. It replaces "Guest #N". | Random, not guessable, reveals no traffic volume, needs no server row (chat C1, C6). |
| D2 | The tag lives **only on the device** (local storage). The server never stores a list of guests. | Count-only rule; "DB te store kora lagbe na". |
| D3 | The **server computes** the tag for a guest review from the scope secret and shows it under an "Anonymous guest" heading. A client cannot post under someone else's tag. | Chat C7; stops impersonation. |
| D4 | A **visit** is one visitor on one Asia/Dhaka day. "New" means the visitor's first ever day. Old visits = A − B is then exact. | Fixes the draft's formula (review issue 5). |
| D5 | Daily counters live in **Upstash Redis**. Once a day the four totals are rolled up into one Postgres row per day. No guest identifier is written anywhere on the server. | Upstash as agreed; history survives a Redis loss; the database holds numbers, not guests. |
| D6 | **Supabase stays the only database.** No Railway database and no Supabase Auth. | PF 4, 8.1; screenshot 4. |
| D7 | Counting is best effort: if Redis is down, the page still works and the miss is counted. | A counter must never break the product. |

## 2. Where it runs

```text
Browser (Vite React SPA on Vercel)
  local storage: guest scope secret -> guest tag (badge), first/last visit day
        |
        | HTTPS, JSON bodies only, no guest cookie
        v
FastAPI API (Railway now; Render in the plan; region Singapore)
  POST /guest-visits ---------------------> Upstash Redis  (daily counters, TTL 8 days)
  POST /reviews/guest  (computes guest_tag)       |
  GET  /auth/session   (member visit, R04)        | nightly roll-up (aggregate numbers only)
        |                                         v
        +------------------------------------> Supabase PostgreSQL
                                                 reviews.guest_tag, visit_daily_stats,
                                                 users.first_visit_on / last_visit_on (R04)
```

The browser talks only to FastAPI (PF 4). Vercel hosts static files only; it runs no middleware for this feature. Upstash is reached from FastAPI over TLS (`rediss://`), using the `redis` package that is already a backend dependency. Use an Upstash database in the same region as the API (ap-southeast-1) and one database per environment.

## 3. Guest identity

### 3.1 The guest tag

```text
guest_tag = CrockfordBase32( SHA-256( "abhijatri:guest-tag:v1\n" + guest_scope_secret ) )[first 50 bits]
display   = XXXXX-XXXXX        alphabet 0123456789ABCDEFGHJKMNPQRSTVWXYZ
```

- `guest_scope_secret` is the existing per-browser secret (`abhijatri_guest_scope`, 48 random bytes, `src/api/reviews.ts`). It is now created on the **first visit**, not at the first review, so the badge exists at once.
- The browser computes the tag with WebCrypto and shows it offline. The server computes the same value when the secret arrives in `POST /reviews/guest`.
- Why a plain hash and not the server HMAC keyring: the badge must work without a round trip. The secret has 384 random bits, so the tag reveals nothing about it. Forging a secret that matches one given tag takes about 2^50 hashes, and the tag grants no authority anyway: it is a public label on moderated text.
- 50 bits gives a 50 % chance of any two tags colliding only after about 33 million guests.
- **Test vector** (both implementations must match): secret `Zm9vYmFyLXRlc3QtdmVjdG9yLW5vdC1hLXJlYWwtc2VjcmV0LTAwMDAwMDAwMDAw` gives `1C669-J0TDY`.

### 3.2 What the device keeps

| `localStorage` key | Value | Status |
|---|---|---|
| `abhijatri_guest_scope` | Guest scope secret | Existing; now created on first visit |
| `abhijatri_guest_name` | Name typed on `/guest` | Existing |
| `abhijatri_guest_name_seen_on` | Dhaka date the name was last seen; the name is forgotten after 30 days without a visit | Existing |
| `abhijatri_first_visit_on` | Dhaka date of this browser's first visit | New |
| `abhijatri_last_visit_on` | Dhaka date of the last counted visit | New; replaces `abhijatri_guest_last_visit` (read once, then removed) |
| `abhijatri_guest_number` | Old "Guest #N" | Retired; read once only to mark the browser as returning |

The tag itself is not stored, because it is derived. All reads and writes are guarded for blocked storage, as `src/api/guests.ts` already does. Blocked storage means a one-off tag for that tab, and the visit is counted as new.

### 3.3 Badge and "Anonymous guest" on notes

| Place | Shows |
|---|---|
| Sidebar session card | "Welcome, Sadia · Guest `1C669-J0TDY`" (Bangla: "স্বাগতম, Sadia · অতিথি `1C669-J0TDY`"). Without a name: "Guest `1C669-J0TDY`". |
| `/guest` page | A badge "You are Guest `1C669-J0TDY`" (Bangla: "আপনি অতিথি `1C669-J0TDY`") beside the welcome heading. |
| Guest review card on a destination | **"Anonymous guest · `1C669-J0TDY`"** (বেনামী অতিথি) only. The typed name is **not** shown and not sent by the public API (owner, 22 Oct 2026); only moderators see it. Reviews written before the tag existed show "Anonymous guest" only. |
| Member review card | Name and Member / Verified Member badge, unchanged. |

The tag stays in Latin letters in both languages, like the receipt, because it is an identifier. "Anonymous" here means "no account", and the submission notice says so: *"Your reviews from this browser show the same guest tag, so readers can see they came from the same guest."* (Security 3.4 notice change.)

**Reset.** `/guest` offers "Start as a new guest". It makes a new scope secret, and therefore a new tag, only when no unsent draft is waiting. It does not reset the visit dates, so it does not inflate "new guests". Until drafts are stored on the device (R15), a draft lives only in the review form's state, and the form and `/guest` are separate pages, so no unsent draft can exist while the button is shown. The "no unsent draft" check is added with R15.

### 3.4 Sign-in, sign-out and loss

- **Guest sign-out** forgets the name only (Decisions 20 Oct). The name is also forgotten after 30 days without a visit (`abhijatri_guest_name_seen_on`). The tag, the visit dates and the secret stay. This fixes the developer's complaint that everything vanished on sign-out.
- **Member sign-in (R04)** sends nothing about the guest to the account. Guest reviews stay receipt-owned guest reviews. On member sign-out the browser is the same guest again with the same tag.
- **Lost when:** storage is cleared, a new browser or device is used, or a private window is opened. By design there is no server-side recovery, because nothing is stored. A visitor who wants persistence creates an account.

## 4. Visit counting

### 4.1 Definitions

| Term | Meaning |
|---|---|
| Day | Asia/Dhaka calendar date (`DEFAULT_DISPLAY_TIMEZONE`), never UTC midnight |
| Visit | One visitor counted once on one day. A browser reports at most once per day as a guest. A member is counted at most once per day by the server. |
| New | The visitor's first ever counted day: the browser had no `abhijatri_first_visit_on`, or the member row had no `first_visit_on` |
| Returning (Old) | Any later day |
| Guest | No member session |
| Verified | A signed-in member (email verified, PF 8.2). The "Verified Member" badge is a separate count on the dashboard (UI-Architecture 1.1). |

A person who browses as a guest and signs in on the same day counts once as a guest and once as Verified that day. This is accepted and shown in the dashboard legend.

### 4.2 Guest visit: `POST /api/v1/guest-visits` (changed)

```http
POST /api/v1/guest-visits
Content-Type: application/json

{ "first_visit": true }
```

Response `204 No Content`.

- The body has exactly one boolean. Any other field (name, tag, secret, device id) returns `422 UNKNOWN_FIELD`.
- The client sends it at most once per Dhaka day: if `abhijatri_last_visit_on` is today, it sends nothing. `first_visit` is `true` only when `abhijatri_first_visit_on` is missing and no retired key is present.
- Limits stay as today: burst `RATE_LIMIT_GUEST_VISIT` (20/minute), then durable `GUEST_VISITS_PER_NETWORK_PER_HOUR` (60), which returns `429 RATE_LIMITED`.
- `Cache-Control: no-store`. No cookie and no CSRF token.
- The response no longer returns a number, so traffic volume is not public. `GET /guest-visits/stats` is removed from the public API (the frontend defines `getGuestVisitStats` but never calls it) and moves to the dashboard API.

### 4.3 Member visit (with R04)

Counted on the server inside `GET /auth/session`, which the client calls on every app load once sign-in exists:

```sql
UPDATE app.users
SET last_visit_on = :today,
    first_visit_on = COALESCE(first_visit_on, :today)
WHERE id = :user_id AND last_visit_on IS DISTINCT FROM :today
RETURNING first_visit_on = :today AS is_new;
```

No row returned means the member was already counted today, and Redis is not called. Members are identified accounts (Community.md 1), so these two date columns are allowed. Until R04 ships, Verified numbers are 0 and the dashboard says "member sign-in not built".

### 4.4 Redis keys

All keys start with `abj:{APP_ENV}:` so development, staging and production cannot mix even on a shared database.

| Key | Type | Written by | TTL |
|---|---|---|---|
| `abj:{env}:visits:{YYYY-MM-DD}` | Hash with fields `guest_new`, `guest_returning`, `member_new`, `member_returning` | One `HINCRBY` + `EXPIRE` in a single transaction per counted visit | 8 days |
| `abj:{env}:rollup-lock:{YYYY-MM-DD}` | String, `SET NX` | Roll-up job | 300 s |

Nothing in Redis identifies a person: no tag, secret, IP, user id or user agent.

### 4.5 Nightly roll-up to Postgres

New table (Alembic migration; RLS enabled and `anon`/`authenticated` grants revoked like every other table):

| Column | Type | Rule |
|---|---|---|
| `day` | `date` PK | Dhaka date |
| `guest_new`, `guest_returning`, `member_new`, `member_returning` | `int` | `CHECK (>= 0)`; `NULL` only for legacy days where the split is unknown |
| `guest_total_legacy` | `int` null | Totals migrated from the old `guest_visits` rows |
| `rolled_up_at` | `timestamptz` | |

- **When:** a GitHub Actions schedule at 00:15 Dhaka (PF 4: scheduled jobs run in GitHub Actions) calls the dashboard roll-up route (`System-Monitoring-Dashboard.md` 5). Opening the dashboard also rolls up any missing finished day from the last 7, so one failed run loses nothing.
- **How:** take the lock; for each finished day whose Redis hash exists, upsert the absolute values (`INSERT … ON CONFLICT (day) DO UPDATE`). Running it twice gives the same row. A missing hash never overwrites an existing row with zeros.
- **Today** is always read live from Redis; earlier days come from Postgres.
- **Migration of `guest_visits`:** copy its per-day counts into `guest_total_legacy` (they cannot be split into new and returning), then drop the table in the same migration. The existing rows are pre-release test data (Backend-Implemented 4.1).

### 4.6 Failure behaviour

| Failure | Behaviour |
|---|---|
| Redis slow or down | Command timeout `REDIS_TIMEOUT_MS` (300 ms). `POST /guest-visits` still returns `204`, the in-process counter `visits_dropped` goes up, and a warning is logged without any request data. The dashboard shows Redis as down and the dropped count. |
| Roll-up job fails | Retried by the next dashboard open for up to 7 days (TTL 8 days). After that the day is lost and the dashboard shows a gap, not a zero. |
| Redis data lost | Finished days are safe in Postgres; only today is lost. |
| Script inflating counts | Same per-network limits as today. Exact protection is impossible without identifying guests, which the owner ruled out; the dashboard shows the 429 count so inflation is visible. |

## 5. Metrics this system produces

For a single day:

| Metric | Formula |
|---|---|
| Guest | `guest_new + guest_returning` |
| Verified | `member_new + member_returning` |
| New Guest | `guest_new` |
| New Verified | `member_new` |
| **A** Total visits | Guest + Verified |
| **B** New visits | New Guest + New Verified |
| **Old visits = A − B** | `guest_returning + member_returning` (true by construction) |

Over a range (7, 30 or 90 days) each metric is the sum of the days. Range totals are **visitor-days**, not distinct people: a guest who comes on 5 days is 5 visits and 1 new. Distinct guests over a range cannot be known without storing guest identities, and the dashboard labels this. "All-time guests" is the sum of `guest_new` plus the legacy total.

## 6. Data inventory and privacy

| Data | Where | Personal? | Retention |
|---|---|---|---|
| Scope secret, name, visit dates | Browser only | Device data under the guest's control | Until cleared or reset |
| `reviews.guest_tag` | Postgres, public on published reviews | Public pseudonym | Same as the review (Review.md retention) |
| Daily counters | Upstash | No | 8 days |
| `visit_daily_stats` | Postgres | No (four integers per day) | Kept; aggregate statistics |
| `users.first_visit_on`, `last_visit_on` | Postgres | Member account data | Deleted with the account |
| Rate-limit buckets | Postgres (existing) | Keyed network digest | 2 days (existing) |

Never stored or logged: the scope secret on the server, raw IPs, user agents, a per-visit row, or a list of guest tags. The tag is not written to logs or analytics (PF 26 already covers scope secrets; add the tag to the log filter as a backstop).

## 7. Configuration

| Variable | Required | Meaning |
|---|---|---|
| `REDIS_URL` | Production and staging: yes | `rediss://default:<password>@<host>:6379` for this environment's Upstash database. Secret; host dashboard only, never committed. Startup fails closed in production if it is missing or not `rediss://`. |
| `REDIS_TIMEOUT_MS` | No | Default `300` |
| `VISIT_COUNTER_ENABLED` | No | Default `true`; the kill switch for counting |

Development and CI use a local Redis container or `fakeredis` in tests; they never touch Upstash.

## 8. Tests

| Test | Proves |
|---|---|
| Tag parity | Python and TypeScript give `1C669-J0TDY` for the vector in 3.1 |
| Tag from server only | `POST /reviews/guest` with a `guest_tag` field returns `422`; the stored tag equals the one derived from the secret |
| Body allowlist | `POST /guest-visits` with any field other than `first_visit` returns `422` |
| A − B identity | Random sequences of visits: Old visits always equals A − B, per day and over ranges |
| Redis down | `204`, `visits_dropped` goes up, no exception reaches the client |
| Roll-up | Idempotent; a missing hash never zeroes an existing row; the lock prevents double runs |
| No identifiers | `visit_daily_stats` has exactly the columns in 4.5; no Redis key or value contains a tag, secret or address |
| Client | Once per Dhaka day; first visit flag only once; sign-out keeps tag and dates; blocked storage still renders |

## 9. Connection to the System Monitoring Dashboard

This system **produces** numbers; the dashboard **reads** them. They share three contracts, and nothing else:

| Contract | Owned by | Used by the dashboard |
|---|---|---|
| Redis hash `abj:{env}:visits:{date}` (4.4) | This document | The "Visitors" panel reads today live |
| Table `visit_daily_stats` (4.5) | This document | The "Visitors" panel reads finished days |
| Metric definitions (sections 4.1 and 5) | This document | The panel labels and the A − B tile |

The roll-up job (4.5) is started through the dashboard's operations API, because that API already has the protected credential. The dashboard registers this system as its `visitors` metric provider (Dashboard doc, section 6). If either side changes a key name, column or definition, both documents change in the same commit.

## 10. Companion changes once approved

| File | Change |
|---|---|
| `Docs/Decisions.md` | New entry, 21 Oct 2026: guest tag (D1 to D3), Guest #N retired, Upstash adopted for counters only (amends the Redis deferral in PF 32 and "Scope control" for this purpose), roll-up to `visit_daily_stats` |
| `Docs/api/API.md` | 4.1 rows; 5.14 rewritten to section 4.2 here; `GET /guest-visits/stats` removed; 5.8 feed adds `guest_tag` |
| `Docs/Schema.md` | `visit_daily_stats`; `reviews.guest_tag char(10) null`; `users.first_visit_on`, `last_visit_on` (with R04); `guest_visits` dropped |
| `Docs/Security.md` | 3.2 inventory (guest tag as public pseudonym); 3.4 notice text; 3.8 processor register: Upstash (aggregate counters, no personal data, ap-southeast-1) |
| `Features/Platform-Foundation.md` | 23.5 processor list adds Upstash; 32 notes the counter exception |
| `Docs/UI-Architecture.md` | 1.1: "Guest #N" becomes "Guest tag"; add "Anonymous guest" (বেনামী অতিথি) |
| `Docs/Architecture.md` | Diagram and environment variables from sections 2 and 7 |

## 11. Build order

1. Backend: Redis client, `POST /guest-visits` change, `visit_daily_stats` migration and roll-up, tests.
2. Frontend: tag, badge, first-visit flag, storage key migration.
3. Backend then frontend: `reviews.guest_tag` and the "Anonymous guest · tag" card.
4. Dashboard phase 1 (Dashboard doc, section 10).
5. Member visits with R04.
