# Security & QA Audit, 21 October 2026: redacted summary and follow-up

**Source:** external "Quality & Security Audit Report" of `main` at `eab9ff1`. The original PDF quoted a live credential, so it is kept **outside** the repository (`.gitignore`, `.github/scripts/check_committed_secrets.py`). This file is the redacted record.
**Follow-up work:** 22 October 2026, on `backend-dev`.

## Findings and status

| ID | Severity | Finding | Status (22 Oct 2026) |
|---|---|---|---|
| F-01 | High → **Critical** | A live Supabase database password in a developer `.env`. **Escalated:** the audit PDF that quoted it was committed in `de1e613` and pushed to the public `backend-dev`, and production used the same password. | **Owner action:** rotate the Supabase password and update Railway `DATABASE_URL`; remove the PDF from branch history (steps below). **Done in code:** CI check for credential URLs and unreviewed binary documents; report PDFs ignored. |
| F-02 | Medium | `react-router-dom` 6.x advisories (open redirect via backslash; SSR constructor injection) | **Fixed:** upgraded to 7.18.4. The app uses only declarative routing with code-built targets, so no import changes. |
| F-03 | Medium | Configuration tests depended on ambient environment variables | **Fixed:** an autouse fixture removes every settings variable, and each case passes its own `app_env`, `database_url` and CORS. The audit's command passes: `env -u APP_ENV -u DATABASE_URL -u RECEIPT_PEPPER pytest tests/test_config.py`. |
| F-04 | Medium | Dev/build toolchain advisories (vitest/tinypool RCE, vite, esbuild, tailwind chain) | **Mostly fixed:** `frontend/` and `ops/` now use Vite 8.3.5, `@vitejs/plugin-react` 6.1.2 and Vitest 5.0.5. `ops/` has 0 advisories. `frontend/` went from 15 (2 critical) to 7 (0 critical, 5 high, 2 moderate), all through Tailwind 3's build-time globbing (braces, micromatch, chokidar, postcss-selector-parser). **Open:** a Tailwind 3 → 4 migration, scheduled separately because the config moves into CSS and every page needs a visual check. |
| F-05 | Low | Stale `certifi` in a virtualenv | **Fixed:** `uv.lock` and the venv are at 2026.10.19; CI installs with `--locked`. |
| F-06 | Low | Security headers missing on early-return 413 and 504 responses | **Fixed:** `app/main.py` `guardrails` now sends every branch through one header step. Tests cover 413 from `Content-Length` and from a streamed body. |
| F-07 | Low | Cyclomatic complexity (`moderate_review` 13) | **Deferred (accepted):** a security-critical state machine with full test coverage; refactoring risk is greater than the benefit. |
| F-08 | Low | `ruff format` drift | **Team decision pending:** one repo-wide format commit plus `ruff format --check` in CI. |
| F-09 | Info | No `Content-Security-Policy` on the API | **Fixed:** `default-src 'none'; frame-ancestors 'none'` on every API response except the development-only `/docs` and `/openapi.json`. The ops dashboard already sends its own CSP from `ops/vercel.json`. |
| §6 | — | Audit regression tests | **Added:** `backend/tests/test_audit_additions.py` covers the receipt-format gate, `Accept-Language` fail-safe, IPv6 /64 and port normalisation, and the F-06 and F-09 header checks. |

## F-01 containment steps (owner runs; nothing is pushed automatically)

1. **Rotate:** Supabase → Project Settings → Database → Reset database password (24+ random characters).
2. **Update Railway** from `backend/` (the value stays out of history), then let it redeploy:
   ```powershell
   $u = Read-Host "New DATABASE_URL"; $u | railway variable set DATABASE_URL --stdin; Remove-Variable u
   ```
3. **Remove the PDF from branch history.** The branch is not merged into `main`; the PDF exists only in `de1e613` and its child `999d419`:
   ```powershell
   git stash -u
   git filter-branch --index-filter "git rm --cached --ignore-unmatch Docs/Security_QA_Audit_Report.pdf" -- f22daf6..backend-dev
   git update-ref -d refs/original/refs/heads/backend-dev
   git log --all --oneline -- Docs/Security_QA_Audit_Report.pdf   # must print nothing
   git stash pop
   git push --force-with-lease origin backend-dev
   ```
   Teammates then run `git fetch` and `git reset --hard origin/backend-dev`. Old commit hashes may stay viewable on GitHub until garbage collection; rotation (step 1) is what closes the hole.

## Verification (22 Oct 2026)

- **Backend:** ruff and mypy clean; 329 tests passed (unit and integration on PostgreSQL 17), run without a local `.env`.
- **Frontend:** `tsc`, 38 vitest tests and the build pass on React Router 7, Vite 8 and Vitest 5.
- **Ops:** `tsc`, 4 tests, build; `npm audit` reports 0.
- **Secret check:** `python .github/scripts/check_committed_secrets.py` flags exactly `Docs/Security_QA_Audit_Report.pdf` until step 3 removes it.
