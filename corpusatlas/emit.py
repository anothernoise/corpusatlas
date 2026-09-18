"""Serialise the graph to the static artifact the browser loads."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import __version__
from .ontology import CONTEXT_RELATIONS, ENTITY_TYPES, INVERSE_LABEL, RELATION_GROUPS


def write_graph(path: Path, nodes: dict, edges: list, *, sources: list[str]) -> dict:
    degree: dict[str, int] = {}
    for e in edges:
        degree[e.src] = degree.get(e.src, 0) + 1
        degree[e.dst] = degree.get(e.dst, 0) + 1

    present = {e.rel for e in edges}
    payload = {
        "generated": date.today().isoformat(),
        "generator": f"corpusatlas {__version__}",
        "sources": sources,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
        # What a renderer needs to draw this graph without hard-coding the
        # ontology: which node types are entities (drawn) as opposed to
        # context (linked from a card), how to label a relation read from
        # its target end, and the canvas filter groups — only those with
        # something in them, so a reader never sees a filter for a relation
        # this graph does not contain.
        "entity_types": sorted(ENTITY_TYPES),
        "inverse_labels": INVERSE_LABEL,
        "relation_groups": {g: [r for r in rels if r in present]
                            for g, rels in RELATION_GROUPS.items()
                            if any(r in present for r in rels)},
        "context_relations": [r for r in CONTEXT_RELATIONS if r in present],
        "nodes": [dict(n.to_json(), degree=degree.get(n.id, 0))
                  for n in sorted(nodes.values(), key=lambda n: n.id)],
        "edges": [e.to_json() for e in sorted(edges, key=lambda e: e.key)],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    # Deterministic output: a rebuild with no content change must produce a
    # byte-identical file, or every CI run creates a pointless commit.
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=False) + "\n",
                    encoding="utf-8")
    return payload["counts"]
