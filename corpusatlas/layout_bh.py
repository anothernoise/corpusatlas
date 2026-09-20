"""Barnes-Hut Quadtree for O(N log N) n-body repulsive force approximation.

Recursively subdivides 2D coordinate space into 4 quadrants. For nodes sufficiently
distant from a quadtree cell (s / d < theta, default theta = 0.5), repulsive forces
are approximated using the cell's center-of-mass rather than evaluating all pair
interactions individually.
"""
from __future__ import annotations

import math
from typing import Optional


class QuadTreeNode:
    __slots__ = (
        "x_min", "y_min", "x_max", "y_max",
        "size", "mass", "cx", "cy",
        "node_id", "children", "is_leaf"
    )

    def __init__(self, x_min: float, y_min: float, x_max: float, y_max: float):
        self.x_min = x_min
        self.y_min = y_min
        self.x_max = x_max
        self.y_max = y_max
        self.size = max(x_max - x_min, y_max - y_min)
        self.mass = 0.0
        self.cx = 0.0
        self.cy = 0.0
        self.node_id: Optional[str] = None
        self.children: Optional[list[QuadTreeNode]] = None
        self.is_leaf = True

    def insert(self, nid: str, x: float, y: float, weight: float = 1.0) -> None:
        if self.mass == 0.0:
            # Empty leaf: store node here
            self.node_id = nid
            self.mass = weight
            self.cx = x
            self.cy = y
            return

        if self.is_leaf:
            # Subdivide existing leaf
            self._subdivide()
            old_id = self.node_id
            old_cx, old_cy = self.cx, self.cy
            old_mass = self.mass
            self.node_id = None
            self.is_leaf = False

            # Re-insert existing node into child
            if old_id is not None:
                self._insert_child(old_id, old_cx, old_cy, old_mass)

        # Update center of mass
        total_mass = self.mass + weight
        self.cx = (self.cx * self.mass + x * weight) / total_mass
        self.cy = (self.cy * self.mass + y * weight) / total_mass
        self.mass = total_mass

        # Insert new node into child
        self._insert_child(nid, x, y, weight)

    def _subdivide(self) -> None:
        mid_x = (self.x_min + self.x_max) * 0.5
        mid_y = (self.y_min + self.y_max) * 0.5
        self.children = [
            QuadTreeNode(self.x_min, self.y_min, mid_x, mid_y),  # NW (0)
            QuadTreeNode(mid_x, self.y_min, self.x_max, mid_y),  # NE (1)
            QuadTreeNode(self.x_min, mid_y, mid_x, self.y_max),  # SW (2)
            QuadTreeNode(mid_x, mid_y, self.x_max, self.y_max),  # SE (3)
        ]

    def _insert_child(self, nid: str, x: float, y: float, weight: float) -> None:
        if self.children is None:
            return
        mid_x = (self.x_min + self.x_max) * 0.5
        mid_y = (self.y_min + self.y_max) * 0.5
        idx = (0 if x < mid_x else 1) + (0 if y < mid_y else 2)
        self.children[idx].insert(nid, x, y, weight)

    def compute_repulsion(self, nid: str, x: float, y: float, k2: float, theta: float) -> tuple[float, float]:
        """Compute repulsive force on (x, y) with strength proportional to k^2."""
        if self.mass == 0.0:
            return 0.0, 0.0

        dx = x - self.cx
        dy = y - self.cy
        dist_sq = dx * dx + dy * dy
        dist = math.sqrt(dist_sq) if dist_sq > 1e-8 else 1e-4

        # If leaf with single node
        if self.is_leaf:
            if self.node_id == nid:
                return 0.0, 0.0
            force = (k2 * self.mass) / dist
            return (dx / dist) * force, (dy / dist) * force

        # Barnes-Hut criterion: size / distance < theta
        if (self.size / dist) < theta:
            force = (k2 * self.mass) / dist
            return (dx / dist) * force, (dy / dist) * force

        # Otherwise, resolve internal children recursively
        fx, fy = 0.0, 0.0
        if self.children:
            for child in self.children:
                cfx, cfy = child.compute_repulsion(nid, x, y, k2, theta)
                fx += cfx
                fy += cfy
        return fx, fy


class QuadTree:
    """Barnes-Hut Quadtree index for 2D particle simulation."""

    def __init__(self, bounds: tuple[float, float, float, float]):
        x_min, y_min, x_max, y_max = bounds
        span = max(x_max - x_min, y_max - y_min, 1.0)
        self.root = QuadTreeNode(x_min, y_min, x_min + span, y_min + span)

    def insert(self, nid: str, x: float, y: float, weight: float = 1.0) -> None:
        self.root.insert(nid, x, y, weight)

    def compute_force(self, nid: str, x: float, y: float, k: float, theta: float = 0.5) -> tuple[float, float]:
        k2 = k * k
        return self.root.compute_repulsion(nid, x, y, k2, theta)


BarnesHutQuadtree = QuadTree
