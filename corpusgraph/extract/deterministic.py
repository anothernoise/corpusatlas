"""Tier 1: recover the graph the author already wrote by hand.

Links, tags and published structured data are exact. No model can beat a
human who typed the relationship on purpose, so this runs first and the other
tiers only fill the gaps it leaves.

Entities come from the registry, never straight from a scorecard's option
strings: an option names a choice in a comparison, and the registry says which
entity (or entities) that choice is.
"""
from __future__ import annotations

from ..model import Document, Edge, Node
from ..ontology import typecheck
from ..resolve import Resolver

# A source document's kind decides what kind of context node it becomes.
NODE_KIND = {"assessment": "Assessment", "radar-entry": "RadarEntry"}

# Which of a radar entry's fields survive onto the published node. The ring and
# the edition are the claim, so they live on the dated entry — never on the
# entity it names.
RADAR_META = ("entry", "quadrant", "ring", "category", "reviewed", "edition", "history")

# An option the registry has never heard of still gets a node, typed as the
# most common kind, so the package works with no registry at all.
# validate_entities.py is what stops an unregistered option from shipping.
FALLBACK_TYPE = "Technology"


def entity_node(resolver: Resolver, eid: str, fallback_label: str) -> Node:
    e = resolver.entity(eid)
    if e is None:
        return Node(id=eid, label=fallback_label, type=FALLBACK_TYPE)
    urls = {k: v for k, v in (("wikipedia", e.get("wikipedia_url")),
                              ("canonical", e.get("canonical_url"))) if v}
    meta = {"notes": e["classification_notes"]} if e.get("classification_notes") else {}
    return Node(id=eid, label=e["name"], type=e["type"], aliases=tuple(e.get("aliases", ())),
                urls=urls, meta=meta)


class DeterministicExtractor:
    name = "deterministic@2"
    tier = "deterministic"

    def __init__(self, resolver: Resolver | None = None):
        # An empty resolver still slugs, so this works with no registry at
        # all — the registry only ever adds identity and types on top.
        self.resolver = resolver or Resolver()

    def run(self, docs: list[Document]):
        nodes: dict[str, Node] = {}
        edges: list[Edge] = []
        types: dict[str, str] = {}
        r = self.resolver

        def add(node: Node) -> None:
            if node.id not in nodes:
                nodes[node.id] = node
                types[node.id] = node.type

        def add_entities(raw: str, kind: str) -> list[str]:
            ids = r.resolve(raw, kind)
            for eid in ids:
                add(entity_node(r, eid, raw))
            return ids

        # Every registered entity is a node, whether or not a scorecard, radar
        # entry or tag happens to name it: the registry is the vocabulary the
        # other tiers link to. One nothing connects is pruned at merge.
        for eid, e in r.entities():
            add(entity_node(r, eid, e["name"]))

        # Packs belong to the curated tier. Letting them through here would turn
        # every pack file into a spurious Document node.
        docs = [d for d in docs if d.kind != "entity-pack"]

        for d in docs:
            ntype = NODE_KIND.get(d.kind, "Document")
            if ntype == "RadarEntry":
                meta = {k: d.meta[k] for k in RADAR_META if d.meta.get(k)}
            else:
                meta = {k: v for k, v in (("date", d.date), ("kind", d.kind)) if v}
            add(Node(id=d.id, label=d.title, type=ntype, url=d.url, meta=meta))
            for t in d.tags:
                add(Node(id=f"topic:{t}", label=t.replace("-", " "), type="Topic"))
                add_entities(t, "tag")
            for p in d.meta.get("platforms", []) or []:
                add_entities(p, "option")
            if d.kind == "radar-entry":
                for p in d.meta.get("options") or []:
                    add_entities(p, "option")
                add_entities(d.meta.get("entry", ""), "radar")

        for d in docs:
            prov = {"doc": d.id, "tier": self.tier, "extractor": self.name}

            for target in d.links:
                if target in nodes:
                    edges.append(Edge(d.id, "REFERENCES", target, dict(prov, via="link")))

            for t in d.tags:
                edges.append(Edge(d.id, "ABOUT", f"topic:{t}", dict(prov, via="tag")))
                # A tag that names an entity is also a statement that the
                # article covers it. Only the registry can say which tags
                # those are — "spark" is a technology, "architecture" is not.
                for eid in r.resolve(t, "tag"):
                    edges.append(Edge(d.id, "COVERS", eid, dict(prov, via="tag")))

            platforms = d.meta.get("platforms", []) or []
            resolved = [(p, r.resolve(p, "option")) for p in platforms]
            for _, ids in resolved:
                for eid in ids:
                    edges.append(Edge(d.id, "ASSESSES", eid, dict(prov, via="scorecard")))
            # Options scored on the same axes were compared with each other.
            # A split option fans out, but its own parts were never compared
            # with each other — Arrow and DataFusion were one choice. Stored
            # once per unordered pair; COMPARES_TO is symmetric.
            pairs = set()
            for i, (_, a_ids) in enumerate(resolved):
                for _, b_ids in resolved[i + 1:]:
                    for a in a_ids:
                        for b in b_ids:
                            if a != b:
                                pairs.add(tuple(sorted((a, b))))
            for a, b in sorted(pairs):
                edges.append(Edge(a, "COMPARES_TO", b, dict(prov, via="scorecard")))

            if d.kind == "radar-entry":
                edges.extend(self._radar_edges(d, prov))

        kept = [e for e in edges
                if e.src in types and e.dst in types
                and typecheck(e.rel, types[e.src], types[e.dst])]
        return list(nodes.values()), kept

    def _radar_edges(self, d: Document, prov: dict) -> list[Edge]:
        """The three joins that put the radar's dated calls into the graph."""
        r = self.resolver
        out: list[Edge] = []
        options = d.meta.get("options") or []
        if options:
            named = [eid for p in options for eid in r.resolve(p, "option")]
            via = "radar-scorecard-option"
        else:
            # No scorecard to join on: only the registry can say what an entry
            # names. Every entry on today's radar is registered, practices
            # included, so none is left hanging.
            named = r.resolve(d.meta.get("entry", ""), "radar")
            via = "radar-registry"
        for eid in dict.fromkeys(named):
            out.append(Edge(eid, "HAS_RADAR_ENTRY", d.id, dict(prov, via=via)))
        if d.meta.get("assessment"):
            out.append(Edge(d.id, "ASSESSED_IN", f"assessment:{d.meta['assessment']}",
                            dict(prov, via="radar-scorecard")))
        if d.meta.get("documented_in"):
            out.append(Edge(d.id, "DOCUMENTED_IN", d.meta["documented_in"],
                            dict(prov, via="radar-url")))
        return out
