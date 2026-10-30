"""State, sequence, ER and Venn figures for the Abhijatri documents.   Usage: python make_other.py"""

from pathlib import Path

from diagram_lib import INK, PAL, draw_erd, draw_sequence, draw_states, draw_venn

OUT = Path(__file__).resolve().parent


def states() -> None:
    blue, green, red, grey, amber = "#DCEBF7", "#E3F3EA", "#F7DDD4", "#EFEFEF", "#FFF1D6"
    st = {
        "PENDING": (36, 50, blue),
        "CHANGES_REQUESTED": (36, 18, amber),
        "REJECTED": (62, 70, red),
        "PUBLISHED": (80, 50, green),
        "HIDDEN": (114, 50, red),
        "WITHDRAWN": (80, 18, grey),
        "UNDER_REVIEW": (114, 22, grey),
        "DELETED": (114, 8, grey),
    }
    edges = [
        ("__start", "PENDING", "submit (Guest or Member)", 0.0, 0.5, 0, 2.6),
        ("PENDING", "PUBLISHED", "PUBLISH: rating counted once", 0.0, 0.5, 0, 2.6),
        ("PENDING", "REJECTED", "REJECT", 0.0, 0.5, -3.0, 2.0),
        ("REJECTED", "PENDING", "appeal overturned", 0.28, 0.5, 6.0, -1.5),
        ("PENDING", "CHANGES_REQUESTED", "REQUEST_CHANGES", 0.25, 0.5, -15.0, 3.0),
        ("CHANGES_REQUESTED", "PENDING", "author edits: new revision", 0.25, 0.5, -15.0, -4.0),
        ("PUBLISHED", "HIDDEN", "HIDE: rating removed", 0.25, 0.5, 0, 4.0),
        ("HIDDEN", "PUBLISHED", "RESTORE", 0.25, 0.5, 0, -4.0),
        ("PENDING", "WITHDRAWN", "author withdraws", 0.0, 0.62, 3.0, 5.0),
        ("CHANGES_REQUESTED", "WITHDRAWN", "author withdraws", 0.0, 0.5, 0, 2.6),
        ("PUBLISHED", "WITHDRAWN", "author withdraws: rating removed", 0.0, 0.5, 11.0, 0),
    ]
    draw_states(str(OUT / "review-state.png"), "Review lifecycle (ReviewStatus) and the transitions the code allows", st, edges,
                size=(13.0, 8.2), dashed={"UNDER_REVIEW", "DELETED"},
                note="Dashed states exist in the model but no current code path sets them (a moderator's claim is held on the task, not on the review). Editing is allowed only in PENDING and CHANGES_REQUESTED; a published review is never edited.")


def sequences() -> None:
    draw_sequence(
        str(OUT / "seq-submit-moderate.png"),
        "Sequence: a Guest submits a review, a moderator publishes it, the author is notified",
        ["Guest browser (PWA)", "API (FastAPI)", "PostgreSQL", "Moderator (staff app)", "Outbox worker", "Email provider"],
        [
            (0, 1, "POST /reviews/guest: receipt, draft id, Turnstile token"),
            (1, 1, "validate; check Turnstile; rate limits; duplicate check", "self"),
            (1, 2, "insert review, first revision, receipt digest, moderation task, outbox event (one transaction)"),
            (2, 1, "committed", "return"),
            (1, 0, "201 { review_id, status PENDING }", "return"),
            (3, 1, "claim task (POST /admin/tasks/{id}/claim)"),
            (1, 3, "lease token (300 s)", "return"),
            (3, 1, "POST /admin/submissions/{id}/moderation-actions: PUBLISH + lease + version"),
            (1, 2, "status PUBLISHED, rating totals, action, audit, outbox event (one transaction)"),
            (4, 2, "claim due outbox events (FOR UPDATE SKIP LOCKED)"),
            (4, 2, "create notification for the author; queue email delivery"),
            (4, 5, "send email (retries after 1 min, 5 min, 30 min, 2 h)"),
        ],
        size=(15.0, 9.6),
    )
    draw_sequence(
        str(OUT / "seq-guest-edit.png"),
        "Sequence: moderator asks for changes, the Guest edits with the receipt, the review returns to the queue",
        ["Moderator (staff app)", "API (FastAPI)", "PostgreSQL", "Guest browser (PWA)"],
        [
            (0, 1, "moderation-actions: REQUEST_CHANGES + reason code + lease + version"),
            (1, 2, "status CHANGES_REQUESTED, action, audit, outbox event"),
            (3, 1, "POST /review-receipts/status: review id + receipt"),
            (1, 3, "CHANGES_REQUESTED + public reason", "return"),
            (3, 1, "PATCH /reviews/{id}/pending: receipt, expected_version, changed fields"),
            (1, 1, "verify receipt digest; check state and version; validate", "self"),
            (1, 2, "new revision (old one SUPERSEDED), status PENDING, task re-queued, review.edited"),
            (1, 3, "200 { status PENDING, version, revision }", "return"),
            (0, 1, "claim task and decide again (PUBLISH)"),
        ],
        size=(13.0, 8.2),
    )


def erd() -> None:
    head = {"core": "#DCEBF7", "review": "#FFF1D6", "mod": "#F7DDD4", "notify": "#E3F3EA"}
    ents = {
        "users": (14, 96, ["PK id", "email, display_name", "status"], head["core"]),
        "user_roles": (14, 72, ["PK id", "FK user_id", "role, revoked_at"], head["core"]),
        "destinations": (52, 100, ["PK id", "name_bn, name_en", "status"], head["core"]),
        "destination_rating_stats": (52, 74, ["PK/FK destination_id", "community sum, count", "guest sum, count"], head["core"]),
        "reviews": (92, 90, ["PK id", "FK destination_id", "FK author_user_id (null = guest)", "status, version, visit_month", "overall_rating, counted_rating", "current_revision_id"], head["review"]),
        "review_revisions": (92, 54, ["PK id", "FK review_id", "sequence, status", "title, body, rating"], head["review"]),
        "review_category_ratings": (126, 54, ["PK/FK revision_id", "PK category", "rating 1..5"], head["review"]),
        "review_receipts": (126, 90, ["PK id", "FK review_id", "key_id, digest"], head["review"]),
        "review_media": (126, 72, ["PK id", "FK review_id", "FK uploader_id", "kind, state"], head["review"]),
        "moderation_actions": (52, 38, ["PK id", "FK review_id", "FK actor_user_id", "decision, new_status"], head["mod"]),
        "appeals": (14, 38, ["PK id", "FK appellant_user_id (null = guest)", "FK moderation_action_id", "state, deadline_at"], head["mod"]),
        "moderation_tasks": (92, 22, ["PK id", "task_type, subject_id", "FK claimed_by", "status, lease_expires_at"], head["mod"]),
        "outbox_events": (14, 8, ["PK id", "topic, aggregate_id", "status, attempts"], head["notify"]),
        "notifications": (52, 8, ["PK id", "FK event_id", "FK recipient_user_id", "kind, priority"], head["notify"]),
        "notification_deliveries": (92, 4, ["PK id", "FK notification_id", "status, attempt_count"], head["notify"]),
    }
    rels = [
        ("users", "user_roles", "has", "1", "N", 0.0),
        ("destinations", "reviews", "is reviewed in", "1", "N", 0.0),
        ("users", "reviews", "writes (member)", "1", "N", 0.0),
        ("destinations", "destination_rating_stats", "has", "1", "1", 0.0),
        ("reviews", "review_revisions", "has", "1", "N", 0.0),
        ("review_revisions", "review_category_ratings", "scores", "1", "N", 0.0),
        ("reviews", "review_receipts", "proved by", "1", "N", 0.0),
        ("reviews", "review_media", "shows", "1", "N", 0.0),
        ("reviews", "moderation_actions", "decided by", "1", "N", 0.0),
        ("moderation_actions", "appeals", "appealed in", "1", "N", 0.0),
        ("outbox_events", "notifications", "becomes", "1", "N", 0.0),
        ("notifications", "notification_deliveries", "emailed as", "1", "N", 0.0),
        ("users", "notifications", "receives", "1", "N", 0.35),
    ]
    ents = {k: (v[0], v[1] + 8, v[2], v[3]) for k, v in ents.items()}
    rels = [r for r in rels if (r[0], r[1]) != ("users", "notifications")]
    draw_erd(str(OUT / "erd.png"), "Entity-relationship diagram: the main tables (foreign keys as in backend/app/models.py)", ents, rels, size=(14.5, 12.8),
             note="Also: notifications.recipient_user_id, moderation_actions.actor_user_id and appeals.appellant_user_id point to users. moderation_tasks.subject_id points to a review, appeal, report, case or verification by task_type, so it has no database foreign key. audit_events is append-only and also has no foreign key.")


def venns() -> None:
    o, g, b = PAL["orange"], PAL["green"], PAL["blue"]
    draw_venn(
        str(OUT / "venn-product.png"),
        "Where Abhijatri sits: three needs that no single tool meets together",
        [
            dict(x=44, y=58, r=30, colour=b, name="Bangla-first and\noffline-ready", name_xy=(24, 86)),
            dict(x=76, y=58, r=30, colour=g, name="Community trust\n(moderated, dated)", name_xy=(96, 86)),
            dict(x=60, y=33, r=30, colour=o, name="Explainable\ncost planning", name_xy=(60, 3)),
        ],
        "Abhijatri",
        [
            (60, 52, "ABHIJATRI\nBangla, offline-first,\ntrusted and priced", 9.5, "bold"),
            (60, 77, "Offline pages with\ndated advisories and\nfreshness labels", 8, "normal"),
            (36, 42, "Cost estimates that\nwork without a signal\n(prototype)", 8, "normal"),
            (84, 42, "Itemised estimates built\nfrom source-dated prices", 8, "normal"),
            (28, 66, "Bangla interface,\ninstallable PWA", 8, "normal"),
            (92, 66, "Moderated reviews,\nguest and member", 8, "normal"),
        ],
        size=(12.0, 10.0),
        subtitle="Offline cost planning is a prototype; the other overlaps are built and tested (Docs/Implemented.md).",
    )
    r, s, m = "#CC79A7", PAL["sky"], PAL["yellow"]
    draw_venn(
        str(OUT / "venn-landscape.png"),
        "What each kind of existing tool offers, and what Abhijatri adds",
        [
            dict(x=42, y=62, r=28, colour=r, name="Booking and\nguide sites", name_xy=(20, 90)),
            dict(x=78, y=62, r=28, colour=s, name="Social media travel\ngroups and blogs", name_xy=(100, 90)),
            dict(x=60, y=36, r=28, colour=m, name="Maps and\noffline apps", name_xy=(60, 5)),
        ],
        "Abhijatri",
        [
            (60, 55, "ABHIJATRI\nBangla-first, moderated,\ndated, offline", 9.5, "bold"),
            (60, 78, "Prices and listings,\nbut commercial\nand often undated", 7.8, "normal"),
            (30, 50, "Navigation, but no\ntravel cost or\ntrust signals", 7.8, "normal"),
            (90, 50, "Real experiences, but\nunmoderated and\nhard to search", 7.8, "normal"),
            (20, 70, "Listings\nand prices", 8, "normal"),
            (100, 70, "Local stories\nand tips", 8, "normal"),
            (60, 22, "Maps and\ndirections", 8, "normal"),
        ],
        size=(12.0, 10.0),
        subtitle="General positioning only: no product is named and no figures are claimed. Abhijatri is the intersection that none of the three covers alone.",
    )
    draw_venn(
        str(OUT / "venn-roles.png"),
        "Team responsibilities and where they overlap (from the proposal's roles)",
        [
            dict(x=42, y=62, r=28, colour=b, name="Frontend and offline\n(Abdullah)", name_xy=(20, 90)),
            dict(x=78, y=62, r=28, colour=g, name="Backend and data\n(Syed Muhtasim)", name_xy=(100, 90)),
            dict(x=60, y=36, r=28, colour=o, name="Quality assurance\n(Irfan)", name_xy=(60, 5)),
        ],
        "Team",
        [
            (60, 55, "Shahriar (leader):\nscope, content, estimator\nrules, integration, documents", 8.5, "bold"),
            (60, 78, "API contract,\nerror handling,\nidempotent retries", 8, "normal"),
            (30, 50, "Offline and\nreal-device tests", 8, "normal"),
            (90, 50, "Integration, security\nand regression tests", 8, "normal"),
            (20, 70, "React, bilingual\nUI, PWA", 8, "normal"),
            (100, 70, "FastAPI, PostgreSQL,\nauthentication", 8, "normal"),
            (60, 22, "Test strategy,\npilot, defects", 8, "normal"),
        ],
        size=(12.0, 10.0),
        subtitle="The centre is shared work that needs all four members; the project leader coordinates it.",
    )


if __name__ == "__main__":
    states()
    sequences()
    erd()
    venns()
    print("drew state, sequence, ER and Venn figures")
