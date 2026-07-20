"""Tier 1: recover the graph the author already wrote by hand.

Links, tags and published structured data are exact. No model can beat a
human who typed the relationship on purpose, so this runs first and the
extraction tier only fills the gaps it leaves.
"""
from __future__ import annotations

from ..model import Document, Edge, Node
from ..ontology import typecheck


class DeterministicExtractor:
    name = "deterministic@1"
    tier = "deterministic"

    def run(self, docs: list[Document]):
        nodes: dict[str, Node] = {}
        edges: list[Edge] = []
        types: dict[str, str] = {}

        def add(node: Node) -> None:
            nodes.setdefault(node.id, node)
            types[node.id] = node.type

        for d in docs:
            ntype = "Assessment" if d.kind == "assessment" else "Document"
            add(Node(id=d.id, label=d.title, type=ntype, url=d.url,
                     meta={k: v for k, v in (("date", d.date), ("kind", d.kind)) if v}))
            for t in d.tags:
                add(Node(id=f"topic:{t}", label=t.replace("-", " "), type="Topic"))
            for p in d.meta.get("platforms", []) or []:
                add(Node(id=f"tech:{_slug(p)}", label=p, type="Technology"))

        for d in docs:
            prov_base = {"doc": d.id, "tier": self.tier, "extractor": self.name}

            for target in d.links:
                if target in nodes:
                    edges.append(Edge(d.id, "REFERENCES", target, dict(prov_base, via="link")))

            for t in d.tags:
                edges.append(Edge(d.id, "ABOUT", f"topic:{t}", dict(prov_base, via="tag")))

            platforms = d.meta.get("platforms", []) or []
            for p in platforms:
                edges.append(Edge(d.id, "ASSESSES", f"tech:{_slug(p)}", dict(prov_base, via="scorecard")))

            # Options scored on the same axes were compared with each other.
            # Undirected in meaning, so emit one direction only and let the
            # renderer treat COMPARES_TO as symmetric.
            for i, a in enumerate(platforms):
                for b in platforms[i + 1:]:
                    edges.append(Edge(f"tech:{_slug(a)}", "COMPARES_TO", f"tech:{_slug(b)}",
                                      dict(prov_base, via="scorecard")))

        kept = [e for e in edges
                if e.src in types and e.dst in types
                and typecheck(e.rel, types[e.src], types[e.dst])]
        return nodes.values(), kept


def _slug(s: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in s)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")
