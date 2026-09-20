"""Dimensionality reduction and semantic embedding projections.

Computes 2D and 3D semantic coordinate maps from dense vector embeddings using fast,
zero-dependency Principal Component Analysis (PCA) via power iteration.
Zero external runtime dependencies.
"""
from __future__ import annotations

import math
import random
from typing import Any


def _dot(v1: list[float], v2: list[float]) -> float:
    return sum(a * b for a, b in zip(v1, v2))


def _norm(v: list[float]) -> float:
    return math.sqrt(sum(x * x for x in v))


def pca_project_embeddings(
    vectors: list[list[float]],
    n_components: int = 2,
    max_iter: int = 80,
    tol: float = 1e-6,
) -> list[list[float]]:
    """Projects high-dimensional vectors down to n_components using pure Python PCA."""
    n = len(vectors)
    if n == 0:
        return []
    dim = len(vectors[0])
    if dim == 0:
        return [[0.0] * n_components for _ in range(n)]

    # 1. Compute mean vector and center matrix
    mean = [sum(vectors[i][d] for i in range(n)) / n for d in range(dim)]
    centered = [[vectors[i][d] - mean[d] for d in range(dim)] for i in range(n)]

    components: list[list[float]] = []

    # 2. Extract principal components via Power Iteration with Deflation
    for comp_idx in range(min(n_components, dim)):
        # Initialize random non-zero unit vector
        v = [(random.random() - 0.5) for _ in range(dim)]
        v_norm = _norm(v)
        if v_norm == 0:
            v[0] = 1.0
            v_norm = 1.0
        v = [x / v_norm for x in v]

        for _ in range(max_iter):
            # Orthogonalize against previously found components (Gram-Schmidt)
            for prev_c in components:
                proj = _dot(v, prev_c)
                v = [v[d] - proj * prev_c[d] for d in range(dim)]

            # Power step: X^T * (X * v)
            # 1) y = X * v (length n)
            y = [_dot(centered[i], v) for i in range(n)]
            # 2) v_next = X^T * y (length dim)
            v_next = [sum(centered[i][d] * y[i] for i in range(n)) for d in range(dim)]

            norm_next = _norm(v_next)
            if norm_next < 1e-12:
                break
            v_next = [x / norm_next for x in v_next]

            # Check convergence
            diff = sum(abs(v_next[d] - v[d]) for d in range(dim))
            v = v_next
            if diff < tol:
                break

        components.append(v)

    # If requested components > dim, pad with zeros
    while len(components) < n_components:
        components.append([0.0] * dim)

    # 3. Project centered vectors onto components
    projected = []
    for i in range(n):
        coords = [_dot(centered[i], components[c]) for c in range(n_components)]
        projected.append(coords)

    # 4. Scale to viewer space (approximately [-600, 600])
    max_val = max(max(abs(c) for c in pt) for pt in projected) if projected else 1.0
    if max_val > 0:
        scale = 600.0 / max_val
        projected = [[round(coord * scale, 2) for coord in pt] for pt in projected]

    return projected


def compute_graph_semantic_projection(
    graph_data: dict[str, Any],
    n_components: int = 3,
) -> dict[str, Any]:
    """Annotates nodes in graph_data with semantic_x, semantic_y, semantic_z coordinates."""
    nodes = graph_data.get("nodes", [])
    if not nodes:
        return graph_data

    # Collect vectors from nodes
    collected_vectors: list[list[float]] = []
    has_vectors = False

    for node in nodes:
        meta = node.setdefault("meta", {})
        vec = meta.get("vector")
        if vec and isinstance(vec, list) and len(vec) > 0:
            collected_vectors.append([float(x) for x in vec])
            has_vectors = True
        else:
            # Fallback deterministic pseudo-vector from node ID hash
            h = hash(node.get("id", ""))
            pseudo = [((h >> (i * 4)) & 0xF) / 15.0 - 0.5 for i in range(8)]
            collected_vectors.append(pseudo)

    coords = pca_project_embeddings(collected_vectors, n_components=max(3, n_components))

    for i, node in enumerate(nodes):
        meta = node.setdefault("meta", {})
        pt = coords[i]
        meta["semantic_x"] = pt[0]
        meta["semantic_y"] = pt[1]
        meta["semantic_z"] = pt[2] if len(pt) > 2 else 0.0

    return graph_data
