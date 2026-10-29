# Documentation QA notes — 28 October 2026

## Overview

The repository has strong coverage of architecture, API, schema, implementation status and security requirements. The main quality issue is that some historical wording now contradicts current code or newer status records.

## Issues

1. **High — Architecture receipt flow is obsolete.** `Docs/Architecture.md` still says Guest submission returns a server-issued receipt and describes the exchange endpoint as current/deprecated, while the code uses client-generated receipts and `/review-receipts/status`.

2. **Medium — implementation status is internally inconsistent.** `Docs/Implemented.md` lists rate limiting as not implemented in one row, but later correctly records durable limits and Turnstile as implemented; reconcile the status table.

3. **Medium — historical evidence needs a clear freshness label.** Several documents cite local results from 19–20 October; label them as historical and link to the current CI run instead of presenting them as current verification.

4. **Low — planned features are mixed with delivered screens.** Planner, packs and saved trips are documented as prototype/deferred in some locations, but their UI wording can make their availability unclear; use one consistent “prototype/not available” label.

## What was done

Compared README, architecture, implementation records, feature specifications and API-related code/tests. Documentation was reviewed only; no project specification was edited.
