"""Declarative ontology schema migration engine.

Allows evolutionary refactoring of knowledge graph artifacts without re-running
full corpus builds from scratch. Handles:
- rename_type: updates node.type across matching nodes
- rename_relation: updates edge.rel across matching edges
- split_type: re-maps node types conditionally or via fallback mapping
- drop_relation: filters obsolete relations
- drop_type: removes deprecated node types and cascades to touching edges
"""
from __future__ import annotations

import copy
import json
import tomllib
from pathlib import Path
from typing import Any


class MigrationRule:
    def __init__(self, spec: dict[str, Any]):
        self.action = spec.get("action", "")
        self.source = spec.get("from", "")
        self.target = spec.get("to", "")
        self.into = spec.get("into", [])
        self.condition = spec.get("condition", {})
        self.default = spec.get("default", "")


def apply_migration(
    graph_data: dict[str, Any],
    migrations: list[dict[str, Any]],
) -> dict[str, Any]:
    """Apply a sequence of migration rules to graph_data, returning a new graph dict."""
    g = copy.deepcopy(graph_data)
    nodes = g.get("nodes", [])
    edges = g.get("edges", [])

    for step in migrations:
        action = step.get("action")
        src = step.get("from")
        dst = step.get("to")

        if action == "rename_type" and src and dst:
            for n in nodes:
                if n.get("type") == src:
                    n["type"] = dst

        elif action == "rename_relation" and src and dst:
            for e in edges:
                if e.get("rel") == src:
                    e["rel"] = dst

        elif action == "drop_relation" and src:
            edges = [e for e in edges if e.get("rel") != src]

        elif action == "drop_type" and src:
            dropped_ids = {n["id"] for n in nodes if n.get("type") == src}
            nodes = [n for n in nodes if n.get("type") != src]
            edges = [e for e in edges if e.get("src") not in dropped_ids and e.get("dst") not in dropped_ids]

        elif action == "split_type" and src:
            # Conditional split or default
            default_target = step.get("default", src)
            mapping = step.get("mapping", {})  # {node_id: new_type}
            for n in nodes:
                if n.get("type") == src:
                    n["type"] = mapping.get(n["id"], default_target)

    # Recalculate node degrees
    degree: dict[str, int] = {}
    for e in edges:
        s, d = e.get("src"), e.get("dst")
        if s:
            degree[s] = degree.get(s, 0) + 1
        if d:
            degree[d] = degree.get(d, 0) + 1

    for n in nodes:
        n["degree"] = degree.get(n["id"], 0)

    # Prune isolated nodes if any resulted from dropped types
    connected_ids = {e["src"] for e in edges} | {e["dst"] for e in edges}
    nodes = [n for n in nodes if n["id"] in connected_ids]

    g["nodes"] = nodes
    g["edges"] = edges
    g["counts"] = {"nodes": len(nodes), "edges": len(edges)}
    return g


def load_migration_spec(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix == ".json":
        data = json.loads(text)
        return data.get("migrations", data if isinstance(data, list) else [])
    doc = tomllib.loads(text)
    return doc.get("migrate", doc.get("migration", []))
