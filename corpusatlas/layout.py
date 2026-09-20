"""Pure-Python graph layout engine (Fruchterman-Reingold / Force-Directed).
Calculates 2D coordinates (x, y), 3D coordinates (x, y, z), and Multi-Scale LOD tiers
with zero third-party dependencies.
"""
from __future__ import annotations

import math
import random
from typing import Any


def compute_layout(nodes: list[dict[str, Any]],
                   edges: list[dict[str, Any]],
                   iterations: int = 60,
                   area: float = 1000000.0,
                   use_barnes_hut: bool = True,
                   theta: float = 0.5,
                   three_d: bool = False) -> list[dict[str, Any]]:
    """Assigns 'x' and 'y' (and 'z' if three_d=True) float coordinates to each node dictionary in place."""
    if not nodes:
        return nodes

    count = len(nodes)
    if count == 1:
        nodes[0]["x"] = 0.0
        nodes[0]["y"] = 0.0
        if three_d:
            nodes[0]["z"] = 0.0
        return nodes

    from .layout_bh import QuadTree

    # Optimal pairwise distance
    k = math.sqrt(area / count)
    t = math.sqrt(area) / 10.0  # Initial temperature
    dt = t / (iterations + 1)

    # Deterministic initial placement
    rng = random.Random(42)
    pos: dict[str, list[float]] = {}
    for i, node in enumerate(nodes):
        nid = node.get("id") or str(i)
        if three_d:
            if "x" in node and "y" in node and "z" in node and isinstance(node.get("z"), (int, float)):
                pos[nid] = [float(node["x"]), float(node["y"]), float(node["z"])]
            else:
                # Fibonacci sphere distribution
                phi = math.acos(1.0 - 2.0 * (i + 0.5) / count)
                theta_angle = math.pi * (1.0 + 5.0 ** 0.5) * (i + 0.5)
                radius = k * math.sqrt(count) * 0.5 * (0.8 + 0.4 * rng.random())
                pos[nid] = [
                    radius * math.sin(phi) * math.cos(theta_angle),
                    radius * math.sin(phi) * math.sin(theta_angle),
                    radius * math.cos(phi)
                ]
        else:
            if "x" in node and "y" in node and isinstance(node["x"], (int, float)):
                pos[nid] = [float(node["x"]), float(node["y"])]
            else:
                angle = (2.0 * math.pi * i) / count
                radius = k * math.sqrt(count) * 0.5 * (0.8 + 0.4 * rng.random())
                pos[nid] = [radius * math.cos(angle), radius * math.sin(angle)]

    node_ids = [n.get("id") or str(i) for i, n in enumerate(nodes)]

    # Adjacency list
    adj: list[tuple[str, str]] = []
    for e in edges:
        s = e.get("src")
        d = e.get("dst")
        if s in pos and d in pos and s != d:
            adj.append((s, d))

    # Main simulation loop
    dim = 3 if three_d else 2
    for _ in range(iterations):
        disp: dict[str, list[float]] = {nid: [0.0] * dim for nid in node_ids}

        # 1. Repulsive forces
        if not three_d and use_barnes_hut and count > 30:
            x_vals = [pos[n][0] for n in node_ids]
            y_vals = [pos[n][1] for n in node_ids]
            min_x, max_x = min(x_vals), max(x_vals)
            min_y, max_y = min(y_vals), max(y_vals)
            pad = 20.0
            tree = QuadTree((min_x - pad, min_y - pad, max_x + pad, max_y + pad))
            for nid in node_ids:
                tree.insert(nid, pos[nid][0], pos[nid][1], 1.0)
            for nid in node_ids:
                fx, fy = tree.compute_force(nid, pos[nid][0], pos[nid][1], k, theta=theta)
                disp[nid][0] += fx
                disp[nid][1] += fy
        else:
            for i in range(count):
                u = node_ids[i]
                u_pos = pos[u]
                for j in range(i + 1, count):
                    v = node_ids[j]
                    v_pos = pos[v]
                    delta = [u_pos[d] - v_pos[d] for d in range(dim)]
                    dist = math.sqrt(sum(d * d for d in delta))
                    if dist < 0.0001:
                        delta = [(rng.random() - 0.5) * 0.1 for _ in range(dim)]
                        dist = math.sqrt(sum(d * d for d in delta))

                    rep = (k * k) / dist
                    for d in range(dim):
                        f = (delta[d] / dist) * rep
                        disp[u][d] += f
                        disp[v][d] -= f

        # 2. Attractive forces along edges
        for u, v in adj:
            u_pos = pos[u]
            v_pos = pos[v]
            delta = [u_pos[d] - v_pos[d] for d in range(dim)]
            dist = math.sqrt(sum(d * d for d in delta))
            if dist < 0.0001:
                continue
            att = (dist * dist) / k
            for d in range(dim):
                f = (delta[d] / dist) * att
                disp[u][d] -= f
                disp[v][d] += f

        # 3. Apply displacement clamped by temperature
        for nid in node_ids:
            cur_disp = disp[nid]
            dist = math.sqrt(sum(d * d for d in cur_disp))
            if dist > 0.0001:
                step = min(dist, t)
                for d in range(dim):
                    pos[nid][d] += (cur_disp[d] / dist) * step

        # Cool down
        t = max(0.01, t - dt)

    # Normalize center to (0, 0, [0])
    avg = [sum(p[d] for p in pos.values()) / count for d in range(dim)]

    for node in nodes:
        nid = node.get("id")
        if nid in pos:
            node["x"] = round(pos[nid][0] - avg[0], 2)
            node["y"] = round(pos[nid][1] - avg[1], 2)
            if three_d:
                node["z"] = round(pos[nid][2] - avg[2], 2)

    return nodes


def compute_multiscale_layout(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    iterations: int = 60,
    dimensions: int = 2
) -> list[dict[str, Any]]:
    """Hierarchical Multi-Scale layout assignment with Level of Detail (LOD) tiers.

    Partitions nodes into:
      LOD 0: Core hubs and backbone topology (top ~15% degree/centrality)
      LOD 1: Intermediate functional clusters (~35%)
      LOD 2: Detailed leaf entities and nodes (~50%)
    """
    if not nodes:
        return nodes

    # Ensure degrees exist
    degree_map: dict[str, int] = {}
    for e in edges:
        s, d = e.get("src"), e.get("dst")
        if s:
            degree_map[s] = degree_map.get(s, 0) + 1
        if d:
            degree_map[d] = degree_map.get(d, 0) + 1

    sorted_nodes = sorted(nodes, key=lambda n: n.get("degree", degree_map.get(n.get("id", ""), 0)), reverse=True)
    count = len(sorted_nodes)

    lod0_cutoff = max(1, int(count * 0.15))
    lod1_cutoff = max(lod0_cutoff + 1, int(count * 0.50))

    for i, n in enumerate(sorted_nodes):
        if i < lod0_cutoff:
            n["lod"] = 0
        elif i < lod1_cutoff:
            n["lod"] = 1
        else:
            n["lod"] = 2

    # Compute coordinates
    three_d = dimensions == 3
    compute_layout(nodes, edges, iterations=iterations, three_d=three_d)
    return nodes
