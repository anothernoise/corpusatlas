"""Pure-Python hierarchical community detection (modularity maximization).

Implements Louvain-style modularity optimization for knowledge graphs
without requiring external C/C++ graph libraries (NetworkX/igraph).
Zero external dependencies.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def evaluate_modularity(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    assignment: dict[str, int],
) -> float:
    """Compute Newman-Girvan modularity Q for a community partition."""
    weights: dict[tuple[str, str], float] = defaultdict(float)
    degrees: dict[str, float] = defaultdict(float)

    for e in edges:
        u, v = e["src"], e["dst"]
        w = float(e.get("confidence", 1.0))
        weights[(u, v)] += w
        weights[(v, u)] += w
        degrees[u] += w
        degrees[v] += w

    two_m = sum(degrees.values())
    if two_m == 0:
        return 0.0

    q = 0.0
    for (u, v), w in weights.items():
        if assignment.get(u) == assignment.get(v):
            q += w - (degrees[u] * degrees[v]) / two_m

    return q / two_m


def detect_communities(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    resolution: float = 1.0,
    max_iter: int = 30,
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """Detect dense node communities by maximizing modularity.

    Returns:
        (node_assignment: {node_id: community_id},
         clusters: list of summary cluster dicts)
    """
    if not nodes:
        return {}, []

    adj: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    node_degrees: dict[str, float] = defaultdict(float)

    for e in edges:
        u, v = e["src"], e["dst"]
        w = float(e.get("confidence", 1.0))
        adj[u][v] += w
        adj[v][u] += w
        node_degrees[u] += w
        node_degrees[v] += w

    for n in nodes:
        nid = n["id"]
        if nid not in node_degrees:
            node_degrees[nid] = 0.0

    two_m = sum(node_degrees.values())
    if two_m == 0:
        assignment = {n["id"]: i for i, n in enumerate(nodes)}
        return assignment, [{"community_id": i, "members": [n["id"]]} for i, n in enumerate(nodes)]

    # Initial community: each node in its own community
    node_to_comm: dict[str, int] = {n["id"]: idx for idx, n in enumerate(nodes)}
    comm_to_nodes: dict[int, set[str]] = {idx: {n["id"]} for idx, n in enumerate(nodes)}
    comm_tot: dict[int, float] = {idx: node_degrees[n["id"]] for idx, n in enumerate(nodes)}

    # Modularity optimization phase
    improved = True
    iteration = 0

    while improved and iteration < max_iter:
        improved = False
        iteration += 1

        for n in nodes:
            u = n["id"]
            c_orig = node_to_comm[u]
            k_u = node_degrees[u]

            # Neighbor communities and edge weights from u to each community
            neighbor_comm_weights: dict[int, float] = defaultdict(float)
            for neighbor, w in adj[u].items():
                c_neigh = node_to_comm[neighbor]
                neighbor_comm_weights[c_neigh] += w

            # Remove u from current community
            comm_to_nodes[c_orig].remove(u)
            comm_tot[c_orig] -= k_u

            # Find best community for u
            best_comm = c_orig
            best_gain = 0.0

            # Weight to original community without u
            w_to_orig = neighbor_comm_weights.get(c_orig, 0.0)

            for c_cand, k_u_in in neighbor_comm_weights.items():
                tot_c = comm_tot[c_cand]
                # Gain formula: delta_Q = k_u_in - resolution * (tot_c * k_u) / two_m
                gain = k_u_in - resolution * (tot_c * k_u) / two_m
                # Relative gain compared to staying in original
                loss_orig = w_to_orig - resolution * (comm_tot[c_orig] * k_u) / two_m
                delta = gain - loss_orig

                if delta > best_gain:
                    best_gain = delta
                    best_comm = c_cand

            # Insert u into best community
            comm_to_nodes[best_comm].add(u)
            comm_tot[best_comm] += k_u
            node_to_comm[u] = best_comm

            if best_comm != c_orig:
                improved = True

    # Renumber communities consecutively 0..K-1
    active_comms = [c for c, members in comm_to_nodes.items() if members]
    comm_map = {old_id: new_id for new_id, old_id in enumerate(active_comms)}

    normalized_assignment = {u: comm_map[c] for u, c in node_to_comm.items()}

    # Build cluster summaries
    nodes_by_id = {n["id"]: n for n in nodes}
    clusters: list[dict[str, Any]] = []

    for old_id, new_id in sorted(comm_map.items(), key=lambda kv: kv[1]):
        members = sorted(comm_to_nodes[old_id])
        member_types = [nodes_by_id[m].get("type", "Unknown") for m in members if m in nodes_by_id]
        type_counts = dict(Counter(member_types).most_common(3))

        # Top member by degree
        top_node_id = max(members, key=lambda m: node_degrees.get(m, 0.0))
        top_label = nodes_by_id[top_node_id].get("label", top_node_id) if top_node_id in nodes_by_id else top_node_id

        clusters.append({
            "community_id": new_id,
            "label": f"Cluster: {top_label}",
            "size": len(members),
            "members": members,
            "dominant_types": type_counts,
        })

    return normalized_assignment, clusters
