"""Columnar and tabular data interoperability for CorpusAtlas.

Provides lazy-imported zero-copy and tabular conversions for:
- PyArrow (Tables / RecordBatches)
- Polars (DataFrames)
- Pandas (DataFrames)

Zero hard dependencies: third-party dataframe packages are only imported on demand.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .model import Edge, Node


def to_dict_records(
    nodes: Iterable[Node], edges: Iterable[Edge]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Convert nodes and edges into normalized flat dictionaries for tabular engines."""
    node_records: list[dict[str, Any]] = []
    for n in nodes:
        node_records.append(
            {
                "id": n.id,
                "label": n.label,
                "type": n.type,
                "url": n.url or "",
                "aliases": list(n.aliases),
                "aliases_json": json.dumps(list(n.aliases), ensure_ascii=False),
                "meta": n.meta,
                "meta_json": json.dumps(n.meta, ensure_ascii=False),
            }
        )

    edge_records: list[dict[str, Any]] = []
    for e in edges:
        edge_records.append(
            {
                "src": e.src,
                "rel": e.rel,
                "dst": e.dst,
                "confidence": e.confidence if e.confidence is not None else 1.0,
                "scope": e.scope or "",
                "explanation": e.explanation or "",
                "sources": list(e.sources),
                "prov": e.prov,
                "prov_json": json.dumps(e.prov, ensure_ascii=False),
            }
        )

    return node_records, edge_records


def to_arrow(nodes: Iterable[Node], edges: Iterable[Edge]) -> tuple[Any, Any]:
    """Convert nodes and edges into PyArrow Tables.

    Requires pyarrow. Install via `pip install "corpusatlas[pyarrow]"`.
    """
    try:
        import importlib
        pa = importlib.import_module("pyarrow")
    except ImportError as exc:
        raise ImportError(
            "pyarrow is required for to_arrow(). Install via 'pip install pyarrow' or 'pip install \"corpusatlas[pyarrow]\"'."
        ) from exc

    node_records, edge_records = to_dict_records(nodes, edges)
    # Simplify complex nested dicts to JSON strings for Arrow schema stability if needed
    arrow_nodes = [
        {k: v for k, v in r.items() if k not in ("aliases", "meta")}
        for r in node_records
    ]
    arrow_edges = [
        {k: v for k, v in r.items() if k not in ("sources", "prov")}
        for r in edge_records
    ]
    return pa.Table.from_pylist(arrow_nodes), pa.Table.from_pylist(arrow_edges)


def to_polars(nodes: Iterable[Node], edges: Iterable[Edge]) -> tuple[Any, Any]:
    """Convert nodes and edges into Polars DataFrames.

    Requires polars. Install via `pip install "corpusatlas[polars]"`.
    """
    try:
        import importlib
        pl = importlib.import_module("polars")
    except ImportError as exc:
        raise ImportError(
            "polars is required for to_polars(). Install via 'pip install polars' or 'pip install \"corpusatlas[polars]\"'."
        ) from exc

    node_records, edge_records = to_dict_records(nodes, edges)
    pl_nodes = [
        {k: v for k, v in r.items() if k not in ("aliases", "meta")}
        for r in node_records
    ]
    pl_edges = [
        {k: v for k, v in r.items() if k not in ("sources", "prov")}
        for r in edge_records
    ]
    return pl.DataFrame(pl_nodes), pl.DataFrame(pl_edges)


def to_pandas(nodes: Iterable[Node], edges: Iterable[Edge]) -> tuple[Any, Any]:
    """Convert nodes and edges into Pandas DataFrames.

    Requires pandas. Install via `pip install "corpusatlas[pandas]"`.
    """
    try:
        import importlib
        pd = importlib.import_module("pandas")
    except ImportError as exc:
        raise ImportError(
            "pandas is required for to_pandas(). Install via 'pip install pandas' or 'pip install \"corpusatlas[pandas]\"'."
        ) from exc

    node_records, edge_records = to_dict_records(nodes, edges)
    pd_nodes = [
        {k: v for k, v in r.items() if k not in ("aliases", "meta")}
        for r in node_records
    ]
    pd_edges = [
        {k: v for k, v in r.items() if k not in ("sources", "prov")}
        for r in edge_records
    ]
    return pd.DataFrame(pd_nodes), pd.DataFrame(pd_edges)


@dataclass
class GraphData:
    """In-memory or loaded graph representation with multi-format export capabilities."""

    nodes: list[Node]
    edges: list[Edge]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return canonical graph dictionary representation."""
        node_records, edge_records = to_dict_records(self.nodes, self.edges)
        res = dict(self.metadata)
        res["counts"] = {"nodes": len(self.nodes), "edges": len(self.edges)}
        res["nodes"] = [n.to_json() for n in self.nodes]
        res["edges"] = [e.to_json() for e in self.edges]
        return res

    def to_arrow(self) -> tuple[Any, Any]:
        return to_arrow(self.nodes, self.edges)

    def to_polars(self) -> tuple[Any, Any]:
        return to_polars(self.nodes, self.edges)

    def to_pandas(self) -> tuple[Any, Any]:
        return to_pandas(self.nodes, self.edges)


def load_graph(path: str | Path) -> GraphData:
    """Load a graph.json file into a GraphData container."""
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))

    nodes: list[Node] = []
    for n in raw.get("nodes", []):
        nodes.append(
            Node(
                id=n["id"],
                label=n.get("label", n["id"]),
                type=n.get("type", "Concept"),
                url=n.get("url"),
                meta=n.get("meta", {}),
                aliases=tuple(n.get("aliases", ())),
                urls=n.get("urls", {}),
            )
        )

    edges: list[Edge] = []
    for e in raw.get("edges", []):
        edges.append(
            Edge(
                src=e["src"],
                rel=e["rel"],
                dst=e["dst"],
                prov=e.get("prov", {}),
                scope=e.get("scope"),
                confidence=e.get("confidence", 1.0),
                sources=tuple(e.get("sources", ())),
                explanation=e.get("explanation"),
            )
        )

    meta = {k: v for k, v in raw.items() if k not in ("nodes", "edges")}
    return GraphData(nodes=nodes, edges=edges, metadata=meta)
