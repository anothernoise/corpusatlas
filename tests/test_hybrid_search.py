"""Tests for BM25 and Hybrid Graph RAG Search with Reciprocal Rank Fusion."""
import json
import tempfile
from pathlib import Path
from corpusatlas.hybrid_search import BM25Ranker, reciprocal_rank_fusion, hybrid_graph_search


def _sample_search_graph():
    return {
        "schema_version": 2,
        "counts": {"nodes": 4, "edges": 3},
        "nodes": [
            {"id": "tech:python", "label": "Python Programming Language", "type": "Technology", "meta": {"desc": "Dynamic scripting language for data science"}},
            {"id": "tech:duckdb", "label": "DuckDB Database", "type": "Technology", "meta": {"desc": "Fast analytical in-process SQL database"}},
            {"id": "tech:sqlite", "label": "SQLite Database", "type": "Technology", "meta": {"desc": "Self-contained serverless SQL database engine"}},
            {"id": "concept:sql", "label": "Structured Query Language", "type": "Concept", "meta": {"desc": "Language for relational databases"}},
        ],
        "edges": [
            {"src": "tech:duckdb", "rel": "implements", "dst": "concept:sql", "confidence": 1.0},
            {"src": "tech:sqlite", "rel": "implements", "dst": "concept:sql", "confidence": 1.0},
            {"src": "tech:python", "rel": "uses", "dst": "tech:duckdb", "confidence": 0.95},
        ],
    }


def test_bm25_ranker_relevance():
    graph = _sample_search_graph()
    corpus_docs = []
    for n in graph["nodes"]:
        text = f"{n['label']} {n.get('meta', {}).get('desc', '')}"
        corpus_docs.append((n["id"], text))

    ranker = BM25Ranker(corpus_docs)
    scores = ranker.search("analytical database sql")
    assert len(scores) > 0
    top_id, top_score = scores[0]
    assert top_id == "tech:duckdb", f"Expected DuckDB to top score for analytical database, got {top_id}"


def test_reciprocal_rank_fusion():
    ranking1 = ["doc1", "doc2", "doc3"]
    ranking2 = ["doc2", "doc1", "doc4"]
    fused = reciprocal_rank_fusion([ranking1, ranking2], k=60)
    # doc1 and doc2 should be at the top
    assert fused[0][0] in ("doc1", "doc2")
    assert fused[1][0] in ("doc1", "doc2")
    assert fused[2][0] in ("doc3", "doc4")


def test_hybrid_graph_search_end_to_end():
    graph = _sample_search_graph()
    res = hybrid_graph_search(graph, query="database", top_k=3)
    assert "nodes" in res
    assert len(res["nodes"]) <= 3
    node_ids = [n["id"] for n in res["nodes"]]
    # Should find SQL / Database related nodes
    assert any("database" in n["label"].lower() or "sql" in n["label"].lower() for n in res["nodes"])
