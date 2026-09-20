"""Tests for pure-Python VectorIndex, Cosine Similarity, and SIMILAR_TO edge generation."""
from corpusatlas.vector import VectorIndex, cosine_similarity, materialize_similarity_edges


def test_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    v4 = [0.7071, 0.7071, 0.0]

    assert abs(cosine_similarity(v1, v2) - 1.0) < 1e-4
    assert abs(cosine_similarity(v1, v3) - 0.0) < 1e-4
    assert abs(cosine_similarity(v1, v4) - 0.7071) < 1e-3


def test_vector_index_nearest_neighbor():
    idx = VectorIndex(dim=3)
    idx.add("python", [1.0, 0.1, 0.0])
    idx.add("ruby", [0.9, 0.2, 0.0])
    idx.add("elephant", [0.0, 0.0, 1.0])

    results = idx.query([1.0, 0.0, 0.0], top_k=2)
    assert len(results) == 2
    top_id, top_score, _ = results[0]
    assert top_id == "python"
    second_id, _, _ = results[1]
    assert second_id == "ruby"


def test_materialize_similarity_edges():
    graph = {
        "nodes": [
            {"id": "n1", "label": "Fast Database"},
            {"id": "n2", "label": "High Performance DB"},
            {"id": "n3", "label": "Giraffe Animal"},
        ],
        "edges": [],
    }
    embeddings = {
        "n1": [1.0, 0.8, 0.0],
        "n2": [0.95, 0.85, 0.0],
        "n3": [0.0, 0.1, 1.0],
    }

    updated = materialize_similarity_edges(graph, embeddings, threshold=0.9)
    assert len(updated["edges"]) == 1
    edge = updated["edges"][0]
    assert edge["rel"] == "SIMILAR_TO"
    assert {edge["src"], edge["dst"]} == {"n1", "n2"}
    assert edge["confidence"] >= 0.9
