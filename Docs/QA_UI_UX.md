# UI/UX QA notes — 28 October 2026

## Overview

Public destination and Guest-review screens have good basic loading/error states, bilingual support, semantic labels and accessible review controls. Prototype travel tools need clearer boundaries before release.

## Issues

1. **High — offline screen makes misleading claims.** `OfflinePacksPage` says “100% offline access” and “Airplane Mode Ready,” but only React state changes; no pack, IndexedDB data or service worker exists.

2. **High — Cost Planner is not usable end to end.** The page automatically calls `/api/v1/estimates`, an endpoint absent from the backend, so it will show an error instead of a budget.

3. **Medium — Planner controls lack complete accessibility semantics.** The party-size range has no programmatic label, and the comfort-tier buttons are not a radiogroup; screen-reader users cannot reliably identify the control state.

4. **Low — saved-trip delete icon has no explicit accessible name.** It depends on a `title`; add `aria-label` so assistive technology announces the action consistently.

## Suggested next step

Hide or label the planner/offline routes as unavailable until their APIs/PWA storage exist, then run a browser and keyboard/screen-reader pass at mobile and desktop breakpoints.

## Resolution (28 October 2026)

Issues 1 to 4 are resolved: the offline, planner and saved-trip screens are replaced by an honest "not available yet" screen (no claims, no API calls, no prototype controls). Details: `Docs/Frontend-Implemented.md` section 5a.
