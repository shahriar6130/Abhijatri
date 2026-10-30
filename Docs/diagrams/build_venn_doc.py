"""Builds Docs/Abhijatri-Venn-Diagram.docx: the overlap (Venn) diagrams and how to draw them by hand."""

from pathlib import Path

from docx_helpers import Doc

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "Abhijatri-Venn-Diagram.docx"
TIKZ = (HERE / "venn-tikz-example.tex").read_text(encoding="utf-8")
BODY = TIKZ[TIKZ.index("\\begin{tikzpicture}"):TIKZ.index("\\end{tikzpicture}") + len("\\end{tikzpicture}")]


def main() -> None:
    doc = Doc(
        "Venn (Overlap) Diagrams",
        "What Abhijatri combines, how it differs from existing tools, and how to draw these diagrams by hand",
        [
            ("Project", "Abhijatri: a Bangla-first, offline-ready community travel platform for Bangladesh (Team ChoturMatra, CSE 3102)"),
            ("Document", "Three Venn diagrams and a drawing guide"),
            ("Version", "1.0, 30 October 2026"),
            ("Basis", "Proposal (problem statement, objectives, roles) and Docs/Implemented.md for what is built"),
            ("Regenerate", "python Docs/diagrams/make_other.py, then python Docs/diagrams/build_venn_doc.py"),
        ],
        "Abhijatri: Venn Diagrams",
    )
    doc.contents()

    doc.h1("1. What a Venn diagram is for")
    doc.p("A Venn diagram shows how groups overlap. In a proposal it answers a question the evaluator always has: \"what is new here?\" "
          "The answer is the overlap: Abhijatri is useful because it combines three things that existing tools offer separately.")
    doc.table(
        ["Diagram", "Question it answers", "Figure"],
        [
            ["Venn 1: what Abhijatri combines", "Which three needs does the product bring together, and what does each pair give?", "Figure 1"],
            ["Venn 2: the landscape", "What do existing kinds of tools offer, and what does Abhijatri add?", "Figure 2"],
            ["Venn 3: team responsibilities", "Where do the four members' roles overlap and need shared work?", "Figure 3"],
        ],
        [5.2, 9.0, 2.3], caption="Diagrams in this document",
    )
    doc.note("**Honesty rule.** A Venn diagram makes a claim, so every label must be true. The overlap that involves offline cost estimates is a prototype in the repository "
             "(Docs/Implemented.md) and is marked as such. The landscape diagram names kinds of tools, not products, and gives no figures, so it makes no claim that cannot be supported.")

    doc.h1("2. Venn 1: what Abhijatri combines")
    doc.figure(HERE / "venn-product.png", "Abhijatri sits where three needs overlap", 15.0, 13.2)
    doc.table(
        ["Region", "What it means", "Status"],
        [
            ["Bangla-first and offline-ready (alone)", "A Bangla default interface that installs as a PWA", "Bangla interface built; installable PWA and offline pages not built"],
            ["Community trust (alone)", "Guest and member reviews that moderators check before they appear", "Built and tested"],
            ["Explainable cost planning (alone)", "Itemised estimates from source-dated prices", "Prototype screen only"],
            ["Offline and trust", "Pages with dated advisories and freshness labels that remain readable without a signal", "Advisory freshness built; offline caching not built"],
            ["Offline and cost", "Estimates that still work without a signal", "Prototype"],
            ["Trust and cost", "Estimates built from prices that carry a source and a date", "Planned with the price catalogue"],
            ["All three: Abhijatri", "A Bangla-first, trusted and priced trip guide that works offline", "The project goal; part built"],
        ],
        [4.6, 7.4, 4.5], caption="Reading Venn 1", size=8.8,
    )

    doc.h1("3. Venn 2: the landscape")
    doc.figure(HERE / "venn-landscape.png", "What each kind of existing tool offers, and what Abhijatri adds", 15.0, 13.2)
    doc.p("The three circles are kinds of tools that travellers use today. Each has real strengths; none covers all of Bangla-first content, moderated and dated information, and offline use together. "
          "This is a positioning statement from the problem section of the proposal, not a market study. If you add figures, cite them.")

    doc.h1("4. Venn 3: team responsibilities")
    doc.figure(HERE / "venn-roles.png", "Roles from the proposal and the work they share", 15.0, 13.2)
    doc.p("The centre is work that needs all four members, such as the end-to-end review flow, and it is coordinated by the project leader. The overlaps show where two members must agree: the API contract (frontend and backend), real-device and offline tests (frontend and quality), and integration and security tests (backend and quality).")

    doc.h1("5. How to draw a Venn diagram yourself")
    doc.h2("5.1 Plan it on paper first")
    doc.steps([
        "**Choose the sets.** Two or three is best. Four needs ellipses and is hard to read; five or more should be a table instead.",
        "**Name each set with a noun phrase** that a stranger understands (\"Community trust\", not \"Feature B\").",
        "**Write one short phrase for every region**: each set alone, each pair, and the centre. If a region is empty, say so or change the sets; an empty region is a useful finding.",
        "**Check every phrase is true** and that prototype or planned parts are marked.",
        "**Decide the size.** Use equal circles unless sizes carry meaning (then say so in a note, because readers will assume bigger means more).",
    ])
    doc.h2("5.2 Tools, and how to draw it in each")
    doc.table(
        ["Tool", "Cost", "Best for", "How (short)"],
        [
            ["diagrams.net (draw.io)", "Free", "Recommended: precise, editable, exports PNG and SVG", "Section 5.3"],
            ["PowerPoint or Google Slides", "Free or installed", "Quick and familiar", "Section 5.4"],
            ["Canva", "Free tier", "Polished look, templates", "Search \"Venn diagram\" in Templates; edit text; download PNG at high quality"],
            ["Lucidchart", "Free tier", "Team collaboration", "Use the \"Venn diagram\" template; drag circles, set transparency in the Fill panel"],
            ["Figma or FigJam", "Free", "Designers; styles and reuse", "Draw three ellipses, set Fill opacity to 30 percent, group, export PNG at 2x or 3x"],
            ["Inkscape", "Free", "Vector control, print quality", "Ellipse tool, set the alpha of the fill, use Path > Intersection to get the overlap shapes"],
            ["LaTeX with TikZ", "Free", "Matches the proposal (it already uses TikZ)", "Section 5.5; a tested snippet is given"],
            ["Python with matplotlib or matplotlib-venn", "Free", "Reproducible figures from code", "Section 5.6"],
            ["Pen, compass and paper", "Free", "First sketch with the team", "Draw circles with a cup or compass; then redraw digitally"],
        ],
        [3.6, 2.2, 5.2, 5.5], caption="Tools for drawing Venn diagrams", size=8.6,
    )
    doc.h2("5.3 draw.io (diagrams.net), step by step")
    doc.steps([
        "Open app.diagrams.net, create a blank diagram, and save the file first (this is your editable source).",
        "From **General**, drag an **Ellipse**. In the **Format** panel set Width and Height equal (for example 300 by 300) so it is a circle.",
        "Set **Fill** to a colour and **Opacity** to about 30 percent (Format > Style > Opacity or the Fill slider). Set the **Line** colour to the same hue, thicker.",
        "Select the circle, press **Ctrl+D** to duplicate, and drag the copy so the two overlap by about one third of the diameter. Hold **Alt** while dragging to move without snapping.",
        "Duplicate again and place the third circle below the other two, centred between them. The three circles now form a triangle with a shared centre.",
        "Add **text boxes** (Text from General) for set names outside the circles and for each region inside. Keep each phrase to two or three short lines.",
        "Use **Arrange > Align > Center** and **Arrange > Distribute** to keep the circles symmetric.",
        "Check the text is readable where the colours blend; if not, make the text bold or darker, or reduce opacity.",
        "**File > Export as > PNG**: zoom 200 percent or DPI 300, border width 10. Also export SVG for the report.",
    ])
    doc.h2("5.4 PowerPoint or Google Slides, step by step")
    doc.steps([
        "Use a blank slide. Insert **Shapes > Oval**; hold **Shift** while dragging to make a circle.",
        "Right-click > **Format Shape**: set **Fill** to a solid colour and **Transparency** to 70 percent; set the outline colour.",
        "Copy and paste twice; move the circles so they overlap. In PowerPoint, **Arrange > Align** to centre them.",
        "Insert text boxes for the labels. Use a white or no-fill text box so words stay readable.",
        "Optional exact overlap shapes: select two circles, **Shape Format > Merge Shapes > Intersect** to cut out the overlap as its own shape, which you can colour and label separately.",
        "**File > Export > PNG** (or Save as picture) at the highest quality.",
    ])
    doc.h2("5.5 LaTeX with TikZ (matches the proposal)")
    doc.p("The proposal is written in LaTeX and already uses TikZ for its Gantt charts, so a TikZ Venn diagram needs no new package beyond `tikz`. "
          "The snippet below was compiled and checked (file `Docs/diagrams/venn-tikz-example.tex`). Change the labels and positions to suit.")
    doc.code(BODY)
    doc.bullets([
        "`\\fill[...,opacity=.30]` draws a see-through circle, so overlaps look darker automatically; `\\draw` adds the outline.",
        "Centres at (-1.2, 0.7), (1.2, 0.7) and (0, -1.4) with radius 2.2 make three equal circles overlapping about one third; move them closer for a bigger overlap.",
        "Put set names with `\\node` outside the circles and overlap labels with `\\node` inside, using `align=center` and `\\\\` for line breaks.",
        "To use it as a figure, wrap it in `\\begin{figure}` with a `\\caption{}` as the proposal does for other figures.",
    ])
    doc.h2("5.6 Python, for reproducible figures")
    doc.p("The figures in this document are drawn by `Docs/diagrams/make_other.py` with matplotlib circles at 30 percent opacity. If you prefer a ready library:")
    doc.code("""# pip install matplotlib matplotlib-venn
from matplotlib import pyplot as plt
from matplotlib_venn import venn3

venn3(subsets=(1, 1, 1, 1, 1, 1, 1),            # equal-size regions, so labels fit
      set_labels=("Bangla-first, offline", "Community trust", "Cost planning"))
plt.savefig("venn.png", dpi=300, bbox_inches="tight")""")
    doc.p("With `matplotlib-venn`, region labels are changed through `venn3(...).get_label_by_id('111').set_text('Abhijatri')` (ids are binary strings: '100' set A only, '110' A and B, '111' all three).")
    doc.h2("5.7 Make it readable and accessible")
    doc.bullets([
        "Use a colour-blind-safe palette. These figures use blue (#0072B2), green (#009E73) and orange (#E69F00) from the Okabe-Ito set.",
        "Never rely on colour alone: every region carries a text label.",
        "Keep text at 8 pt or larger after the figure is scaled to the page width.",
        "Keep the title short and say what the diagram shows. Put caveats in a one-line note under the title, as these figures do.",
        "Number the figure, caption it, and mention it in the text.",
        "Test the diagram in black and white: it should still make sense.",
    ])
    doc.h2("5.8 Checklist before you submit")
    doc.table(
        ["Done", "Check"],
        [["[  ]", c] for c in [
            "Every set has a clear noun-phrase name",
            "Every region has a short, true label (or is stated to be empty)",
            "Prototype and planned items are marked",
            "Colours are distinguishable and not the only signal",
            "Text is readable at A4 width",
            "The figure has a number, a caption and is referred to in the text",
            "The editable source file is saved next to the image",
            "No unsupported numbers or competitor claims",
        ]],
        [1.4, 15.1],
    )
    doc.save(OUT)
    print("saved", OUT)


if __name__ == "__main__":
    main()
