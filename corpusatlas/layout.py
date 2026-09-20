"""Pure-Python graph layout engine (Fruchterman-Reingold / Force-Directed).
Calculates 2D coordinates (x, y) for nodes with zero third-party dependencies.
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
                   theta: float = 0.5) -> list[dict[str, Any]]:
    """Assigns 'x' and 'y' float coordinates to each node dictionary in place."""
    if not nodes:
        return nodes

    count = len(nodes)
    if count == 1:
        nodes[0]["x"] = 0.0
        nodes[0]["y"] = 0.0
        return nodes

    from .layout_bh import QuadTree

    # Optimal pairwise distance
    k = math.sqrt(area / count)
    t = math.sqrt(area) / 10.0  # Initial temperature
    dt = t / (iterations + 1)

    # Deterministic initial placement on a circle or seeded jitter
    rng = random.Random(42)
    pos: dict[str, list[float]] = {}
    for i, node in enumerate(nodes):
        nid = node.get("id") or str(i)
        # Use existing position if already present, else distribute in circle
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
    for _ in range(iterations):
        disp: dict[str, list[float]] = {nid: [0.0, 0.0] for nid in node_ids}

        # 1. Repulsive forces
        if use_barnes_hut and count > 30:
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
                ux, uy = pos[u]
                for j in range(i + 1, count):
                    v = node_ids[j]
                    vx, vy = pos[v]
                    dx = ux - vx
                    dy = uy - vy
                    dist = math.hypot(dx, dy)
                    if dist < 0.0001:
                        dx = (rng.random() - 0.5) * 0.1
                        dy = (rng.random() - 0.5) * 0.1
                        dist = math.hypot(dx, dy)

                    rep = (k * k) / dist
                    fx = (dx / dist) * rep
                    fy = (dy / dist) * rep
                    disp[u][0] += fx
                    disp[u][1] += fy
                    disp[v][0] -= fx
                    disp[v][1] -= fy

        # 2. Attractive forces along edges
        for u, v in adj:
            ux, uy = pos[u]
            vx, vy = pos[v]
            dx = ux - vx
            dy = uy - vy
            dist = math.hypot(dx, dy)
            if dist < 0.0001:
                continue
            att = (dist * dist) / k
            fx = (dx / dist) * att
            fy = (dy / dist) * att
            disp[u][0] -= fx
            disp[u][1] -= fy
            disp[v][0] += fx
            disp[v][1] += fy

        # 3. Apply displacement clamped by temperature
        for nid in node_ids:
            dx, dy = disp[nid]
            dist = math.hypot(dx, dy)
            if dist > 0.0001:
                step = min(dist, t)
                pos[nid][0] += (dx / dist) * step
                pos[nid][1] += (dy / dist) * step

        # Cool down
        t = max(0.01, t - dt)

    # Normalize center to (0, 0)
    avg_x = sum(p[0] for p in pos.values()) / count
    avg_y = sum(p[1] for p in pos.values()) / count

    for node in nodes:
        nid = node.get("id")
        if nid in pos:
            node["x"] = round(pos[nid][0] - avg_x, 2)
            node["y"] = round(pos[nid][1] - avg_y, 2)

    return nodes
