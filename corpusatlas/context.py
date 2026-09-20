"""Personalized PageRank (PPR) and Graph RAG subgraph extraction.

Provides random walk with restart (PPR) power iteration to extract the most
semantically relevant subgraph for a given query entity, filtering noise and
prioritizing tightly bound multi-hop concepts for LLM context prompts.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any


def personalized_pagerank(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    seed_id: str,
    alpha: float = 0.15,
    max_iter: int = 40,
    tol: float = 1e-6,
) -> dict[str, float]:
    """Compute Personalized PageRank (Random Walk with Restart) from seed_id.

    alpha: restart probability back to seed_id.
    """
    all_node_ids = {n["id"] for n in nodes}
    if seed_id not in all_node_ids:
        return {}

    # Build adjacency list (bidirectional with edge confidence weighting)
    adj: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    out_degree: dict[str, float] = defaultdict(float)

    for e in edges:
        s, d = e.get("src"), e.get("dst")
        if not s or not d:
            continue
        weight = float(e.get("confidence", 1.0))
        adj[s][d] += weight
        adj[d][s] += weight
        out_degree[s] += weight
        out_degree[d] += weight

    nodes_list = list(all_node_ids)
    num_nodes = len(nodes_list)
    if num_nodes == 0:
        return {}

    # Initialize distribution: 100% on seed
    p: dict[str, float] = {nid: 0.0 for nid in nodes_list}
    p[seed_id] = 1.0

    # Power iteration
    for _ in range(max_iter):
        next_p: dict[str, float] = defaultdict(float)

        # Distribute probability mass along outgoing edges
        for u, score in p.items():
            if score == 0.0:
                continue
            deg = out_degree.get(u, 0.0)
            if deg == 0.0:
                # Dangling node teleports back to seed
                next_p[seed_id] += (1.0 - alpha) * score
            else:
                for v, weight in adj[u].items():
                    next_p[v] += (1.0 - alpha) * score * (weight / deg)

        # Add restart teleportation mass
        next_p[seed_id] += alpha

        # Check convergence (L1 norm)
        diff = sum(abs(next_p[nid] - p[nid]) for nid in nodes_list)
        p = {nid: next_p.get(nid, 0.0) for nid in nodes_list}
        if diff < tol:
            break

    return p


def extract_rag_subgraph(
    graph_data: dict[str, Any],
    query_entity: str,
    algorithm: str = "ppr",
    top_k: int = 20,
    depth: int = 1,
    alpha: float = 0.15,
) -> dict[str, Any]:
    """Extract subgraph around query_entity using PPR or BFS."""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])
    query = query_entity.strip()

    target_node = None
    for n in nodes:
        if n.get("id") == query or n.get("id") == f"entity:{query}":
            target_node = n
            break
        if n.get("label", "").lower() == query.lower():
            target_node = n
            break

    if not target_node:
        return {"error": f"Entity '{query_entity}' not found in graph"}

    tid = target_node["id"]
    nodes_by_id = {n["id"]: n for n in nodes}

    # Direct 1-hop outbound and inbound edges
    selected_ids: set[str] = {tid}
    all_outbound = [e for e in edges if e.get("src") == tid]
    all_inbound = [e for e in edges if e.get("dst") == tid]
    for e in all_outbound:
        selected_ids.add(e["dst"])
    for e in all_inbound:
        selected_ids.add(e["src"])

    if algorithm == "ppr":
        scores = personalized_pagerank(nodes, edges, tid, alpha=alpha)
        # Sort by PPR score descending (excluding seed itself first)
        ranked = sorted(
            [(nid, s) for nid, s in scores.items() if nid != tid and nid not in selected_ids],
            key=lambda x: -x[1],
        )
        for nid, score in ranked[:top_k]:
            selected_ids.add(nid)
    elif depth >= 2:
        # 2-hop BFS
        one_hop = set(selected_ids)
        for e in edges:
            if e.get("src") in one_hop and e.get("dst") != tid:
                selected_ids.add(e.get("dst"))
            elif e.get("dst") in one_hop and e.get("src") != tid:
                selected_ids.add(e.get("src"))

    # Format outbound edges with rich metadata
    outbound = [
        {
            "src": e.get("src"),
            "rel": e.get("rel"),
            "dst": e.get("dst"),
            "relation": e.get("rel"),
            "target": e.get("dst"),
            "target_label": nodes_by_id.get(e.get("dst"), {}).get("label", e.get("dst")),
            "target_type": nodes_by_id.get(e.get("dst"), {}).get("type"),
            "confidence": e.get("confidence", 1.0),
            "explanation": e.get("explanation"),
            "document": e.get("doc") or e.get("prov", {}).get("doc"),
            "doc": e.get("doc") or e.get("prov", {}).get("doc"),
            "tier": e.get("tier") or e.get("prov", {}).get("tier"),
        }
        for e in all_outbound
    ]

    # Format inbound edges with rich metadata
    inbound = [
        {
            "src": e.get("src"),
            "rel": e.get("rel"),
            "dst": e.get("dst"),
            "source": e.get("src"),
            "source_label": nodes_by_id.get(e.get("src"), {}).get("label", e.get("src")),
            "source_type": nodes_by_id.get(e.get("src"), {}).get("type"),
            "relation": e.get("rel"),
            "confidence": e.get("confidence", 1.0),
            "explanation": e.get("explanation"),
            "document": e.get("doc") or e.get("prov", {}).get("doc"),
            "doc": e.get("doc") or e.get("prov", {}).get("doc"),
            "tier": e.get("tier") or e.get("prov", {}).get("tier"),
        }
        for e in all_inbound
    ]

    # Connected subgraph edges between non-seed nodes
    subgraph_edges = [
        e for e in edges
        if e.get("src") in selected_ids and e.get("dst") in selected_ids
        and e.get("src") != tid and e.get("dst") != tid
    ]

    evidence_docs = sorted(list({
        e.get("doc") or e.get("prov", {}).get("doc") or e.get("document")
        for e in all_outbound + all_inbound + subgraph_edges
        if (e.get("doc") or e.get("prov", {}).get("doc") or e.get("document"))
    }))

    return {
        "entity": target_node,
        "algorithm": algorithm,
        "selected_nodes": [nodes_by_id[nid] for nid in selected_ids if nid in nodes_by_id],
        "outbound_edges": outbound,
        "inbound_edges": inbound,
        "two_hop_edges": subgraph_edges[:20],
        "subgraph_edges": subgraph_edges,
        "evidence_documents": evidence_docs,
    }


def format_rag_markdown(context_data: dict[str, Any]) -> str:
    """Format extracted RAG subgraph as concise, high-density LLM prompt markdown."""
    target = context_data.get("entity", {})
    tid = target.get("id", "")
    lines = [
        f"# Entity Context: {target.get('label', tid)} ({target.get('type', 'Entity')})",
        f"- **ID**: `{tid}`",
    ]
    if target.get("url"):
        lines.append(f"- **URL**: {target['url']}")
    if target.get("description"):
        lines.append(f"- **Description**: {target['description']}")
    lines.append("")

    lines.append("## Direct Relationships (Outbound)")
    outbound = context_data.get("outbound_edges", [])
    if not outbound:
        lines.append("_No outbound relationships._")
    else:
        for e in outbound:
            t_label = e.get("target_label", e.get("dst"))
            t_type = e.get("target_type", "Entity")
            tier_info = f" [{e.get('tier', 'tier')}: {e.get('confidence', 1.0)}]" if e.get("tier") else f" [conf: {e.get('confidence', 1.0):.2f}]"
            lines.append(f"- **{e['rel']}** -> {t_label} ({t_type}){tier_info}")
            if e.get("explanation"):
                lines.append(f"  *Note: {e['explanation']}*")
            if e.get("document"):
                lines.append(f"  *Evidence: {e['document']}*")

    lines.append("")
    lines.append("## Inbound Relationships")
    inbound = context_data.get("inbound_edges", [])
    if not inbound:
        lines.append("_No inbound relationships._")
    else:
        for e in inbound:
            s_label = e.get("source_label", e.get("src"))
            s_type = e.get("source_type", "Entity")
            lines.append(f"- {s_label} ({s_type}) -> **{e['rel']}** -> {target.get('label', tid)}")
            if e.get("explanation"):
                lines.append(f"  *Note: {e['explanation']}*")
            if e.get("document"):
                lines.append(f"  *Evidence: {e['document']}*")

    lines.append("")
    sub_edges = context_data.get("subgraph_edges", [])
    if sub_edges:
        lines.append("## Connected Subgraph (Multi-Hop Context)")
        for e in sub_edges[:20]:
            lines.append(f"- {e['src']} -{e['rel']}-> {e['dst']}")
        lines.append("")

    docs = context_data.get("evidence_documents", [])
    if docs:
        lines.append("## Evidence & Source Documents")
        for doc in docs:
            lines.append(f"- {doc}")
        lines.append("")

    return "\n".join(lines)
