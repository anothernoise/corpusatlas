"""Serialise the graph to the static artifact the browser loads."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import cast

from . import __version__
from .ontology import DEFAULT, Ontology

# The artifact's own shape, independent of the package version that wrote
# it — `generator` says which corpusatlas built this file, but a consumer
# that wants to know whether it understands the *fields* (not the code that
# produced them) needs something that only changes when the shape does.
# Bump this when a field's meaning or presence changes in a way a consumer
# would need to branch on; a purely additive field (like `context_types` in
# 0.5.0) does not require a bump, since old readers already ignore keys they
# don't recognise.
SCHEMA_VERSION = 1


def write_graph(path: Path, nodes: dict, edges: list, *, sources: list[str],
                ontology: Ontology = DEFAULT, layout: bool = False,
                entity_colors: dict[str, str] | None = None) -> dict:
    degree: dict[str, int] = {}
    for e in edges:
        degree[e.src] = degree.get(e.src, 0) + 1
        degree[e.dst] = degree.get(e.dst, 0) + 1

    present = {e.rel for e in edges}
    node_dicts = [dict(n.to_json(), degree=degree.get(n.id, 0))
                  for n in sorted(nodes.values(), key=lambda n: n.id)]
    edge_dicts = [e.to_json() for e in sorted(edges, key=lambda e: e.key)]

    if layout:
        from .layout import compute_layout
        compute_layout(node_dicts, edge_dicts)

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated": date.today().isoformat(),
        "generator": f"corpusatlas {__version__}",
        "sources": sources,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
        "entity_types": sorted(ontology.entity_types),
        "context_types": sorted(ontology.context_types),
        "inverse_labels": ontology.inverse_label,
        "relation_groups": {g: [r for r in rels if r in present]
                            for g, rels in ontology.relation_groups.items()
                            if any(r in present for r in rels)},
        "context_relations": [r for r in ontology.context_relations if r in present],
        "nodes": node_dicts,
        "edges": edge_dicts,
    }
    if entity_colors:
        payload["entity_colors"] = entity_colors
    path.parent.mkdir(parents=True, exist_ok=True)
    # Deterministic output: a rebuild with no content change must produce a
    # byte-identical file, or every CI run creates a pointless commit.
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=False) + "\n",
                    encoding="utf-8")
    return cast(dict, payload["counts"])

