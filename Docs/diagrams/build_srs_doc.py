"""Builds Docs/Abhijatri-SRS-Completion.docx: coverage check of the proposal and the missing SRS sections, ready to paste."""

import json
from collections import Counter
from pathlib import Path

from docx_helpers import BAD_FILL, GOOD_FILL, Doc

HERE = Path(__file__).resolve().parent
DOCS = HERE.parent
OUT = DOCS / "Abhijatri-SRS-Completion.docx"

GREEN, AMBER, RED = "E3F3EA", "FFF4D6", "F9DFD8"


def api_groups() -> list[list[str]]:
    spec = json.loads((DOCS / "api" / "openapi-v1.json").read_text(encoding="utf-8"))
    counts = Counter()
    for path, methods in spec["paths"].items():
        route = path.replace("/api/v1", "")
        seg = route.strip("/").split("/")
        key = "/" + seg[0]
        if seg[0] == "admin":
            key = "/admin"
        counts[key] += sum(1 for m in methods if m in ("get", "post", "put", "patch", "delete"))
    meaning = {
        "/admin": "Staff API: task queue and leases, review decisions, appeals, reports, enforcement, verification cases, audit log, staff roles, notification administration, media decisions",
        "/auth": "Registration, email verification, sign-in and sign-out, password reset, TOTP enrolment, re-authentication, session and CSRF token",
        "/reviews": "Guest and member review creation, edit while unpublished, withdraw, owner view, member history, media upload, reports",
        "/review-receipts": "Receipt status and guest appeals (the receipt travels in the request body)",
        "/destinations": "Published destination list, profile, and the public review feed",
        "/notifications": "Member inbox, unread count, mark read, live stream",
        "/notification-preferences": "Email and notification preferences",
        "/appeals": "Member appeals against rejection or hiding",
        "/verifications": "Verified Member requests and evidence",
        "/ops": "Operator panels (token protected)",
        "/health": "Liveness and readiness",
        "/staff": "Original review moderation endpoints (kept for the vertical slice)",
        "/guest-visits": "First-visit signal counted in Redis",
        "/review-parameters": "Limits and labels the review form needs",
        "/webhooks": "Email provider callbacks",
    }
    rows = [[k, str(v), meaning.get(k, "")] for k, v in sorted(counts.items(), key=lambda kv: -kv[1])]
    rows.append(["Total", str(sum(counts.values())), "operations in docs/api/openapi-v1.json"])
    return rows


def main() -> None:
    doc = Doc(
        "SRS Completion and Proposal Coverage",
        "What the project proposal already covers, what a complete SRS still needs, and the missing sections ready to paste",
        [
            ("Project", "Abhijatri: a Bangla-first, offline-ready community travel platform for Bangladesh (Team ChoturMatra, CSE 3102)"),
            ("Document", "Proposal coverage check, SRS gap analysis, and the missing SRS sections"),
            ("Version", "1.0, 30 October 2026"),
            ("Checked against", "Docs/Abhijatri_Project_Proposal.tex and its PDF (proposal date 12 October 2026) and the repository at 30 October 2026"),
            ("Companion documents", "Abhijatri-DFD.docx (data flow diagrams), Abhijatri-Venn-Diagram.docx, Abhijatri-Proposal-Judging-Checklist.docx"),
            ("Standard followed", "Section order follows the usual SRS structure of IEEE 29148 (introduction, overall description, specific requirements, appendices)"),
        ],
        "Abhijatri: SRS Completion",
    )
    doc.contents()

    # ------------------------------------------------------------------ 1
    doc.h1("1. Summary")
    doc.p("The proposal already contains **all nine** points your instructor requires. Each is present and substantial. What it does not contain is the rest of a Software Requirements Specification (SRS): "
          "a glossary, constraints, assumptions, external interface requirements, data requirements, detailed use case descriptions, state and sequence diagrams, a data flow diagram, a traceability matrix, and revision history. "
          "It was also written on 12 October 2026, before the review, moderation, notification and account features were built, so some statements need an \"as built\" note.")
    doc.table(
        ["Question", "Answer"],
        [
            ["Are the nine required proposal points present?", "Yes, all nine (section 2)."],
            ["Is there a use case diagram?", "Yes: the UML use case model with four actors and ten packages (proposal section \"Primary Use Cases\"). It is reproduced in section 4.4 of this document."],
            ["Is there a complete SRS?", "Not yet. 14 standard SRS elements are missing or only partly covered (section 3). Sections 4 to 10 supply them."],
            ["Is there a data flow diagram?", "No in the proposal. It is now in Abhijatri-DFD.docx (context, level 0, level 1 and level 2)."],
            ["Does the proposal match what was built?", "Mostly in intent, but with differences listed in section 11 (for example Supabase Auth instead of self-managed password hashing, and the offline features still being prototypes)."],
        ],
        [6.0, 10.5], caption="Summary of findings",
    )
    doc.note("**How to use this document.** Sections 4 to 11 are written so they can be copied into the proposal or the SRS report as they are. "
             "Where something is a prototype or not built, the text says so plainly; do not remove those statements, because they are what the repository supports.")

    # ------------------------------------------------------------------ 2
    doc.h1("2. The nine required proposal points: coverage")
    fills = {(i, 1): GREEN for i in range(9)}
    doc.table(
        ["#", "Required point", "Where in the proposal", "Assessment and what to improve"],
        [
            ["1", "Executive Summary", "Section 1, Executive Summary", "Present. Covers the problem, the solution and the semester outcome (a tested PWA with five seeded destinations). Improve: add one sentence of as-built status and one headline measure."],
            ["2", "Problem Statement", "Section 2, five subsections (fragmented information, unclear costs, weak connectivity, Bangla-first support, trust and freshness)", "Present and well structured. Improve: add one or two cited sources or survey figures if available, because the section states the gap without evidence."],
            ["3", "Objectives and Goals", "Section 3, objectives O1 to O8 with completion measures", "Present and measurable (for example 10 of 10 airplane-mode tests, at least eight consenting participants). Improve: add the results as they become known; note that O4 depends on offline features that are not built yet."],
            ["4", "Functional Requirements", "Section 4: core and future features, user roles, FR01 to FR17 catalogue, cost planner rules, use case model, user stories, MVP exclusions", "Present and the strongest section. Improve: add use case specifications (section 4.6 here) and an as-built status per requirement (section 4.4)."],
            ["5", "Non-functional Requirements", "Section 5, table with performance, security, reliability, scalability, usability and accessibility, maintainability, portability, privacy", "Present with acceptance measures. Improve: state uptime and load targets as numbers, name an accessibility standard, and record measured results."],
            ["6", "Stakeholders", "Section 6, seven stakeholder groups with interest and engagement", "Present. Improve: add influence and interest levels and who is the decision owner."],
            ["7", "Timeline / Milestones", "Section 7: milestones M1 to M4 and gate G1, formal testing phase, Gantt chart with dependencies and effort", "Present and detailed. Improve: add a \"planned versus actual\" column as of the submission date."],
            ["8", "Risk Assessment", "Section 8, 13 risks with level, early warning, mitigation and owner", "Present. Improve: add likelihood and impact scores, residual risk and a risk for dependence on third-party services (Supabase, Cloudflare, email provider)."],
            ["9", "Feasibility Study", "Section 9: technical, economic (BDT 6,000 ceiling), schedule, operational and ethical", "Present, covers all three required kinds plus one more. Improve: update the cost table with the actual hosting and service costs, and say what happens if free tiers end."],
        ],
        [0.8, 3.2, 5.0, 7.5], caption="Coverage of the nine required points", size=8.6, fills=fills,
    )

    # ------------------------------------------------------------------ 3
    doc.h1("3. What a complete SRS adds: gap analysis")
    srs = [
        ["Introduction", "Purpose of the document", "Partly", "Executive Summary and Scope Decision", "Section 4.1.1"],
        ["Introduction", "Scope of the product", "Yes", "Scope Decision, MVP exclusions", "Reuse; section 4.1.2 restates it"],
        ["Introduction", "Definitions, acronyms, abbreviations (glossary)", "Missing", "none (0 mentions)", "Section 4.1.3"],
        ["Introduction", "References", "Missing", "none", "Section 4.1.4"],
        ["Overall description", "Product perspective and system context", "Partly", "Architecture is mentioned only in feasibility", "Section 4.2.1 with the context DFD"],
        ["Overall description", "Product functions", "Yes", "Core and future features", "Section 4.2.2 maps them to processes"],
        ["Overall description", "User classes and characteristics", "Yes", "User roles table", "Section 4.2.3 adds Verified Member, moderator, superadmin, ops"],
        ["Overall description", "Operating environment", "Partly", "Portability row", "Section 4.2.4"],
        ["Overall description", "Design and implementation constraints", "Missing", "none", "Section 4.2.5"],
        ["Overall description", "Assumptions and dependencies", "Partly", "3 scattered mentions", "Section 4.2.6"],
        ["Specific requirements", "External interface requirements (user, software, hardware, communications)", "Missing", "none", "Section 4.3"],
        ["Specific requirements", "Functional requirements", "Yes", "FR01 to FR17", "Reuse; section 4.4 adds status as built"],
        ["Specific requirements", "Non-functional requirements", "Yes", "Eight categories", "Reuse; section 4.8 adds evidence"],
        ["Specific requirements", "Data requirements (data model, retention)", "Missing", "none", "Section 4.5 with the ER diagram"],
        ["Specific requirements", "Use case specifications", "Partly", "Diagram and user stories only", "Section 4.6"],
        ["Specific requirements", "Behaviour models (state, sequence)", "Missing", "none", "Sections 4.7 (state) and 4.8 (sequence)"],
        ["Appendices", "Data flow diagram", "Missing", "none", "Abhijatri-DFD.docx"],
        ["Appendices", "Requirements traceability matrix", "Partly", "User stories trace to FR", "Section 4.9: FR to use case to API to test"],
        ["Appendices", "Verification plan", "Yes", "Formal testing table and phases", "Reuse"],
        ["Appendices", "Revision history and approval", "Missing", "none", "Section 4.11"],
    ]
    fills = {}
    for i, r in enumerate(srs):
        fills[(i, 2)] = {"Yes": GREEN, "Partly": AMBER, "Missing": RED}[r[2]]
    doc.table(["SRS part", "Element", "Status in the proposal", "What exists", "Supplied by"], srs, [2.6, 4.7, 2.0, 3.8, 3.5], caption="SRS elements: present, partly present, missing", size=8.4, fills=fills)
    missing = sum(1 for r in srs if r[2] == "Missing")
    partly = sum(1 for r in srs if r[2] == "Partly")
    doc.p(f"Of {len(srs)} elements, {len(srs) - missing - partly} are present, {partly} are partly present and {missing} are missing. "
          "The 14 gaps (missing plus partly present) are all filled by the sections that follow.")

    # ------------------------------------------------------------------ 4
    doc.page_break()
    doc.h1("4. Paste-ready SRS sections")
    doc.note("Numbering below is the section numbering of the SRS you would assemble: 4.1 is SRS section 1 and so on. Rename them when you paste.")

    # ---- 4.1
    doc.h2("4.1 Introduction")
    doc.h3("4.1.1 Purpose")
    doc.p("This Software Requirements Specification describes Abhijatri, a Bangla-first, offline-ready community travel platform for Bangladesh. It states what the system must do and the qualities it must have, "
          "so that the team, the instructor and the evaluators can judge the finished product against the same list. It is written for the four team members (frontend, backend, quality assurance and project leader), the course instructor and external evaluators.")
    doc.h3("4.1.2 Scope")
    doc.p("Abhijatri lets travellers explore destinations in Bangla or English, read dated advisories, write and read moderated reviews, and (in the semester plan) estimate trip cost and use destination packs without a connection. "
          "Staff moderate content, decide appeals, verify members and monitor the system.")
    doc.table(
        ["In scope (semester MVP)", "Out of scope (future or excluded)"],
        [
            ["Five seeded destination profiles with sourced, dated guidance, contacts and advisories", "Real payment, SMS gateways, NID verification, live inventory"],
            ["Bangla and English interface", "Native mobile applications"],
            ["Guest and member reviews, structured ratings, moderation, appeals, reports, notifications", "Live chat, arbitrary private groups, vendor responses, booking"],
            ["Accounts, email verification, TOTP for staff, roles, audit log", "Automated sentiment analysis and machine-learning moderation"],
            ["Operations dashboard and retention jobs", "Editing a published review (withdraw and resubmit instead)"],
            ["Prototype screens for cost planning, offline packs and saved trips (not yet functional)", "Agency and guide onboarding, commissions"],
        ],
        [8.2, 8.3], caption="Scope boundary",
    )
    doc.h3("4.1.3 Definitions, acronyms and abbreviations")
    gl = [
        ["API", "Application programming interface. Here, the FastAPI service under /api/v1."],
        ["Appeal", "A request to reconsider a rejection or hiding decision, allowed until the end of the 30th day (Asia/Dhaka)."],
        ["Audit event", "An append-only record of a privileged action: who, what, when, and why."],
        ["BDT", "Bangladeshi taka."],
        ["CSRF", "Cross-site request forgery; prevented with a token that must accompany every signed-in write."],
        ["Draft id", "A random UUID created on the device for one review; the server keeps only one review per draft id, so retries are safe."],
        ["Guest", "A visitor without an account. Guest reviews never change the Community Rating."],
        ["Guest Feedback", "The average of published Guest ratings, shown separately from the Community Rating."],
        ["Community Rating", "A Bayesian score built only from eligible Verified Member reviews."],
        ["IndexedDB", "The browser database planned for drafts and offline packs (not built yet)."],
        ["Lease", "A time-limited claim (300 seconds) a moderator holds on a task so two people do not decide the same item."],
        ["Member / Verified Member", "A signed-in user / a member whose identity evidence staff approved."],
        ["MFA / TOTP", "Multi-factor authentication / time-based one-time password from an authenticator app."],
        ["Moderator / Superadmin", "Staff roles. Both need TOTP; only a superadmin can grant roles."],
        ["MVP", "Minimum viable product: the semester deliverable."],
        ["Outbox", "A database table of events written in the same transaction as the change they describe, processed later by a worker."],
        ["PWA", "Progressive web application: a website that can be installed and work offline."],
        ["RLS", "PostgreSQL row-level security, enabled on every public table."],
        ["Receipt", "A secret the Guest's browser generates (abr1_ plus 43 characters). The server stores only a keyed digest and never reissues it."],
        ["Revision", "One saved version of a review's content; revisions are append-only."],
        ["Supabase", "Hosted PostgreSQL, identity and storage provider used by the project."],
        ["Turnstile", "Cloudflare's bot-check widget used on guest submissions."],
        ["Verified Visit", "A future, separate claim that a visit happened; not the same as Verified Member."],
        ["WP / R-number", "Work package and Gantt task identifiers (for example R07 = structured review CRUD)."],
    ]
    doc.table(["Term", "Meaning in this project"], gl, [3.4, 13.1], caption="Glossary", size=8.6, bold_first_col=True)
    doc.h3("4.1.4 References")
    doc.bullets([
        "Abhijatri Project Proposal, 12 October 2026 (`Docs/Abhijatri_Project_Proposal.pdf`).",
        "`Docs/Architecture.md`, `Docs/Schema.md`, `Docs/Security.md`, `Docs/Decisions.md`, `Docs/Implemented.md`.",
        "`Docs/Backend-Implemented.md` and `Docs/Frontend-Implemented.md` (what is built and the evidence).",
        "`Docs/api/API.md` and `Docs/api/openapi-v1.json` (the API contract).",
        "`Features/Review.md`, `Features/Platform-Foundation.md`, `Features/Execution.md` (feature specifications).",
        "`Docs/Moderation-Dashboard-Specification.md`, `Docs/Notification-Documentation.md`, `Docs/System-Monitoring-Dashboard.md`.",
        "IEEE Std 29148-2018, Systems and software engineering: Life cycle processes: Requirements engineering (structure of this SRS).",
        "Abhijatri-DFD.docx and Abhijatri-Venn-Diagram.docx (companion documents).",
    ])
    doc.h3("4.1.5 Overview of the rest")
    doc.p("Section 4.2 describes the product in context. Section 4.3 lists its interfaces. Sections 4.4 to 4.8 give functional, data and behaviour requirements. Section 4.9 traces requirements to code and tests. "
          "Sections 4.10 and 4.11 compare the proposal with what was built and record revisions.")

    # ---- 4.2
    doc.h2("4.2 Overall description")
    doc.h3("4.2.1 Product perspective")
    doc.p("Abhijatri is a new, self-contained system with four deployable parts and a small number of external services. "
          "The public web app (React, TypeScript) talks only to the API; it holds no database key. The FastAPI service enforces all authorisation, moderation, receipt checks and rating arithmetic. "
          "PostgreSQL (hosted by Supabase) is the source of truth. A separate staff web app and a private operations app use the same API.")
    doc.figure(HERE / "dfd-context.png", "System context (the context data flow diagram)", 15.8, 12.0)
    doc.h3("4.2.2 Product functions")
    doc.table(
        ["Function group", "What the system does", "DFD process"],
        [
            ["Destination guidance", "Shows bilingual destination profiles, advisories with a current, stale or expired state, contacts and rating summaries", "1.0"],
            ["Trip planning (prototype)", "Estimate cost, save trip briefs, download packs", "2.0"],
            ["Accounts", "Register, verify email, sign in, reset password, TOTP for staff, roles", "3.0"],
            ["Reviews", "Create, edit while unpublished, withdraw, view status and history, attach media, appeal, report", "4.0"],
            ["Notifications", "In-app inbox and email with preferences, retries and digests", "5.0"],
            ["Moderation", "Task queue, decisions, ratings, appeals, reports, enforcement, verification", "6.0"],
            ["Operations", "Panels, audit log, visit counters, retention", "7.0"],
        ],
        [3.6, 10.5, 2.4], caption="Product functions and the data flow processes that realise them",
    )
    doc.h3("4.2.3 User classes")
    doc.table(
        ["User class", "Description", "Technical skill", "Can do"],
        [
            ["Guest", "Traveller without an account; may use Bangla only and a low-end Android phone", "Low", "Browse, read reviews, submit one review with a receipt, check status, edit or withdraw it, appeal a rejection"],
            ["Member", "Signed-in user with a verified email", "Low to medium", "Everything a Guest can; also own review history, media upload, appeals, reports, notifications, verification request"],
            ["Verified Member", "Member whose evidence staff approved", "Low to medium", "Their reviews can count toward the Community Rating"],
            ["Moderator", "Staff with TOTP", "Medium", "Claim tasks, decide reviews, appeals and reports, review verification"],
            ["Superadmin", "Staff with TOTP and a recent password check for sensitive actions", "High", "Everything a moderator can; grant roles, see dead letters and delivery records"],
            ["Ops operator", "Holds the ops token", "High", "Read monitoring panels only"],
        ],
        [2.6, 5.4, 2.3, 6.2], caption="User classes",
    )
    doc.h3("4.2.4 Operating environment")
    doc.bullets([
        "Client: current Chromium-based Android browsers and modern desktop browsers; Safari limitations are documented where a device is available.",
        "Server: Python 3.12 container running FastAPI behind HTTPS; PostgreSQL 17 (Supabase); Redis over TLS for counters only.",
        "Build: Node 22 for the three front-end apps; CI on every pull request (lint, type check, tests, migration check, dependency audit, secret scan, image build).",
        "Time zone: the server stores UTC; dates shown to users and appeal deadlines use Asia/Dhaka.",
    ])
    doc.h3("4.2.5 Design and implementation constraints")
    doc.table(
        ["ID", "Constraint", "Source"],
        [
            ["C1", "Bangla is the default language; Bangla text must render correctly including conjuncts, and names are limited by code point count, not bytes.", "Proposal; Review.md 3.4"],
            ["C2", "The browser never holds a database or service key; all authority is on the server.", "Architecture.md section 1"],
            ["C3", "No real payment, SMS gateway, NID or live inventory in the semester.", "Proposal MVP exclusions"],
            ["C4", "Total direct cost must stay within the planning ceiling of BDT 6,000.", "Proposal feasibility"],
            ["C5", "Final completion on 17 or 18 January 2027; formal testing 4 to 11 January 2027.", "Proposal timeline"],
            ["C6", "A published review is never edited; the author withdraws and writes a new one.", "Review.md 5.2"],
            ["C7", "A Guest review never changes the Community Rating; receipts are never reissued.", "Review.md 3.2, 4.2"],
            ["C8", "Personal data is minimised: no NID, no payment data; optional contacts stay on the device.", "Proposal privacy; Security.md"],
            ["C9", "Hosted free or low-cost tiers limit storage, email volume and request rates.", "Decisions.md"],
            ["C10", "Every schema change is a reversible migration; the API contract in openapi-v1.json is checked in CI.", "backend/migrations, tests/test_openapi_contract.py"],
        ],
        [1.0, 11.2, 4.3], caption="Constraints", size=8.8,
    )
    doc.h3("4.2.6 Assumptions and dependencies")
    doc.table(
        ["ID", "Assumption or dependency", "If it fails"],
        [
            ["A1", "Supabase Auth, PostgreSQL and Storage are available.", "Sign-in, reviews or media are unavailable; the API answers SERVICE_UNAVAILABLE and readiness reports 503."],
            ["A2", "Cloudflare Turnstile is reachable for guest submissions.", "New guest reviews cannot be submitted; reading and receipt operations continue."],
            ["A3", "An email provider is configured and delivers.", "Email retries (1 min, 5 min, 30 min, 2 h) then fails; the in-app notification still exists."],
            ["A4", "Users have a Chromium-based or modern browser.", "Some features degrade; documented limits apply."],
            ["A5", "At least two trained moderators are available (a decision on appeal needs a second person).", "Appeals wait in the queue."],
            ["A6", "Destination data is researched, sourced and dated by the team.", "Advisories become stale or expired and are labelled so."],
            ["A7", "Redis is available for counters.", "Visit and event counters lose data; reviews are not affected."],
            ["A8", "Users consent to the moderation and retention notice shown with a submission.", "No submission is accepted without a consent version."],
        ],
        [1.0, 7.5, 8.0], caption="Assumptions and dependencies", size=8.8,
    )

    # ---- 4.3
    doc.h2("4.3 External interface requirements")
    doc.h3("4.3.1 User interfaces")
    doc.table(
        ["Application", "Main screens", "Notes"],
        [
            ["Public PWA (frontend/)", "Landing, guest entry, register, verify email, sign in, forgot and reset password, overview, destinations and detail, reviews (form, receipt status, withdraw), account verification, appeals, notifications; prototype: planner, offline packs, saved trips", "Bangla first; English selectable; keyboard and screen-reader support are required; prototype screens must be labelled"],
            ["Staff app (staff/)", "Sign-in with TOTP, task queue with lease, decision form, media, appeals, reports, enforcement, verification cases, staff, audit, inbox, notifications", "Never part of the public build; staff routes answer 404 to non-staff"],
            ["Ops app (ops/)", "Health, content, traffic, members, notifications, queue and reviews panels", "Read-only; token in a header; separate deployment"],
        ],
        [3.2, 8.5, 4.8], caption="User interfaces", size=8.6,
    )
    doc.h3("4.3.2 Software interface: the API")
    doc.p("The contract is `Docs/api/openapi-v1.json` (checked against the code by a test) and `Docs/api/API.md`. All errors use one body, `{ error: { code, message, request_id, field_errors } }`, with Bangla and English messages. "
          "Signed-in writes need a CSRF token; guest operations send the receipt in the JSON body only; lists use opaque cursors.")
    doc.table(["Group", "Operations", "Purpose"], api_groups(), [3.2, 2.3, 11.0], caption="API operations by group (from openapi-v1.json)", size=8.6)
    doc.h3("4.3.3 Third-party services")
    doc.table(
        ["Service", "Purpose", "Data exchanged", "When unavailable"],
        [
            ["Supabase Auth", "Identity, passwords, TOTP", "Credentials, tokens, user id", "Sign-in and registration fail with a clear error; existing sessions continue until expiry"],
            ["Supabase PostgreSQL", "System of record", "All application tables", "Readiness 503; the API does not accept writes"],
            ["Supabase Storage", "Private media and evidence", "Signed links, processed files", "Upload answers SERVICE_UNAVAILABLE with a Retry-After header"],
            ["Cloudflare Turnstile", "Bot check on guest submission", "One-time token", "Guest submissions refused; other features unaffected"],
            ["Email provider (SMTP, Gmail, Brevo, Resend)", "Notification email", "Email address, message, delivery status webhooks", "Retried, then marked failed; alert raised after a threshold"],
            ["Upstash Redis", "Visit and event counters", "Counter increments and totals", "Counters lost; core flows unaffected"],
        ],
        [3.4, 3.4, 4.0, 5.7], caption="Third-party services", size=8.6,
    )
    doc.h3("4.3.4 Hardware and communications interfaces")
    doc.bullets([
        "No special hardware. Target device: a low-end Android phone on a slow mobile network; the proposal's measure is usable core text within 5 seconds on a throttled Fast 3G profile.",
        "All traffic uses HTTPS; cookies are HttpOnly and Secure in production; CORS allows only the configured origins.",
    ])

    # ---- 4.4
    doc.landscape()
    doc.h2("4.4 System features: use case model and requirement status")
    doc.p("The use case model below is the proposal's own diagram (four actors; packages for supporting functions, cost estimator, offline, review, community, administration and verification; booking and payment are demonstration only).")
    doc.figure(DOCS / "Abhijatri_UseCase_compressed.png", "Abhijatri use case model (from the proposal). Packages 4 and 6c are demonstration-only.", 24.0, 15.2)
    doc.portrait()
    doc.p("Status of each functional requirement as of 30 October 2026, from the repository (Docs/Implemented.md, Docs/Backend-Implemented.md, Docs/Frontend-Implemented.md and the tests):")
    status = [
        ["FR01", "Destination catalogue", "Implemented", "Five destinations with sourced, dated content; R01 content review pending"],
        ["FR02", "Language selection", "Implemented", "Bangla default, English selectable; no test of the language switch was found"],
        ["FR03", "Account lifecycle", "Partly", "Register, verify, sign in, reset, sign out built; account deletion request not found in the API"],
        ["FR04", "Structured review", "Implemented", "Guest and member; seven category ratings; the local offline draft is not built (see FR12)"],
        ["FR05", "Review moderation", "Implemented", "Publish, reject, hide, restore, request changes; audit and actor recorded; DELETED state defined but not used"],
        ["FR06", "Review reporting", "Implemented (member)", "Member reports with duplicate control; anonymous public reports planned"],
        ["FR07", "Destination rating", "Implemented", "Guest Feedback average; Bayesian Community Rating from eligible Verified Member reviews, hidden below the threshold"],
        ["FR08", "Cost planner", "Prototype", "Screen only; no estimator logic or API"],
        ["FR09", "Pricing units", "Not implemented", "Depends on the planner and a price catalogue"],
        ["FR10", "Offline pack", "Prototype", "No service worker, manifest or IndexedDB yet"],
        ["FR11", "Saved trip brief", "Prototype", "Screen only"],
        ["FR12", "Offline review draft", "Not implemented", "Draft store (IndexedDB) planned for R15"],
        ["FR13", "Retry-safe submission", "Partly", "Permanent draft id uniqueness and receipt recovery built and tested; Idempotency-Key replay is built for staff decisions, planned for other writes"],
        ["FR14", "Pack update", "Not implemented", "Depends on FR10"],
        ["FR15", "Advisory freshness", "Implemented", "Current, stale, expired and not-yet-effective, on the Dhaka date"],
        ["FR16", "Administration", "Partly", "Staff roles, audit log, notification administration, media decisions built; staff editing of destination content not built"],
        ["FR17", "Storage control", "Not implemented", "Depends on FR10"],
    ]
    fills = {}
    for i, r in enumerate(status):
        fills[(i, 2)] = GREEN if r[2].startswith("Implemented") else (AMBER if r[2] in ("Partly", "Prototype") else RED)
    doc.table(["ID", "Requirement", "Status", "Evidence or note"], status, [1.2, 3.6, 2.8, 8.9], caption="Functional requirement status", size=8.6, fills=fills)
    done = sum(1 for r in status if r[2].startswith("Implemented"))
    doc.p(f"Summary: {done} implemented, {sum(1 for r in status if r[2] == 'Partly')} partly implemented, {sum(1 for r in status if r[2] == 'Prototype')} prototypes and {sum(1 for r in status if r[2] == 'Not implemented')} not implemented, of {len(status)}. "
          "The offline group (FR10, FR11, FR12, FR14, FR17) and the estimator (FR08, FR09) are the main remaining work.")

    # ---- 4.5
    doc.h2("4.5 Data requirements")
    doc.landscape()
    doc.figure(HERE / "erd.png", "Entity-relationship diagram of the main tables", 22.0, 14.6)
    doc.portrait()
    doc.p("The database has more than 35 tables; the diagram shows the ones needed to understand reviews, moderation and notifications. Every public table has row-level security enabled, and the application connects as the owner role.")
    doc.table(
        ["Data", "Where kept", "Retention or protection"],
        [
            ["Review text and ratings", "reviews, review_revisions, review_category_ratings", "Kept while published; revisions append-only; personal content may be tombstoned by the retention job"],
            ["Guest receipt and scope secret", "Browser only; server holds keyed digests (review_receipts, reviews.guest_scope_hash)", "Raw values never stored or logged; receipts never reissued"],
            ["Account identity", "users, user_roles; passwords and TOTP in Supabase Auth", "Passwords never in the application database"],
            ["Verification evidence", "Private storage; verification_cases, verification_evidence", "Files erased within 24 hours of a decision; rejected cases kept 30 days"],
            ["Photos and videos", "review_media; private bucket", "Uploads not completed within 24 hours are purged; re-encoded images have EXIF and GPS removed"],
            ["Notifications", "notifications and delivery tables", "Standard items 90 days; critical items 24 months; open appeals preserved"],
            ["Outbox events", "outbox_events", "Processed rows removed after 30 days"],
            ["Rate-limit counters", "rate_limit_buckets", "Old windows purged automatically"],
            ["Audit events", "audit_events", "Append-only; the application role cannot update or delete"],
        ],
        [3.6, 6.5, 6.4], caption="Data kept and how it is protected", size=8.6,
    )

    # ---- 4.6
    doc.h2("4.6 Use case specifications")
    doc.p("Six core use cases are specified in full. Each maps to a package in the use case model and to a flow in the data flow diagrams.")

    def uc(title, rows):
        doc.table(["Field", "Specification"], rows, [3.2, 13.3], caption=title, size=8.4, bold_first_col=True)

    uc("UC-01 Submit a review", [
        ["Actors", "Guest or Member (primary); Cloudflare Turnstile (secondary)"],
        ["Trigger", "The user finishes the structured review form and presses Submit."],
        ["Preconditions", "A published destination exists. A Guest has a generated receipt, scope secret and draft id. A Member is signed in with a CSRF token."],
        ["Main flow", "1. The client sends the review (title, note, overall rating, optional category ratings, language, traveller type, comfort tier, visit month, consent version).\n2. The server checks the schema and receipt format.\n3. If the draft id already exists with the same receipt, it returns the existing review (no charge).\n4. For a Guest it verifies the Turnstile token and durable rate limits and pending ceilings.\n5. It creates the review (PENDING), first revision, category ratings, receipt digest, moderation task and outbox event in one transaction.\n6. It answers 201 with review id and status."],
        ["Alternative flows", "A member who already has an active review for the same destination and month gets MEMBER_REVIEW_EXISTS. A different receipt on an existing draft gets DRAFT_ALREADY_SUBMITTED."],
        ["Exceptions", "Turnstile failure (CHALLENGE_FAILED), rate limit (RATE_LIMITED with Retry-After), guest writes paused (GUEST_WRITES_PAUSED), validation errors with field codes."],
        ["Postconditions", "One PENDING review is queued for moderation; nothing is counted or public."],
        ["Requirements", "FR04, FR13, FR05"],
        ["API and tests", "POST /reviews/guest, POST /reviews/member; tests/test_review_postgres.py, test_receipts.py, test_abuse.py, test_category_ratings.py"],
    ])
    uc("UC-02 Edit an unpublished review", [
        ["Actors", "Guest (with receipt) or Member (owner)"],
        ["Trigger", "The author changes a pending review or answers a moderator's request for changes."],
        ["Preconditions", "The review is PENDING or CHANGES_REQUESTED and the author knows its current version."],
        ["Main flow", "1. The client sends PATCH /reviews/{id}/pending with expected_version and only the changed fields (a Guest adds the receipt; a Member uses the session and CSRF token).\n2. The server proves ownership (receipt digest or author id).\n3. It checks the state and the version.\n4. It validates and merges the changes with the current revision.\n5. It writes a new revision, marks the old one SUPERSEDED, sets the review to PENDING and re-queues the moderation task.\n6. It answers 200 with the new version and revision number."],
        ["Alternative flows", "Moving a member review onto a month already reviewed gives MEMBER_REVIEW_EXISTS."],
        ["Exceptions", "Wrong receipt (RECEIPT_NOT_FOUND, counted toward a progressive block); another person's review (404); any other state (INVALID_TRANSITION); stale version (REVIEW_VERSION_CONFLICT)."],
        ["Postconditions", "A new revision exists; the review is hidden and uncounted until a moderator publishes it."],
        ["Requirements", "FR04, FR05; Review.md 5.2"],
        ["API and tests", "PATCH /reviews/{id}/pending; tests/test_review_crud.py (member and guest edit, refused states, month collision, request-changes round trip)"],
    ])
    uc("UC-03 Moderate a review", [
        ["Actors", "Moderator or Superadmin"],
        ["Trigger", "A moderator opens the queue and takes a pending review."],
        ["Preconditions", "Staff signed in with TOTP; a moderation task exists; the moderator is not the author."],
        ["Main flow", "1. Claim the task and receive a lease token (300 seconds; heartbeat extends it).\n2. Read the content and any media.\n3. Send the decision (PUBLISH, REJECT, REQUEST_CHANGES, HIDE, RESTORE) with the task id, lease token, the review's version and a reason code.\n4. In one transaction the server changes the status, updates rating totals exactly once, decides media, writes the moderation action, an audit event and an outbox event, and completes the task.\n5. The worker later notifies the author."],
        ["Alternative flows", "A decision can be replayed with the same Idempotency-Key and returns the stored result."],
        ["Exceptions", "Stale version (REVIEW_VERSION_CONFLICT); lost lease (LEASE_LOST); impossible move (TRANSITION_NOT_ALLOWED); own review (SELF_MODERATION_FORBIDDEN)."],
        ["Postconditions", "Status and aggregates are consistent; the decision is auditable; the author is notified."],
        ["Requirements", "FR05, FR07, FR16"],
        ["API and tests", "POST /admin/tasks/{id}/claim, POST /admin/submissions/{id}/moderation-actions; tests/test_admin.py, test_review_postgres.py, test_review_crud.py"],
    ])
    uc("UC-04 Appeal a rejection", [
        ["Actors", "Member (session) or Guest (receipt); a second moderator"],
        ["Trigger", "The author sees a rejection with its reason and appeal deadline."],
        ["Preconditions", "The review is REJECTED (or HIDDEN for a member) and the 30-day window (end of day 30, Asia/Dhaka) has not closed."],
        ["Main flow", "1. The author files the appeal (member: POST /appeals; guest: POST /review-receipts/appeals with the receipt and a 20 to 2000 character statement).\n2. The server records one appeal per decision and queues an appeal task.\n3. A moderator other than the original decider claims it and decides upheld or overturned.\n4. If overturned, a rejected review returns to PENDING for a fresh review; a hidden review is restored.\n5. The author is notified (a Guest sees the outcome in the receipt status)."],
        ["Exceptions", "Window closed (APPEAL_WINDOW_CLOSED); second appeal (DUPLICATE_APPEAL); the original decider tries to decide (APPEAL_REVIEWER_NOT_INDEPENDENT)."],
        ["Postconditions", "The appeal has a final state and an audit record."],
        ["Requirements", "FR05; Review.md 4.2, 5.4"],
        ["API and tests", "POST /appeals, POST /review-receipts/appeals, POST /admin/appeals/{id}/decision; tests/test_cases.py, test_review_crud.py"],
    ])
    uc("UC-05 Estimate trip cost (prototype)", [
        ["Actors", "Guest or Member"],
        ["Trigger", "The traveller enters party size, dates, comfort tier and choices."],
        ["Intended flow", "The estimator applies source-dated prices by pricing unit (person, room, vehicle, group, day, night, meal, entry) and returns an itemised BDT range with per-person cost and a confidence label."],
        ["Status", "Prototype screen only. There is no estimator logic, price catalogue or API in the repository yet (FR08, FR09)."],
        ["Requirements", "FR08, FR09; proposal section 4 (cost planner rules and worked example)"],
        ["Verification plan", "Ten held-out trips evaluated after the price catalogue is frozen (objective O6)."],
    ])
    uc("UC-06 Download an offline pack (prototype)", [
        ["Actors", "Guest or Member"],
        ["Trigger", "The traveller chooses a destination pack to keep for airplane mode."],
        ["Intended flow", "The app downloads a versioned pack (guidance, contacts, coordinates, advisories, costs) into IndexedDB, asks for persistent storage, and later replaces it atomically after validating a newer manifest."],
        ["Status", "Prototype screen only. No service worker, manifest, IndexedDB or pack API exists yet (FR10, FR14, FR17)."],
        ["Requirements", "FR10, FR14, FR17"],
        ["Verification plan", "10 of 10 packs open in airplane mode on real devices (objective O4)."],
    ])

    # ---- 4.7
    doc.landscape()
    doc.h2("4.7 Review lifecycle (state diagram)")
    doc.figure(HERE / "review-state.png", "Review states and the transitions the code allows", 24.0, 15.0)
    doc.portrait()
    doc.table(
        ["Event", "From", "To", "Who", "Side effects"],
        [
            ["Submit", "(new)", "PENDING", "Guest or Member", "Revision 1, receipt digest, task, outbox event"],
            ["PUBLISH", "PENDING", "PUBLISHED", "Moderator", "Rating counted once (Guest Feedback or Community Rating); category totals move; author notified"],
            ["REJECT", "PENDING", "REJECTED", "Moderator", "Public-safe reason; 30-day appeal window starts"],
            ["REQUEST_CHANGES", "PENDING", "CHANGES_REQUESTED", "Moderator", "Author notified with the reason; no rating change"],
            ["Edit", "PENDING or CHANGES_REQUESTED", "PENDING", "Author", "New revision; old one SUPERSEDED; task re-queued"],
            ["HIDE", "PUBLISHED", "HIDDEN", "Moderator", "Rating removed in the same transaction"],
            ["RESTORE", "HIDDEN", "PUBLISHED", "Moderator", "Rating added back"],
            ["Withdraw", "PENDING, CHANGES_REQUESTED or PUBLISHED", "WITHDRAWN", "Author", "Rating removed; task cancelled; idempotent"],
            ["Appeal overturned", "REJECTED", "PENDING", "A second moderator", "Back to the queue for a fresh review"],
        ],
        [2.6, 3.6, 2.9, 2.6, 4.8], caption="Transitions", size=8.4,
    )
    doc.p("The states UNDER_REVIEW and DELETED exist in the data model and are accepted by some checks, but no current code path sets them; a moderator's claim is held on the task, not on the review.")

    # ---- 4.8
    doc.h2("4.8 Behaviour: sequence diagrams and non-functional evidence")
    doc.landscape()
    doc.figure(HERE / "seq-submit-moderate.png", "Submit, moderate, publish and notify", 23.5, 14.5)
    doc.figure(HERE / "seq-guest-edit.png", "Request changes, edit with the receipt, return to the queue", 23.0, 14.5)
    doc.portrait()
    doc.p("Non-functional requirements and the evidence available for them at 30 October 2026:")
    nf = [
        ["Performance", "Core text usable within 5 s on throttled Fast 3G; pack opens within the stated time", "Not measured. Public lists are paginated (default 20, maximum 50) and public responses are cached for 60 seconds; no timing test is in the repository.", "Gap"],
        ["Security and access control", "Server-side authority, CSRF, TOTP for staff, role checks, audit, rate limits, Turnstile, RLS", "Built and tested: tests/test_auth.py, test_admin.py, test_rls.py, test_abuse.py; dependency audit clean; committed-secret check in CI", "Met"],
        ["Reliability and availability", "Identical retries create no duplicate; interrupted pack update keeps the last pack", "Retry safety built and tested; outbox is at-least-once and idempotent; pack update not applicable yet; no uptime measurement", "Partly"],
        ["Scalability", "Stateless API, indexes, pagination, bounded queries", "Built; no load test", "Partly"],
        ["Usability and accessibility", "Bangla default, labelled forms, keyboard access, Bengali conjunct rendering tested", "Bilingual UI built; QA notes list remaining accessibility items; no screen-reader test record", "Partly"],
        ["Maintainability", "Modular code, migrations, API docs, tests, code review", "502 backend tests, 64, 24 and 19 front-end tests, lint and strict typing in CI, 18 migrations, contract tests", "Met"],
        ["Portability", "Chromium Android, modern desktop", "Builds pass; no recorded real-device run", "Partly"],
        ["Privacy", "Minimal data, consent, retention, deletion support", "Retention jobs and consent version built; account deletion request not found", "Partly"],
    ]
    fills = {(i, 3): {"Met": GREEN, "Partly": AMBER, "Gap": RED}[r[3]] for i, r in enumerate(nf)}
    doc.table(["Category", "Requirement (proposal)", "Evidence in the repository", "Status"], nf, [3.0, 4.6, 7.4, 1.5], caption="Non-functional requirements: evidence", size=8.2, fills=fills)

    # ---- 4.9
    doc.h2("4.9 Requirements traceability matrix")
    doc.table(
        ["FR", "Use case package (diagram)", "API operations", "Automated tests", "Status"],
        [
            ["FR01", "5.1 Explore Destination", "GET /destinations, /destinations/{id}", "test_destination_unit, test_destination_http, test_destination_postgres, test_seed_content", "Implemented"],
            ["FR02", "Supporting: Switch Language", "Accept-Language on all routes", "No test of the language switch found", "Implemented"],
            ["FR03", "Supporting; 6b Verification: Email and Account", "POST /auth/register, verify-email, login, logout, password-reset/*; GET /auth/session", "test_auth", "Partly"],
            ["FR04", "3. Review: Fill Structured Review, Submit Review", "POST /reviews/guest, /reviews/member; GET /review-parameters", "test_review_postgres, test_review_unit, test_category_ratings, test_receipts, test_review_crud", "Implemented"],
            ["FR05", "5. Community: Moderate Review", "GET /admin/queue; POST /admin/tasks/{id}/claim, /admin/submissions/{id}/moderation-actions", "test_admin, test_review_postgres, test_review_crud", "Implemented"],
            ["FR06", "5. Community: Report Review", "POST /reviews/{id}/reports; POST /admin/reports/{id}/transition", "test_admin (report flow and rules)", "Implemented (member)"],
            ["FR07", "5. Community: View Destination Rating", "GET /destinations/{id}/reviews; rating logic in services.py", "test_review_postgres, test_destination_postgres", "Implemented"],
            ["FR08, FR09", "1. Cost Estimator", "None yet", "None yet", "Prototype / not implemented"],
            ["FR10, FR14, FR17", "2. Offline", "None yet", "None yet", "Prototype / not implemented"],
            ["FR11", "2. Offline: Save Local Trip Brief", "None (local)", "None yet", "Prototype"],
            ["FR12", "3. Review: Save Offline Review Draft", "None (local)", "None yet", "Not implemented"],
            ["FR13", "3. Review: Submit with Idempotency Key", "POST /reviews/guest (draft id), POST /reviews/member; Idempotency-Key on staff decisions", "test_review_postgres (retry deduplication), test_receipts, test_admin (idempotent decision)", "Partly"],
            ["FR15", "6a Verification: Advisory and Offline Pack", "GET /destinations/{id} (advisory state)", "test_destination_unit (boundaries, Dhaka date)", "Implemented"],
            ["FR16", "Administration", "GET /admin/staff, POST /admin/staff/{id}/role, GET /admin/audit-events, notification admin routes", "test_admin, test_notifications", "Partly"],
            ["R07 (review CRUD)", "3. Review (edit, withdraw, history, appeal)", "PATCH /reviews/{id}/pending, GET /reviews/{id}, GET /reviews/mine, POST /reviews/{id}/withdraw, POST /review-receipts/appeals", "test_review_crud (16 tests)", "Implemented"],
            ["Notifications", "Not in the proposal's diagram", "GET /notifications, PATCH /notifications/{id}, /notification-preferences", "test_notifications", "Implemented"],
        ],
        [1.6, 3.6, 4.7, 4.0, 2.6], caption="Traceability: requirement to use case to API to test", size=7.8,
    )
    doc.note("Two features are built but not drawn in the proposal's use case diagram: the notification system and the review edit and appeal flows. Add them to the diagram when the PDF is revised.")

    # ---- 4.10
    doc.h2("4.10 As built versus proposed")
    doc.table(
        ["Topic", "Proposal (12 October 2026)", "As built (30 October 2026)", "Action"],
        [
            ["Authentication", "Argon2id hashing and opaque server-side sessions", "Supabase Auth holds passwords and TOTP; the API verifies signed tokens and sets HttpOnly session cookies with a CSRF token", "Update the security row and the technical feasibility text"],
            ["Staff security", "Role-based access", "Staff need TOTP (AAL2); superadmin needs a recent password check for role changes; every action is audited", "Add to NFR text"],
            ["Guest identity", "Guest reviews with a draft id", "Client-generated receipt, keyed digests, durable rate limits, Turnstile, public pseudonymous guest tag", "Describe in the review section"],
            ["Review lifecycle", "Published, hidden, rejected or deleted", "Adds PENDING, CHANGES_REQUESTED, WITHDRAWN, SUPERSEDED revisions, appeals and edit-while-pending", "Update FR05 and the state model"],
            ["Photos and video", "Image attachment for Verified Members", "Any signed-in member may attach up to 5 photos and 1 video; no transcoding", "Record as a scope decision (Decisions.md)"],
            ["Notifications", "Not in scope", "Full outbox, inbox, email, digests and webhooks", "Add as a feature"],
            ["Observability", "Not specified", "Ops dashboard, audit log, alerts", "Add to NFR"],
            ["Hosting", "Optional short-term hosting, BDT 2,500", "Supabase, Upstash and hosted API and front-ends", "Update the cost table with actual costs"],
            ["Offline and PWA", "Core of the MVP", "Prototype screens only; no service worker or IndexedDB", "State the status; plan the remaining work"],
            ["Cost estimator", "Rule-based itemised estimate", "Prototype screen only", "State the status"],
            ["Booking and payment", "Demonstration only", "Not built", "Keep as demonstration or remove from the diagram"],
        ],
        [2.6, 4.3, 5.6, 4.0], caption="Proposal and implementation compared", size=8.2,
    )

    # ---- 4.11
    doc.h2("4.11 Revision history and approval")
    doc.table(
        ["Version", "Date", "Author", "Change"],
        [
            ["0.1", "12 October 2026", "Team ChoturMatra", "Project proposal"],
            ["1.0", "30 October 2026", "Prepared for the team", "SRS completion sections, coverage check, traceability"],
            ["", "", "", ""],
        ],
        [2.0, 3.4, 4.5, 6.6], caption="Revision history",
    )
    doc.table(
        ["Role", "Name", "Signature", "Date"],
        [
            ["Project leader", "Shahriar Islam", "", ""],
            ["Frontend and offline", "Abdullah Bin Sorwar Choudhury", "", ""],
            ["Backend and data", "Syed Muhtasim Alam", "", ""],
            ["Quality assurance", "Md. Irfan Iqbal", "", ""],
            ["Course instructor", "", "", ""],
        ],
        [4.0, 6.0, 3.8, 2.7], caption="Approval",
    )
    doc.save(OUT)
    print("saved", OUT)


if __name__ == "__main__":
    main()
