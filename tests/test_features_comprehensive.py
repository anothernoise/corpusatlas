"""Tests for the advanced CLI features:
- corpusatlas context: LLM Graph RAG subgraph formatter
- corpusatlas infer: co-occurrence & taxonomy edge inference
- corpusatlas build --layout: pre-calculated ForceAtlas2 coordinates
- corpusatlas diff --gui: visual delta graph exporter
- corpusatlas publish: zero-config static site distribution packager
- corpusatlas scaffold: TOML pack template generator
- corpusatlas watch: source file change watcher
"""
import io
import json
import os
import sys
import tempfile
import tomllib
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpusatlas.__main__ import main


SAMPLE_GRAPH = {
    "version": "2.0.0",
    "sources": ["test"],
    "nodes": [
        {
            "id": "entity:spark",
            "label": "Apache Spark",
            "type": "Technology",
            "url": "https://spark.apache.org",
            "description": "Unified analytics engine for large-scale data processing.",
            "degree": 3,
        },
        {
            "id": "entity:scala",
            "label": "Scala",
            "type": "Language",
            "description": "Object-oriented and functional language.",
            "degree": 1,
        },
        {
            "id": "entity:hadoop",
            "label": "Apache Hadoop",
            "type": "Technology",
            "description": "Framework for distributed storage and processing.",
            "degree": 2,
        },
        {
            "id": "entity:delta-lake",
            "label": "Delta Lake",
            "type": "TableFormat",
            "description": "Open-source storage framework.",
            "degree": 2,
        },
    ],
    "edges": [
        {
            "src": "entity:spark",
            "rel": "WRITTEN_IN",
            "dst": "entity:scala",
            "tier": "curated",
            "confidence": 1.0,
            "explanation": "Spark is primarily implemented in Scala.",
            "doc": "doc:spark-overview",
        },
        {
            "src": "entity:spark",
            "rel": "COMPATIBLE_WITH",
            "dst": "entity:hadoop",
            "tier": "curated",
            "confidence": 0.9,
            "explanation": "Runs on YARN and HDFS.",
            "doc": "doc:spark-overview",
        },
        {
            "src": "entity:delta-lake",
            "rel": "BUILT_FOR",
            "dst": "entity:spark",
            "tier": "deterministic",
            "confidence": 0.95,
            "explanation": "Delta Lake provides ACID transactions on top of Spark.",
            "doc": "doc:delta-overview",
        },
        {
            "src": "entity:delta-lake",
            "rel": "COMPATIBLE_WITH",
            "dst": "entity:hadoop",
            "tier": "deterministic",
            "confidence": 0.85,
            "doc": "doc:delta-overview",
        },
    ],
}


def test_context_markdown_format():
    with tempfile.TemporaryDirectory() as d:
        gpath = Path(d) / "graph.json"
        gpath.write_text(json.dumps(SAMPLE_GRAPH), encoding="utf-8")

        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main(["context", "--graph", str(gpath), "--entity", "spark", "--format", "markdown"])
        assert ret == 0
        out = buf.getvalue()
        assert "Apache Spark" in out
        assert "WRITTEN_IN" in out
        assert "Scala" in out
        assert "Delta Lake" in out
        assert "ACID transactions" in out


def test_context_json_format():
    with tempfile.TemporaryDirectory() as d:
        gpath = Path(d) / "graph.json"
        gpath.write_text(json.dumps(SAMPLE_GRAPH), encoding="utf-8")

        buf = io.StringIO()
        with redirect_stdout(buf):
            ret = main(["context", "--graph", str(gpath), "--entity", "entity:spark", "--format", "json"])
        assert ret == 0
        data = json.loads(buf.getvalue())
        assert data["entity"]["id"] == "entity:spark"
        assert len(data["outbound_edges"]) == 2
        assert len(data["inbound_edges"]) == 1
        assert data["inbound_edges"][0]["source"] == "entity:delta-lake"


def test_context_missing_entity_fails_gracefully():
    with tempfile.TemporaryDirectory() as d:
        gpath = Path(d) / "graph.json"
        gpath.write_text(json.dumps(SAMPLE_GRAPH), encoding="utf-8")
        ret = main(["context", "--graph", str(gpath), "--entity", "nonexistent-entity"])
        assert ret == 1


def test_infer_cooccurrence():
    with tempfile.TemporaryDirectory() as d:
        gpath = Path(d) / "graph.json"
        gpath.write_text(json.dumps(SAMPLE_GRAPH), encoding="utf-8")
        outpath = Path(d) / "inferred.json"

        # spark and hadoop share doc:spark-overview
        # delta-lake and hadoop share doc:delta-overview
        # spark and delta-lake share doc:spark-overview and doc:delta-overview
        ret = main(["infer", "--graph", str(gpath), "--out", str(outpath), "--threshold", "0.3", "--min-docs", "1"])
        assert ret == 0
        assert outpath.exists()
        inferred = json.loads(outpath.read_text(encoding="utf-8"))
        assert "inferred_edges" in inferred
        rel_types = {e["rel"] for e in inferred["inferred_edges"]}
        assert "CO_OCCURS_WITH" in rel_types


def test_diff_gui_output():
    with tempfile.TemporaryDirectory() as d:
        old_path = Path(d) / "old.json"
        new_path = Path(d) / "new.json"
        gui_path = Path(d) / "diff_gui.json"

        old_graph = {
            "version": "2.0.0",
            "nodes": [
                {"id": "a", "label": "A", "type": "Concept", "degree": 1},
                {"id": "b", "label": "B", "type": "Concept", "degree": 1},
            ],
            "edges": [{"src": "a", "rel": "CONNECTS", "dst": "b", "tier": "deterministic"}],
        }
        new_graph = {
            "version": "2.0.0",
            "nodes": [
                {"id": "a", "label": "A-Updated", "type": "Concept", "degree": 1},
                {"id": "c", "label": "C", "type": "Concept", "degree": 1},
            ],
            "edges": [{"src": "a", "rel": "CONNECTS", "dst": "c", "tier": "deterministic"}],
        }

        old_path.write_text(json.dumps(old_graph), encoding="utf-8")
        new_path.write_text(json.dumps(new_graph), encoding="utf-8")

        ret = main(["diff", "--old", str(old_path), "--new", str(new_path), "--gui", "--out", str(gui_path)])
        assert ret == 0
        assert gui_path.exists()
        diff_data = json.loads(gui_path.read_text(encoding="utf-8"))
        node_diffs = {n["id"]: n.get("diff") for n in diff_data["nodes"]}
        assert node_diffs["c"] == "added"
        assert node_diffs["b"] == "removed"
        assert node_diffs["a"] == "changed"


def test_publish_bundle():
    with tempfile.TemporaryDirectory() as d:
        gpath = Path(d) / "graph.json"
        gpath.write_text(json.dumps(SAMPLE_GRAPH), encoding="utf-8")
        dist = Path(d) / "dist"

        ret = main(["publish", "--graph", str(gpath), "--out-dir", str(dist)])
        assert ret == 0
        assert (dist / "index.html").exists()
        assert (dist / "style.css").exists()
        assert (dist / "app.js").exists()
        assert (dist / "graph.json").exists()
        published_graph = json.loads((dist / "graph.json").read_text(encoding="utf-8"))
        assert len(published_graph["nodes"]) == 4


def test_scaffold_pack():
    with tempfile.TemporaryDirectory() as d:
        out_toml = Path(d) / "pack.toml"
        ret = main(["scaffold", "--topic", "Vector Databases", "--out", str(out_toml)])
        assert ret == 0
        assert out_toml.exists()
        data = tomllib.loads(out_toml.read_text(encoding="utf-8"))
        assert "entity" in data
        assert "relation" in data
        assert any("Vector Databases" in str(v) for v in data.values())


def test_build_with_layout():
    # Build a tiny graph and verify coordinates x and y are assigned
    with tempfile.TemporaryDirectory() as d:
        corpus = Path(d) / "docs"
        corpus.mkdir()
        (corpus / "test.md").write_text("# Test\nTesting mentions.\n", encoding="utf-8")

        cfg = Path(d) / "corpusatlas.toml"
        cfg.write_text(f"""
sources = [{{ type = "obsidian", path = "{corpus.as_posix()}" }}]
""", encoding="utf-8")

        out = Path(d) / "graph.json"
        ret = main(["build", "--config", str(cfg), "--out", str(out), "--layout"])
        assert ret == 0
        assert out.exists()
        g = json.loads(out.read_text(encoding="utf-8"))
        for n in g["nodes"]:
            assert "x" in n
            assert "y" in n


if __name__ == "__main__":
    for name, val in list(globals().items()):
        if name.startswith("test_") and callable(val):
            val()
            print(f"PASS {name}")
    print("\nAll new feature tests passed!")

