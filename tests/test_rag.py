"""Tests for Phase 2: GraphRAG Context Extractor and NL Graph Query."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from corpusatlas.nl_query import execute_nl_query, parse_nl_query
from corpusatlas.rag import extract_rag_context


def _sample_graph_data():
    return {
        "nodes": [
            {"id": "entity:spark", "label": "Apache Spark", "type": "Technology", "meta": {"description": "Unified engine for large-scale data analytics"}},
            {"id": "entity:kafka", "label": "Apache Kafka", "type": "Technology", "meta": {"description": "Distributed event streaming platform"}},
            {"id": "entity:streaming", "label": "Spark Streaming", "type": "Component", "meta": {"description": "Micro-batch streaming engine"}},
            {"id": "entity:postgres", "label": "PostgreSQL", "type": "Technology", "meta": {"description": "Relational database"}},
            {"id": "entity:airflow", "label": "Apache Airflow", "type": "Technology", "meta": {"description": "Workflow orchestration platform"}},
        ],
        "edges": [
            {"source": "entity:streaming", "target": "entity:spark", "rel": "component_of", "tier": "deterministic"},
            {"source": "entity:streaming", "target": "entity:kafka", "rel": "consumes", "tier": "deterministic"},
            {"source": "entity:spark", "target": "entity:postgres", "rel": "writes_to", "tier": "deterministic"},
            {"source": "entity:airflow", "target": "entity:spark", "rel": "orchestrates", "tier": "deterministic"},
            {"source": "entity:postgres", "target": "entity:spark", "rel": "compares_with", "tier": "packs"},
        ],
        "documents": [
            {"id": "doc:spark-overview", "title": "Spark Analytics Guide", "text": "Spark works with Kafka and PostgreSQL."},
        ],
    }


def test_extract_rag_context_finds_seed_and_khop_neighbors():
    graph = _sample_graph_data()
    ctx = extract_rag_context(graph, query="Spark Streaming", k_hops=1, token_budget=1000)

    assert "seeds" in ctx
    seed_ids = [s["id"] for s in ctx["seeds"]]
    assert "entity:streaming" in seed_ids

    # Neighbors should include Spark and Kafka within 1 hop
    neighbor_ids = [n["id"] for n in ctx["nodes"]]
    assert "entity:spark" in neighbor_ids
    assert "entity:kafka" in neighbor_ids

    # Prompt text should be rendered and non-empty
    prompt = ctx["prompt_text"]
    assert "Apache Spark" in prompt
    assert "Apache Kafka" in prompt
    assert "component_of" in prompt


def test_extract_rag_context_respects_token_budget():
    graph = _sample_graph_data()
    # Very small token budget: ~30 tokens (approx 120 chars)
    ctx = extract_rag_context(graph, query="Spark", k_hops=2, token_budget=40)
    prompt = ctx["prompt_text"]
    # 40 tokens * 4 chars/token is 160 chars; prompt must not exceed reasonable bound
    assert len(prompt) < 400


def test_extract_rag_context_json_and_triples_format():
    graph = _sample_graph_data()
    json_ctx = extract_rag_context(graph, query="Kafka", format="json")
    assert isinstance(json_ctx, dict)
    assert len(json_ctx["nodes"]) >= 1

    md_ctx = extract_rag_context(graph, query="Kafka", format="markdown")
    assert isinstance(md_ctx["prompt_text"], str)
    assert "### Relevant Entities" in md_ctx["prompt_text"]


def test_nl_query_dependency_and_connections():
    graph = _sample_graph_data()

    # Query: What depends on Spark or orchestrates it?
    res = execute_nl_query(graph, "What connects to Spark?")
    assert res["matched_intent"] in ("connections", "dependencies")
    target_labels = [r["label"] for r in res["results"]]
    assert "Apache Airflow" in target_labels or "Spark Streaming" in target_labels


def test_nl_query_path_finding():
    graph = _sample_graph_data()

    # Query path from Airflow to Kafka
    res = execute_nl_query(graph, "How is Apache Airflow connected to Apache Kafka?")
    assert res["matched_intent"] == "path"
    assert "path" in res
    assert len(res["path"]) >= 2


def test_nl_query_comparisons():
    graph = _sample_graph_data()

    res = execute_nl_query(graph, "Compare PostgreSQL and Spark")
    assert res["matched_intent"] == "comparison"
    assert len(res["results"]) > 0


def test_cli_rag_and_query_subcommands():
    from corpusatlas.__main__ import main
    graph_data = _sample_graph_data()

    with tempfile.TemporaryDirectory() as td:
        gpath = Path(td) / "graph.json"
        gpath.write_text(json.dumps(graph_data), encoding="utf-8")

        # Test CLI rag
        ret = main(["rag", "--graph", str(gpath), "--query", "Spark", "--k-hops", "1"])
        assert ret == 0

        # Test CLI query --ask
        ret2 = main(["query", "--graph", str(gpath), "--ask", "What connects to Spark?"])
        assert ret2 == 0
