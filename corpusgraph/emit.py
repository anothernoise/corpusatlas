"""Serialise the graph to the static artifact the browser loads."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def write_graph(path: Path, nodes: dict, edges: list, *, sources: list[str]) -> dict:
    degree: dict[str, int] = {}
    for e in edges:
        degree[e.src] = degree.get(e.src, 0) + 1
        degree[e.dst] = degree.get(e.dst, 0) + 1

    payload = {
        "generated": date.today().isoformat(),
        "generator": "corpusgraph 0.1.0",
        "sources": sources,
        "counts": {"nodes": len(nodes), "edges": len(edges)},
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
