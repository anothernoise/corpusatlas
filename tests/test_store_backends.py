"""Tests for build --store memory | sqlite | duckdb backends."""
import json
import os
import tempfile
from pathlib import Path
from corpusatlas.model import Node, Edge
from corpusatlas.pipeline_store import SQLitePipelineStore


def test_sqlite_pipeline_store_compaction_and_streaming():
    """Verify SQLitePipelineStore deduplication, dangling pruning, and streaming."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_store.db"
        store = SQLitePipelineStore(db_path)

        # Tier 0: deterministic nodes & edges
        n1 = Node(id="tech:python", label="Python", type="Technology")
        n2 = Node(id="tech:duckdb", label="DuckDB", type="Technology")
        e1 = Edge(src="tech:python", rel="uses", dst="tech:duckdb", confidence=1.0)
        store.add_tier_nodes([n1, n2], tier_order=0)
        store.add_tier_edges([e1], tier_order=0)

        # Tier 1: packs with duplicate node but different tier
        n1_dup = Node(id="tech:python", label="Python Programming", type="Technology")
        n3 = Node(id="tech:sqlite", label="SQLite", type="Technology")
        e2 = Edge(src="tech:python", rel="uses", dst="tech:sqlite", confidence=0.9)
        # Dangling edge to non-existent node
        e_dangle = Edge(src="tech:python", rel="uses", dst="tech:unknown", confidence=0.5)
        store.add_tier_nodes([n1_dup, n3], tier_order=1)
        store.add_tier_edges([e2, e_dangle], tier_order=1)

        # Compact
        node_count, edge_count = store.compact()
        assert node_count == 3, f"Expected 3 nodes, got {node_count}"
        assert edge_count == 2, f"Expected 2 edges (dangling pruned), got {edge_count}"

        nodes = list(store.stream_nodes())
        edges = list(store.stream_edges())

        # First-writer-wins check for n1
        n_python = next(n for n in nodes if n.id == "tech:python")
        assert n_python.label == "Python", f"Expected 'Python', got '{n_python.label}'"

        store.close()
        assert db_path.exists()


def test_cmd_build_store_sqlite_and_memory_parity():
    """Verify build CLI produces valid graph output under both memory and sqlite stores."""
    from corpusatlas.__main__ import main

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg_path = root / "corpusatlas.toml"
        notes_dir = root / "notes"
        notes_dir.mkdir()
        (notes_dir / "a.md").write_text("# Note A\n[[Note B]]\n#topic\n", encoding="utf-8")
        (notes_dir / "b.md").write_text("# Note B\nSome text.\n", encoding="utf-8")

        cfg_path.write_text(f"""
[corpus]
name = "test"

[[sources]]
type = "obsidian"
path = "{notes_dir}"
""", encoding="utf-8")

        out_mem = root / "graph_mem.json"
        out_sql = root / "graph_sql.json"
        db_path = root / "staging.db"

        rc_mem = main(["build", "--config", str(cfg_path), "--out", str(out_mem), "--store", "memory"])
        assert rc_mem == 0

        rc_sql = main(["build", "--config", str(cfg_path), "--out", str(out_sql), "--store", "sqlite", "--db-path", str(db_path)])
        assert rc_sql == 0
        assert db_path.exists()

        g_mem = json.loads(out_mem.read_text(encoding="utf-8"))
        g_sql = json.loads(out_sql.read_text(encoding="utf-8"))

        assert g_mem["counts"]["nodes"] == g_sql["counts"]["nodes"]
        assert g_mem["counts"]["edges"] == g_sql["counts"]["edges"]

