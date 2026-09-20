"""Natural language to graph query translation and execution module."""
from __future__ import annotations

import re
from collections import deque
from typing import Any, Dict, List, Optional, Tuple


def _find_entities_in_text(text: str, nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    lowered = text.lower()
    matches = []
    for n in sorted(nodes, key=lambda x: len(x.get("label", "")), reverse=True):
        lbl = n.get("label", "").lower()
        nid = n.get("id", "").lower()
        if (lbl and lbl in lowered) or (nid and nid in lowered):
            matches.append(n)
            # Avoid duplicate substrings
            lowered = lowered.replace(lbl, " ")
    return matches


def parse_nl_query(query: str, nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
    q = query.strip().lower()
    matched_nodes = _find_entities_in_text(query, nodes)

    intent = "connections"
    if any(k in q for k in ("path", "connect to", "connected to", "how to get", "route")):
        intent = "path"
    elif any(k in q for k in ("compare", "vs", "versus", "difference", "comparison")):
        intent = "comparison"
    elif any(k in q for k in ("depend", "relies on", "requires", "prerequisite")):
        intent = "dependencies"
    elif any(k in q for k in ("hub", "central", "most connected", "popular")):
        intent = "hubs"

    return {
        "query": query,
        "intent": intent,
        "entities": matched_nodes,
    }


def execute_nl_query(graph_data: Dict[str, Any], query: str) -> Dict[str, Any]:
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    node_map = {n["id"]: n for n in nodes}

    parsed = parse_nl_query(query, nodes)
    intent = parsed["intent"]
    entities = parsed["entities"]

    # Build adjacency
    adj: Dict[str, List[Dict[str, Any]]] = {n["id"]: [] for n in nodes}
    for e in edges:
        s, t = e.get("source"), e.get("target")
        if s in adj:
            adj[s].append(e)
        if t in adj:
            adj[t].append(e)

    results: List[Dict[str, Any]] = []
    summary = ""
    extra: Dict[str, Any] = {}

    if intent == "path" and len(entities) >= 2:
        src_id, tgt_id = entities[0]["id"], entities[1]["id"]
        # BFS shortest path
        queue: deque[Tuple[str, List[str]]] = deque([(src_id, [src_id])])
        visited = {src_id}
        found_path: Optional[List[str]] = None

        while queue:
            curr, path = queue.popleft()
            if curr == tgt_id:
                found_path = path
                break
            for e in adj.get(curr, []):
                other = e["target"] if e["source"] == curr else e["source"]
                if other not in visited:
                    visited.add(other)
                    queue.append((other, path + [other]))

        if found_path:
            extra["path"] = [node_map[p] for p in found_path if p in node_map]
            path_str = " -> ".join(n["label"] for n in extra["path"])
            summary = f"Found path of length {len(found_path) - 1}: {path_str}"
        else:
            summary = f"No direct path found between {entities[0]['label']} and {entities[1]['label']}."

    elif intent == "comparison":
        if len(entities) >= 2:
            e1_id, e2_id = entities[0]["id"], entities[1]["id"]
            # Check for direct comparison or common neighbors
            comp_edges = [
                e for e in edges
                if (e.get("source") in (e1_id, e2_id) and e.get("target") in (e1_id, e2_id))
            ]
            results = comp_edges
            summary = f"Found {len(comp_edges)} direct relations/comparisons between {entities[0]['label']} and {entities[1]['label']}."
        else:
            # List all comparison edges
            results = [e for e in edges if "compare" in e.get("rel", "").lower()]
            summary = f"Found {len(results)} comparisons in graph."

    elif intent == "hubs":
        ranked = sorted(nodes, key=lambda n: len(adj.get(n["id"], [])), reverse=True)
        results = ranked[:10]
        summary = f"Top {len(results)} hubs by degree centrality."

    else:  # connections or dependencies
        if entities:
            target_id = entities[0]["id"]
            connected_edges = adj.get(target_id, [])
            connected_node_ids = set()
            for e in connected_edges:
                connected_node_ids.add(e["target"] if e["source"] == target_id else e["source"])
            results = [node_map[nid] for nid in connected_node_ids if nid in node_map]
            summary = f"Found {len(results)} entities connected to {entities[0]['label']}."
        else:
            summary = "Could not identify specific entity in query; showing overview."
            results = nodes[:5]

    return {
        "query": query,
        "matched_intent": intent,
        "summary": summary,
        "results": results,
        **extra,
    }
