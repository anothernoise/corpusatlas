"""Spatial Quadtree Tile generator for client-side LOD streaming.

Partitions 2D layout coordinates into a multi-resolution quadtree pyramid:
tiles/{z}/{x}_{y}.json and manifest.json.
Allows web viewers and mobile frontends to stream large knowledge graphs
incrementally without loading hundreds of thousands of nodes at once.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Iterable

from .model import Edge, Node


def generate_spatial_tiles(
    nodes: Iterable[Node],
    edges: Iterable[Edge],
    out_dir: str | Path,
    max_zoom: int = 3,
    layout_meta_key: str = "pos",
) -> dict[str, Any]:
    """Partition layout into quadtree tiles from z=0 to z=max_zoom.

    Nodes require 2D coordinates in node.meta[layout_meta_key] as [x, y],
    or node.meta["x"] and node.meta["y"].
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    node_list = list(nodes)
    edge_list = list(edges)

    # Extract coordinates
    coords: dict[str, tuple[float, float]] = {}
    degree: dict[str, int] = {n.id: 0 for n in node_list}
    for e in edge_list:
        degree[e.src] = degree.get(e.src, 0) + 1
        degree[e.dst] = degree.get(e.dst, 0) + 1

    min_x, max_x = float("inf"), float("-inf")
    min_y, max_y = float("inf"), float("-inf")

    # If coordinates are missing, fallback to deterministic circle or grid
    has_coords = False
    for n in node_list:
        xy = n.meta.get(layout_meta_key)
        if isinstance(xy, (list, tuple)) and len(xy) >= 2:
            x, y = float(xy[0]), float(xy[1])
            coords[n.id] = (x, y)
            has_coords = True
        elif "x" in n.meta and "y" in n.meta:
            x, y = float(n.meta["x"]), float(n.meta["y"])
            coords[n.id] = (x, y)
            has_coords = True

    if not has_coords and node_list:
        # Generate synthetic circular layout for tiling
        step = (2.0 * math.pi) / len(node_list)
        for i, n in enumerate(node_list):
            x = 500.0 * math.cos(i * step)
            y = 500.0 * math.sin(i * step)
            coords[n.id] = (x, y)

    for x, y in coords.values():
        if x < min_x:
            min_x = x
        if x > max_x:
            max_x = x
        if y < min_y:
            min_y = y
        if y > max_y:
            max_y = y

    # Add margin
    span_x = max(max_x - min_x, 1.0)
    span_y = max(max_y - min_y, 1.0)
    min_x -= span_x * 0.05
    max_x += span_x * 0.05
    min_y -= span_y * 0.05
    max_y += span_y * 0.05
    span_x = max_x - min_x
    span_y = max_y - min_y

    tiles_written = 0
    node_map = {n.id: n for n in node_list}

    # Generate pyramid
    for z in range(max_zoom + 1):
        grid_size = 2**z
        z_dir = out / str(z)
        z_dir.mkdir(parents=True, exist_ok=True)

        tile_nodes: dict[tuple[int, int], list[Node]] = {}
        tile_node_ids: dict[tuple[int, int], set[str]] = {}

        # Place nodes into grid cells
        for n in node_list:
            if n.id not in coords:
                continue
            x, y = coords[n.id]
            norm_x = (x - min_x) / span_x
            norm_y = (y - min_y) / span_y
            gx = min(int(norm_x * grid_size), grid_size - 1)
            gy = min(int(norm_y * grid_size), grid_size - 1)

            # In lower zoom levels (z < max_zoom), prioritize high degree nodes
            # Keep top fraction of nodes based on zoom level
            keep_prob = (z + 1) / (max_zoom + 1)
            # If z is 0, keep top 25% or min 20 nodes
            if z < max_zoom:
                # Top degree threshold
                deg = degree.get(n.id, 0)
                if deg < 2 and keep_prob < 0.5:
                    continue

            tile_nodes.setdefault((gx, gy), []).append(n)
            tile_node_ids.setdefault((gx, gy), set()).add(n.id)

        # Place edges into tile cells if both endpoints present in cell
        for (gx, gy), cell_nodes in tile_nodes.items():
            cell_ids = tile_node_ids[(gx, gy)]
            cell_edges = [
                e for e in edge_list
                if e.src in cell_ids and e.dst in cell_ids
            ]

            tile_data = {
                "z": z,
                "x": gx,
                "y": gy,
                "nodes": [n.to_json() for n in cell_nodes],
                "edges": [e.to_json() for e in cell_edges],
            }

            tile_file = z_dir / f"{gx}_{gy}.json"
            tile_file.write_text(json.dumps(tile_data, ensure_ascii=False), encoding="utf-8")
            tiles_written += 1

    manifest = {
        "bbox": [min_x, min_y, max_x, max_y],
        "max_zoom": max_zoom,
        "node_count": len(node_list),
        "edge_count": len(edge_list),
        "tile_count": tiles_written,
    }

    manifest_file = out / "manifest.json"
    manifest_file.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
