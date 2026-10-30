"""Rebuild every figure used by the Abhijatri Word documents.   Usage: python make_diagrams.py [key ...]

Draws each data flow diagram, checks the Gane-Sarson rules and the parent/child balance, and exits non-zero
if any rule is broken.
"""

import sys
from pathlib import Path

from diagram_lib import canon, check_dfd, draw_dfd

OUT = Path(__file__).resolve().parent


def signature_of(d, process_ids):
    """(outside node, direction) pairs seen from a set of processes of diagram d."""
    sig = set()
    for f in d.flows:
        if f.src in process_ids and f.dst not in process_ids:
            sig.add((canon(f.dst), "out"))
            if f.both:
                sig.add((canon(f.dst), "in"))
        if f.dst in process_ids and f.src not in process_ids:
            sig.add((canon(f.src), "in"))
            if f.both:
                sig.add((canon(f.src), "out"))
    return sig


def check_balance(diagrams):
    """A child's boundary flows must equal the decomposed parent process's flows (local stores excepted)."""
    by_key = {d.key: d for d in diagrams}
    problems = []
    for child in diagrams:
        if not child.parent:
            continue
        parent = by_key[child.parent]
        pid = child.parent_process
        child_own = {n.id for n in child.nodes if n.kind == "process"}
        child_sig = signature_of(child, child_own)
        if parent.level == "context":
            # level 0 against the context diagram: every outside entity and its directions must match
            ctx = signature_of(parent, {"0"})
            ent = {(canon(n.id)) for n in child.nodes if n.kind == "entity"}
            l0_sig = {(n, d) for n, d in child_sig if n in ent}
            if l0_sig != ctx:
                problems.append(f"{child.key}: not balanced with {parent.key}: child-only {sorted(l0_sig - ctx)}, parent-only {sorted(ctx - l0_sig)}")
            continue
        parent_sig = signature_of(parent, {pid})
        parent_nodes = {canon(n.id) for n in parent.nodes}
        local = {n for n, _ in child_sig if n not in parent_nodes}
        for n in local:
            kind = next(x.kind for x in child.nodes if canon(x.id) == n)
            if kind != "store":
                problems.append(f"{child.key}: {n} is not on the parent diagram but is not a store")
        child_sig = {(n, d) for n, d in child_sig if n not in local}
        if child_sig != parent_sig:
            problems.append(f"{child.key}: not balanced with {parent.key} process {pid}: child-only {sorted(child_sig - parent_sig)}, parent-only {sorted(parent_sig - child_sig)}")
    return problems


def main(only):
    import dfd_levels

    problems = []
    for d in dfd_levels.ALL:
        problems += check_dfd(d)
        if only and d.key not in only:
            continue
        draw_dfd(d, str(OUT / f"{d.key}.png"))
        print("drew", d.key)
    problems += check_balance(dfd_levels.ALL)
    for p in problems:
        print("RULE VIOLATION:", p)
    print("rule violations:", len(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
