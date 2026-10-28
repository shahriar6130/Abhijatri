# System Monitoring Dashboard

**Status:** Phase 1 implemented 22 October 2026 (token access, six panels, operations API, ops app, nightly roll-up); completed 27 October 2026 (catalogue-driven layout, 5xx counting of unhandled errors, `reviews.submitted` counter, full test coverage, test guide in section 12). Proposed 21 October 2026.
**Live:** dashboard `https://abhijatri-ops-44afee.vercel.app` (Vercel), API `https://abhijatri-backend.up.railway.app` (Railway, `abhijatri-api`).
**Companion:** `Docs/Guest-Identity-and-Visits.md` (produces the visitor numbers). Section 9 describes how the two connect. Issues with the earlier draft: `Docs/Reviews/Guest-Identity-Monitoring-review.md`.
**Goal from the team chat:** a private System Monitoring Dashboard where the team "sees everything in the system", and where new things can be connected later without rebuilding it.

## 1. Rules

| # | Rule | Source |
|---|---|---|
| R1 | The dashboard is a **separate build** on its own host. No dashboard code, route or link exists in the public app. | PF 5.1 |
| R2 | **A private URL is not protection.** Every request is checked by the API with a credential. | Security 4.1 |
| R3 | It is **read-only**, except for the roll-up trigger. Actions such as the Guest writes switch stay where their audit rules are (PF 14.6, R11). | Security 4.1, 4.3 |
| R4 | It shows **aggregates and system state, never people**: no names, guest tags, secrets, receipts, raw IPs, emails or review bodies. | Count-only rule; PF 26; Security 3.3 |
| R5 | Every number says where it comes from and how fresh it is. A missing source shows "unavailable", never 0. | Proposal "no fake live claims" |
| R6 | New monitoring is added as a **provider** (section 6), not by editing the core. | Owner request, 21 Oct 2026 |

## 2. Where it runs

```text
Ops dashboard (separate Vite app, own Vercel project, noindex)
        |
        | HTTPS, Authorization: Bearer <OPS_DASHBOARD_TOKEN>   (phase 2: staff session cookie + MFA)
        v
FastAPI  /api/v1/ops/*   (same API service, read-only queries)
        |                 \
        v                  v
 Supabase PostgreSQL     Upstash Redis
 (content, reviews,      (today's visit counters,
  visit_daily_stats)      request/event counters)
```

- **Host now:** a second Vercel project from the same repository (for example `ops/` directory, its own `vercel.json`), on an unlisted `*.vercel.app` name, with `X-Robots-Tag: noindex` and a strict CSP (no third-party scripts).
- **Host later:** `admin.<owned-domain>` as part of the staff build, once the domain and staff login exist (PF 5.1).
- The ops origin is added to the API's `CORS_ALLOWED_ORIGINS`.

## 3. Access control

### 3.1 Phase 1: ops token (now, until staff login)

| Item | Rule |
|---|---|
| Credential | `OPS_DASHBOARD_TOKEN`, at least 32 random bytes, set only in the API host's secret settings and kept in the password manager of two named owners |
| Disabled by default | If the variable is unset, every `/ops/*` route returns `404`. Production startup refuses a token shorter than 32 characters. |
| Transport | `Authorization: Bearer …` header only. Never in a URL, cookie or log. |
| Check | Constant-time compare (`hmac.compare_digest`). Wrong token: `401`, durable limit 10 failures per network per hour, then `429`. |
| Browser | The page asks for the token and keeps it in `sessionStorage` (gone when the tab closes), never `localStorage`. |
| Responses | `Cache-Control: no-store` |
| Rotation | Change the variable and redeploy; rotate when a team member leaves and at least each semester. |
| Decision record | A dated `Decisions.md` entry, because this is a new credential (PF 25 forbids development identity in production; this token is not an identity and reads aggregates only). |

### 3.2 Phase 2: staff login (with R04 and R11)

The token is removed. Access needs a staff session (`__Host-abhijatri_staff_session`, MFA) and `can(actor, "ops.read")`, granted to `ADMINISTRATOR` and `SUPER_ADMINISTRATOR`. The roll-up trigger needs `ops.run`. Each dashboard open writes an audit event. Panels can then declare a stricter permission (section 6).

## 4. Panels in the first version

| Panel id | Shows | Source | Freshness |
|---|---|---|---|
| `visitors` | Today: Guest, Verified, New Guest, New Verified, Total visits (A), New (B), **Old visits (A − B)**. Chart for 7/30/90 days, new vs returning. All-time guests. Legend: "visits are one visitor per day; same-day guest and member are counted in both". | Redis (today), `visit_daily_stats` (past days) | Live; past days after roll-up |
| `content` | Published destinations; guide items; advisories current / stale / expired; contacts | Postgres counts | Live |
| `reviews` | Reviews by status; pending against the ceilings (50 per destination, 500 total) with the 80 % warning; Guest writes paused switch state; Guest Feedback vs Community counts | Postgres counts, config | Live |
| `traffic` | Today's requests by status class (2xx, 4xx, 5xx), 429s, `CHALLENGE_FAILED`, top route templates by 5xx, `visits_dropped` | Redis event counters (section 7) | Up to 60 s |
| `health` | API version (commit), environment, uptime; database ready and latency; Alembic revision vs head; pool in use; Redis ping latency, last counter flush, last roll-up day; Turnstile enabled; counter switch | Probes run at request time, config | Live |
| `members` | Members, email-verified, active Verified Member badges, staff accounts by role. Shows "member sign-in not built" until R04. | Postgres counts | Live |

Not in the dashboard: the moderation queue itself (that is the staff moderation screen), any list of guests or tags, review text.

## 5. Operations API

All routes under `/api/v1/ops`, all `no-store`, all need the credential in section 3.

| Route | Purpose |
|---|---|
| `GET /ops/panels` | The panel catalogue: id, title (Bangla and English), version, refresh interval, permission. The dashboard builds its layout from this. |
| `GET /ops/panels/{panel_id}?days=30` | One panel's data in the panel format (section 6.2). Each panel loads and fails on its own. |
| `GET /ops/overview?days=30` | All panels at once, for a first paint. A failing provider gives `status: "unavailable"` for its panel only. |
| `POST /ops/jobs/visit-rollup` | Runs the roll-up from `Guest-Identity-and-Visits.md` 4.5. Idempotent. Called by the nightly GitHub Actions job and when the dashboard opens. |

Limits: 60 requests per minute per credential. A provider has a 2-second budget; a slower one is cut off and shown as unavailable.

## 6. Adding monitoring as the system grows

### 6.1 Provider contract (backend)

Each feature that wants to appear on the dashboard adds one provider module. The core never changes.

```python
# backend/app/ops/providers/<panel_id>.py
from app.ops.registry import Panel, register

@register
class ReviewsPanel(Panel):
    id = "reviews"                    # stable, kebab or snake case
    version = 1                       # bump when the data shape changes
    title = {"bn": "রিভিউ", "en": "Reviews"}
    permission = "ops.read"           # phase 2; a stricter one if needed
    refresh_seconds = 60
    sources = ("postgres",)           # postgres | redis | config | external
    owner = "backend"                 # who answers for it

    def collect(self, ctx) -> PanelResult:   # ctx: db session, redis, settings, days
        ...                                  # aggregates only; returns the 6.2 shape
```

`app/ops/registry.py` collects registered panels, runs each `collect` with the time budget, catches its errors, and adds `status`, `generated_at` and `sources`.

As built, `collect` is **synchronous** (it runs in a worker thread, 16 at most), not `async`. The registry adds `title`, `refresh_seconds` and `notes` to every panel. The optional `"view"` field is not implemented yet because no panel needs it. A provider that times out is cut off from the response, but its worker thread keeps running until `collect` returns, so keep every query short (the database statement timeout is the backstop).

### 6.2 Panel data format

```json
{
  "id": "reviews",
  "version": 1,
  "status": "ok",
  "generated_at": "2026-10-21T17:00:00Z",
  "sources": [{ "name": "postgres", "fresh_at": "2026-10-21T17:00:00Z" }],
  "blocks": [
    { "type": "stat",   "key": "pending_total", "label": {"bn": "অপেক্ষমাণ", "en": "Pending"}, "value": 12, "limit": 500, "level": "ok" },
    { "type": "series", "key": "by_day", "label": {"bn": "…", "en": "Submitted per day"}, "points": [{"date": "2026-10-20", "value": 4}] },
    { "type": "table",  "key": "by_status", "columns": ["status", "count"], "rows": [["PUBLISHED", 31]] },
    { "type": "status", "key": "guest_writes", "label": {"bn": "…", "en": "Guest writes"}, "value": "open", "level": "ok" }
  ]
}
```

- Block types: `stat`, `series`, `table`, `status`. The dashboard renders any panel from these four, so **a new backend panel shows up without a frontend change**.
- `level` is `ok`, `warn` or `critical`. Thresholds live in the provider, next to the rule they protect (for example the 80 % pending warning from PF 14.3).
- `status` is `ok`, `degraded` or `unavailable`. A missing number is `null` with `unavailable`, never 0 (R5).
- A provider that needs a custom view can name `"view": "<component>"`; the dashboard keeps a small map from view name to component and falls back to the generic blocks.

### 6.3 Event counters (for traffic-style metrics)

Features count events through one helper instead of writing to Redis themselves:

```python
from app.ops.events import count
count("reviews.submitted")          # names must be in EVENT_NAMES
```

- `app/ops/events.py` keeps an **allowlist** `EVENT_NAMES`. A name not in the list is rejected in tests, so no one can put a user value (an email, a path with an id) into a counter name.
- Counts are held in memory per process and flushed every `METRICS_FLUSH_SECONDS` (60) in one pipeline to the hash `abj:{env}:events:{YYYY-MM-DD}` with an 8-day TTL. This keeps Upstash usage to about 1,440 calls per day per instance instead of one per request.
- The request middleware counts status classes and route templates (never raw paths, PF 26).
- If a counter must outlive 8 days, its provider adds it to a daily roll-up table, following the visit roll-up pattern.

### 6.4 Checklist for a new panel

1. Write the provider (6.1) returning aggregates only (R4).
2. Add any new event names to `EVENT_NAMES` (6.3).
3. Add a test that the panel returns the 6.2 shape, respects its time budget, and contains no identifiers.
4. Document the panel in section 4 (id, what it shows, source, freshness) in the same commit.
5. If it uses a new external service, add it to the processor register (Security 3.8).

### 6.5 Planned panels

| Panel | Arrives with |
|---|---|
| `moderation` (queue age, decisions per moderator role, appeals) | R10, R11 |
| `auth` (sign-ins, failed logins, MFA enrolment, locked accounts) | R04 |
| `media` (uploads, rejected files, storage used) | R07 |
| `offline-packs` (pack versions, downloads) | R12, R13 |
| `community` (communities, posts, reports) | Community.md build |
| `outbox` (pending events, oldest age, failures) | PF 15 worker |
| `backups` (last backup, last restore test) | PF 23 jobs |
| `costs` (Upstash commands, Supabase size, Vercel and API host usage) | When billing APIs are wired; manual entry until then |

## 7. Alerts (later)

Phase 1 has no notifications; levels are only shown. When needed, a scheduled GitHub Actions job calls `GET /ops/overview` and sends any `critical` block to the team channel or email (Resend). Because thresholds already live in the providers, alerts need no new rules.

## 8. Upstash usage budget

| Use | Commands per day (approx.) |
|---|---|
| Visits | 2 per counted visit (1,000 visitors: 2,000) |
| Event flush | 1,440 per API instance |
| Dashboard | about 5 per panel load |

About 100,000 to 150,000 commands a month at 1,000 visitors a day. Check the current Upstash free-plan limit in its console before launch; the `costs` panel tracks this later.

## 9. Connection to Guest Identity and Visit Counting

```text
Guest-Identity-and-Visits                      System-Monitoring-Dashboard
--------------------------                      ---------------------------
POST /guest-visits  --HINCRBY-->  Redis abj:{env}:visits:{date}  <--read today--  visitors provider
GET /auth/session   --HINCRBY-->           |
                                           | roll-up (POST /ops/jobs/visit-rollup,
                                           v  nightly + on dashboard open)
                                 Postgres visit_daily_stats       <--read past---  visitors provider
Metric definitions (4.1, 5)  ------------------------------------>  panel labels, A − B tile
visits_dropped counter (4.6) --events--> Redis abj:{env}:events   <-------------  traffic provider
```

| Shared item | Defined in | Rule |
|---|---|---|
| Visit counter keys and TTL | Guest doc 4.4 | Dashboard reads, never writes |
| `visit_daily_stats` | Guest doc 4.5 | Written only by the roll-up job |
| Roll-up job | Guest doc 4.5 (logic), this doc 5 (route) | Same idempotent code path for cron and dashboard |
| Metric names and formulas | Guest doc 5 | The `visitors` provider imports them; it does not redefine them |
| `abj:{env}:` prefix and `REDIS_URL` | Guest doc 4.4, 7 | One Upstash database per environment, shared by both |

A change to any shared item updates both documents in the same commit.

## 10. Build order

1. `app/ops/registry.py`, `events.py`, the token check and the four routes; the `visitors` and `health` providers.
2. The ops Vite app: token prompt, catalogue, generic block renderer, 7/30/90-day selector; second Vercel project.
3. `content`, `reviews`, `traffic`, `members` providers.
4. GitHub Actions nightly roll-up job.
5. Phase 2 access (3.2) with R04 and R11; move to `admin.<owned-domain>`.

## 11. Tests

| Test | Proves |
|---|---|
| Token unset | Every `/ops/*` route is `404` |
| Wrong or missing token | `401`, then `429` after the limit; the token never appears in logs |
| Public build | The public `dist/` contains no `/ops` code or ops origin (string check in CI) |
| Provider isolation | One provider raising or timing out leaves the others `ok` |
| Panel shape | Every registered panel matches 6.2 |
| No identifiers | No panel output contains a guest tag, email, IP or secret pattern (`abr1_`, scope length) |
| Event allowlist | Counting an unknown name fails the test suite |
| Unhandled errors | A request that raises is counted in `http.5xx` and `route_5xx:<template>` (never the raw path) |
| Limits and headers | 60 requests a minute then `429`; `no-store` on 200, 401, 404 and 429 |
| CORS | The ops origin passes the preflight with the `Authorization` header; another origin gets no CORS header |
| Real data | `content` shows the published destinations; `traffic` shows counted events; `reviews.submitted` rises on a created review |
| Ops app | The client sends the token only in the header, keeps it in `sessionStorage`, orders panels by the catalogue, and renders all four block types in both languages |

## 12. Testing guide (local and live)

### 12.1 Automated checks

```text
cd backend
$env:TEST_DATABASE_URL = "postgresql+psycopg://abhijatri:abhijatri_dev@localhost:5434/abhijatri_test"
.venv\Scripts\python -m pytest -q          # 341 tests, none skipped when the variable is set
.venv\Scripts\python -m ruff check .
.venv\Scripts\python -m mypy app
cd ..\ops      ; npm ci ; npm test ; npm run build     # 19 tests
cd ..\frontend ; npm ci ; npm test ; npm run build     # 40 tests; the public build must not mention ops
```

`TEST_DATABASE_URL` must name a database ending in `_test`; the suite drops and recreates its tables. Start the local services first: `docker compose up -d postgres redis` with `POSTGRES_PORT=5434`.

### 12.2 Run everything locally

1. Services: `docker compose up -d postgres redis` (Postgres on 5434, Redis on 6379).
2. `backend/.env` must hold `DATABASE_URL` (port 5434), `REDIS_URL=redis://localhost:6379/0`, `OPS_DASHBOARD_TOKEN` (43 characters), `CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:5174`.
3. Migrate: `cd backend ; .venv\Scripts\python -m alembic upgrade head` (expect `0009_guest_tag_visit_stats (head)`).
4. API: `.venv\Scripts\python -m uvicorn app.main:app --port 8000 --reload` and check `http://localhost:8000/api/v1/health` returns `{"status":"ok"}`.
5. Public app: `cd frontend ; npm run dev -- --port 5173` (http://localhost:5173).
6. Dashboard: `cd ops ; npm run dev -- --port 5174` (http://localhost:5174). Without `ops/.env` it calls `http://localhost:8000`.
7. Open http://localhost:5174, paste the token from `backend/.env`, press **Open dashboard**.

### 12.3 What to check on the dashboard, panel by panel

| Step | Do this | Expect |
|---|---|---|
| 1 | Open the dashboard with a wrong token | "The token is not valid." and you stay on the token page. Ten wrong tries in an hour give "Too many failed attempts". |
| 2 | Open it with the right token | Six panels: Visitors, Content, Reviews, Traffic, Health, Members, in the order of `GET /ops/panels`, each with an `ok` badge and a "sources / fresh" footer. |
| 3 | In the public app, open http://localhost:5173 once (new browser profile or cleared storage) | **Visitors**: Guest 1, New Guest 1, Total visits (A) 1, New (B) 1, **Old visits (A − B) 0**. |
| 4 | Reload the public app the same day | Nothing changes: one visit per browser per Dhaka day. |
| 5 | In dev tools run `localStorage.setItem('abhijatri_last_visit_on','2000-01-01')`, reload the public app | A second post with `first_visit:false`. Dashboard Refresh: Guest 2, New 1, **Old 1**. A − B equals Old. |
| 6 | Press **Start as a new guest** on `/guest`, then reload | The tag changes but the visit dates stay, so **New Guest does not rise**. |
| 7 | Submit a guest review in the public app (Turnstile test key locally) | **Reviews**: pending rises by one and the by-status table shows the new row. **Traffic** after up to 60 s: 2xx rises. |
| 8 | Switch 7 / 30 / 90 days | Charts redraw. Days with no roll-up show gaps, not zeros. |
| 9 | Press **Run roll-up** | "Nothing new to roll up" the first day; after midnight (Dhaka) it lists the finished day. Pressing it again is harmless (idempotent). |
| 10 | Stop Redis (`docker compose stop redis`) and Refresh | **Visitors** and **Traffic** show `degraded` with dashes (never 0); **Health** shows Redis down; the other panels stay `ok`. Start it again with `docker compose start redis`. |
| 11 | Switch to বাংলা | Titles, labels, table headers and digits are in Bangla. |
| 12 | Press **Sign out**, then reopen the tab | The token is gone: `sessionStorage` is cleared when the tab closes. |
| 13 | Dev tools, Application: check storage | Only `sessionStorage` has `abhijatri_ops_token`; `localStorage` has none from the dashboard. |
| 14 | Dev tools, Network | Every ops call has `Authorization: Bearer …`, no cookie, no token in any URL, and `Cache-Control: no-store` on the responses. |

Generate traffic quickly from a terminal (no token needed for these):

```text
curl -X POST http://localhost:8000/api/v1/guest-visits -H "Content-Type: application/json" -d "{\"first_visit\":true}"
curl http://localhost:8000/api/v1/does-not-exist        # a 4xx for the Traffic panel
```

API-level checks (replace `$T` with the token, never paste it into chat or a URL):

```text
curl -i http://localhost:8000/api/v1/ops/panels                              # 401, no body detail
curl -i -H "Authorization: Bearer $T" http://localhost:8000/api/v1/ops/panels   # 200, six panels
curl -i "http://localhost:8000/api/v1/ops/overview?days=7" -H "Authorization: Bearer $T"
curl -i -X POST http://localhost:8000/api/v1/ops/jobs/visit-rollup -H "Authorization: Bearer $T"
curl -i "http://localhost:8000/api/v1/ops/overview?token=$T"                 # 401: a URL token is never accepted
```

### 12.4 Live (Railway API + Vercel dashboard)

Live addresses: dashboard `https://abhijatri-ops-44afee.vercel.app`, API `https://abhijatri-backend.up.railway.app`.

1. **Deploy order.** Push `backend-dev` to GitHub and merge to `main` so Railway redeploys the API (Railway builds from `main`). Then redeploy the dashboard from `ops/` (Vercel project root directory `ops`, build `npm run build`, output `dist`). Set the Vercel environment variable `VITE_API_BASE_URL=https://abhijatri-backend.up.railway.app` for Production **before** the build, because Vite bakes it in.
2. **Railway variables** (service `abhijatri-api`, environment `production`): `OPS_DASHBOARD_TOKEN` (at least 32 characters), `REDIS_URL` (`rediss://…` Upstash), `CORS_ALLOWED_ORIGINS` containing `https://abhijatri-ops-44afee.vercel.app` and your public frontend origin (exact scheme and host, no trailing path, never `*`), `APP_ENV=production`, `CLIENT_ADDRESS_HEADER`, `TURNSTILE_*`. After a change, Railway redeploys; confirm the deploy shows `SUCCESS`.
3. **Smoke tests from a terminal:**

```text
curl https://abhijatri-backend.up.railway.app/api/v1/health                  # {"status":"ok"}
curl -i https://abhijatri-backend.up.railway.app/api/v1/ops/panels           # 401 (404 would mean the token is unset)
curl -i -X OPTIONS https://abhijatri-backend.up.railway.app/api/v1/ops/overview \
  -H "Origin: https://abhijatri-ops-44afee.vercel.app" \
  -H "Access-Control-Request-Method: GET" -H "Access-Control-Request-Headers: authorization"
                                                                              # 200 with access-control-allow-origin = the ops origin
curl -I https://abhijatri-ops-44afee.vercel.app                              # x-robots-tag: noindex, nofollow, noarchive and a strict content-security-policy
```

4. **In the browser:** open the dashboard URL, paste the production token, and repeat 12.3 steps 2 and 8 to 14. The footer of the token page shows `API: <the API it will call>`; it must be the Railway address, not localhost.
5. **Public traffic into the live dashboard:** visit the public app (Vercel) once; after reloading the dashboard, Visitors shows the visit. Live visits are counted in Upstash, so Visitors works only when `REDIS_URL` is set and `VISIT_COUNTER_ENABLED` is not `false`.
6. **Nightly roll-up:** GitHub, Actions, **visit-rollup**, **Run workflow**. It needs the repository secrets `OPS_API_URL` (the Railway address) and `OPS_DASHBOARD_TOKEN`; without them the job skips cleanly. Expect a green run and "Rolled up" or "Nothing new" in the dashboard.

### 12.5 If something is wrong

| Symptom | Cause and fix |
|---|---|
| "Could not reach the API" with the right URL | The API is down, the deployed API predates the ops routes, or `CORS_ALLOWED_ORIGINS` lacks the dashboard origin (shown in the message). Fix the variable and redeploy. |
| "The ops API is off" (404) | `OPS_DASHBOARD_TOKEN` is unset on the API. Set it (32 or more characters) and redeploy. |
| Token page shows `API: http://localhost:8000` on Vercel | `VITE_API_BASE_URL` was missing at build time. Set it and redeploy the dashboard. |
| Blocked by the browser (CSP `connect-src`) | `ops/vercel.json` allows only `*.up.railway.app` and `*.onrender.com`. A custom API domain must be added there. |
| Visitors shows `degraded` and dashes | Redis is unreachable or `REDIS_URL` is wrong (production needs `rediss://`). Check Health for the Redis line. |
| Traffic shows zeros after real traffic | Events flush every 60 s; wait a minute and refresh. |
| "Too many failed attempts" | 10 wrong tokens from one network in an hour. Wait, or rotate the token. |
| Production API refuses to start | A short token (under 32 characters), a missing `rediss://` URL or `*` in CORS. Read the Railway deploy log. |
