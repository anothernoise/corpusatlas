"""Dense vector indexing, cosine similarity search, and semantic similarity edge materialization.

Enables hybrid symbolic-dense knowledge graph construction in pure standard library Python.
Zero external dependencies.
"""
from __future__ import annotations

import math
from typing import Any, Iterable


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two dense float vectors."""
    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        norm1 += a * a
        norm2 += b * b

    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (math.sqrt(norm1) * math.sqrt(norm2))


class VectorIndex:
    """Pure-Python exact nearest-neighbor vector similarity index."""

    def __init__(self, dim: int | None = None):
        self.dim = dim
        self.entries: list[tuple[str, list[float], dict[str, Any]]] = []

    def add(
        self,
        item_id: str,
        vector: list[float],
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.dim is not None and len(vector) != self.dim:
            raise ValueError(f"Expected vector of dimension {self.dim}, got {len(vector)}")
        self.entries.append((item_id, vector, metadata or {}))

    def query(
        self,
        query_vector: list[float],
        top_k: int = 10,
        threshold: float = 0.0,
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Query index for top_k nearest neighbors by cosine similarity."""
        scored = []
        for item_id, vec, meta in self.entries:
            sim = cosine_similarity(query_vector, vec)
            if sim >= threshold:
                scored.append((item_id, sim, meta))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def materialize_similarity_edges(
    graph_data: dict[str, Any],
    embeddings: dict[str, list[float]],
    threshold: float = 0.85,
    rel_name: str = "SIMILAR_TO",
) -> dict[str, Any]:
    """Calculate pairwise vector similarities and append SIMILAR_TO edges for scores >= threshold."""
    node_ids = sorted(list(embeddings.keys()))
    new_edges = list(graph_data.get("edges", []))
    existing_pairs = {(e["src"], e["dst"]) for e in new_edges}

    similarity_edge_count = 0
    for i in range(len(node_ids)):
        id_a = node_ids[i]
        vec_a = embeddings[id_a]
        for j in range(i + 1, len(node_ids)):
            id_b = node_ids[j]
            vec_b = embeddings[id_b]
            sim = cosine_similarity(vec_a, vec_b)
            if sim >= threshold:
                if (id_a, id_b) not in existing_pairs and (id_b, id_a) not in existing_pairs:
                    new_edges.append({
                        "src": id_a,
                        "rel": rel_name,
                        "dst": id_b,
                        "confidence": round(sim, 4),
                        "explanation": f"Semantic vector similarity {sim:.4f} >= threshold {threshold}",
                        "prov": {"type": "vector_similarity"},
                    })
                    existing_pairs.add((id_a, id_b))
                    similarity_edge_count += 1

    updated = dict(graph_data)
    updated["edges"] = new_edges
    updated["counts"] = {
        "nodes": len(updated.get("nodes", [])),
        "edges": len(new_edges),
    }
    updated["similarity_edges_added"] = similarity_edge_count
    return updated
