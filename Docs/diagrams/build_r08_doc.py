"""Builds Docs/R08-Rating-Test-Cases.docx: what R08 (Bayesian score and rating exclusion) delivers, the automated
evidence, and test cases a person can run (Gantt R08, Review.md 6.1 to 6.4)."""

from pathlib import Path

from docx_helpers import Doc

OUT = Path(__file__).resolve().parent.parent / "R08-Rating-Test-Cases.docx"
GREEN, AMBER = "E3F3EA", "FFF4D6"

CASES = {
    "A. The score": [
        ("S1", "Hidden below five", "Open a destination with 0 to 4 eligible Verified Member reviews.", "No Community Rating number. The page shows \"Seeded Destination Selection\" and the review count."),
        ("S2", "Appears at five", "Publish the fifth eligible review.", "The Community Rating appears with the count. Five 5-star reviews show 4.3 (not 5.0); five 2-star reviews show 2.8."),
        ("S3", "Formula", "Check the API: `GET /api/v1/destinations/{id}` -> `community_rating.score`.", "Equals (sum + 5 x 3.5) / (count + 5). The `average` field is the plain mean and is shown separately."),
        ("S4", "Guest feedback is separate", "Publish guest reviews on a destination.", "They appear under Guest Feedback with their own average and count. The Community Rating count does not change."),
    ],
    "B. Who counts": [
        ("E1", "Verified Member counts", "Publish a review by a Verified Member.", "Community count +1, sum + rating. The review's rating state is ELIGIBLE."),
        ("E2", "Unverified member", "Publish a review by a member with no Verified record.", "The review is public; the Community Rating does not change (INELIGIBLE_UNVERIFIED)."),
        ("E3", "Expired, revoked or pending verification", "Repeat E2 with an expired, a revoked and a not-yet-approved record.", "None counts."),
        ("E4", "Expiry after publishing", "Let a counted member's verification expire.", "The earlier review stays counted (eligibility is frozen at publication)."),
        ("E5", "Conflict of interest", "Mark a published review as conflicted (staff screen or `POST /admin/submissions/{id}/conflict`), then clear it.", "Marking removes it from the totals; clearing restores it. Works for member and guest reviews."),
        ("E6", "Project-team account", "Publish a review by a team account.", "Not counted."),
        ("E7", "Future month or empty text", "Publish a review whose visit month is next month, or whose title is blank (database fixture).", "Not counted (INELIGIBLE_INVALID); the text is still public."),
        ("E8", "Duplicate", "With a moderator duplicate override, publish a second review by the same author for the same destination and month.", "Only the earlier one counts. If the earlier one is withdrawn and the later one re-checked, the later one counts."),
        ("E9", "Hidden, rejected, withdrawn, deleted", "Hide, reject, withdraw and delete one review each.", "None appears in the public list. Totals, category averages and the score exclude them. Restoring a hidden review brings it back."),
    ],
    "C. Reports": [
        ("R1", "Serious report", "A member reports a published review for `privacy` or `conflict_of_interest`.", "The review stays public but stops counting at once; the totals drop."),
        ("R2", "Closing the report", "A moderator dismisses or actions the report.", "The review counts again."),
        ("R3", "Routine report", "Report for `spam`, `offensive`, `false_information` or `other`.", "No change to the rating. The moderator decides through the normal queue."),
    ],
    "D. Verification revoked for abuse": [
        ("V1", "Revoke", "As a moderator call `POST /admin/members/{user_id}/verification/revoke` with `{\"reason_code\": \"REVIEW_FARMING\"}` for a member with counted reviews in two destinations.", "`reviews_uncounted` equals the number of counted reviews. Both destinations' totals drop by exactly that member's ratings. The reviews stay published."),
        ("V2", "Other members unaffected", "Check another member's counted review in the same destination.", "Still counted."),
        ("V3", "Audit and notice", "Open the audit log and the member's notifications.", "`verification.revoke_for_abuse` with the review count; the member received \"Your Verified Member status was removed\"."),
        ("V4", "Repeat and self", "Revoke the same member again; revoke your own account.", "Repeat: 404. Own account: 403, recorded as a denied attempt."),
        ("V5", "New reviews", "The member publishes a new review afterwards.", "Not counted."),
    ],
    "E. Reconciliation": [
        ("C1", "Clean", "As a superadmin call `POST /admin/ratings/reconcile` with `{\"repair\": false}` on a healthy database.", "`drifts` is empty."),
        ("C2", "Detect", "In a test database add 1 to a destination's `community_rating_sum`, then call it again.", "One `community` drift with the stored and expected pairs. The total is unchanged (detect-only)."),
        ("C3", "Repair", "Call with `{\"repair\": true}`.", "The total is corrected, the totals version rose by 1, and one `ratings.reconcile_repair` audit event holds before and after."),
        ("C4", "Nightly job", "Run `python -m app.jobs.reconcile_ratings` against the broken database, then with `--repair`.", "First run prints the drift and exits with status 1; the second exits with 0 and the totals match."),
        ("C5", "Ops route and alert", "Call `POST /ops/jobs/rating-reconciliation` with the ops token on a broken database.", "Answer `{clean: false}`; superadmins get one \"Rating totals do not match\" notice a day. Nothing is repaired."),
        ("C6", "Corrupt review row", "Set a counted review to DELETED in a test database and reconcile with repair.", "The row is reported as not repairable; the totals are rebuilt from the rows that count."),
    ],
    "F. Evidence and access": [
        ("X1", "Semester evidence", "As staff call `GET /admin/rating-evidence`.", "Active and ever-approved Verified Members, median and maximum approval hours, and each destination as `top_rated` (5 or more) or `seeded`."),
        ("X2", "Anonymous", "Call the three admin routes without signing in.", "401 AUTH_REQUIRED."),
        ("X3", "Member", "Call them as an ordinary member.", "404 (the route is not disclosed)."),
        ("X4", "Moderator and reconcile", "Call `POST /admin/ratings/reconcile` as a moderator.", "403, recorded as a denied attempt."),
        ("X5", "CSRF and TOTP", "Call revoke without the CSRF token; call it from a session without an authenticator code.", "Refused; nothing changes."),
        ("X6", "Ops token", "Call the ops route without the token.", "401."),
    ],
}


def main() -> None:
    doc = Doc(
        "R08: Bayesian Score and Rating Exclusion",
        "What was built, the evidence, and test cases (Gantt R08, Review.md 6.1 to 6.4)",
        [
            ("Project", "Abhijatri (Team ChoturMatra, CSE 3102)"),
            ("Version", "1.0, 31 October 2026"),
            ("Specification", "`Features/Review.md` 6.1 to 6.4; record in `Docs/Backend-Implemented.md` 5.21"),
            ("Automated result", "287 unit and 272 integration tests pass; migration round trip and `alembic check` clean"),
            ("Credentials", "None are written in this document. Use your own test accounts."),
        ],
        "Abhijatri: R08 rating test cases",
    )
    doc.contents()

    doc.h1("1. What R08 delivers")
    doc.p("The score and the add-and-remove-on-transition logic already existed. R08 completes what the specification still required.")
    doc.table(
        ["Part", "What it does", "Where"],
        [
            ["Bayesian score", "(sum + 5 x 3.5) / (count + 5), shown only from five eligible Verified Member reviews; below that the page says Seeded Destination Selection", "`review_parameters.py` (already built)"],
            ["One eligibility rule set", "Every reason a review may not count, in one function and one order", "`app/eligibility.py`"],
            ["Re-check", "Moves the totals by the difference when something other than a decision changes whether a review counts", "`services.recheck_rating`"],
            ["Serious reports", "An open privacy or conflict-of-interest report suspends the rating; closing it restores", "`admin/actions.py`"],
            ["Abuse revocation", "Ends a member's Verified status and uncounts all their ratings in one transaction", "`rating_integrity.py`, `POST /admin/members/{id}/verification/revoke`"],
            ["Reconciliation", "Recomputes every total from the review rows; detect-only by default; audited repair", "`rating_integrity.py`, `jobs/reconcile_ratings.py`, nightly workflow"],
            ["Semester evidence", "Members, turnaround, per-destination counts and Top Rated or Seeded mode", "`GET /admin/rating-evidence`"],
            ["Migration 0019", "Adds the value INELIGIBLE_INVALID", "`migrations/versions/0019_rating_integrity.py`"],
        ],
        [3.2, 9.0, 4.3], caption="Delivered work", size=8.6,
    )

    doc.h1("2. Eligibility rules in order")
    doc.table(
        ["#", "Rule", "Result"],
        [
            ["1", "Not published", "INELIGIBLE_REMOVED (INELIGIBLE_REPORTED while hidden)"],
            ["2", "Conflict of interest declared", "INELIGIBLE_CONFLICT"],
            ["3", "Guest review", "INELIGIBLE_GUEST (Guest Feedback only)"],
            ["4", "Team account, or no active Verified Member record", "INELIGIBLE_UNVERIFIED"],
            ["5", "Future visit month, no text, rating out of range", "INELIGIBLE_INVALID"],
            ["6", "Same author, destination and month already counted", "INELIGIBLE_DUPLICATE"],
            ["7", "Open serious report (privacy, conflict of interest)", "INELIGIBLE_REPORTED"],
            ["8", "None of the above", "ELIGIBLE"],
        ],
        [1.0, 9.0, 6.5], caption="Rules, first failing check wins", size=9,
    )

    doc.h1("3. Automated evidence")
    doc.table(
        ["Check", "Result"],
        [
            ["Backend unit tests", "287 passed"],
            ["Backend integration tests (PostgreSQL)", "272 passed, 54 of them new for R08"],
            ["Migrations: upgrade, `alembic check`, downgrade", "Clean"],
            ["Front-end tests", "Public app 98 passed (3 new: the fallback formula equals the server's)"],
            ["Mutation check", "Removing the duplicate rule or the serious-report rule makes 3 tests fail, so the tests do guard them"],
            ["Property test", "Random sequences of publish, hide, restore, withdraw, report, close report and conflict flag; the totals equal a full recomputation after every step"],
            ["Concurrency", "A revocation racing a publish of the same author ends consistent; a failure midway leaves nothing half applied"],
            ["Online database (read-only)", "All five destinations' totals equal a full recomputation; no review row contradicts itself"],
            ["Online migration 0019", "Not applied from this session (permission denied). It is applied by the container on the next deploy (`alembic upgrade head` at start), or by you with the one-line statement in section 5"],
        ],
        [6.0, 10.5], caption="Evidence", size=8.8, fills={(8, 1): AMBER},
    )

    doc.h1("4. Test cases")
    doc.p("Run on the local stack. The API calls can be made from a signed-in staff browser console or any HTTP client with the session cookie and CSRF token. Use your own accounts.")
    total = 0
    for section, cases in CASES.items():
        doc.h2(section)
        doc.table(["ID", "Case", "Steps", "Expected", "Pass"], [[c[0], c[1], c[2], c[3], ""] for c in cases], [1.0, 2.8, 6.0, 5.8, 1.0], size=8.2, caption=section)
        total += len(cases)

    doc.h1("5. Applying migration 0019 online")
    doc.p("Nothing needs doing if you merge to `main`: the container runs `alembic upgrade head` before it starts. To apply it earlier, run this in the Supabase SQL editor of the online project (additive, safe to repeat):")
    doc.code("ALTER TYPE rating_eligibility ADD VALUE IF NOT EXISTS 'INELIGIBLE_INVALID';\nUPDATE alembic_version SET version_num = '0019_rating_integrity' WHERE version_num = '0018_review_crud';")

    doc.h1("6. Not part of R08")
    doc.bullets([
        "Ranked Top Rated list, filters and View More (discovery, H02).",
        "A staff screen button for revocation: the API is ready.",
        "A review delete workflow: the DELETED state is excluded by the rules and tested.",
    ])
    doc.h1("7. Sign-off")
    doc.table(["Item", "Done"], [[f"All {total} cases run; each Pass or noted", ""], ["Tester: ____________   Date: ____________", ""]], [14.0, 2.5])
    doc.save(OUT)
    print("saved", OUT, f"{total} cases")


if __name__ == "__main__":
    main()
