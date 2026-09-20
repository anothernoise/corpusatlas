"""Tests for pure-Python hierarchical community detection (modularity maximization)."""
import json
from corpusatlas.community import detect_communities, evaluate_modularity


def _create_two_cluster_graph():
    # Cluster A: tech:python, tech:duckdb, tech:sqlite (tightly linked)
    # Cluster B: bio:lion, bio:tiger, bio:cheetah (tightly linked)
    # Bridge: tech:python <-> bio:lion (weak bridge)
    nodes = [
        {"id": "tech:python", "label": "Python", "type": "Technology"},
        {"id": "tech:duckdb", "label": "DuckDB", "type": "Technology"},
        {"id": "tech:sqlite", "label": "SQLite", "type": "Technology"},
        {"id": "bio:lion", "label": "Lion", "type": "Mammal"},
        {"id": "bio:tiger", "label": "Tiger", "type": "Mammal"},
        {"id": "bio:cheetah", "label": "Cheetah", "type": "Mammal"},
    ]
    edges = [
        # Cluster A internal
        {"src": "tech:python", "dst": "tech:duckdb", "confidence": 1.0},
        {"src": "tech:duckdb", "dst": "tech:sqlite", "confidence": 1.0},
        {"src": "tech:sqlite", "dst": "tech:python", "confidence": 1.0},
        # Cluster B internal
        {"src": "bio:lion", "dst": "bio:tiger", "confidence": 1.0},
        {"src": "bio:tiger", "dst": "bio:cheetah", "confidence": 1.0},
        {"src": "bio:cheetah", "dst": "bio:lion", "confidence": 1.0},
        # Bridge
        {"src": "tech:python", "dst": "bio:lion", "confidence": 0.1},
    ]
    return nodes, edges


def test_community_detection_separates_clusters():
    nodes, edges = _create_two_cluster_graph()
    assignment, clusters = detect_communities(nodes, edges)

    # All cluster A members should share the same community ID
    c_python = assignment["tech:python"]
    assert assignment["tech:duckdb"] == c_python
    assert assignment["tech:sqlite"] == c_python

    # All cluster B members should share a different community ID
    c_lion = assignment["bio:lion"]
    assert assignment["bio:tiger"] == c_lion
    assert assignment["bio:cheetah"] == c_lion

    assert c_python != c_lion, f"Cluster A ({c_python}) and Cluster B ({c_lion}) should be distinct"
    assert len(clusters) == 2


def test_modularity_evaluation_positive():
    nodes, edges = _create_two_cluster_graph()
    assignment, _ = detect_communities(nodes, edges)
    q = evaluate_modularity(nodes, edges, assignment)
    assert q > 0.3, f"Expected high modularity for distinct clusters, got {q:.3f}"
