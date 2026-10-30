"""Builds Docs/Abhijatri-DFD.docx from the diagram data (so the tables and the pictures cannot disagree)."""

from pathlib import Path

import dfd_levels
from diagram_lib import canon, check_dfd
from docx_helpers import BAD_FILL, GOOD_FILL, Doc
from dfd_data import STORE_TABLES
from make_diagrams import check_balance, signature_of

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "Abhijatri-DFD.docx"
ALL = {d.key: d for d in dfd_levels.ALL}

L0_CARRIES = {
    ("Guest", "1.0"): "destination id, language, first-visit flag",
    ("1.0", "Guest"): "bilingual destination profile, advisories with freshness state, contacts, rating summaries, one page of published reviews",
    ("D1", "1.0"): "published destinations, guide items, advisories, contacts",
    ("D4b", "1.0"): "Guest Feedback and Community Rating totals",
    ("Guest", "2.0"): "party, dates, comfort tier, transport and lodging choices (prototype)",
    ("2.0", "Guest"): "itemised BDT estimate, offline pack (prototype)",
    ("D1", "2.0"): "price and pack data (planned)",
    ("2.0", "D10"): "saved trips, packs and drafts in the browser (prototype; IndexedDB is not built yet)",
    ("Guest", "4.0"): "guest review with receipt, scope secret, draft id and Turnstile token; receipt status, edit, withdraw and appeal requests",
    ("4.0", "Guest"): "review id, status, rejection reason, appeal deadline",
    ("Member", "3.0"): "email, password, verification link, TOTP code, reset request",
    ("3.0", "Member"): "session cookies, CSRF token",
    ("Admin", "3.0"): "staff role grants",
    ("3.0", "Admin"): "staff list",
    ("Member", "4.0"): "member review, edit, withdraw, appeal, report, media request",
    ("4.0", "Member"): "review id, status, review history",
    ("5.0", "Member"): "inbox items, unread count",
    ("Member", "5.0"): "email preferences, read and archive actions",
    ("3.0", "Auth"): "credentials, MFA codes, reset requests",
    ("Auth", "3.0"): "signed tokens, user identity",
    ("3.0", "D2"): "accounts, roles, session activity (read and write)",
    ("4.0", "Turnstile"): "challenge token",
    ("Turnstile", "4.0"): "pass or fail",
    ("4.0", "Storage"): "signed upload link requests",
    ("Storage", "4.0"): "uploaded photo or video",
    ("4.0", "D3"): "reviews, revisions, category ratings, receipt digests, media records (read and write)",
    ("4.0", "D6"): "review.submitted, review.edited, review.withdrawn events",
    ("4.0", "D5"): "moderation task, appeal or report case",
    ("Moderator", "6.0"): "task claims, decisions, appeal and report outcomes",
    ("6.0", "Moderator"): "review queue, case files, evidence links",
    ("Admin", "6.0"): "enforcement actions",
    ("6.0", "Admin"): "case reports",
    ("Member", "6.0"): "verification request, evidence files",
    ("D3", "6.0"): "review data (read and write: new status, version, media state)",
    ("6.0", "D5"): "tasks, decisions, cases, sanctions (read and write)",
    ("6.0", "D4"): "rating totals (read and write, in the decision's transaction)",
    ("6.0", "D6"): "review.state_changed, appeal.decided events",
    ("6.0", "Storage"): "signed link requests",
    ("Storage", "6.0"): "evidence files",
    ("6.0", "D8"): "audit events",
    ("D6", "5.0"): "outbox events (read and write: processed, retry, dead letter)",
    ("5.0", "D7"): "notifications, deliveries, attempts (read and write)",
    ("5.0", "Email"): "email messages",
    ("Email", "5.0"): "bounce and complaint webhooks",
    ("Ops", "7.0"): "ops-token panel requests",
    ("7.0", "Ops"): "health, content, traffic and queue panels",
    ("7.0", "Redis"): "visit and event counters",
    ("Redis", "7.0"): "counter totals",
    ("D8", "7.0"): "audit data",
    ("7.0", "Admin"): "audit log, delivery records",
}


def nm(d, node_id):
    n = d.node(node_id)
    label = n.label.replace(" (duplicate)", "")
    return f"{n.tag or n.id} {label}" if n.kind != "entity" else label


def flow_rows(d, with_carries=False):
    rows = []
    for i, f in enumerate(d.flows, 1):
        arrow = "<->" if f.both else "->"
        row = [f"F{i}", nm(d, f.src), nm(d, f.dst), f.label + (" (both ways)" if f.both else "")]
        if with_carries:
            row.append(L0_CARRIES.get((f.src, f.dst), ""))
        rows.append(row)
    return rows


def boundary_labels(d, pids, node, direction):
    out = []
    for f in d.flows:
        if direction == "in" and f.dst in pids and canon(f.src) == node and f.src not in pids:
            out.append(f.label)
        if direction == "out" and f.src in pids and canon(f.dst) == node and f.dst not in pids:
            out.append(f.label)
        if f.both and canon(f.dst) == node and f.dst not in pids and f.src in pids and direction == "in":
            out.append(f.label)
        if f.both and canon(f.src) == node and f.src not in pids and f.dst in pids and direction == "out":
            out.append(f.label)
    return sorted(set(out))


def check_tables() -> list[str]:
    """Every table named in a data store must exist in backend/app/models.py."""
    import re

    models = (HERE.parents[1] / "backend" / "app" / "models.py").read_text(encoding="utf-8")
    existing = set(re.findall(r'__tablename__ = "(\w+)"', models))
    missing = []
    for sid, (_, tables) in STORE_TABLES.items():
        for table in tables:
            if table not in existing:
                missing.append(f"{sid}: table {table} not in models.py")
    return missing


def main() -> None:
    problems = []
    problems += check_tables()
    for d in dfd_levels.ALL:
        problems += check_dfd(d)
    problems += check_balance(dfd_levels.ALL)
    assert not problems, problems

    doc = Doc(
        "Data Flow Diagrams",
        "How to draw them, which tools to use, and the complete Abhijatri data flow model",
        [
            ("Project", "Abhijatri: a Bangla-first, offline-ready community travel platform for Bangladesh (Team ChoturMatra, CSE 3102)"),
            ("Document", "Data flow diagram (DFD) guide and model: context, level 0, level 1 and level 2"),
            ("Version", "1.0, 30 October 2026"),
            ("Basis", "The implemented system: backend/app/models.py (tables), Docs/api/openapi-v1.json (92 routes), Docs/Architecture.md, Docs/Backend-Implemented.md 5.13 to 5.19"),
            ("Notation", "Gane-Sarson (rounded process boxes, open-ended data stores, square external entities)"),
            ("Regenerate", "python Docs/diagrams/make_diagrams.py, then python Docs/diagrams/build_dfd_doc.py"),
        ],
        "Abhijatri: Data Flow Diagrams",
    )
    doc.contents()

    # ------------------------------------------------------------------ 1
    doc.h1("1. Purpose and summary")
    doc.p("A data flow diagram (DFD) shows how data moves through a system: where it comes from, which processes change it, where it is kept, and where it goes. "
          "It answers the question \"what happens to the data?\", not \"in what order do things happen?\" (that is a flowchart or sequence diagram).")
    doc.p("This document does three things:")
    doc.bullets([
        "**Part A** teaches how to draw a correct DFD by hand: the symbols, the rules, the levelling method and a step-by-step procedure.",
        "**Part B** lists the tools you can use (free and paid) and explains how to draw a DFD in each, so the team can redraw or edit the figures themselves.",
        "**Part C** is the complete DFD of Abhijatri as built: a context diagram, a level 0 diagram with seven processes, four level 1 diagrams and two level 2 diagrams. "
        "**Part D** is the data dictionary and the balancing proof.",
    ])
    doc.table(
        ["Diagram", "What it shows", "Figure"],
        [
            ["Context (level C)", "The whole platform as one process with ten external entities", "Figure 1"],
            ["Level 0", "Seven main processes, ten data stores, all external entities", "Figure 2"],
            ["Level 1: 4.0 Reviews", "Create, edit, withdraw, view, media, appeal and report", "Figure 3"],
            ["Level 1: 6.0 Moderation", "Task queue, decisions, appeals, reports, verification", "Figure 4"],
            ["Level 1: 5.0 Notifications", "Outbox relay, inbox, email delivery, provider webhooks", "Figure 5"],
            ["Level 1: 3.0 Accounts", "Registration, sign-in, password reset, TOTP, staff roles", "Figure 6"],
            ["Level 2: 4.3 Edit review", "Owner check, state and version check, new revision", "Figure 7"],
            ["Level 2: 6.2 Decide review", "Lease and version check, state change, ratings, media, audit", "Figure 8"],
        ],
        [4.2, 10.0, 2.3], caption="Diagrams in this document",
    )
    doc.note("**What was checked.** Every diagram was drawn from one data file and passed an automatic check of the DFD rules in Part A "
             "(no process without an input and an output, no flow between two non-processes, no unnamed flow) and a balance check against its parent diagram. "
             "The result was 0 violations. The checks are listed in section 7.")
    doc.note("**Honest scope.** Cost estimation, offline packs, saved trips and booking are prototypes in the repository (Docs/Implemented.md). They are drawn dashed. "
             "There is no service worker, manifest or IndexedDB yet, so the device store D10 is dashed too.", fill="EAF2FB")

    # ------------------------------------------------------------------ Part A
    doc.page_break()
    doc.h1("2. Part A: How to draw a data flow diagram")
    doc.h2("2.1 The four symbols (Gane-Sarson)")
    doc.table(
        ["Symbol", "Shape", "Meaning", "Naming rule", "Abhijatri example"],
        [
            ["External entity", "Square", "A person or system outside the one you are modelling. It is a source or a sink of data.", "Noun", "Guest, Moderator, Supabase Auth"],
            ["Process", "Rounded rectangle with a number box", "Something that changes data: it must turn inputs into outputs.", "Verb + object, numbered 1.0, 4.3, 4.3.2", "4.0 Submit and manage reviews"],
            ["Data store", "Open-ended rectangle with a D-number", "Data at rest: a table, file or queue.", "Noun (what is kept), D1, D2 ...", "D3 Reviews"],
            ["Data flow", "Arrow with a label", "Data moving between the symbols above.", "Noun phrase (what data)", "guest review, receipt, scope secret"],
        ],
        [2.6, 2.8, 4.4, 3.2, 3.5], caption="DFD symbols",
    )
    doc.p("Yourdon-DeMarco notation uses circles for processes and two parallel lines for data stores. The meaning is identical. "
          "Use one notation throughout a document; this one uses Gane-Sarson because it is the style most university courses and tools (Visio, Lucidchart) provide.")
    doc.h2("2.2 The rules every DFD must follow")
    doc.table(
        ["#", "Rule", "Why it matters", "Common mistake"],
        [
            ["1", "Every process has at least one input and at least one output.", "A process with no input is a miracle (it invents data); with no output it is a black hole.", "A process that only receives data and never gives anything back"],
            ["2", "Data never flows directly between two external entities, two data stores, or an entity and a store. A process is always in between.", "Only processes can read, change and write data.", "An arrow from a database straight to a user"],
            ["3", "Name processes with a verb and an object, stores with a noun, flows with a noun phrase.", "Names make the diagram readable without a legend.", "\"Process data\", \"Send\" on an arrow, \"Database\" as a store name"],
            ["4", "Number processes (1.0, 4.3, 4.3.2) and stores (D1, D2).", "Numbers connect each level to its parent and to the data dictionary.", "Renumbering a process on a lower level"],
            ["5", "Balance the levels: the flows crossing the boundary of a child diagram equal the flows of the parent process it explains.", "Otherwise the levels describe different systems.", "Adding a new external flow while decomposing"],
            ["6", "Show data, not control. No decisions, loops, start or end symbols, and no timing.", "That belongs in a flowchart or sequence diagram.", "Drawing \"if approved\" diamonds"],
            ["7", "Keep 7 plus or minus 2 processes on one diagram.", "More than nine becomes unreadable; decompose instead.", "A single sheet with 20 processes"],
            ["8", "Use the same name and number for a store or entity everywhere it appears. A store used by two distant processes may be drawn twice with a duplicate marker.", "Prevents two copies being mistaken for two stores.", "Calling the same table \"Reviews\" on one page and \"Posts\" on another"],
            ["9", "Do not draw a store that nothing writes to or nothing reads from.", "An unused store is a design error or a missing process.", "A store with only outgoing arrows"],
            ["10", "A store that only one process uses may first appear on that process's child diagram (a local store).", "Keeps the parent diagram simple.", "Showing every internal table on level 0"],
            ["11", "Draw a request and its response as two arrows, and read-and-write of a store as one double-headed arrow.", "Keeps each flow's content clear.", "One arrow labelled \"login\" with no return"],
        ],
        [0.8, 5.0, 5.0, 5.7], caption="DFD rules", size=8.6,
    )
    doc.h2("2.3 Levelling: from one box to the detail")
    doc.bullets([
        "**Context diagram (level C).** The whole system is one process, numbered 0, surrounded by every external entity. No stores. It fixes the boundary of the system.",
        "**Level 0.** Open the box: 7 plus or minus 2 main processes, the data stores they share, and the same external entities with the same flows as the context diagram.",
        "**Level 1.** Take one level 0 process and open it into its own sub-processes (4.1, 4.2, ...). Its boundary flows must equal that process's flows at level 0.",
        "**Level 2.** Do the same again for a sub-process that is still too complex (4.3.1, 4.3.2, ...). Stop when a process can be described in a few sentences or one function.",
    ])
    doc.h2("2.4 Step-by-step procedure")
    doc.steps([
        "**Fix the boundary.** Write one sentence saying what is inside the system and what is not. (Abhijatri: the PWA, API, staff app and ops app; not Supabase, Cloudflare or the email provider.)",
        "**List the external entities.** Ask: who gives data to the system, and who receives data from it? Include other systems, not only people.",
        "**List the data stores.** Take the data model (tables, files, queues) and group tables that are always used together into one store. Write the table names beside each store.",
        "**List the events or use cases.** Each use case (\"submit review\", \"decide appeal\") suggests a process. Group closely related use cases into one level 0 process.",
        "**Draw the context diagram.** One process, all entities, a pair of arrows per entity (in and out). Name each arrow by the data it carries.",
        "**Draw level 0.** Place entities at the edge, processes in the middle, stores near the processes that use them. Put things that talk to each other next to each other to avoid crossing lines.",
        "**Label every flow** with the data, not the action: \"guest review, receipt\" not \"send review\".",
        "**Check the rules** in section 2.2 one by one, using the checklist in section 2.5.",
        "**Decompose** the processes that are too big or too important to leave as one box. Repeat steps 6 to 8 for each; keep numbering.",
        "**Balance and describe.** Compare each child's boundary flows with its parent's. Write the data dictionary: what each flow and store contains.",
        "**Walk through a scenario.** Trace one real case (a guest submits a review, a moderator publishes it) through the diagrams and confirm each step has an arrow.",
    ])
    doc.h2("2.5 Quick self-check before you submit")
    doc.table(
        ["Check", "Yes / No"],
        [[c, ""] for c in [
            "Every process has an input and an output",
            "No arrow joins two entities, two stores, or an entity and a store",
            "All flows are named with nouns; all processes with verb + object",
            "Processes and stores are numbered, and numbers match the data dictionary",
            "The level 0 entity flows match the context diagram",
            "Each child diagram's boundary flows match its parent process",
            "No decisions, loops or timing appear",
            "No more than nine processes on any diagram",
            "Prototype or planned parts are marked, not drawn as working",
            "A real scenario can be traced from start to finish",
            "Text is readable at A4 size (at least 8 pt after scaling)",
        ]],
        [13.5, 3.0], caption="Self-check list",
    )

    # ------------------------------------------------------------------ Part B
    doc.page_break()
    doc.h1("3. Part B: Tools for drawing DFDs by hand")
    doc.p("You do not need special software. Pick one tool the whole team can open and keep the editable source file in the repository next to the exported image.")
    doc.table(
        ["Tool", "Cost", "Best for", "Strengths", "Limits"],
        [
            ["diagrams.net (draw.io)", "Free; browser or desktop; saves .drawio to a file, Google Drive or GitHub", "Recommended for the team", "No account needed, exports PNG/SVG/PDF, rounded shapes, grid and snapping, runs offline in the desktop app", "No built-in DFD checker; you apply the rules yourself"],
            ["Lucidchart", "Free tier with limits on objects and documents", "Teams already using it (the use case diagram was drawn there)", "Shape libraries including data flow shapes (enable them from the Shape Libraries panel), real-time collaboration", "Free tier limits; export needs care"],
            ["Microsoft Visio", "Paid (Microsoft 365 plans), often available through a university", "Formal documents", "A data flow diagram template exists; precise alignment", "Heavy; Windows or web"],
            ["Visual Paradigm (Online or desktop)", "Free community tier with limits; paid for more", "Analysis diagrams with levelled decomposition", "DFD support and tools for linking levels", "Free edition limits and watermark on some exports"],
            ["PowerPoint or Google Slides", "Free or already installed", "Quick diagrams, presentations", "Everyone has it; Merge Shapes and alignment tools", "No connectors that stick as reliably; easy to mis-align"],
            ["Excalidraw or FigJam", "Free", "Sketching and brainstorming", "Fast, hand-drawn look, shareable link", "Not precise; fine for drafts, weaker for the final figure"],
            ["Mermaid (text) in GitHub or mermaid.live", "Free", "Diagrams that live in Markdown and update with the code", "Text source can be reviewed in a pull request; renders on GitHub", "No Gane-Sarson shapes; layout is automatic and can be hard to control"],
            ["PlantUML", "Free (needs Java or an online server)", "Developers who want text-defined diagrams", "Text source, many diagram types", "No native DFD symbols; approximate with rectangles and databases"],
            ["Python with matplotlib (how the figures here were made)", "Free", "Regenerating many diagrams from one data file and checking the rules automatically", "Rules checked by code; every figure rebuilt in one command", "Needs programming; layout coordinates are set by hand"],
            ["Pen and paper, then scan", "Free", "First draft on a whiteboard or in a meeting", "Fastest way to agree the structure", "Redraw digitally for submission"],
        ],
        [3.3, 3.0, 3.1, 4.1, 3.0], caption="Tools for drawing DFDs", size=8.4,
    )
    doc.h2("3.1 Recommended workflow for the team")
    doc.steps([
        "Agree the processes, stores and entities on paper or a whiteboard first (45 minutes). Photograph it.",
        "One person redraws it in diagrams.net using the steps in 3.2, and saves the **.drawio source** in `Docs/diagrams/`.",
        "Export a **PNG at 300 dpi (width at least 2400 px)** and an SVG. Insert the PNG into Word or LaTeX at the full text width.",
        "A second person checks the diagram against the self-check list (section 2.5) and the balancing table (section 6).",
        "Commit the source and the image together so the next edit starts from the source, not from the picture.",
    ])
    doc.h2("3.2 Drawing a DFD in diagrams.net (draw.io), step by step")
    doc.steps([
        "Open app.diagrams.net, choose **Create New Diagram**, a blank diagram, and save it first (the file is your source).",
        "Turn on **View > Grid** and **Snap to grid** so boxes align.",
        "**Process:** from the General shapes drag a *Rounded Rectangle*, about 4 cm by 2 cm. Type the number on the first line (4.0) and the name below. Draw a thin horizontal line under the number to make the number box.",
        "**External entity:** drag a *Rectangle*; add an inner rectangle slightly smaller to give the double border used here. Fill a pale orange.",
        "**Data store:** drag a *Rectangle*, then remove its right border (Edit Style: add `strokeColor=none` for the right edge by drawing the left, top and bottom lines only, or use the \"Data Store\" shape if your library has one). Put the D-number in a small box at the left.",
        "**Flows:** hover over a shape and drag from the blue arrow to the target shape so the connector sticks. Double-click the line to type the label. Use *Waypoints > Curved* only when you must avoid another box.",
        "For a **request and response** pair, draw two connectors and drag each slightly apart so they run parallel.",
        "Use **Format Panel > Arrange > Align** and **Distribute** to line up columns of processes.",
        "**Export:** File > Export as > PNG, set **Zoom 200 percent or DPI 300**, tick *Transparent background* off, *Border width 10*. Also export SVG.",
        "Save, and keep the .drawio next to the image in the repository.",
    ])
    doc.h2("3.3 Drawing a DFD in PowerPoint or Google Slides")
    doc.steps([
        "Use a **blank slide, widescreen (16:9)**. Turn on gridlines and guides (View).",
        "Insert **Shapes > Rounded Rectangle** for processes, **Rectangle** for entities, and a rectangle with only left, top and bottom outlines for stores (draw three lines, group them).",
        "Draw flows with **Insert > Shapes > Arrow** or **Elbow Connector**. Connectors snap to shape handles, so move shapes, not lines.",
        "Add labels as **text boxes** with a white fill so lines do not run through the words.",
        "Select everything, **Group**, then **File > Export (or Save as picture) as PNG** at the highest quality.",
    ])
    doc.h2("3.4 Drawing a DFD in Lucidchart or Visio")
    doc.bullets([
        "Create a new document, open **Shape Libraries**, search for \"data flow\" and enable the library. Choose the Gane-Sarson set so the shapes match this document.",
        "Drag process, entity and store shapes onto the page, then connect them with line tools; labels are attached to the lines so they move with them.",
        "Use **Align and Distribute** to keep columns tidy; use **Layers** if you want prototype parts on a separate, switchable layer.",
        "Export as PNG or PDF at print resolution.",
    ])
    doc.h2("3.5 Using Mermaid when you want the diagram to live in Markdown")
    doc.p("Mermaid has no Gane-Sarson shapes, but a flowchart can approximate a DFD: round brackets for processes, square brackets for entities, and cylinder shapes for stores. "
          "Use it for quick diagrams in a README, not for the final submission figure.")
    doc.code("""flowchart LR
    G[Guest] -->|guest review, receipt| P4(4.0 Submit and manage reviews)
    P4 -->|review id, status| G
    P4 <-->|reviews, revisions| D3[(D3 Reviews)]
    P4 -->|moderation task| D5[(D5 Moderation records)]""")
    doc.h2("3.6 Layout tips that make a DFD readable")
    doc.bullets([
        "Put **people on the left and outside systems on the right**; processes in the middle; stores near the processes that use them.",
        "Draw a **request and its response as two parallel arrows**, not one arrow with two heads, unless it is reading and writing a store.",
        "Put each flow's label **near the process end** of the arrow when several arrows leave the same entity; the lines are far apart there.",
        "Keep **crossings to a minimum**: move boxes, not lines. If one flow must cross others, make it a gentle curve and keep it short.",
        "Use **colour only as a helper** (orange entities, blue processes, green stores). Shapes and text must still make sense in black and white.",
        "Mark **prototype or planned** items with a dashed outline and say so in a note.",
    ])

    # ------------------------------------------------------------------ Part C
    doc.landscape()
    doc.h1("4. Part C: The Abhijatri data flow diagrams")
    doc.p("Reading guide: external entities are orange squares, processes blue rounded boxes, data stores green open-ended boxes. A double-headed arrow means a process reads and writes the store. "
          "A dashed outline means prototype. Store D4 is drawn twice on level 0 (duplicate marker, an extra bar at the right end) because process 1.0 reads it and process 6.0 writes it.")
    doc.h2("4.1 Context diagram")
    doc.figure(HERE / "dfd-context.png", "Context diagram: the Abhijatri platform and its ten external entities", 25.0, 15.2)
    doc.p("The platform is treated as one process. Guests and Members use the public PWA; moderators and administrators use the staff app; the ops operator reads the monitoring panels with a token. "
          "Supabase Auth holds passwords and TOTP secrets, Cloudflare Turnstile checks that a guest is a person, the email provider delivers email, Supabase Storage keeps uploaded media and evidence, and Upstash Redis counts visits and events.")
    doc.h2("4.2 Level 0 diagram")
    doc.figure(HERE / "dfd-level0.png", "Level 0: seven main processes, ten data stores", 25.0, 15.6)
    doc.table(
        ["Process", "What it does", "Main code"],
        [
            ["1.0 Browse destinations and advice", "Serves published destination profiles, advisories (current, stale or expired), contacts, ratings and the public review feed; counts the first visit.", "destination_api.py, api.py (feed), visits.py"],
            ["2.0 Plan trips offline (prototype)", "Cost estimate, offline pack and saved trip screens. Prototype only; no estimator API or storage exists yet.", "frontend PlannerPage, OfflinePacksPage, SavedTripsPage"],
            ["3.0 Authenticate and manage accounts", "Register, verify email, sign in, reset password, TOTP, sessions with CSRF, staff roles.", "auth/routes.py, auth/sessions.py"],
            ["4.0 Submit and manage reviews", "Create (guest, member), edit while unpublished, withdraw, status and history, media, appeals and reports.", "services.py, api.py, member_routes.py, media.py"],
            ["5.0 Notify members and staff", "Turns outbox events into notifications and email; inbox, preferences, webhooks, digests.", "notify/worker.py, notify/messages.py, notify/delivery.py"],
            ["6.0 Moderate, verify and rate", "Task queue with leases, review decisions (and the rating change in the same transaction), appeals, reports, enforcement, verification cases.", "admin/routes.py, admin/actions.py, admin/cases.py, services.moderate_review"],
            ["7.0 Monitor, audit and retain data", "Ops panels, audit log reading, visit roll-ups, retention jobs.", "ops/, jobs/retention.py"],
        ],
        [5.2, 14.0, 6.0], caption="Level 0 processes", size=8.6,
    )
    doc.h2("4.3 Level 1 diagrams")
    doc.h3("Level 1: 4.0 Submit and manage reviews")
    doc.figure(HERE / "dfd-level1-reviews.png", "Level 1: process 4.0 decomposed into 4.1 to 4.7", 25.0, 15.6)
    doc.p("4.1 screens every guest or member submission (schema, receipt format, Turnstile for guests, durable rate limits). 4.2 creates the review, its first revision, the receipt digest, a moderation task and an outbox event in one transaction. "
          "4.3 to 4.5 are the R07 operations: edit, withdraw, and the owner's status and history views. 4.6 handles photos and video through signed upload links. 4.7 files appeals and reports.")
    doc.h3("Level 1: 6.0 Moderate, verify and rate")
    doc.figure(HERE / "dfd-level1-moderation.png", "Level 1: process 6.0 decomposed into 6.1 to 6.5", 25.0, 15.6)
    doc.p("Every decision needs the task's lease token and the review's expected version. Ratings are updated inside 6.2 in the same database transaction as the status change, so a published review is counted exactly once. "
          "D11 (idempotency keys) is local to this process and first appears here.")
    doc.h3("Level 1: 5.0 Notify members and staff")
    doc.figure(HERE / "dfd-level1-notifications.png", "Level 1: process 5.0 decomposed into 5.1 to 5.5", 25.0, 14.0)
    doc.p("Events are claimed with FOR UPDATE SKIP LOCKED, converted to notifications with a unique key on (event, recipient, kind) so replays never duplicate, and emailed with retries after 1 minute, 5 minutes, 30 minutes and 2 hours. "
          "After six failed relay attempts an event becomes a dead letter that superadmins and the ops dashboard can see.")
    doc.h3("Level 1: 3.0 Authenticate and manage accounts")
    doc.figure(HERE / "dfd-level1-accounts.png", "Level 1: process 3.0 decomposed into 3.1 to 3.5", 25.0, 15.0)
    doc.p("Passwords and TOTP secrets never reach the Abhijatri database; Supabase Auth keeps them and returns signed tokens. The database stores the user, the staff role and session activity.")
    doc.h2("4.4 Level 2 diagrams")
    doc.h3("Level 2: 4.3 Edit unpublished review")
    doc.figure(HERE / "dfd-level2-edit-review.png", "Level 2: process 4.3 decomposed into 4.3.1 to 4.3.5", 25.0, 14.5)
    doc.p("The edit is allowed only while the review is PENDING or CHANGES_REQUESTED. The previous revision is marked SUPERSEDED, a new append-only revision is written, the review returns to PENDING and a moderation task is queued again. Nothing is counted because the review is not published.")
    doc.h3("Level 2: 6.2 Decide review")
    doc.figure(HERE / "dfd-level2-decide-review.png", "Level 2: process 6.2 decomposed into 6.2.1 to 6.2.5", 25.0, 15.2)
    doc.p("A stale version gives REVIEW_VERSION_CONFLICT, a lost lease gives LEASE_LOST, and a moderator cannot decide their own review. All writes (status, rating totals, media states, action row, audit event, outbox event) commit together.")

    # ------------------------------------------------------------------ Part D
    doc.portrait()
    doc.h1("5. Part D: Data dictionary")
    doc.h2("5.1 External entities")
    doc.table(
        ["Entity", "Who or what it is", "What it gives the system", "What it receives"],
        [
            ["Guest", "A traveller without an account", "Destination requests, guest reviews with a receipt, receipt operations, visit signal", "Guidance, review status"],
            ["Member / Verified Member", "A signed-in user; Verified Member is a badge after staff approval", "Sign-up, sign-in, reviews, appeals, reports, verification evidence, preferences", "Session, review history, notifications"],
            ["Moderator", "Staff with the moderator role and TOTP", "Claims, decisions, outcomes", "Queue, case files, evidence links, staff notices"],
            ["Administrator / Superadmin", "Staff with the superadmin role", "Role grants, enforcement actions, notification rules and templates", "Staff list, case reports, audit log, delivery records"],
            ["Ops operator", "A person holding the ops token", "Panel requests", "Health, content, traffic and queue panels"],
            ["Supabase Auth", "Hosted identity service", "Signed tokens, user identity", "Credentials, MFA codes, reset requests"],
            ["Cloudflare Turnstile", "Bot check service", "Pass or fail", "Challenge token"],
            ["Email provider", "SMTP, Gmail, Brevo or Resend", "Bounce and complaint webhooks", "Email messages"],
            ["Supabase Storage", "Private object storage", "Uploaded files and signed links", "Signed link requests, processed files"],
            ["Upstash Redis", "Counter service", "Counter totals", "Visit and event counters"],
        ],
        [3.3, 4.0, 5.2, 4.0], caption="External entities", size=8.6,
    )
    doc.h2("5.2 Data stores")
    rows = []
    for sid, (name, tables) in sorted(STORE_TABLES.items(), key=lambda kv: int(kv[0][1:])):
        first = {"D9": "Local to 4.0 (level 1)", "D11": "Local to 6.0 (level 1)"}.get(sid, "Level 0")
        rows.append([sid, name, ", ".join(tables) if tables else "Browser storage, not a database table (prototype)", first])
    rows.append(["(inside 7.0)", "Visit statistics", "visit_daily_stats (used only inside process 7.0, so not drawn)", "Not drawn"])
    doc.table(["Store", "Name", "Tables or place", "Where first shown"], rows, [1.5, 4.0, 8.0, 3.0], caption="Data stores and the tables behind them", size=8.6)
    doc.p("The table names come from `backend/app/models.py`. The build script verifies each one exists in that file (section 7).")
    doc.h2("5.3 Level 0 data flows and what they carry")
    d0 = ALL["dfd-level0"]
    doc.table(["ID", "From", "To", "Data flow", "What it carries"], flow_rows(d0, True), [1.0, 3.2, 3.2, 3.6, 5.5], caption="Level 0 data flows", size=8.0)
    doc.h2("5.4 Flows on the other diagrams")
    for key in ("dfd-context", "dfd-level1-reviews", "dfd-level1-moderation", "dfd-level1-notifications", "dfd-level1-accounts", "dfd-level2-edit-review", "dfd-level2-decide-review"):
        d = ALL[key]
        doc.h3(d.title.split(":", 1)[0] + ": " + d.title.split(": ", 1)[1] if ": " in d.title else d.title)
        doc.table(["ID", "From", "To", "Data flow"], flow_rows(d), [1.0, 4.5, 4.5, 6.5], size=8.0)

    # ------------------------------------------------------------------ balancing
    doc.h1("6. Balancing: the levels agree")
    doc.p("A child diagram is balanced with its parent when the flows crossing the child's boundary are exactly the flows of the parent process. "
          "The table lists, for each parent flow, the child flows that realise it. An empty child column would be a violation; there are none.")
    by_key = {d.key: d for d in dfd_levels.ALL}
    fills = {}
    rows = []
    ri = 0
    for child in dfd_levels.ALL:
        if not child.parent:
            continue
        parent = by_key[child.parent]
        pid = child.parent_process
        own = {n.id for n in child.nodes if n.kind == "process"}
        psig = signature_of(parent, {pid}) if parent.level != "context" else None
        if psig is None:
            continue
        csig = signature_of(child, own)
        parent_nodes = {canon(n.id) for n in parent.nodes}
        for node, direction in sorted(psig):
            plabels = boundary_labels(parent, {pid}, node, direction)
            clabels = boundary_labels(child, own, node, direction)
            ok = (node, direction) in csig
            rows.append([f"{parent.title.split(':')[0]} / {pid}", ("from " if direction == "in" else "to ") + nm(parent, node if node in {n.id for n in parent.nodes} else node), "; ".join(plabels), "; ".join(clabels) or "MISSING"])
            fills[(ri, 3)] = GOOD_FILL if ok else BAD_FILL
            ri += 1
        local = sorted({n for n, _ in csig if n not in parent_nodes})
        for n in local:
            rows.append([f"{child.title.split(':')[0]} / {pid}", "local store", "(not on parent)", nm(child, n)])
            fills[(ri, 3)] = GOOD_FILL
            ri += 1
    doc.table(["Child of", "Boundary", "Parent flow", "Child flows that realise it"], rows, [3.4, 4.2, 4.2, 4.8], caption="Parent and child boundary flows", size=7.6, fills=fills)
    doc.p("Level 0 against the context diagram: every external entity on level 0 has the same directions of flow as on the context diagram (in, out, or both). The automatic check reports no difference.")

    # ------------------------------------------------------------------ checks
    doc.h1("7. What was checked, and what was not")
    ctx_and_levels = len(dfd_levels.ALL)
    nflows = sum(len(d.flows) for d in dfd_levels.ALL)
    nproc = sum(1 for d in dfd_levels.ALL for n in d.nodes if n.kind == "process")
    doc.table(
        ["Check", "How", "Result"],
        [
            ["Every flow joins a process to an entity, a store or another process", "Automatic, all diagrams", f"Pass ({nflows} flows on {ctx_and_levels} diagrams)"],
            ["Every process has an input and an output", "Automatic", f"Pass ({nproc} process boxes)"],
            ["No unnamed flow, no unconnected symbol", "Automatic", "Pass"],
            ["Children balance with parents; level 0 matches the context diagram", "Automatic (this document's section 6)", "Pass"],
            ["Table names in the store table exist in models.py", "Script compares with backend/app/models.py", "Pass"],
            ["Routes and behaviours drawn match the code", "Read against Backend-Implemented.md 5.13 to 5.19 and the R07 tests", "Reviewed by the author; no automated link from picture to code"],
            ["Readability when printed on A4", "Figures viewed at page size", "Labels readable; a few labels sit close to crossing arrows on level 0 and level 1 (see limits)"],
        ],
        [6.0, 5.5, 5.0], caption="Verification", size=8.6,
    )
    doc.h2("Limits")
    doc.bullets([
        "The diagrams show the system as built on 30 October 2026. When a route or table changes, update `dfd_levels.py`, rebuild, and re-read the balancing table.",
        "Level 1 diagrams were drawn for the four processes with the most behaviour (accounts, reviews, notifications, moderation). Processes 1.0 and 7.0 are simple enough to read from the level 0 description; decompose them if the course requires a level 1 for every process.",
        "Some label positions were set by hand; if a label touches a line in Word, move it in the source and rebuild.",
        "The Word table of contents is a field. Press F9 (or accept the prompt when opening) to fill in page numbers.",
    ])
    doc.h2("How to regenerate")
    doc.code("""cd Docs/diagrams
python make_diagrams.py        # draws the DFDs and checks the rules and balancing
python make_other.py           # state, sequence, ER and Venn figures
python build_dfd_doc.py        # rebuilds Docs/Abhijatri-DFD.docx""")

    doc.save(OUT)
    print("saved", OUT)


if __name__ == "__main__":
    main()
