"""Graph delta calculation and incremental view maintenance.

Zero-dependency incremental graph state comparison, incremental degree tracking,
and affected community detection to avoid global graph recomputation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple


def _edge_key(e: dict[str, Any]) -> tuple[str, str, str, str]:
    return (str(e.get("src", "")), str(e.get("rel", "")), str(e.get("dst", "")), str(e.get("scope") or ""))


def _node_signature(n: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in n.items() if k != "degree"}


@dataclass
class GraphDelta:
    added_nodes: List[Dict[str, Any]] = field(default_factory=list)
    removed_nodes: List[Dict[str, Any]] = field(default_factory=list)
    modified_nodes: List[Dict[str, Any]] = field(default_factory=list)
    added_edges: List[Dict[str, Any]] = field(default_factory=list)
    removed_edges: List[Dict[str, Any]] = field(default_factory=list)
    unchanged_nodes_count: int = 0
    unchanged_edges_count: int = 0


def compute_graph_delta(old_graph: dict[str, Any], new_graph: dict[str, Any]) -> GraphDelta:
    """Computes the difference between old_graph and new_graph."""
    old_nodes = {n["id"]: n for n in old_graph.get("nodes", [])}
    new_nodes = {n["id"]: n for n in new_graph.get("nodes", [])}

    added_node_ids = set(new_nodes) - set(old_nodes)
    removed_node_ids = set(old_nodes) - set(new_nodes)
    common_node_ids = set(old_nodes) & set(new_nodes)

    added_nodes = [new_nodes[nid] for nid in sorted(added_node_ids)]
    removed_nodes = [old_nodes[nid] for nid in sorted(removed_node_ids)]

    modified_nodes = []
    unchanged_nodes = 0
    for nid in sorted(common_node_ids):
        if _node_signature(old_nodes[nid]) != _node_signature(new_nodes[nid]):
            modified_nodes.append(new_nodes[nid])
        else:
            unchanged_nodes += 1

    old_edges = {_edge_key(e): e for e in old_graph.get("edges", [])}
    new_edges = {_edge_key(e): e for e in new_graph.get("edges", [])}

    added_edge_keys = set(new_edges) - set(old_edges)
    removed_edge_keys = set(old_edges) - set(new_edges)
    common_edge_keys = set(old_edges) & set(new_edges)

    added_edges = [new_edges[k] for k in sorted(added_edge_keys)]
    removed_edges = [old_edges[k] for k in sorted(removed_edge_keys)]

    return GraphDelta(
        added_nodes=added_nodes,
        removed_nodes=removed_nodes,
        modified_nodes=modified_nodes,
        added_edges=added_edges,
        removed_edges=removed_edges,
        unchanged_nodes_count=unchanged_nodes,
        unchanged_edges_count=len(common_edge_keys),
    )


def update_degrees_incrementally(
    nodes: list[dict[str, Any]],
    added_edges: list[dict[str, Any]],
    removed_edges: list[dict[str, Any]]
) -> None:
    """Incrementally updates node degrees in-place without recounting all edges."""
    delta_deg: dict[str, int] = {}
    for e in added_edges:
        src = e.get("src")
        dst = e.get("dst")
        if src:
            delta_deg[src] = delta_deg.get(src, 0) + 1
        if dst:
            delta_deg[dst] = delta_deg.get(dst, 0) + 1

    for e in removed_edges:
        src = e.get("src")
        dst = e.get("dst")
        if src:
            delta_deg[src] = delta_deg.get(src, 0) - 1
        if dst:
            delta_deg[dst] = delta_deg.get(dst, 0) - 1

    for n in nodes:
        nid = n.get("id")
        if nid in delta_deg:
            cur = n.get("degree", 0)
            n["degree"] = max(0, cur + delta_deg[nid])


def detect_affected_communities(
    delta: GraphDelta,
    node_to_community: dict[str, int]
) -> set[int]:
    """Identifies community cluster IDs impacted by added, removed, or modified nodes/edges."""
    affected: Set[int] = set()

    for n in delta.added_nodes + delta.removed_nodes + delta.modified_nodes:
        nid = n.get("id", "")
        if nid in node_to_community:
            affected.add(node_to_community[nid])

    for e in delta.added_edges + delta.removed_edges:
        src = e.get("src", "")
        dst = e.get("dst", "")
        if src in node_to_community:
            affected.add(node_to_community[src])
        if dst in node_to_community:
            affected.add(node_to_community[dst])

    return affected


def apply_delta_to_graph(base_graph: dict[str, Any], delta: GraphDelta) -> dict[str, Any]:
    """Applies a GraphDelta patch to a base graph to produce an updated graph."""
    nodes_by_id = {n["id"]: dict(n) for n in base_graph.get("nodes", [])}
    for n in delta.removed_nodes:
        nodes_by_id.pop(n["id"], None)
    for n in delta.added_nodes:
        nodes_by_id[n["id"]] = dict(n)
    for n in delta.modified_nodes:
        nodes_by_id[n["id"]] = dict(n)

    edges_by_key = {_edge_key(e): dict(e) for e in base_graph.get("edges", [])}
    for e in delta.removed_edges:
        edges_by_key.pop(_edge_key(e), None)
    for e in delta.added_edges:
        edges_by_key[_edge_key(e)] = dict(e)

    result = dict(base_graph)
    result["nodes"] = sorted(nodes_by_id.values(), key=lambda n: n["id"])
    result["edges"] = sorted(edges_by_key.values(), key=_edge_key)
    return result
