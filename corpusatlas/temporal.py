"""Bi-temporal knowledge graph processing and timeline snapshot engine.

Enables point-in-time snapshot queries and temporal progression tracking
based on valid time (valid_from, valid_to) and transaction time (created_at).
Zero external dependencies.
"""
from __future__ import annotations

from typing import Any


def is_valid_at(item: dict[str, Any], as_of: str) -> bool:
    """Determine if a node or edge was valid at a given date string (ISO format)."""
    valid_from = item.get("valid_from") or item.get("date")
    valid_to = item.get("valid_to")

    if valid_from and as_of < str(valid_from):
        return False
    if valid_to and as_of > str(valid_to):
        return False
    return True


def filter_as_of(graph_data: dict[str, Any], as_of_date: str) -> dict[str, Any]:
    """Return a point-in-time sub-graph valid as of as_of_date."""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    valid_nodes = [n for n in nodes if is_valid_at(n, as_of_date)]
    valid_node_ids = {n["id"] for n in valid_nodes}

    valid_edges = [
        e for e in edges
        if is_valid_at(e, as_of_date)
        and e["src"] in valid_node_ids
        and e["dst"] in valid_node_ids
    ]

    updated = dict(graph_data)
    updated["as_of"] = as_of_date
    updated["nodes"] = valid_nodes
    updated["edges"] = valid_edges
    updated["counts"] = {
        "nodes": len(valid_nodes),
        "edges": len(valid_edges),
    }
    return updated


def extract_timeline(graph_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract chronological sequence of dates and graph evolution milestones."""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    dates = set()
    for item in nodes + edges:
        for k in ("valid_from", "valid_to", "date", "created_at"):
            val = item.get(k)
            if val and isinstance(val, str):
                dates.add(val)

    sorted_dates = sorted(dates)
    timeline: list[dict[str, Any]] = []

    for d in sorted_dates:
        active_nodes = sum(1 for n in nodes if is_valid_at(n, d))
        active_edges = sum(1 for e in edges if is_valid_at(e, d))
        timeline.append({
            "date": d,
            "active_nodes": active_nodes,
            "active_edges": active_edges,
        })

    return timeline
