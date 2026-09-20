"""Tests for Phase 3: SPARQL Engine, Graph Topology Analytics, and Architecture Linter."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from corpusatlas.analyze import analyze_graph_topology
from corpusatlas.lint import lint_graph
from corpusatlas.sparql import execute_sparql


def _sample_graph_data():
    return {
        "nodes": [
            {"id": "entity:frontend", "label": "Web UI", "type": "Application", "meta": {"owner": "team-a"}},
            {"id": "entity:api", "label": "API Gateway", "type": "Service", "meta": {"owner": "team-b"}},
            {"id": "entity:db", "label": "Primary DB", "type": "Database", "meta": {}},
            {"id": "entity:cache", "label": "Redis Cache", "type": "Database", "meta": {"owner": "team-b"}},
            {"id": "entity:isolated", "label": "Legacy Script", "type": "Tool", "meta": {}},
        ],
        "edges": [
            {"source": "entity:frontend", "target": "entity:api", "rel": "calls", "tier": "deterministic"},
            {"source": "entity:api", "target": "entity:db", "rel": "queries", "tier": "deterministic"},
            {"source": "entity:api", "target": "entity:cache", "rel": "reads_from", "tier": "deterministic"},
            {"source": "entity:frontend", "target": "entity:db", "rel": "direct_query", "tier": "deterministic"},  # anti-pattern!
        ],
    }


def test_sparql_triple_pattern_matching():
    graph = _sample_graph_data()

    # Query all nodes that query something
    query = """
    SELECT ?s ?o WHERE {
        ?s :queries ?o .
    }
    """
    res = execute_sparql(graph, query)
    assert len(res) == 1
    assert res[0]["s"] == "entity:api"
    assert res[0]["o"] == "entity:db"


def test_sparql_type_and_rel_conjunction():
    graph = _sample_graph_data()

    query = """
    SELECT ?x WHERE {
        ?x a :Application .
    }
    """
    res = execute_sparql(graph, query)
    assert len(res) == 1
    assert res[0]["x"] == "entity:frontend"


def test_graph_topology_analytics():
    graph = _sample_graph_data()
    metrics = analyze_graph_topology(graph)

    assert "num_nodes" in metrics
    assert metrics["num_nodes"] == 5
    assert metrics["num_edges"] == 4
    assert metrics["num_orphans"] == 1
    assert "entity:isolated" in metrics["orphan_node_ids"]
    assert "density" in metrics
    assert "articulation_points" in metrics
    # Node "entity:api" or others might be articulation points
    assert isinstance(metrics["articulation_points"], list)
    assert "health_score" in metrics


def test_architecture_linter_forbidden_relations():
    graph = _sample_graph_data()
    rules = {
        "forbidden_edges": [
            {
                "source_type": "Application",
                "rel": "direct_query",
                "target_type": "Database",
                "message": "Applications must not directly query databases; use API layer.",
            }
        ]
    }
    violations = lint_graph(graph, rules)
    errors = [v for v in violations if v["severity"] == "error"]
    assert len(errors) == 1
    assert "directly query" in errors[0]["message"] or "direct_query" in errors[0]["message"]


def test_architecture_linter_required_attributes():
    graph = _sample_graph_data()
    rules = {
        "required_node_attributes": [
            {
                "type": "Database",
                "attribute": "owner",
                "message": "All databases must specify an owner in metadata.",
            }
        ]
    }
    violations = lint_graph(graph, rules)
    # entity:db has empty meta, so it misses "owner"
    db_violations = [v for v in violations if v.get("node_id") == "entity:db"]
    assert len(db_violations) == 1


def test_architecture_linter_cycle_detection():
    cyclic_graph = {
        "nodes": [
            {"id": "a", "label": "A", "type": "Service"},
            {"id": "b", "label": "B", "type": "Service"},
        ],
        "edges": [
            {"source": "a", "target": "b", "rel": "depends_on"},
            {"source": "b", "target": "a", "rel": "depends_on"},
        ],
    }
    rules = {"acyclic_relations": ["depends_on"]}
    violations = lint_graph(cyclic_graph, rules)
    cycle_errs = [v for v in violations if "cycle" in v["message"].lower()]
    assert len(cycle_errs) > 0


def test_cli_sparql_analyze_lint_subcommands():
    from corpusatlas.__main__ import main
    graph_data = _sample_graph_data()

    with tempfile.TemporaryDirectory() as td:
        gpath = Path(td) / "graph.json"
        gpath.write_text(json.dumps(graph_data), encoding="utf-8")

        # Test SPARQL
        ret = main(["sparql", "--graph", str(gpath), "--query", "SELECT ?s WHERE { ?s a :Application }"])
        assert ret == 0

        # Test Analyze
        ret2 = main(["analyze", "--graph", str(gpath), "--json"])
        assert ret2 == 0

        # Test Lint
        rpath = Path(td) / "rules.toml"
        rpath.write_text("""
        [[forbidden_edges]]
        source_type = "Application"
        rel = "direct_query"
        target_type = "Database"
        message = "No direct DB query"
        """, encoding="utf-8")
        ret3 = main(["lint", "--graph", str(gpath), "--rules", str(rpath)])
        assert ret3 == 1  # Fails with exit code 1 because violation found
