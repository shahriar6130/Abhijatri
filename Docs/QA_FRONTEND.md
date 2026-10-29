# Frontend QA notes — 28 October 2026

## Overview

`npm run build` completed successfully and all 32 Vitest tests passed. The implemented destination and Guest-review client is type-safe at build time; unimplemented modules should not be presented as live features.

## Issues

1. **High — broken planner integration.** `PlannerPage.tsx` sends a POST request to `/api/v1/estimates`, but the backend has no matching route; every estimate attempt fails.

2. **High — dependency advisories.** `npm audit` reports 9 issues (2 critical, 1 high, 6 moderate), primarily in the Vite/Vitest development toolchain. Upgrade deliberately and rerun the build/test suite.

3. **Medium — prototype IDs/data bypass live destination data.** Planner, offline packs and saved trips use `PROTOTYPE_DESTINATIONS` and slugs such as `sajek-valley`, while the live destination API uses UUIDs.

4. **Medium — no browser E2E coverage was found.** Unit tests cover helper/API-client logic, but no automated test proves routing, submission, errors or responsive UI in a browser.

## What was done

Installed the lockfile-defined dependencies, ran the production build and ran the test suite. No frontend source or lockfile was changed.

## Resolution (28 October 2026)

1. Resolved: the planner no longer calls `/api/v1/estimates`.
2. Resolved: `npm audit` reports 0 vulnerabilities in `frontend`, `ops` and `staff` after the Vite 8 / Vitest 5 upgrade.
3. Resolved: prototype data and slug ids are deleted.
4. Open: browser E2E tests are still not in CI.

Details: `Docs/Frontend-Implemented.md` section 5a.
