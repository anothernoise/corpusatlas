"""Convert a built graph.json to Turtle, for SPARQL over a corpusatlas
graph. Unlike GraphML/CSV/neo4j — which just reformat the same lean column
set — this one is a real modelling decision, previously set aside for that
reason (see README's "Other formats"); it's here now because the tradeoffs
below are a defensible, worked-out answer, not a shortcut.

**Resources.** Every node becomes an IRI under `--base` (default a
corpusatlas.dev placeholder — this project doesn't host real per-graph
resource URIs, so pick your own `--base` for anything meant to be
dereferenced). A graph.json id like `entity:apache-spark` keeps its
structure but not its colon, which has its own meaning in Turtle's prefixed
names; `_local()` below is the one place that mapping happens.

**Types and relations.** `rdf:type` for a node's ontology type, and the
relation name itself as the predicate for a plain edge (`ca:IMPLEMENTS`,
not some generic "relatedTo") — the ontology already is the vocabulary,
so a second one isn't invented here. All under one `ca:` namespace,
because this format doesn't know an artifact's ontology beyond what's in
`entity_types`/`relation_groups`, and minting a distinct namespace per
custom ontology is exactly the kind of decision this file exists to avoid
making unasked.

**Provenance, confidence, scope.** The one genuine fork in the road.
Turtle's plain triples can't carry metadata about themselves, so every edge
is written twice: once as the bare `<src> ca:REL <dst> .` triple a simple
SPARQL query expects, and — only when there's metadata to carry — again as
a standard `rdf:Statement` reification naming the same subject/predicate/
object plus `ca:confidence`, `ca:explanation`, `ca:scope`, `ca:tier` and
`ca:claimedBy`. Considered and rejected: RDF-star (not yet universally
supported by SPARQL engines this might be loaded into) and singleton
properties (a distinct predicate IRI per edge — technically clean, but it
means a query for "everything IMPLEMENTS-related" has to know to look for a
family of predicates instead of one). Reification is the more verbose
choice and the more compatible one.
"""
from __future__ import annotations

import re
from pathlib import Path

DEFAULT_BASE = "https://corpusatlas.dev/resource/"
CA = "https://corpusatlas.dev/ns#"

_UNSAFE = re.compile(r"[^A-Za-z0-9._~-]")


def _local(node_id: str) -> str:
    """A graph.json id as a safe IRI path segment — ':' is replaced (it has
    structural meaning in Turtle's own prefixed-name syntax), and anything
    else outside IRI-unreserved characters is percent-encoded."""
    safe = node_id.replace(":", "_")
    return _UNSAFE.sub(lambda m: f"%{ord(m.group()):02X}", safe)


def _lit(value: object) -> str:
    s = str(value)
    s = s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    return f'"{s}"'


def _block(subject: str, pairs: list[tuple[str, str]]) -> list[str]:
    """subject pred1 obj1 ;\n    pred2 obj2 .  — one Turtle statement block."""
    lines = []
    for i, (pred, obj) in enumerate(pairs):
        sep = ";" if i < len(pairs) - 1 else "."
        prefix = f"{subject} " if i == 0 else "    "
        lines.append(f"{prefix}{pred} {obj} {sep}")
    return lines


def write_turtle(path: Path, graph: dict, *, base: str = DEFAULT_BASE) -> None:
    lines = [
        f"@prefix ca: <{CA}> .",
        "@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        f"@base <{base}> .",
        "",
    ]

    for n in graph["nodes"]:
        subj = f"<{_local(n['id'])}>"
        pairs: list[tuple[str, str]] = [("a", f"ca:{n['type']}"), ("rdfs:label", _lit(n["label"]))]
        if n.get("degree"):
            pairs.append(("ca:degree", str(n["degree"])))
        if n.get("url"):
            pairs.append(("ca:url", _lit(n["url"])))
        lines.extend(_block(subj, pairs))
        lines.append("")

    for i, e in enumerate(sorted(graph["edges"],
                                 key=lambda e: (e["src"], e["rel"], e["dst"], e.get("scope") or ""))):
        s, o = f"<{_local(e['src'])}>", f"<{_local(e['dst'])}>"
        p = f"ca:{e['rel']}"
        lines.append(f"{s} {p} {o} .")

        prov = e.get("prov") or {}
        meta: list[tuple[str, str]] = []
        if e.get("confidence") is not None:
            meta.append(("ca:confidence", repr(float(e["confidence"]))))
        if e.get("explanation"):
            meta.append(("ca:explanation", _lit(e["explanation"])))
        if e.get("scope"):
            meta.append(("ca:scope", _lit(e["scope"])))
        if prov.get("tier"):
            meta.append(("ca:tier", _lit(prov["tier"])))
        if prov.get("doc"):
            meta.append(("ca:claimedBy", _lit(prov["doc"])))
        if meta:
            stmt = f"_:stmt{i}"
            full = [("a", "rdf:Statement"), ("rdf:subject", s),
                    ("rdf:predicate", p), ("rdf:object", o), *meta]
            lines.extend(_block(stmt, full))
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
