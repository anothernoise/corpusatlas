"""Adapter for tabular data sources (Polars, Pandas, PyArrow, or list of dicts).

Enables importing knowledge graph nodes and edges directly from tabular structures
without requiring third-party libraries to be installed if using standard dicts.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, Iterator

from ..model import Document, Edge, Node


def _to_records(data: Any) -> list[dict[str, Any]]:
    """Normalize Polars / Pandas / PyArrow / iterable of dicts into list[dict]."""
    if data is None:
        return []
    # Polars DataFrame
    if hasattr(data, "to_dicts") and callable(data.to_dicts):
        return data.to_dicts()
    # PyArrow Table / RecordBatch
    if hasattr(data, "to_pylist") and callable(data.to_pylist):
        return data.to_pylist()
    # Pandas DataFrame
    if hasattr(data, "to_dict") and callable(data.to_dict):
        try:
            return data.to_dict(orient="records")
        except TypeError:
            pass
    # Iterable of dicts
    if isinstance(data, Iterable):
        return [dict(item) for item in data]
    return []


class DataFrameAdapter:
    """Ingests nodes and edges directly from tabular data structures."""

    def __init__(
        self,
        nodes_data: Any = None,
        edges_data: Any = None,
        source_name: str = "dataframe",
    ):
        self.source_name = source_name
        self.raw_nodes = _to_records(nodes_data)
        self.raw_edges = _to_records(edges_data)

    def documents(self) -> Iterator[Document]:
        """Yield Document representations from tabular rows or a synthetic dataset Document."""
        has_doc = False
        for r in self.raw_nodes:
            if r.get("type") == "Document" or str(r.get("id", "")).startswith("doc:"):
                has_doc = True
                nid = str(r["id"])
                label = str(r.get("label", nid))
                meta = r.get("meta", {})
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {"raw": meta}
                text = str(r.get("text", f"{label} " + json.dumps(meta, ensure_ascii=False)))
                yield Document(
                    id=nid,
                    title=label,
                    url=str(r.get("url", f"local://{nid}")),
                    kind=str(r.get("kind", "dataframe")),
                    text=text,
                    meta=meta,
                )
        if not has_doc:
            doc_id = f"doc:{self.source_name}"
            summary = (
                f"Tabular source '{self.source_name}' containing "
                f"{len(self.raw_nodes)} nodes and {len(self.raw_edges)} edges."
            )
            yield Document(
                id=doc_id,
                title=f"Dataset: {self.source_name}",
                url=f"local://{self.source_name}",
                kind="dataframe",
                text=summary,
                meta={
                    "node_count": len(self.raw_nodes),
                    "edge_count": len(self.raw_edges),
                },
            )

    def nodes(self) -> Iterator[Node]:
        """Yield parsed Node objects from tabular data."""
        for r in self.raw_nodes:
            nid = str(r["id"])
            label = str(r.get("label", nid))
            ntype = str(r.get("type", "Concept"))
            meta = r.get("meta", {})
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except Exception:
                    meta = {"raw": meta}
            aliases = r.get("aliases", ())
            if isinstance(aliases, list):
                aliases = tuple(aliases)
            yield Node(
                id=nid,
                label=label,
                type=ntype,
                url=r.get("url"),
                meta=meta,
                aliases=aliases,
                urls=r.get("urls", {}),
            )

    def edges(self) -> Iterator[Edge]:
        """Yield parsed Edge objects from tabular data."""
        for r in self.raw_edges:
            src = str(r["src"])
            rel = str(r.get("rel", "relates_to"))
            dst = str(r["dst"])
            conf = float(r.get("confidence", 1.0))
            scope = r.get("scope")
            expl = r.get("explanation")
            prov = r.get("prov", {"doc": f"doc:{self.source_name}"})
            if isinstance(prov, str):
                try:
                    prov = json.loads(prov)
                except Exception:
                    prov = {"doc": prov}
            sources = r.get("sources", ())
            if isinstance(sources, list):
                sources = tuple(sources)
            yield Edge(
                src=src,
                rel=rel,
                dst=dst,
                confidence=conf,
                scope=scope,
                explanation=expl,
                prov=prov,
                sources=sources,
            )
