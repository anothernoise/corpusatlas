"""Tier 1: recover the graph the author already wrote by hand.

Links, tags and published structured data are exact. No model can beat a
human who typed the relationship on purpose, so this runs first and the
extraction tier only fills the gaps it leaves.
"""
from __future__ import annotations

from ..model import Document, Edge, Node
from ..ontology import typecheck
from ..resolve import Resolver

# A source document's kind decides what kind of node it becomes. Anything
# unlisted is an ordinary Document.
NODE_KIND = {"assessment": "Assessment", "radar-entry": "RadarEntry"}

# Which of a radar entry's fields survive onto the published node. The ring and
# the edition are the claim, so they live here on the dated entry — never on the
# technology it names.
RADAR_META = ("entry", "quadrant", "ring", "category", "reviewed", "edition", "history")


class DeterministicExtractor:
    name = "deterministic@1"
    tier = "deterministic"

    def __init__(self, resolver: Resolver | None = None):
        # An empty resolver still slugs, so this works with no alias table at
        # all — the table only ever adds judgement calls on top.
        self.resolver = resolver or Resolver()

    def run(self, docs: list[Document]):
        nodes: dict[str, Node] = {}
        edges: list[Edge] = []
        types: dict[str, str] = {}

        def add(node: Node) -> None:
            nodes.setdefault(node.id, node)
            types[node.id] = node.type

        for d in docs:
            ntype = NODE_KIND.get(d.kind, "Document")
            if ntype == "RadarEntry":
                meta = {k: d.meta[k] for k in RADAR_META if d.meta.get(k)}
            else:
                meta = {k: v for k, v in (("date", d.date), ("kind", d.kind)) if v}
            add(Node(id=d.id, label=d.title, type=ntype, url=d.url, meta=meta))

            for t in d.tags:
                add(Node(id=f"topic:{t}", label=t.replace("-", " "), type="Topic"))
            for p in d.meta.get("platforms", []) or []:
                add(Node(id=self.resolver.resolve(p, "tech"), label=p, type="Technology"))

            if d.kind == "radar-entry":
                for p in d.meta.get("options") or []:
                    add(Node(id=self.resolver.resolve(p, "tech"), label=p, type="Technology"))
                aliased = self.resolver.resolve(d.meta.get("entry", ""), "radar")
                if aliased:
                    add(Node(id=aliased, label=self.resolver.label(aliased) or d.title,
                             type="Technology"))

        for d in docs:
            prov_base = {"doc": d.id, "tier": self.tier, "extractor": self.name}

            for target in d.links:
                if target in nodes:
                    edges.append(Edge(d.id, "REFERENCES", target, dict(prov_base, via="link")))

            for t in d.tags:
                edges.append(Edge(d.id, "ABOUT", f"topic:{t}", dict(prov_base, via="tag")))
                # A tag that names a technology is also a statement that the
                # article covers it. Only the alias table can say which tags
                # those are — "spark" is a technology, "olap" is a subject.
                tech = self.resolver.resolve(t, "tag")
                if tech:
                    edges.append(Edge(d.id, "COVERS", tech, dict(prov_base, via="tag-alias")))

            platforms = d.meta.get("platforms", []) or []
            for p in platforms:
                edges.append(Edge(d.id, "ASSESSES", self.resolver.resolve(p, "tech"),
                                  dict(prov_base, via="scorecard")))

            # Options scored on the same axes were compared with each other.
            # Undirected in meaning, so emit one direction only and let the
            # renderer treat COMPARES_TO as symmetric.
            for i, a in enumerate(platforms):
                for b in platforms[i + 1:]:
                    edges.append(Edge(self.resolver.resolve(a, "tech"), "COMPARES_TO",
                                      self.resolver.resolve(b, "tech"),
                                      dict(prov_base, via="scorecard")))

            if d.kind == "radar-entry":
                edges.extend(self._radar_edges(d, prov_base))

        kept = [e for e in edges
                if e.src in types and e.dst in types
                and typecheck(e.rel, types[e.src], types[e.dst])]
        return nodes.values(), kept

    def _radar_edges(self, d: Document, prov_base: dict) -> list[Edge]:
        """The three joins that put the radar's dated calls into the graph."""
        out: list[Edge] = []
        options = d.meta.get("options") or []
        for p in options:
            out.append(Edge(self.resolver.resolve(p, "tech"), "HAS_RADAR_ENTRY", d.id,
                            dict(prov_base, via="radar-scorecard-option")))
        if not options:
            # No scorecard to join on. The alias table names the technology when
            # there is one; an entry naming a practice resolves to nothing and
            # carries no technology edge, which is the honest answer rather than
            # inventing a product to hang it from.
            aliased = self.resolver.resolve(d.meta.get("entry", ""), "radar")
            if aliased:
                out.append(Edge(aliased, "HAS_RADAR_ENTRY", d.id,
                                dict(prov_base, via="radar-alias")))
        if d.meta.get("assessment"):
            out.append(Edge(d.id, "ASSESSED_IN", f"assessment:{d.meta['assessment']}",
                            dict(prov_base, via="radar-scorecard")))
        if d.meta.get("documented_in"):
            out.append(Edge(d.id, "DOCUMENTED_IN", d.meta["documented_in"],
                            dict(prov_base, via="radar-url")))
        return out
