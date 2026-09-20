"""Graph topology and health analytics module."""
from __future__ import annotations

from typing import Any, Dict, List, Set


def _find_articulation_points(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> List[str]:
    """Find articulation points (cut vertices) using Hopcroft-Tarjan DFS algorithm."""
    adj: Dict[str, List[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        s, t = e["source"], e["target"]
        if s in adj and t in adj and s != t:
            adj[s].append(t)
            adj[t].append(s)

    tin: Dict[str, int] = {}
    low: Dict[str, int] = {}
    timer = 0
    articulation_points: Set[str] = set()

    def dfs(v: str, p: str = "-1"):
        nonlocal timer
        tin[v] = low[v] = timer
        timer += 1
        children = 0
        for to in adj[v]:
            if to == p:
                continue
            if to in tin:
                low[v] = min(low[v], tin[to])
            else:
                dfs(to, v)
                low[v] = min(low[v], low[to])
                if low[to] >= tin[v] and p != "-1":
                    articulation_points.add(v)
                children += 1
        if p == "-1" and children > 1:
            articulation_points.add(v)

    for n in nodes:
        nid = n["id"]
        if nid not in tin:
            dfs(nid)

    return sorted(articulation_points)


def analyze_graph_topology(graph_data: Dict[str, Any]) -> Dict[str, Any]:
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    num_nodes = len(nodes)
    num_edges = len(edges)

    # Degree counts
    degree: Dict[str, int] = {n["id"]: 0 for n in nodes}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in degree:
            degree[s] += 1
        if t in degree:
            degree[t] += 1

    orphans = [nid for nid, deg in degree.items() if deg == 0]
    num_orphans = len(orphans)

    # Density
    density = 0.0
    if num_nodes > 1:
        possible_edges = num_nodes * (num_nodes - 1)
        density = round(num_edges / possible_edges, 4)

    avg_degree = round((2.0 * num_edges / num_nodes), 2) if num_nodes > 0 else 0.0

    # Articulation points
    art_points = _find_articulation_points(nodes, edges)

    # Connected components
    adj: Dict[str, List[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in adj and t in adj:
            adj[s].append(t)
            adj[t].append(s)

    visited: Set[str] = set()
    components: List[int] = []
    for n in nodes:
        nid = n["id"]
        if nid not in visited:
            stack = [nid]
            visited.add(nid)
            size = 0
            while stack:
                curr = stack.pop()
                size += 1
                for nxt in adj.get(curr, []):
                    if nxt not in visited:
                        visited.add(nxt)
                        stack.append(nxt)
            components.append(size)

    # Health score (100 base)
    # Deductions:
    # - % of orphans * 40
    # - single points of failure (articulation points) penalty
    orphan_penalty = min(40.0, (num_orphans / max(1, num_nodes)) * 100.0)
    spof_penalty = min(30.0, len(art_points) * 5.0)
    health_score = max(0, min(100, int(100 - orphan_penalty - spof_penalty)))

    return {
        "num_nodes": num_nodes,
        "num_edges": num_edges,
        "num_orphans": num_orphans,
        "orphan_node_ids": orphans,
        "connected_components_count": len(components),
        "component_sizes": sorted(components, reverse=True),
        "density": density,
        "average_degree": avg_degree,
        "articulation_points": art_points,
        "health_score": health_score,
    }
