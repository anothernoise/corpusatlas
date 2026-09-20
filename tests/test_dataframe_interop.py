import sys
import tempfile
from pathlib import Path
from corpusatlas.model import Node, Edge
from corpusatlas.dataframe import (
    to_dict_records,
    to_arrow,
    to_polars,
    to_pandas,
    load_graph,
    GraphData,
)
from corpusatlas.adapters.dataframe import DataFrameAdapter


def test_dataframe_interop_dict_records():
    nodes = [
        Node(id="tech:python", label="Python", type="Technology", meta={"version": "3.12"}),
        Node(id="tech:rust", label="Rust", type="Technology"),
    ]
    edges = [
        Edge(src="tech:python", rel="interops_with", dst="tech:rust", confidence=0.95),
    ]

    node_recs, edge_recs = to_dict_records(nodes, edges)
    assert len(node_recs) == 2
    assert node_recs[0]["id"] == "tech:python"
    assert node_recs[0]["type"] == "Technology"
    assert len(edge_recs) == 1
    assert edge_recs[0]["src"] == "tech:python"
    assert edge_recs[0]["rel"] == "interops_with"
    assert edge_recs[0]["confidence"] == 0.95


def test_dataframe_interop_lazy_imports_and_conversions():
    nodes = [Node(id="a", label="Alpha", type="Concept")]
    edges = [Edge(src="a", rel="relates", dst="a", confidence=1.0)]

    # If pyarrow is present, test conversion; if not, test graceful ImportError
    try:
        import pyarrow as pa
        node_table, edge_table = to_arrow(nodes, edges)
        assert isinstance(node_table, pa.Table)
        assert len(node_table) == 1
        assert "id" in node_table.column_names
    except ImportError:
        try:
            to_arrow(nodes, edges)
            assert False, "Should have raised ImportError"
        except ImportError as e:
            assert "pyarrow" in str(e).lower()

    # Test polars
    try:
        import polars as pl
        node_df, edge_df = to_polars(nodes, edges)
        assert isinstance(node_df, pl.DataFrame)
        assert len(node_df) == 1
        assert "id" in node_df.columns
    except ImportError:
        try:
            to_polars(nodes, edges)
            assert False, "Should have raised ImportError"
        except ImportError as e:
            assert "polars" in str(e).lower()

    # Test pandas
    try:
        import pandas as pd
        node_df, edge_df = to_pandas(nodes, edges)
        assert isinstance(node_df, pd.DataFrame)
        assert len(node_df) == 1
        assert "id" in node_df.columns
    except ImportError:
        try:
            to_pandas(nodes, edges)
            assert False, "Should have raised ImportError"
        except ImportError as e:
            assert "pandas" in str(e).lower()


def test_graph_data_wrapper_and_load_graph():
    nodes = [Node(id="n1", label="Node 1", type="Concept")]
    edges = [Edge(src="n1", rel="links", dst="n1", confidence=0.8)]
    g = GraphData(nodes=nodes, edges=edges, metadata={"schema_version": 2})

    recs = g.to_dict()
    assert len(recs["nodes"]) == 1
    assert len(recs["edges"]) == 1

    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "test_graph.json"
        import json
        p.write_text(json.dumps({
            "schema_version": 2,
            "counts": {"nodes": 1, "edges": 1},
            "nodes": [{"id": "n1", "label": "Node 1", "type": "Concept"}],
            "edges": [{"src": "n1", "rel": "links", "dst": "n1", "confidence": 0.8}],
        }), encoding="utf-8")

        loaded = load_graph(p)
        assert len(loaded.nodes) == 1
        assert len(loaded.edges) == 1
        assert loaded.nodes[0].id == "n1"


def test_dataframe_adapter():
    node_records = [
        {"id": "doc:1", "label": "First Document", "type": "Document", "meta": {"author": "Alice"}},
        {"id": "tech:python", "label": "Python", "type": "Technology"},
    ]
    edge_records = [
        {"src": "doc:1", "rel": "mentions", "dst": "tech:python", "confidence": 0.99},
    ]

    adapter = DataFrameAdapter(nodes_data=node_records, edges_data=edge_records, source_name="test_source")
    docs = list(adapter.documents())
    assert len(docs) == 1
    assert docs[0].kind == "dataframe"
    assert "Alice" in docs[0].text or "First Document" in docs[0].text

    raw_nodes = list(adapter.nodes())
    raw_edges = list(adapter.edges())
    assert len(raw_nodes) == 2
    assert raw_nodes[0].id == "doc:1"
    assert len(raw_edges) == 1
    assert raw_edges[0].src == "doc:1"
