"""Small drawing library for the Abhijatri documents (Gane-Sarson DFD, state, sequence, ERD, Venn).

One data structure per diagram; the same data feeds the picture, the rule checker and the Word tables,
so a diagram and its data dictionary cannot disagree. Run `python make_diagrams.py` to rebuild everything.
Colours are the Okabe-Ito colour-blind-safe palette; meaning never depends on colour alone (shape and text
also differ).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, Ellipse, FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle  # noqa: E402

INK = "#1b1b1b"
GREY = "#6b6b6b"
PAL = {
    "entity_fill": "#FFF1D6",   # orange tint
    "entity_edge": "#D55E00",
    "process_fill": "#DCEBF7",  # blue tint
    "process_edge": "#0072B2",
    "store_fill": "#E3F3EA",    # green tint
    "store_edge": "#009E73",
    "proto_fill": "#F2F2F2",
    "flow": "#333333",
    "accent": "#CC79A7",
    "yellow": "#F0E442",
    "sky": "#56B4E9",
    "vermillion": "#D55E00",
    "green": "#009E73",
    "blue": "#0072B2",
    "orange": "#E69F00",
}
plt.rcParams["font.family"] = ["Segoe UI", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


# --------------------------------------------------------------------------------------- DFD model


@dataclass
class Node:
    id: str
    kind: str  # entity | process | store
    label: str
    x: float
    y: float
    w: float = 0.0
    h: float = 0.0
    proto: bool = False  # prototype / not available: drawn dashed and grey
    tag: str = ""        # text shown instead of the id (a duplicate data store shows the same D-number twice)
    dup: bool = False    # duplicate store marker (extra bar), Gane-Sarson convention


@dataclass
class Flow:
    src: str
    dst: str
    label: str
    data: str = ""        # what the flow carries, for the data dictionary
    rad: float = 0.0      # curvature of the arrow
    t: float = 0.5        # label position along the arrow (0..1)
    dx: float = 0.0       # label nudge
    dy: float = 0.0
    both: bool = False    # read and write of a store drawn as one double-headed arrow
    off: float = 0.0      # shift sideways (drawn as parallel lines when a pair of opposite flows share two nodes)
    wrap: int = 24        # label wrap width in characters


@dataclass
class DFD:
    key: str
    title: str
    level: str  # context | 0 | 1 | 2
    nodes: list[Node]
    flows: list[Flow]
    size: tuple[float, float] = (13.0, 9.0)  # inches; 1 data unit = 0.1 inch
    parent: str | None = None      # key of the parent diagram
    parent_process: str | None = None  # process id that this diagram decomposes
    note: str = ""
    yshift: float = 0.0  # added to every node's y (lets layouts be written bottom-up without clipping)
    note_bottom: bool = False  # draw the note at the bottom-left instead of under the title
    legend: tuple[float, float] | None = None  # legend origin in data units; default bottom right
    _by_id: dict[str, Node] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        defaults = {"entity": (15.0, 5.6), "process": (19.0, 9.0), "store": (19.0, 4.6)}
        for n in self.nodes:
            dw, dh = defaults[n.kind]
            n.w = n.w or dw
            n.h = n.h or dh
            n.y += self.yshift
        self._by_id = {n.id: n for n in self.nodes}

    def node(self, node_id: str) -> Node:
        return self._by_id[node_id]


def check_dfd(d: DFD, *, external_ok: set[str] | None = None) -> list[str]:
    """Return rule violations (an empty list means the diagram obeys the Gane-Sarson rules)."""
    problems: list[str] = []
    ids = {n.id for n in d.nodes}
    inbound: dict[str, int] = {n.id: 0 for n in d.nodes}
    outbound: dict[str, int] = {n.id: 0 for n in d.nodes}
    for f in d.flows:
        if f.src not in ids or f.dst not in ids:
            problems.append(f"{d.key}: flow '{f.label}' has an unknown end ({f.src} -> {f.dst})")
            continue
        a, b = d.node(f.src).kind, d.node(f.dst).kind
        if not f.label.strip():
            problems.append(f"{d.key}: unnamed flow {f.src} -> {f.dst}")
        if "process" not in (a, b):
            problems.append(f"{d.key}: flow '{f.label}' joins two non-processes ({a} -> {b}); every flow needs a process")
        outbound[f.src] += 1
        inbound[f.dst] += 1
        if f.both:
            outbound[f.dst] += 1
            inbound[f.src] += 1
    for n in d.nodes:
        if n.kind == "process" and (inbound[n.id] == 0 or outbound[n.id] == 0):
            problems.append(f"{d.key}: process {n.id} has no {'input' if inbound[n.id] == 0 else 'output'} (black hole or miracle)")
        if n.kind in ("entity", "store") and inbound[n.id] + outbound[n.id] == 0:
            problems.append(f"{d.key}: {n.kind} {n.id} is not connected")
    return problems


def canon(node_id: str) -> str:
    """A duplicate store (D4b) is the same store as D4."""
    return node_id[:-1] if node_id.endswith('b') and node_id[:-1].startswith('D') and node_id[:-1][1:].isdigit() else node_id


def external_signature(d: DFD) -> set[tuple[str, str]]:
    """(outside node id, 'in'|'out') pairs seen from the diagram's own processes, for balancing checks."""
    own = {n.id for n in d.nodes if n.kind == "process"}
    sig: set[tuple[str, str]] = set()
    for f in d.flows:
        if f.src in own and f.dst not in own:
            sig.add((f.dst, "out"))
            if f.both:
                sig.add((f.dst, "in"))
        if f.dst in own and f.src not in own:
            sig.add((f.src, "in"))
            if f.both:
                sig.add((f.src, "out"))
    return sig


# --------------------------------------------------------------------------------------- DFD drawing


def _edge_point(n: Node, tx: float, ty: float, gap: float = 0.25) -> tuple[float, float]:
    dx, dy = tx - n.x, ty - n.y
    if dx == 0 and dy == 0:
        return n.x, n.y
    hw, hh = n.w / 2 + gap, n.h / 2 + gap
    scale = min(hw / abs(dx) if dx else math.inf, hh / abs(dy) if dy else math.inf)
    return n.x + dx * scale, n.y + dy * scale


def _exit_point(n: Node, p: tuple[float, float], d: tuple[float, float], gap: float = 0.25) -> tuple[float, float]:
    """Where a ray from p (inside node n) travelling along d leaves the node's rectangle (plus a small gap)."""
    hw, hh = n.w / 2, n.h / 2
    best = math.inf
    if d[0] > 1e-9:
        best = min(best, (n.x + hw - p[0]) / d[0])
    elif d[0] < -1e-9:
        best = min(best, (n.x - hw - p[0]) / d[0])
    if d[1] > 1e-9:
        best = min(best, (n.y + hh - p[1]) / d[1])
    elif d[1] < -1e-9:
        best = min(best, (n.y - hh - p[1]) / d[1])
    if best is math.inf or best < 0:
        best = 0.0
    return p[0] + d[0] * best, p[1] + d[1] * best


def _flow_ends(a: Node, b: Node, off: float, gap: float = 0.25):
    dx, dy = b.x - a.x, b.y - a.y
    ln = math.hypot(dx, dy) or 1.0
    ux, uy = dx / ln, dy / ln
    nx, ny = -uy, ux
    pa = (a.x + nx * off, a.y + ny * off)
    pb = (b.x + nx * off, b.y + ny * off)
    p1 = _exit_point(a, pa, (ux, uy))
    p2 = _exit_point(b, pb, (-ux, -uy))
    return (p1[0] + ux * gap, p1[1] + uy * gap), (p2[0] - ux * gap, p2[1] - uy * gap)


def _bezier_mid(p1, p2, rad):
    (x1, y1), (x2, y2) = p1, p2
    mx, my = (x1 + x2) / 2, (y1 + y2) / 2
    dx, dy = x2 - x1, y2 - y1
    cx, cy = mx + rad * dy, my - rad * dx
    return cx, cy


def _bezier_point(p1, p2, rad, t):
    cx, cy = _bezier_mid(p1, p2, rad)
    x = (1 - t) ** 2 * p1[0] + 2 * (1 - t) * t * cx + t**2 * p2[0]
    y = (1 - t) ** 2 * p1[1] + 2 * (1 - t) * t * cy + t**2 * p2[1]
    return x, y


def _wrap(text: str, width: int) -> str:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + (1 if cur else 0) > width:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return "\n".join(lines)


def draw_dfd(d: DFD, path: str, *, dpi: int = 200) -> None:
    fw, fh = d.size
    fig = plt.figure(figsize=(fw, fh))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, fw * 10)
    ax.set_ylim(0, fh * 10)
    ax.set_aspect("equal")
    ax.axis("off")

    ax.text(2, fh * 10 - 2.5, d.title, fontsize=14, fontweight="bold", color=INK, va="top")
    if d.note:
        if d.note_bottom:
            ax.text(2, 3.0, d.note, fontsize=8.5, color=GREY, va="bottom")
        else:
            ax.text(2, fh * 10 - 6.2, d.note, fontsize=8.5, color=GREY, va="top")

    # nodes
    for n in d.nodes:
        dashed = "--" if n.proto else "-"
        if n.kind == "entity":
            ax.add_patch(Rectangle((n.x - n.w / 2, n.y - n.h / 2), n.w, n.h, fc="#F2F2F2" if n.proto else PAL["entity_fill"],
                                   ec=PAL["entity_edge"], lw=1.8, ls=dashed, zorder=3))
            ax.add_patch(Rectangle((n.x - n.w / 2 + 0.5, n.y - n.h / 2 + 0.5), n.w - 1.0, n.h - 1.0, fc="none",
                                   ec=PAL["entity_edge"], lw=0.7, ls=dashed, zorder=3))
            ax.text(n.x, n.y, _wrap(n.label, 20), ha="center", va="center", fontsize=9.5, fontweight="bold", color=INK, zorder=4)
        elif n.kind == "process":
            ax.add_patch(FancyBboxPatch((n.x - n.w / 2, n.y - n.h / 2), n.w, n.h, boxstyle="round,pad=0,rounding_size=1.4",
                                        fc=PAL["proto_fill"] if n.proto else PAL["process_fill"], ec=PAL["process_edge"], lw=1.8,
                                        ls=dashed, zorder=3))
            ax.plot([n.x - n.w / 2, n.x + n.w / 2], [n.y + n.h / 2 - 2.3, n.y + n.h / 2 - 2.3], color=PAL["process_edge"], lw=1.0,
                    ls=dashed, zorder=4)
            ax.text(n.x, n.y + n.h / 2 - 1.15, n.id, ha="center", va="center", fontsize=9, fontweight="bold", color=PAL["process_edge"], zorder=5)
            ax.text(n.x, n.y - 1.1, _wrap(n.label, 22), ha="center", va="center", fontsize=9.5, fontweight="bold", color=INK, zorder=5)
        else:  # store: open-ended rectangle with an id box
            x0, x1, y0, y1 = n.x - n.w / 2, n.x + n.w / 2, n.y - n.h / 2, n.y + n.h / 2
            ax.add_patch(Rectangle((x0, y0), n.w, n.h, fc=PAL["proto_fill"] if n.proto else PAL["store_fill"], ec="none", zorder=2))
            ax.plot([x0, x1], [y1, y1], color=PAL["store_edge"], lw=1.8, ls=dashed, zorder=3)
            ax.plot([x0, x1], [y0, y0], color=PAL["store_edge"], lw=1.8, ls=dashed, zorder=3)
            ax.plot([x0, x0], [y0, y1], color=PAL["store_edge"], lw=1.8, ls=dashed, zorder=3)
            ax.plot([x0 + 4.2, x0 + 4.2], [y0, y1], color=PAL["store_edge"], lw=1.0, zorder=3)
            ax.text(x0 + 2.1, n.y, n.tag or n.id, ha="center", va="center", fontsize=9, fontweight="bold", color=PAL["store_edge"], zorder=5)
            if n.dup:  # duplicate marker: a second bar on the right end
                ax.plot([x1 - 1.2, x1 - 1.2], [y0, y1], color=PAL["store_edge"], lw=1.0, zorder=3)
            ax.text(x0 + 5.0 + (n.w - 5.0) / 2 - 0.4, n.y, _wrap(n.label, 24), ha="center", va="center", fontsize=8.8, color=INK, zorder=5)

    # an entity with many flows is a hub: labels go near the process end, where arrows are well separated
    degree: dict[str, int] = {}
    for f in d.flows:
        degree[f.src] = degree.get(f.src, 0) + 1
        degree[f.dst] = degree.get(f.dst, 0) + 1

    def is_hub(node_id: str) -> bool:
        return d.node(node_id).kind == "entity" and degree.get(node_id, 0) >= 5

    # a pair of opposite flows between the same two nodes is drawn as two parallel arrows
    pairs = {(f.src, f.dst) for f in d.flows if not f.both}

    # flows
    for f in d.flows:
        a, b = d.node(f.src), d.node(f.dst)
        off = f.off
        if off == 0.0 and not f.both and f.rad == 0.0 and (f.dst, f.src) in pairs:
            off = 2.2
        p1, p2 = _flow_ends(a, b, off)
        style = "<|-|>" if f.both else "-|>"
        ax.add_patch(FancyArrowPatch(p1, p2, connectionstyle=f"arc3,rad={f.rad}", arrowstyle=style, mutation_scale=11, lw=1.25,
                                     color=PAL["flow"], zorder=1, shrinkA=0, shrinkB=0))
        t_label = f.t
        if is_hub(f.src) and not is_hub(f.dst):
            t_label = 0.74
        elif is_hub(f.dst) and not is_hub(f.src):
            t_label = 0.26
        lx, ly = _bezier_point(p1, p2, f.rad, t_label)
        ax.text(lx + f.dx, ly + f.dy, _wrap(f.label, f.wrap), ha="center", va="center", fontsize=7.6, color=INK, zorder=6,
                bbox=dict(boxstyle="round,pad=0.16", fc="white", ec="none", alpha=0.92))

    # legend
    lx, ly = d.legend if d.legend else (fw * 10 - 52, 6.5)
    ax.add_patch(Rectangle((lx, ly - 1.1), 3.6, 2.2, fc=PAL["entity_fill"], ec=PAL["entity_edge"], lw=1.3))
    ax.text(lx + 4.6, ly, "External entity", fontsize=7.5, va="center")
    ax.add_patch(FancyBboxPatch((lx + 20, ly - 1.1), 3.6, 2.2, boxstyle="round,pad=0,rounding_size=0.6", fc=PAL["process_fill"], ec=PAL["process_edge"], lw=1.3))
    ax.text(lx + 24.6, ly, "Process", fontsize=7.5, va="center")
    ax.plot([lx + 34, lx + 34], [ly - 1.1, ly + 1.1], color=PAL["store_edge"], lw=1.3)
    ax.plot([lx + 34, lx + 37.6], [ly + 1.1, ly + 1.1], color=PAL["store_edge"], lw=1.3)
    ax.plot([lx + 34, lx + 37.6], [ly - 1.1, ly - 1.1], color=PAL["store_edge"], lw=1.3)
    ax.text(lx + 38.6, ly, "Data store", fontsize=7.5, va="center")
    ax.plot([lx, lx + 3.6], [ly - 3.0, ly - 3.0], color=GREY, lw=1.3, ls="--")
    ax.text(lx + 4.6, ly - 3.0, "Dashed = prototype / not available", fontsize=7.5, va="center")

    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------------------- state diagram


def draw_states(path: str, title: str, states: dict[str, tuple[float, float, str]], edges: list[tuple], size=(13.0, 7.2), dpi=200, dashed: set[str] | None = None, note: str = ""):
    """states: id -> (x, y, fill colour); edges: (src, dst, label, rad, t, dx, dy)."""
    fw, fh = size
    fig = plt.figure(figsize=size)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, fw * 10)
    ax.set_ylim(0, fh * 10)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.text(2, fh * 10 - 2.5, title, fontsize=14, fontweight="bold", va="top")
    W, H = 19.0, 6.4
    pos = {k: (v[0], v[1]) for k, v in states.items()}
    pos["__start"] = (6.0, states["PENDING"][1] if "PENDING" in states else fh * 5)
    ax.add_patch(Circle(pos["__start"], 1.1, fc=INK, ec=INK, zorder=4))
    for k, (x, y, col) in states.items():
        ax.add_patch(FancyBboxPatch((x - W / 2, y - H / 2), W, H, boxstyle="round,pad=0,rounding_size=1.8", fc=col, ec=INK, lw=1.5,
                                    ls="--" if dashed and k in dashed else "-", zorder=3))
        ax.text(x, y, k.replace("_", "\n") if len(k) > 14 else k, ha="center", va="center", fontsize=9.5, fontweight="bold", zorder=4)

    def edge_pt(k, tx, ty, gap=0.3):
        x, y = pos[k]
        if k == "__start":
            ang = math.atan2(ty - y, tx - x)
            return x + math.cos(ang) * (1.1 + gap), y + math.sin(ang) * (1.1 + gap)
        dx, dy = tx - x, ty - y
        sc = min((W / 2 + gap) / abs(dx) if dx else math.inf, (H / 2 + gap) / abs(dy) if dy else math.inf)
        return x + dx * sc, y + dy * sc

    for e in edges:
        s, t_, label = e[0], e[1], e[2]
        rad = e[3] if len(e) > 3 else 0.0
        tt = e[4] if len(e) > 4 else 0.5
        dx = e[5] if len(e) > 5 else 0.0
        dy = e[6] if len(e) > 6 else 0.0
        p1, p2 = edge_pt(s, *pos[t_]), edge_pt(t_, *pos[s])
        ax.add_patch(FancyArrowPatch(p1, p2, connectionstyle=f"arc3,rad={rad}", arrowstyle="-|>", mutation_scale=12, lw=1.3, color=PAL["flow"], zorder=2))
        if label:
            lx, ly = _bezier_point(p1, p2, rad, tt)
            ax.text(lx + dx, ly + dy, _wrap(label, 24), ha="center", va="center", fontsize=7.8, zorder=6, bbox=dict(boxstyle="round,pad=0.16", fc="white", ec="none", alpha=0.92))
    if note:
        ax.text(2, 2.0, _wrap(note, 150), fontsize=8.2, color=GREY, va="bottom")
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------------------- sequence diagram


def draw_sequence(path: str, title: str, actors: list[str], messages: list[tuple], size=(13.0, 8.5), dpi=200, notes: dict[int, str] | None = None):
    """messages: (from_index, to_index, text, kind) with kind 'call' | 'return' | 'self'."""
    fw, fh = size
    fig = plt.figure(figsize=size)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, fw * 10)
    ax.set_ylim(0, fh * 10)
    ax.axis("off")
    ax.text(2, fh * 10 - 2.5, title, fontsize=14, fontweight="bold", va="top")
    n = len(actors)
    left, right = 14.0, fw * 10 - 14.0
    xs = [left + i * (right - left) / (n - 1) for i in range(n)]
    top = fh * 10 - 12
    bottom = 4.0
    for x, name in zip(xs, actors):
        ax.add_patch(FancyBboxPatch((x - 9, top - 3.2), 18, 6.4, boxstyle="round,pad=0,rounding_size=1.2", fc=PAL["process_fill"], ec=PAL["process_edge"], lw=1.5, zorder=3))
        ax.text(x, top, _wrap(name, 16), ha="center", va="center", fontsize=8.6, fontweight="bold", zorder=4)
        ax.plot([x, x], [top - 3.2, bottom], color=GREY, lw=1.0, ls=(0, (4, 3)), zorder=1)
    step = (top - 3.2 - bottom - 4) / (len(messages) + 0.5)
    y = top - 3.2 - 4.0
    for i, m in enumerate(messages):
        a, b, text = m[0], m[1], m[2]
        kind = m[3] if len(m) > 3 else "call"
        if kind == "self":
            ax.add_patch(FancyArrowPatch((xs[a], y), (xs[a], y - step * 0.55), connectionstyle="arc3,rad=-1.6", arrowstyle="-|>", mutation_scale=11, lw=1.2, color=PAL["flow"], zorder=2))
            ax.text(xs[a] + 4.8, y - step * 0.27, _wrap(text, 60), ha="left", va="center", fontsize=7.6, zorder=6, bbox=dict(boxstyle="round,pad=0.14", fc="white", ec="none", alpha=0.9))
        else:
            ax.add_patch(FancyArrowPatch((xs[a], y), (xs[b], y), arrowstyle="-|>", mutation_scale=11, lw=1.2, color=PAL["flow"], ls="--" if kind == "return" else "-", zorder=2))
            ax.text((xs[a] + xs[b]) / 2, y + 1.35, _wrap(text, 70), ha="center", va="bottom", fontsize=7.6, zorder=6, bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.9))
        ax.text(xs[0] - 12.0, y, str(i + 1), fontsize=7.5, color=GREY, va="center", ha="center")
        y -= step
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------------------- ERD


def draw_erd(path: str, title: str, entities: dict[str, tuple[float, float, list[str], str]], rels: list[tuple], size=(13.0, 9.0), dpi=200, note: str = ""):
    """entities: name -> (x, y, [field lines], colour); rels: (a, b, label, card_a, card_b, rad)."""
    fw, fh = size
    fig = plt.figure(figsize=size)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, fw * 10)
    ax.set_ylim(0, fh * 10)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.text(2, fh * 10 - 2.5, title, fontsize=14, fontweight="bold", va="top")
    W = 22.0
    boxes: dict[str, tuple[float, float, float, float]] = {}
    for name, (x, y, fields, col) in entities.items():
        h = 5.8 + 2.05 * len(fields)
        boxes[name] = (x, y, W, h)
        ax.add_patch(Rectangle((x - W / 2, y - h / 2), W, h, fc="white", ec=INK, lw=1.4, zorder=3))
        ax.add_patch(Rectangle((x - W / 2, y + h / 2 - 3.2), W, 3.2, fc=col, ec=INK, lw=1.4, zorder=4))
        ax.text(x, y + h / 2 - 1.6, name, ha="center", va="center", fontsize=8.8, fontweight="bold", zorder=5)
        for i, line in enumerate(fields):
            ax.text(x - W / 2 + 1.0, y + h / 2 - 5.4 - 2.05 * i, line, ha="left", va="center", fontsize=7.4, zorder=5, color=INK)

    def pt(name, tx, ty):
        x, y, w, h = boxes[name]
        dx, dy = tx - x, ty - y
        sc = min((w / 2) / abs(dx) if dx else math.inf, (h / 2) / abs(dy) if dy else math.inf)
        return x + dx * sc, y + dy * sc

    for a, b, label, ca, cb, rad in rels:
        xa, ya = boxes[a][:2]
        xb, yb = boxes[b][:2]
        p1, p2 = pt(a, xb, yb), pt(b, xa, ya)
        ax.add_patch(FancyArrowPatch(p1, p2, connectionstyle=f"arc3,rad={rad}", arrowstyle="-", lw=1.2, color=PAL["flow"], zorder=2))
        lx, ly = _bezier_point(p1, p2, rad, 0.5)
        ax.text(lx, ly, label, fontsize=7.2, ha="center", va="center", color=GREY, zorder=6, bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.9))
        for (cx, cy), card, other in ((p1, ca, p2), (p2, cb, p1)):
            ox, oy = _bezier_point(p1, p2, rad, 0.12 if cx == p1[0] and cy == p1[1] else 0.88)
            ax.text(ox, oy, card, fontsize=8, fontweight="bold", ha="center", va="center", zorder=6, bbox=dict(boxstyle="round,pad=0.08", fc="white", ec="none", alpha=0.9))
    if note:
        ax.text(2, 1.0, _wrap(note, 170), fontsize=8.2, color=GREY, va="bottom")
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)


# --------------------------------------------------------------------------------------- Venn


def draw_venn(path: str, title: str, circles: list[dict], center_label: str, texts: list[tuple], size=(11.0, 9.0), dpi=200, subtitle: str = ""):
    """circles: dicts with x, y, r, colour, name, name_xy; texts: (x, y, text, size, weight)."""
    fw, fh = size
    fig = plt.figure(figsize=size)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, fw * 10)
    ax.set_ylim(0, fh * 10)
    ax.set_aspect("equal")
    ax.axis("off")
    ax.text(2, fh * 10 - 2.5, title, fontsize=14, fontweight="bold", va="top")
    if subtitle:
        ax.text(2, fh * 10 - 7.0, subtitle, fontsize=8.5, color=GREY, va="top")
    for c in circles:
        ax.add_patch(Circle((c["x"], c["y"]), c["r"], fc=c["colour"], alpha=0.30, ec=c["colour"], lw=2.2, zorder=2))
        nx, ny = c["name_xy"]
        ax.text(nx, ny, c["name"], ha="center", va="center", fontsize=11, fontweight="bold", color=INK, zorder=6)
    for x, y, text, fs, weight in texts:
        ax.text(x, y, text, ha="center", va="center", fontsize=fs, fontweight=weight, color=INK, zorder=7, linespacing=1.25)
    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)
