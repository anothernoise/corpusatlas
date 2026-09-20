"""Declarative architecture and graph linter."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


def _detect_directed_cycles(nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], rel_filter: Set[str]) -> List[List[str]]:
    adj: Dict[str, List[str]] = {n["id"]: [] for n in nodes}
    for e in edges:
        if e.get("rel") in rel_filter:
            s, t = e["source"], e["target"]
            if s in adj and t in adj:
                adj[s].append(t)

    visited: Dict[str, int] = {n["id"]: 0 for n in nodes}  # 0: unvisited, 1: visiting, 2: visited
    cycles: List[List[str]] = []
    current_path: List[str] = []

    def dfs(u: str):
        visited[u] = 1
        current_path.append(u)
        for v in adj.get(u, []):
            if visited[v] == 1:
                # Cycle found
                cycle_start = current_path.index(v)
                cycles.append(current_path[cycle_start:] + [v])
            elif visited[v] == 0:
                dfs(v)
        current_path.pop()
        visited[u] = 2

    for n in nodes:
        if visited[n["id"]] == 0:
            dfs(n["id"])

    return cycles


def lint_graph(graph_data: Dict[str, Any], rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    node_map = {n["id"]: n for n in nodes}

    violations: List[Dict[str, Any]] = []

    # 1. Forbidden edges
    forbidden = rules.get("forbidden_edges", [])
    for rule in forbidden:
        s_type = rule.get("source_type")
        t_type = rule.get("target_type")
        rel = rule.get("rel")
        msg = rule.get("message", f"Forbidden relation: {s_type} --[{rel}]--> {t_type}")
        severity = rule.get("severity", "error")

        for e in edges:
            src_node = node_map.get(e["source"])
            tgt_node = node_map.get(e["target"])
            if not src_node or not tgt_node:
                continue
            if s_type and src_node.get("type") != s_type:
                continue
            if t_type and tgt_node.get("type") != t_type:
                continue
            if rel and e.get("rel") != rel:
                continue

            violations.append({
                "rule": "forbidden_edges",
                "severity": severity,
                "message": msg,
                "edge": e,
            })

    # 2. Required node attributes
    required_attrs = rules.get("required_node_attributes", [])
    for rule in required_attrs:
        req_type = rule.get("type")
        attr = rule.get("attribute")
        msg = rule.get("message", f"Node of type {req_type} missing required attribute {attr}")
        severity = rule.get("severity", "error")

        for n in nodes:
            if req_type and n.get("type") != req_type:
                continue
            meta = n.get("meta") or {}
            val = n.get(attr) or meta.get(attr)
            if not val:
                violations.append({
                    "rule": "required_node_attributes",
                    "severity": severity,
                    "message": msg,
                    "node_id": n["id"],
                })

    # 3. Acyclic relations
    acyclic_rels = set(rules.get("acyclic_relations", []))
    if acyclic_rels:
        cycles = _detect_directed_cycles(nodes, edges, acyclic_rels)
        for c in cycles:
            cycle_str = " -> ".join(c)
            violations.append({
                "rule": "acyclic_relations",
                "severity": "error",
                "message": f"Cycle detected in acyclic relations: {cycle_str}",
            })

    # 4. Max degree (god component check)
    max_deg = rules.get("max_degree")
    if max_deg and isinstance(max_deg, (int, float)):
        deg: Dict[str, int] = {n["id"]: 0 for n in nodes}
        for e in edges:
            if e["source"] in deg:
                deg[e["source"]] += 1
            if e["target"] in deg:
                deg[e["target"]] += 1
        for nid, count in deg.items():
            if count > max_deg:
                violations.append({
                    "rule": "max_degree",
                    "severity": "warning",
                    "message": f"Node {nid} has degree {count} exceeding threshold {max_deg}",
                    "node_id": nid,
                })

    return violations
