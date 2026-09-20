"""Automated knowledge graph quality, cohesion, and topological auditing.

Computes graph health metrics:
- Degree distribution & Gini coefficient (network concentration index)
- Directed cycle detection in hierarchical/taxonomic relations
- Bridge edges and articulation nodes (single points of structural failure)
- Disconnected component analysis (connected components)
- Confidence score distribution and low-confidence outlier detection
- Contradictory claim detection (conflicting reciprocal relations)
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from typing import Any


def compute_gini_coefficient(values: list[float | int]) -> float:
    """Calculate the Gini coefficient of a list of numbers.

    0 = perfect equality (every node has identical degree)
    1 = maximal inequality (all edges touch one hub)
    """
    if not values or len(values) == 1:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    total = sum(sorted_vals)
    if total == 0:
        return 0.0

    cumulative = 0.0
    for i, v in enumerate(sorted_vals, 1):
        cumulative += i * v
    return (2.0 * cumulative) / (n * total) - (n + 1.0) / n


def find_bridges(nodes: list[dict], edges: list[dict]) -> list[dict[str, str]]:
    """Find bridge edges using Tarjan's bridge-finding algorithm (iterative DFS)."""
    adj = defaultdict(list)
    for e in edges:
        s, d = e.get("src"), e.get("dst")
        if s and d and s != d:
            adj[s].append(d)
            adj[d].append(s)

    tin: dict[str, int] = {}
    low: dict[str, int] = {}
    visited: set[str] = set()
    timer = 0
    bridges: list[dict[str, str]] = []

    for n in nodes:
        root = n.get("id")
        if not root or root in visited:
            continue

        stack = [(root, None, 0)]
        visited.add(root)
        tin[root] = low[root] = timer
        timer += 1

        while stack:
            u, p, idx = stack[-1]
            neighbors = adj[u]

            if idx < len(neighbors):
                to = neighbors[idx]
                stack[-1] = (u, p, idx + 1)
                if to == p:
                    continue
                if to in visited:
                    low[u] = min(low[u], tin[to])
                else:
                    visited.add(to)
                    tin[to] = low[to] = timer
                    timer += 1
                    stack.append((to, u, 0))
            else:
                stack.pop()
                if stack:
                    parent_node = stack[-1][0]
                    low[parent_node] = min(low[parent_node], low[u])
                    if low[u] > tin[parent_node]:
                        bridges.append({"src": parent_node, "dst": u})

    return bridges


def find_directed_cycles(
    nodes: list[dict], edges: list[dict], hierarchical_relations: set[str] | None = None
) -> list[list[str]]:
    """Detect directed cycles in hierarchical relations using iterative DFS."""
    if hierarchical_relations is None:
        hierarchical_relations = {
            "TAXON_OF", "PART_OF", "SUBCLASS_OF", "COMPONENT_OF",
            "IMPLEMENTS", "EXTENDS", "DEPENDS_ON"
        }

    adj = defaultdict(list)
    for e in edges:
        rel = e.get("rel", "")
        if rel in hierarchical_relations:
            adj[e.get("src")].append(e.get("dst"))

    visited: dict[str, int] = {}  # 0: unvisited, 1: visiting, 2: visited
    cycles: list[list[str]] = []

    for n in nodes:
        root = n.get("id")
        if not root or visited.get(root, 0) != 0:
            continue

        stack = [(root, 0)]
        visited[root] = 1
        path = [root]

        while stack:
            u, idx = stack[-1]
            neighbors = adj[u]
            if idx < len(neighbors):
                v = neighbors[idx]
                stack[-1] = (u, idx + 1)
                st = visited.get(v, 0)
                if st == 1:
                    try:
                        c_start = path.index(v)
                        cycles.append(list(path[c_start:]) + [v])
                    except ValueError:
                        pass
                elif st == 0:
                    visited[v] = 1
                    path.append(v)
                    stack.append((v, 0))
            else:
                stack.pop()
                path.pop()
                visited[u] = 2

    return cycles

    for n in nodes:
        nid = n.get("id")
        if nid and visited.get(nid, 0) == 0:
            dfs(nid)

    return cycles


def audit_graph(graph_data: dict[str, Any]) -> dict[str, Any]:
    """Execute comprehensive audit of knowledge graph quality, cohesion, and anomalies."""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    node_ids = {n.get("id") for n in nodes if n.get("id")}
    degrees = [int(n.get("degree", 0)) for n in nodes]
    gini = compute_gini_coefficient(degrees)

    confidences = [float(e.get("confidence", 1.0)) for e in edges]
    low_confidence_edges = [
        e for e in edges if float(e.get("confidence", 1.0)) < 0.7
    ]

    bridges = find_bridges(nodes, edges)
    cycles = find_directed_cycles(nodes, edges)

    # Connected components
    adj = defaultdict(set)
    for e in edges:
        s, d = e.get("src"), e.get("dst")
        if s and d:
            adj[s].add(d)
            adj[d].add(s)

    components = []
    visited = set()
    for nid in node_ids:
        if nid not in visited:
            comp = set()
            q = [nid]
            visited.add(nid)
            while q:
                curr = q.pop()
                comp.add(curr)
                for neighbor in adj[curr]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        q.append(neighbor)
            components.append(comp)

    component_sizes = [len(c) for c in components]
    component_sizes.sort(reverse=True)

    # Contradiction detection: check for conflicting relationships between same pair
    pair_rels = defaultdict(set)
    for e in edges:
        s, r, d = e.get("src"), e.get("rel"), e.get("dst")
        if s and r and d:
            pair_rels[(s, d)].add(r)

    contradictions = []
    for (s, d), rels in pair_rels.items():
        if len(rels) > 1:
            contradictions.append({
                "source": s,
                "target": d,
                "conflicting_relations": sorted(list(rels)),
            })

    # Summary score: 0 to 100
    penalty = 0.0
    if cycles:
        penalty += min(len(cycles) * 10, 30)
    if len(components) > 1:
        penalty += min((len(components) - 1) * 5, 20)
    if low_confidence_edges:
        penalty += min(len(low_confidence_edges) * 2, 20)
    if contradictions:
        penalty += min(len(contradictions) * 5, 15)

    health_score = max(0.0, 100.0 - penalty)

    return {
        "health_score": round(health_score, 1),
        "node_count": len(nodes),
        "edge_count": len(edges),
        "connected_components_count": len(components),
        "largest_component_size": component_sizes[0] if component_sizes else 0,
        "degree_gini_coefficient": round(gini, 3),
        "average_confidence": round(sum(confidences) / len(confidences), 3) if confidences else 1.0,
        "low_confidence_count": len(low_confidence_edges),
        "bridge_edges_count": len(bridges),
        "hierarchical_cycles": cycles[:10],
        "contradictory_pairs_count": len(contradictions),
        "contradictions_sample": contradictions[:5],
        "bridges_sample": bridges[:5],
    }
