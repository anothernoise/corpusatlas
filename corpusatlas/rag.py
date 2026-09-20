"""GraphRAG context extraction and prompt generation module."""
from __future__ import annotations

from collections import deque
from typing import Any, Dict, List, Set, Tuple


def _score_match(query: str, text: str) -> float:
    q = query.strip().lower()
    t = text.strip().lower()
    if not q or not t:
        return 0.0
    if q == t:
        return 1.0
    if t.startswith(q) or q in t:
        return 0.8
    q_words = set(q.split())
    t_words = set(t.split())
    overlap = len(q_words & t_words)
    if overlap:
        return 0.5 * (overlap / len(q_words))
    return 0.0


def extract_rag_context(
    graph_data: Dict[str, Any],
    query: str,
    k_hops: int = 2,
    token_budget: int = 2000,
    format: str = "markdown",
) -> Dict[str, Any]:
    """Extract a k-hop subgraph around query entities and format prompt context."""
    nodes = {n["id"]: n for n in graph_data.get("nodes", [])}
    edges = graph_data.get("edges", [])

    # Build adjacency list
    adj: Dict[str, List[Dict[str, Any]]] = {nid: [] for nid in nodes}
    for e in edges:
        src = e.get("source")
        tgt = e.get("target")
        if src in adj:
            adj[src].append(e)
        if tgt in adj:
            adj[tgt].append(e)

    # 1. Identify seed nodes
    scored_seeds: List[Tuple[float, str]] = []
    for nid, node in nodes.items():
        label = node.get("label", "")
        desc = (node.get("meta") or {}).get("description", "")
        aliases = node.get("aliases") or []
        best_score = _score_match(query, label)
        for alias in aliases:
            best_score = max(best_score, _score_match(query, alias))
        if desc:
            best_score = max(best_score, _score_match(query, desc) * 0.7)
        if best_score > 0.1:
            scored_seeds.append((best_score, nid))

    scored_seeds.sort(key=lambda x: x[0], reverse=True)
    seed_ids = [s[1] for s in scored_seeds[:5]]
    if not seed_ids and nodes:
        # Fallback to first node if nothing matched
        seed_ids = [next(iter(nodes))]

    # 2. BFS k-hop traversal
    visited_nodes: Set[str] = set(seed_ids)
    selected_edges: List[Dict[str, Any]] = []
    queue: deque[Tuple[str, int]] = deque([(sid, 0) for sid in seed_ids])

    while queue:
        curr, depth = queue.popleft()
        if depth >= k_hops:
            continue
        for edge in adj.get(curr, []):
            src, tgt = edge["source"], edge["target"]
            other = tgt if src == curr else src
            if edge not in selected_edges:
                selected_edges.append(edge)
            if other not in visited_nodes and other in nodes:
                visited_nodes.add(other)
                queue.append((other, depth + 1))

    subgraph_nodes = [nodes[nid] for nid in visited_nodes]

    # 3. Format context respecting token budget (~4 chars per token)
    char_budget = token_budget * 4

    lines: List[str] = [
        "### Relevant Entities",
    ]
    for n in subgraph_nodes:
        desc = (n.get("meta") or {}).get("description", "")
        desc_part = f": {desc}" if desc else ""
        line = f"- **{n.get('label', n['id'])}** ({n.get('type', 'Unknown')}){desc_part}"
        if sum(len(x) + 1 for x in lines) + len(line) > char_budget * 0.5:
            break
        lines.append(line)

    lines.append("\n### Graph Relations")
    for e in selected_edges:
        s_lbl = nodes.get(e["source"], {}).get("label", e["source"])
        t_lbl = nodes.get(e["target"], {}).get("label", e["target"])
        rel = e.get("rel", "related_to")
        line = f"- `{s_lbl}` --[{rel}]--> `{t_lbl}`"
        if sum(len(x) + 1 for x in lines) + len(line) > char_budget * 0.9:
            break
        lines.append(line)

    prompt_text = "\n".join(lines)
    if len(prompt_text) > char_budget:
        prompt_text = prompt_text[:char_budget] + "\n... (truncated for token budget)"

    return {
        "seeds": [nodes[sid] for sid in seed_ids if sid in nodes],
        "nodes": subgraph_nodes,
        "edges": selected_edges,
        "prompt_text": prompt_text,
        "format": format,
    }
