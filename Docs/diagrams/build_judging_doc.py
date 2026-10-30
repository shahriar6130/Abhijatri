"""Builds Docs/Abhijatri-Proposal-Judging-Checklist.docx: a judge's rubric, honest scores, tick-box checks and an improvement plan."""

from pathlib import Path

from docx_helpers import Doc

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "Abhijatri-Proposal-Judging-Checklist.docx"

GREEN, AMBER, RED = "E3F3EA", "FFF4D6", "F9DFD8"

# (criterion, max, before, after, what a judge looks for, evidence, remaining gap)
RUBRIC = [
    ("Executive summary", 4, 3.5, 3.5, "One page: problem, solution, expected outcome, in plain words",
     "Proposal section 1: problem, solution, five seeded destinations, final demonstration", "Add one line of as-built status"),
    ("Problem statement", 5, 4, 4, "A real gap, why it matters, evidence",
     "Proposal section 2, five subsections", "No cited sources or survey figures"),
    ("Objectives and goals", 8, 7, 7, "Specific, measurable, dated",
     "Proposal section 3: O1 to O8 with completion measures", "Several measures (O4, O6, O7) are not yet evidenced"),
    ("Functional requirements", 12, 10, 11, "Complete, unambiguous, prioritised, traceable features with input and output",
     "FR01 to FR17, roles, user stories, planner rules; status per requirement added in SRS 4.4", "Offline and estimator requirements are not built"),
    ("Use cases and use case diagram", 6, 5, 6, "A correct UML diagram plus described use cases",
     "Diagram in the proposal; six use case specifications in SRS 4.6", "Notifications, edit and appeal flows are missing from the diagram"),
    ("Non-functional requirements", 10, 7, 8, "All six kinds with measurable targets and a way to test",
     "Proposal section 5 (eight categories); evidence table in SRS 4.8", "No numeric uptime or load target; performance and accessibility not measured"),
    ("Stakeholders", 4, 3, 3, "Who, their interest, power and how they are engaged",
     "Proposal section 6, seven groups", "No influence and interest ranking"),
    ("Timeline and milestones", 6, 5, 5, "Phases, dates, deliverables, dependencies",
     "Milestones M1 to M4, gate G1, Gantt with effort", "No planned-versus-actual column"),
    ("Risk assessment", 6, 4, 4, "Risks scored, mitigated, owned, reviewed",
     "13 risks with warning sign, mitigation, owner", "No likelihood or impact score; no third-party service risk"),
    ("Feasibility study", 8, 6, 6, "Technical, economic and schedule feasibility with reasoning",
     "Proposal section 9, plus operational and ethical", "Costs are allowances, not actuals; free-tier dependence not discussed"),
    ("SRS completeness", 8, 3, 7, "Introduction, overall description, interfaces, data, behaviour, appendices",
     "SRS completion sections 4.1 to 4.11", "Not yet merged into the proposal PDF"),
    ("Diagrams", 8, 1, 7, "Use case, data flow (levelled), state, sequence, ER, readable and consistent",
     "Use case in proposal; DFD levels C, 0, 1, 2, state, two sequences, ERD, Venn in the new documents", "Figures are not in the PDF; editable draw.io sources not provided"),
    ("Traceability and testability", 5, 3, 4, "Each requirement maps to a test or acceptance check",
     "User stories to FR in the proposal; FR to use case to API to test in SRS 4.9", "Some rows say none yet (offline, estimator)"),
    ("Consistency and accuracy", 4, 2, 3, "No contradictions; the document matches the product",
     "As-built table in SRS 4.10", "Proposal text still describes self-managed passwords and offline as core"),
    ("Presentation and professionalism", 4, 3, 3, "Clear structure, readable tables, figure and table numbers, no errors",
     "Numbered sections, captions, consistent style in the proposal", "Check for dated statements and inconsistent terms"),
    ("Implementation evidence", 2, 0, 2, "A judge may ask to see that the plan is real",
     "502 backend and 107 front-end tests, CI, 18 migrations, deployed pilot services", "No recorded real-device offline test or pilot results"),
]


def main() -> None:
    total_max = sum(r[1] for r in RUBRIC)
    before = sum(r[2] for r in RUBRIC)
    after = sum(r[3] for r in RUBRIC)
    assert total_max == 100, total_max

    doc = Doc(
        "Proposal Judging Checklist",
        "How a judge would score the Abhijatri proposal and SRS, with honest scores and a plan to improve",
        [
            ("Project", "Abhijatri (Team ChoturMatra, CSE 3102)"),
            ("Document", "Judge's rubric, tick-box verification list and improvement guideline"),
            ("Version", "1.0, 30 October 2026"),
            ("Scored by", "Prepared for the team as a self-assessment. These are estimates, not the instructor's marks."),
            ("Assessed", "Proposal (12 October 2026), the repository at 30 October 2026 and the new documents (SRS completion, DFD, Venn)"),
            ("Scoring", f"{total_max} points over 16 criteria. 'Before' = proposal alone; 'After' = proposal plus the new documents, once pasted in"),
        ],
        "Abhijatri: Judging Checklist",
    )
    doc.contents()

    doc.h1("1. Result at a glance")
    doc.table(
        ["", "Score", "Meaning"],
        [
            ["Before the new documents", f"{before:g} / {total_max}", "The proposal alone: strong on the nine required points, weak on SRS structure and diagrams"],
            ["After the new documents are added", f"{after:g} / {total_max}", "Assuming the SRS sections, DFD, state, sequence, ER and Venn figures are inserted into the proposal or submitted with it"],
            ["Still open after that", f"{total_max - after:g} points", "Evidence the repository cannot supply today: measured performance and accessibility, real-device offline tests, the offline and estimator features, pilot results"],
        ],
        [5.2, 2.6, 8.7], caption="Score summary",
    )
    doc.note("**How honest is this?** Marks are given only where something in the repository or the documents supports them. A judge who weighs a working demonstration heavily will score "
             "the offline and cost-estimator features low, because they are prototype screens. The fastest gains are in section 4 (priority 1).")

    doc.h1("2. The rubric: criterion by criterion")
    fills = {}
    rows = []
    for i, (name, mx, b, a, look, evidence, gap) in enumerate(RUBRIC):
        rows.append([name, f"{mx}", f"{b:g}", f"{a:g}", look, evidence, gap])
        ratio = a / mx
        fills[(i, 3)] = GREEN if ratio >= 0.85 else (AMBER if ratio >= 0.6 else RED)
    rows.append(["**Total**", f"**{total_max}**", f"**{before:g}**", f"**{after:g}**", "", "", ""])
    doc.landscape()
    doc.table(["Criterion", "Max", "Before", "After", "What a judge looks for", "Evidence", "Remaining gap"], rows,
              [3.6, 1.0, 1.2, 1.2, 5.4, 7.0, 6.3], caption="Rubric with before and after scores", size=8.2, fills=fills)
    doc.portrait()

    doc.h1("3. Tick-box verification list")
    doc.p("Tick each item before submission. An item you cannot tick is either a task (section 4) or something to say honestly in the report.")

    def check_section(title, items):
        doc.h3(title)
        doc.table(["Done", "Check"], [["[  ]", c] for c in items], [1.4, 15.1], size=9.0)

    check_section("A. The nine required proposal points", [
        "Executive Summary states the problem, the solution and the expected outcome in under one page",
        "Problem Statement names the gap and why it matters, with at least one source or figure",
        "Every objective has a number, a date or a pass test (not just \"improve\" or \"support\")",
        "Functional requirements have an ID, input and output for each; roles and user stories are present",
        "Non-functional requirements cover performance, security and access control, reliability and availability, scalability, usability and accessibility, maintainability",
        "Each non-functional requirement has a measure and a way to test it",
        "Stakeholders list who, their interest or authority, and how they are engaged",
        "Timeline lists phases, key dates and deadlines; slipping a deadline has a stated consequence",
        "Risk register lists likelihood, impact, early warning, mitigation and owner",
        "Feasibility covers technical, economic and schedule feasibility, each with a conclusion",
    ])
    check_section("B. SRS structure", [
        "Purpose, scope, glossary and references are present",
        "Product perspective with a context diagram is present",
        "Design and implementation constraints are listed",
        "Assumptions and dependencies are listed with what happens if each fails",
        "External interfaces (user, software, hardware, communications) are described",
        "Data requirements and a data model diagram are present",
        "Use cases have specifications (actor, trigger, flow, exceptions, postconditions)",
        "A traceability matrix links requirement to use case to test",
        "Revision history and approval block are present",
    ])
    check_section("C. Diagrams", [
        "Use case diagram: actors, system boundary, include and extend relations, packages labelled",
        "Context diagram (data flow level C) shows one process and every external entity",
        "Level 0 DFD has seven to nine processes and numbered data stores",
        "Level 1 and level 2 diagrams are balanced with their parents",
        "No data flow diagram breaks a rule (process without input or output, flow between two stores)",
        "State diagram shows every state the code can reach",
        "Sequence diagram shows the main flow with the order of messages",
        "ER diagram shows keys and the cardinality of relations",
        "Venn diagram labels each overlap with a capability, not just a word",
        "Every figure has a number, a caption and is mentioned in the text",
        "Every figure is readable at A4 width (8 pt or larger text after scaling)",
        "Colour is not the only way meaning is shown (shape and text also differ)",
    ])
    check_section("D. Accuracy and honesty", [
        "Every feature described as built is built (check Docs/Implemented.md)",
        "Prototype and planned features are labelled as such everywhere, including diagrams",
        "Numbers (test counts, route counts, table counts) match the repository on the submission date",
        "Dates, versions and costs are current",
        "The same term means the same thing everywhere (Guest, Member, Verified Member, receipt, revision)",
        "Claims about competitors are general and not unsupported",
    ])
    check_section("E. Presentation", [
        "Title page has the project, team, date and version",
        "Table of contents and lists of figures and tables are updated (Word: F9)",
        "Headings are numbered and consistent; no orphan headings at the bottom of a page",
        "Tables have header rows, no cell is empty without a reason, and long tables repeat their header",
        "Spelling and grammar checked in English and, where used, in Bangla",
        "File names are clear and the PDF opens on a phone",
    ])
    check_section("F. Evidence ready to show", [
        "CI is green on the main branch (all five jobs)",
        "Backend and front-end test results can be shown",
        "A live or recorded demonstration of one full flow (submit, moderate, publish, notify)",
        "A record of the offline test, or an honest statement that offline is still a prototype",
        "Pilot or usability results, or a plan and date for them",
    ])

    doc.h1("4. How to improve: prioritised guideline")
    doc.p("Priority 1 items cost marks now and are quick. Priority 2 strengthen the document. Priority 3 polish it. Owners follow the proposal's roles: Shahriar (leader), Abdullah (frontend and offline), Syed Muhtasim (backend and data), Irfan (quality assurance).")
    p1 = [
        ["P1", "Insert the new diagrams and SRS sections into the proposal (context DFD, level 0, state, ER, glossary, constraints, interfaces, traceability)", "Shahriar", "Docs/Abhijatri_Project_Proposal.tex (or a new SRS document); figures from Docs/diagrams/", "+10 to +12"],
        ["P1", "Add an \"as built\" status column to the FR catalogue and an \"as built versus proposed\" table", "Shahriar", "Proposal section 4; use SRS 4.4 and 4.10", "+1 to +2"],
        ["P1", "Update the security text: Supabase Auth holds passwords and TOTP; sessions with CSRF; staff TOTP", "Syed Muhtasim", "Proposal section 5 and technical feasibility", "+1"],
        ["P1", "Label offline, estimator, saved trips and booking as prototype or planned everywhere; do not present them as working", "Abdullah", "Proposal, UI labels, use case diagram", "Protects accuracy marks"],
        ["P1", "Add notifications, review edit and appeal flows to the use case diagram", "Shahriar", "Lucidchart source; Abhijatri_UseCase_compressed.png", "+0.5"],
    ]
    p2 = [
        ["P2", "Add likelihood and impact scores and residual risk to the register; add third-party service dependence and free-tier limits", "Shahriar, Irfan", "Proposal section 8", "+1 to +2"],
        ["P2", "Give numeric targets for availability, load and response time and a test for each", "Syed Muhtasim", "Proposal section 5; add a small load test and record results", "+1 to +2"],
        ["P2", "Measure and record performance on a throttled connection and on a real low-end phone", "Irfan, Abdullah", "A short test report in Docs/", "+1"],
        ["P2", "Run and record an accessibility check (keyboard only, screen reader, contrast) on the main screens", "Abdullah, Irfan", "Docs/QA_UI_UX.md", "+1"],
        ["P2", "Build or honestly re-scope offline packs and the cost estimator; if re-scoped, update objectives O3, O4 and O6", "Abdullah, Shahriar", "Proposal section 3; code", "Largest remaining gain"],
        ["P2", "Add stakeholder influence and interest levels and name the decision owner", "Shahriar", "Proposal section 6", "+0.5"],
        ["P2", "Update the cost table with actual hosting and service costs and what happens if free tiers end", "Shahriar", "Proposal section 9.2", "+1"],
        ["P2", "Add planned versus actual dates to the milestone table", "Shahriar", "Proposal section 7", "+0.5"],
    ]
    p3 = [
        ["P3", "Cite sources for the problem statement (surveys, travel statistics, reports)", "Shahriar", "Proposal section 2", "+1"],
        ["P3", "Provide editable draw.io or Lucidchart sources for every diagram", "Shahriar", "Docs/diagrams/", "Easier future edits"],
        ["P3", "Add a one-page glossary of Bangla terms used in the interface", "Abdullah", "SRS 4.1.3", "Polish"],
        ["P3", "Proofread English and Bangla; check figure and table numbering after insertion", "Whole team", "All documents", "Polish"],
    ]
    doc.landscape()
    doc.table(["Priority", "Action", "Owner", "File or place", "Expected gain (points)"], p1 + p2 + p3, [1.6, 10.4, 3.2, 7.6, 3.6], caption="Improvement actions", size=8.4,
              fills={(i, 0): (RED if r[0] == "P1" else AMBER if r[0] == "P2" else GREEN) for i, r in enumerate(p1 + p2 + p3)})
    doc.portrait()
    doc.h2("4.1 Presentation tips for the evaluation")
    doc.bullets([
        "Lead with the **user journey**: explore a destination, write a review, see it moderated and published. It is built and can be shown live.",
        "Say clearly what is built and what is a prototype. Evaluators trust a team that does not overclaim.",
        "Show the **use case diagram, level 0 DFD and review state diagram** on three slides; they explain the whole system in two minutes.",
        "Have the green CI page and the test counts ready as evidence of quality.",
        "Prepare an answer for \"what would you do with more time?\": offline packs, the estimator, published-review editing (v1.1) and Idempotency-Key replay for all writes.",
        "Use the same terms in speech and slides as in the documents (Guest, Member, Verified Member, receipt, revision).",
    ])
    doc.h2("4.2 Questions a judge may ask, and where the answer is")
    doc.table(
        ["Likely question", "Short answer", "Where"],
        [
            ["How do you stop duplicate reviews when the network drops?", "A permanent draft id and receipt on the review; a retry returns the same review", "SRS 4.6 UC-01; tests/test_review_postgres.py"],
            ["How is a guest review protected from abuse?", "Turnstile, durable rate limits, pending ceilings, receipt digests, an emergency switch", "SRS 4.2.6; Backend-Implemented.md 2"],
            ["Can a moderator publish their own review?", "No: SELF_MODERATION_FORBIDDEN", "SRS 4.6 UC-03"],
            ["What if two moderators open the same review?", "A 300-second lease and a version check; the second gets LEASE_LOST or REVIEW_VERSION_CONFLICT", "DFD level 2: 6.2"],
            ["Is the rating always consistent?", "Totals change in the same transaction as the status change", "DFD level 1: 6.0"],
            ["Is offline mode working?", "Not yet; it is a prototype and is labelled so", "SRS 4.4, FR10"],
            ["How do you know the API matches the documents?", "A test compares the code with openapi-v1.json and API.md on every build", "tests/test_openapi_contract.py"],
        ],
        [5.5, 7.0, 4.0], caption="Likely questions", size=8.6,
    )
    doc.save(OUT)
    print("saved", OUT, f"before={before:g} after={after:g} max={total_max}")


if __name__ == "__main__":
    main()
