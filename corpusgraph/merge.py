"""Merge extractor output into one graph — including retraction.

Append-only merge is the easy half. The half that rots quietly is retraction:
an edge is a claim made BY a document, so when a document disappears from the
corpus its claims have to go with it, or the graph slowly fills with assertions
from articles that no longer exist.
"""
from __future__ import annotations

from dataclasses import replace

from .model import Edge, Node  # noqa: F401

# Fields a later producer may fill in when the first writer left them empty.
# Never label, type or meta: those are the first writer's, and extractors run
# in precedence order precisely so that hand-written data wins.
ENRICHABLE = ("url", "aliases", "urls")


def merge(node_sets, edge_sets, live_doc_ids: set[str]):
    nodes: dict[str, Node] = {}
    for group in node_sets:
        for n in group:
            first = nodes.get(n.id)
            if first is None:
                nodes[n.id] = n
            elif first.type == n.type:
                fill = {f: getattr(n, f) for f in ENRICHABLE
                        if not getattr(first, f) and getattr(n, f)}
                if fill:
                    nodes[n.id] = replace(first, **fill)

    seen: dict[tuple, Edge] = {}
    for group in edge_sets:
        for e in group:
            # Retraction: drop any claim whose source document is gone.
            if e.prov.get("doc") and e.prov["doc"] not in live_doc_ids:
                continue
            seen.setdefault(e.key, e)

    edges = [e for e in seen.values() if e.src in nodes and e.dst in nodes]

    # Drop nodes nothing connects to. An isolated node is noise in a view whose
    # entire purpose is showing relationships.
    connected = {e.src for e in edges} | {e.dst for e in edges}
    nodes = {k: v for k, v in nodes.items() if k in connected}
    edges = [e for e in edges if e.src in nodes and e.dst in nodes]
    return nodes, edges
