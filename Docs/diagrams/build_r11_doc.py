"""Builds Docs/R11-Reports-Moderation-Audit-Test-Cases.docx: what R11 delivers, the evidence, every test case
(automated ones mapped to the test that covers them) and the manual cases for the screens (Gantt R11)."""

from pathlib import Path

from docx_helpers import Doc

OUT = Path(__file__).resolve().parent.parent / "R11-Reports-Moderation-Audit-Test-Cases.docx"
GREEN, AMBER = "E3F3EA", "FFF4D6"

# (id, case, covered by, expected)
AUTOMATED = {
    "A. Member reports": [
        ("RP1", "Each of the nine reasons is accepted and queued with its priority", "test_reports: test_every_reason_is_accepted_and_queued_with_its_priority (9)", "201; priority 2 for privacy, safety, impersonation, copyright, harassment, else 1; review stays published"),
        ("RP2", "The old code `offensive` is stored as `harassment`", "test_the_old_offensive_code_is_stored_as_harassment", "Stored reason is harassment"),
        ("RP3", "Unknown reasons and `removal_request` are refused for members", "test_unknown_reasons_and_the_removal_code_are_refused_for_members (7)", "422; no report created"),
        ("RP4", "Only published reviews by someone else can be reported", "test_only_published_reviews_by_someone_else_can_be_reported", "404 unpublished or unknown, 403 own review"),
        ("RP5", "A visitor, or a request without CSRF, cannot report as a member", "test_a_visitor_or_a_request_without_csrf_cannot_report", "401 and 403"),
        ("RP6", "A second open report is a conflict until the first is closed", "test_a_second_open_report_is_a_conflict_until_the_first_is_closed", "409 DUPLICATE_OPEN_REPORT, then 201 after closing"),
        ("RP7", "Details are limited to 1000 characters; extra fields refused", "test_details_are_limited_to_a_thousand_characters", "422 at 1001, 201 at 1000"),
        ("RP8", "Member limits: 20 an hour, 5 per review a day, counted per member", "test_member_limits_count_attempts_and_reset_by_window; test_the_per_review_limit_counts_failed_attempts_too", "429 RATE_LIMITED with Retry-After; another member unaffected"),
        ("RP9", "A restricted member cannot report", "test_a_restricted_member_cannot_report", "403 ACCOUNT_RESTRICTED"),
        ("RP10", "Audit row and outbox event are written together; a refusal leaves neither", "test_a_member_report_writes_the_audit_row_and_the_outbox_event_together", "One `report.create`; unchanged counts after a 409"),
        ("RP11", "Serious member reports suspend the rating and closing restores it", "test_a_serious_member_report_suspends_the_rating_and_closing_it_restores_it (3); R08 suite", "Rating leaves the totals; text stays public"),
        ("RP14", "My reports: own only, paged, no staff fields", "test_my_reports_lists_only_my_own_without_staff_fields", "Five fields per item; 401 anonymous; 422 bad cursor"),
        ("RP15", "A NUL character is a validation error, not a server error", "test_a_nul_character_in_a_member_report_is_refused", "422"),
    ],
    "B. Anonymous reports and removal requests": [
        ("AN1", "Accepted, queued, no address stored, no rating effect", "test_an_anonymous_report_is_accepted_queued_and_keeps_no_address", "202 {received: true}; scope digest 32 bytes; rating still eligible after a recheck"),
        ("AN2", "Failed challenge creates nothing", "test_a_failed_challenge_or_a_foreign_origin_creates_nothing", "403 CHALLENGE_FAILED"),
        ("AN3", "Foreign origin refused", "same test", "403 CSRF_INVALID"),
        ("AN4", "Network limit applies to everyone behind one address", "test_the_network_limit_applies_to_everyone_behind_one_address", "429 on the third; another address 202"),
        ("AN5", "A repeat from the same visitor answers the same and makes no second row", "test_a_repeat_report_from_the_same_visitor_answers_the_same_and_makes_no_second_row", "Identical 202; one row"),
        ("AN6", "A different visitor creates another report", "same test", "Two rows"),
        ("AN7", "A removal request needs a contact", "test_a_removal_request_needs_a_valid_contact_and_a_real_statement (6)", "422 for empty, blank, invalid, short statement"),
        ("AN8", "Contact is an email or a phone number", "test_malformed_anonymous_reports_are_refused (9); test_a_phone_number_is_a_valid_contact; test_the_contact_check_agrees_with_the_one_in_the_public_form", "Same rule on the server and in the form"),
        ("AN9", "Contact is for staff only", "test_the_contact_is_for_staff_only", "Visible in the staff queue; absent from member, public, audit and logs"),
        ("AN11", "Unpublished or unknown review answers the same", "test_unpublished_and_unknown_reviews_answer_the_same_and_create_nothing", "202 either way; no row"),
        ("AN12", "Audit row holds no personal data", "test_an_anonymous_report_is_audited_without_personal_data", "No address, contact, text or token"),
        ("AN13", "Removal request: priority, challenge action, review untouched", "test_a_removal_request_becomes_a_high_priority_report_with_a_required_contact", "Reason removal_request; priority 2; review still published"),
        ("AN14", "NUL in details or contact", "test_a_nul_character_in_a_report_is_a_validation_error_not_a_server_error (2)", "422; no row"),
    ],
    "C. Hide pending decision and the rating": [
        ("HP1", "A moderator hides a reported review until a decision", "test_a_moderator_hides_a_reported_review_until_a_decision_is_recorded", "Review HIDDEN, report in_review, takedown case, one audit each, task stays open"),
        ("HP2", "The author is told", "test_the_author_is_told_when_their_review_is_hidden", "Notification content.hidden or content.taken_down"),
        ("HP3", "Rating removed when the moderator does not keep it", "test_the_moderator_chooses_whether_the_rating_stays[False]", "Totals unchanged by the hidden review"),
        ("HP4", "Rating kept when the moderator chooses", "test_the_moderator_chooses_whether_the_rating_stays[True]", "Counted rating stays, even after a serious report removed it"),
        ("HP5", "Refusals", "test_hide_pending_refuses_the_unauthorised_the_stale_and_the_already_hidden", "404 member, 401 visitor, 409 wrong lease or stale version, 422 wrong reason or already hidden"),
        ("HP6", "Own review", "test_a_moderator_cannot_hide_their_own_review_this_way", "403 SELF_MODERATION_FORBIDDEN"),
        ("HP7", "A failure leaves nothing half done", "test_a_failure_while_hiding_leaves_no_half_state", "Review still published, no case, no audit"),
        ("HP8", "Restoring counts the rating again", "test_restoring_after_a_hide_pending_counts_the_rating_again", "Totals back"),
        ("KR1", "A kept rating stays in the totals while hidden", "test_a_kept_rating_stays_in_the_totals_while_the_review_is_hidden", "Counted, eligible, reconciliation clean"),
        ("KR2", "A plain hide removes it", "test_a_plain_hide_removes_the_rating_by_default", "Totals zero"),
        ("KR3", "Changing the flag moves the totals; no change means no version bump", "test_changing_the_flag_later_moves_the_totals", "Both directions"),
        ("KR4", "Eligibility rules still apply to a kept rating", "test_a_kept_rating_is_still_subject_to_the_eligibility_rules", "Conflicted author not counted"),
        ("KR5", "A kept guest rating stays in Guest Feedback", "test_a_kept_guest_rating_stays_in_guest_feedback", "Guest totals"),
        ("KR6", "Withdrawing a kept review uncounts it once", "test_withdrawing_a_kept_review_uncounts_it_once", "A retry changes nothing"),
        ("KR7", "Reconciliation sees a kept rating missing from the totals", "test_reconciliation_finds_a_kept_rating_missing_from_the_totals", "Drift found and repaired"),
        ("KR8", "Over HTTP: takedown keeps the rating only when asked; the flag can change later", "test_a_takedown_opened_over_http_keeps_the_rating_only_when_asked", "Default false"),
        ("KR9", "Random takedowns never drift from a full recomputation", "test_random_takedowns_keep_the_totals_equal_to_a_full_recompute (property, 30 examples)", "Reconciliation clean after every step"),
        ("KR10", "Restore racing a flag change", "test_restore_racing_a_flag_change_ends_consistent", "Consistent either way"),
    ],
    "D. Reopen, lists and the 30-day purge": [
        ("RO1", "A superadmin reopens inside the window (day 1 and day 29)", "test_a_superadmin_reopens_a_rejected_review_inside_the_window (2)", "PENDING, version +1, task priority 1, REOPEN action row, audit, author notice"),
        ("RO2", "Day 31 is refused", "test_the_window_closes_after_thirty_days", "409 REOPEN_WINDOW_CLOSED"),
        ("RO3", "A purged review cannot be reopened", "test_a_purged_review_cannot_be_reopened", "409 REOPEN_WINDOW_CLOSED"),
        ("RO4", "Only a superadmin; a refusal is audited", "test_only_a_superadmin_can_reopen_and_a_refusal_is_audited", "403 moderator with `denied.role`; 404 member; 401 visitor"),
        ("RO5", "State, version, reason and input checks", "test_reopen_validates_state_version_reason_and_input", "409 stale, 422 wrong reason, 422 not rejected"),
        ("RO6", "Lists show the recovery window and page without repeats", "test_the_lists_show_the_recovery_window_and_page_without_repeats", "Newest decision first; recoverable_until = decision + 30 days; HIDDEN has none"),
        ("RO7", "A purged review shows no text and no deadline", "test_a_purged_review_shows_no_text_and_no_deadline", "[removed]"),
        ("RO8", "List parameters validated; staff only", "test_list_parameters_are_validated (5); test_the_lists_are_for_staff_only", "422, 401, 404"),
        ("RO9", "Retention redacts text and media after 30 days", "test_retention_redacts_a_rejected_review_after_thirty_days", "Title and body [removed], media removed, audit by the system, second run does nothing"),
        ("RO10", "Day 29 is kept", "test_a_review_rejected_twenty_nine_days_ago_is_kept", "Not purged"),
        ("RO11", "An open appeal blocks the purge", "test_an_open_appeal_blocks_the_purge_until_it_is_decided", "Purged only after the appeal is decided"),
        ("RO12", "A reopened review is never purged", "test_a_reopened_review_is_never_purged", "0 purged"),
        ("RO13", "A review another run is working on is skipped", "test_a_review_another_run_is_working_on_is_skipped", "Skipped, then purged next run"),
        ("RO14", "Purged text reaches no API response", "test_purged_text_never_reaches_an_api_response", "Owner, member list and staff list show [removed] or nothing"),
    ],
    "E. Restrictions and sanction expiry": [
        ("RS1", "A restriction blocks create, edit, media and report; withdraw, appeal and reading stay open", "test_a_restricted_member_cannot_post_edit_attach_or_report_but_can_still_withdraw_appeal_and_read", "403 ACCOUNT_RESTRICTED; withdraw 200"),
        ("RS2", "A suspension is refused everywhere", "test_a_suspended_account_is_refused_everywhere", "403 ACCOUNT_DISABLED"),
        ("RS3", "A warning blocks nothing", "test_a_warning_blocks_nothing", "201"),
        ("RS4", "A restriction created through the staff API takes effect at once", "test_a_restriction_created_through_the_staff_api_takes_effect_at_once", "403"),
        ("RS5", "An expired restriction stops blocking without the job, and is ended and audited", "test_an_expired_restriction_stops_blocking_without_the_job_and_is_ended_and_audited", "State expired, `sanction.expired` by the system, member told"),
        ("RS6", "An expired suspension re-enables the account on the next request", "test_an_expired_suspension_re_enables_the_account_on_the_next_request", "403 then 200; account active; one audit"),
        ("RS7", "A sanction with only a review date stays in force", "test_a_sanction_with_only_a_review_date_stays_in_force", "Still blocked"),
        ("RS8", "A reversed sanction does not block", "test_a_reversed_sanction_does_not_block", "201"),
        ("RS9", "The daily job still sweeps what no request met", "test_the_daily_job_still_sweeps_what_no_request_met", "Account active"),
        ("RS10", "Expiry by a request and by the job at once happens once", "test_expiry_by_a_request_and_by_the_job_at_once_happens_exactly_once", "One audit row"),
        ("RS11", "The retention route needs the token and is idempotent", "test_the_retention_route_needs_the_token_and_is_idempotent; test_ops access matrix", "401 without the token; 200 twice"),
    ],
    "F. Reason catalogue": [
        ("RC1", "Served to staff in both languages", "test_the_catalogue_is_served_to_staff_with_both_languages", "401, 404, then groups with strict flags and labels"),
        ("RC2", "A strict group refuses codes from another group", "test_every_strict_group_refuses_codes_from_another_group; test_decision_routes_apply_the_catalogue", "422 VALIDATION_FAILED, field reason_code"),
        ("RC3", "The staff app's built-in lists match the server", "test_the_staff_app_built_in_reason_lists_match_the_servers_catalogue", "Equal code sets"),
        ("RC4", "Old free-text reasons still show", "test_old_free_text_reasons_still_render_in_the_lists", "Shown as written"),
    ],
    "G. Audit log": [
        ("AU1", "Decision history and audit log refuse UPDATE, DELETE, TRUNCATE", "test_the_decision_history_is_append_only_like_the_audit_log; test_audit_events_refuse_update_delete_and_truncate", "append-only error"),
        ("AU2", "Every state-changing route has a stated audit trail", "test_every_state_changing_staff_and_report_route_has_a_stated_audit_trail; test_every_listed_action_is_written_somewhere_in_the_code", "A new route without an entry fails"),
        ("AU3", "An unlisted audit action fails the suite and only warns in production", "test_an_unlisted_action_fails_in_the_suite_and_only_warns_in_production", "AssertionError in tests"),
        ("AU4", "Paging never skips or repeats rows with one timestamp (120 rows)", "test_paging_never_skips_or_repeats_rows_that_share_a_timestamp", "121 distinct rows, newest first"),
        ("AU5", "Every filter alone and combined", "test_each_filter_alone_and_combined", "action, target, actor, role, request id"),
        ("AU6", "Date range: from inclusive, to exclusive", "test_date_range_includes_from_and_excludes_to", "Inverted range 422"),
        ("AU7", "Limit between 1 and 100; bad cursor refused; old `before` works", "test_limit_must_be_between_one_and_one_hundred (3); test_a_bad_cursor_is_refused (5); test_the_older_before_parameter_still_works", "422 INVALID_CURSOR"),
        ("AU8", "The action catalogue", "test_the_catalogue_endpoint_lists_actions_for_staff_only", "Sorted list plus the denied prefix"),
        ("AU9", "Export: superadmin, CSV, headers, audited", "test_a_superadmin_exports_csv_and_the_export_is_itself_audited", "audit.exported with filters and row count"),
        ("AU10", "Export stops at the cap and says so", "test_an_export_stops_at_the_cap_and_says_so", "X-Truncated true"),
        ("AU11", "Export cells cannot run as formulas", "test_export_cells_cannot_run_as_spreadsheet_formulas (5)", "Cells start with a quote"),
        ("AU12", "Moderator, visitor, member cannot export", "test_a_moderator_cannot_export_and_the_attempt_is_audited", "403, 401, 404; nothing audited as exported"),
        ("AU13", "No secrets or personal data in the new audit rows", "test_the_new_actions_never_write_secrets_or_personal_data", "No phone, email, token, receipt"),
        ("AU14", "A wrong-role request is audited with the route and the role needed", "test_a_wrong_role_request_is_audited_with_the_route_and_what_was_needed", "`denied.role`"),
        ("AU15", "A stranger probing leaves no trace; repeated denials raise one alert", "test_a_stranger_probing_staff_routes_leaves_no_trace_in_the_log; test_repeated_denials_raise_the_security_alert_once", "No denied rows; one anomaly event"),
    ],
    "H. Access matrix, input safety, migration": [
        ("SM1", "Each new staff route: visitor, member, no-TOTP, revoked, disabled, moderator, superadmin", "test_every_caller_gets_the_right_answer_on_each_new_staff_route (7 routes)", "401, 404, MFA_REQUIRED, 404, ACCOUNT_DISABLED, allowed or 403"),
        ("SM2", "Staff writes need CSRF and a trusted origin", "test_staff_writes_need_the_csrf_token_and_a_trusted_origin (2)", "403, 403, then the route answers"),
        ("SM3", "Hostile input is refused or harmless and never leaks internals", "test_hostile_input_is_refused_or_harmless_and_never_leaks_internals (5)", "200, 404 or 422; no SQL or stack text"),
        ("MG1", "Upgrade, `alembic check`, downgrade, upgrade", "Run in the final gate", "Clean; no pending operations"),
        ("MG2", "Contract and schema tests", "test_openapi_contract; test_docs_schema", "Snapshot and API.md agree"),
    ],
    "I. Front end (unit)": [
        ("FE1", "Nine reasons, both languages, no removal code", "frontend reports.test.ts", "Pass"),
        ("FE2", "Anonymous report: no cookie, no CSRF, challenge token, trimmed fields", "frontend reports.test.ts", "Pass"),
        ("FE3", "Error kinds: duplicate, rate limited, restricted, challenge, invalid, offline", "frontend reports.test.ts", "Pass"),
        ("FE4", "Contact and review id checks", "frontend reports.test.ts; backend parity test", "Pass"),
        ("FE5", "Hide pending sends the report version, lease and keep-rating choice", "staff r11.test.ts", "Pass"),
        ("FE6", "Reopen, lists, recovery countdown, superadmin-only buttons", "staff r11.test.ts", "Pass"),
        ("FE7", "Audit filters, cursor, export, date range", "staff r11.test.ts", "Pass"),
        ("FE8", "Catalogue loaded once, failure not remembered, fallback used", "staff r11.test.ts", "Pass"),
    ],
}

MANUAL = {
    "J. Manual cases in the browser": [
        ("M1", "Member reports with each reason", "Sign in as a member. Open a destination with another person's published review. Press Report, choose each reason in turn (one review each), Send.", "\"Report sent. Thank you.\" Nine reasons listed, in Bangla after switching language. A second report on the same review says you already have one open."),
        ("M2", "Member report list", "Open Account > My reports.", "Each report with its reason and state (Received, Being reviewed, Action taken, No action needed); no staff names or notes."),
        ("M3", "Guest report", "Sign out. Open the same review. Press Report, give a reason, an optional contact, complete the security check, Send.", "The same thanks. An invalid contact (for example \"hello\") is refused before sending. No account is needed."),
        ("M4", "Lost receipt", "Open Reviews (/reviews). In \"Lost your receipt?\" press Request removal. Fill the review ID, a statement and a contact.", "Errors under each field when empty or wrong; after sending, \"Request received. The review stays as it is until the check is done.\""),
        ("M5", "Moderator sees priority and contact", "In the staff app open Queue, filter Reports.", "A privacy report shows \"High priority\"; an anonymous report shows \"Anonymous report\" and the contact, labelled staff only."),
        ("M6", "Hide pending decision", "Claim a report on a published review. Under \"Hide pending decision\" pick a reason, leave \"Keep its rating\" unticked, press Hide now.", "\"The review is hidden until a decision is recorded.\" The review no longer appears on the destination page. The report is In review."),
        ("M7", "Keep the rating", "Repeat on a counted review with the box ticked.", "The review is hidden but the destination's Community Rating count is unchanged."),
        ("M8", "Restore", "On the same report press Restore the review.", "The review is public again and counted."),
        ("M9", "Rejected and hidden", "As a superadmin open Rejected & hidden. Pick Rejected.", "Each rejected review with \"N days H hours left to reopen\". A moderator sees the list but no Reopen button."),
        ("M10", "Reopen", "Press Reopen, choose a reason, Confirm reopen.", "\"The review is back in the queue.\" It appears in Queue at the top; the author gets a notice."),
        ("M11", "Audit search", "Open Audit. Filter by action report.create, then by a date range and role.", "Matching events only, newest first; Older loads more without repeats; pick an event to see its details."),
        ("M12", "Audit export", "As a superadmin press Export CSV; as a moderator look for the button.", "A file audit-events.csv downloads; the moderator has no button. Open it in a spreadsheet: no cell runs as a formula."),
        ("M13", "Restricted member", "Give a member a posting restriction (Enforcement). Sign in as that member and try to post, edit, attach a photo, report.", "Each is refused with the restriction message; withdraw and appeals still work."),
        ("M14", "Restriction ends by itself", "Set the restriction's end a minute ahead; wait; try again.", "Posting works again without anyone running a job; the audit log has sanction.expired."),
        ("M15", "Phone, keyboard, dark theme", "At 360 px width, with the keyboard only, and in the night theme, repeat M3 and M4.", "No horizontal scroll, every control reachable, errors readable."),
    ],
}


def table(doc: Doc, title: str, rows: list[tuple[str, str, str, str]], automated: bool) -> None:
    doc.h2(title)
    head = ["ID", "Case", "Covered by" if automated else "Steps", "Expected", "Pass"]
    doc.table(head, [[a, b, c, d, "auto" if automated else ""] for a, b, c, d in rows], [1.1, 4.0, 5.3, 4.9, 1.2], size=7.8, caption=title, fills={(i, 4): GREEN for i in range(len(rows))} if automated else None)


def main() -> None:
    total_auto = sum(len(rows) for rows in AUTOMATED.values())
    total_manual = sum(len(rows) for rows in MANUAL.values())
    doc = Doc(
        "R11: Review Reporting, Moderation Actions and Audit Log",
        "What was built, the evidence, and every test case (Gantt R11; Review.md 5.4; Moderation spec P-00, P-01, P-03, P-06)",
        [
            ("Project", "Abhijatri (Team ChoturMatra, CSE 3102)"),
            ("Version", "1.0, 1 November 2026"),
            ("Record", "`Docs/Backend-Implemented.md` 5.22; contract `Docs/api/API.md` 5.22"),
            ("Automated result", "Backend: 289 unit and 438 integration tests; front end: 109 public and 45 staff tests"),
            ("Cases", f"{total_auto} automated groups of cases mapped to tests, {total_manual} manual cases"),
            ("Credentials", "None are written in this document. Use your own test accounts."),
        ],
        "Abhijatri: R11 test cases",
    )
    doc.contents()

    doc.h1("1. What R11 delivers")
    doc.p("The core of R10 and R11 already existed. This release closed the gaps against Review.md 5.4 and the Moderation specification, and fixed two real defects found on the way.")
    doc.table(
        ["Area", "Delivered"],
        [
            ["Reporting", "Nine reasons; member reports with limits and audit; anonymous reports and lost-receipt removal requests; queue priority; my reports"],
            ["Moderation actions", "Hide pending a decision (moderator's choice); a takedown can keep the rating; reopen a rejected review within 30 days; Rejected and Hidden lists; 30-day purge; reason-code catalogue"],
            ["Audit log", "Decision history and audit log immutable; keyset search with filters; action catalogue; capped, neutralised, audited CSV export; every write has a stated audit trail"],
            ["Defects fixed", "A posting restriction did not stop review writes; an expired sanction kept blocking until a job ran; wrong-role staff requests were not audited; a NUL character caused a 503"],
            ["Operations", "Daily retention workflow and route; migration 0020; new rate-limit settings"],
        ],
        [3.4, 13.1], caption="Delivered work", size=8.8,
    )

    doc.h1("2. Automated cases")
    doc.p("Each row names the test that covers it. Run them with `uv run pytest -m integration` (the local test database only) and `npm test` in `frontend` and `staff`.")
    for title, rows in AUTOMATED.items():
        table(doc, title, rows, True)

    doc.h1("3. Manual cases")
    doc.p("Run these on a local stack or a test environment with your own accounts. Do not leave test reviews published.")
    for title, rows in MANUAL.items():
        table(doc, title, rows, False)

    doc.h1("4. Deployment notes")
    doc.bullets([
        "Migration `0020_reports_mod_audit` runs when the container starts (`alembic upgrade head`). Do not start this code against a database that has not had it: every review query reads `reviews.purged_at`.",
        "To apply it earlier, run `uv run alembic upgrade head` from `backend/` with `DATABASE_URL` pointing at the target database.",
        "Add the repository secrets `OPS_API_URL` and `OPS_DASHBOARD_TOKEN` so `retention.yml` and `rating-reconciliation.yml` can run.",
        "New settings (defaults shown in `backend/.env.example`): MEMBER_REPORT_PER_HOUR, MEMBER_REPORT_PER_REVIEW_PER_DAY, ANON_REPORT_PER_NETWORK_PER_HOUR, ANON_REPORT_PER_NETWORK_PER_DAY.",
    ])
    doc.h1("5. Not part of R11")
    doc.bullets([
        "P-02 moderators must be Verified Members; P-04 moderators see each other; P-05 reopen a rejected verification.",
        "A hash chain over the audit log and monthly partitioning (needed only at about 10 million rows).",
        "Automatic hiding of reported reviews: declined on purpose, because a few accounts could hide any review.",
    ])
    doc.h1("6. Sign-off")
    doc.table(["Item", "Done"], [[f"All {total_manual} manual cases run; each Pass or noted", ""], ["Tester: ____________   Date: ____________", ""]], [14.0, 2.5])
    doc.save(OUT)
    print("saved", OUT, f"{total_auto} automated rows, {total_manual} manual cases")


if __name__ == "__main__":
    main()
