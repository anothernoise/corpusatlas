"""The curated tier: reviewed entity packs, turned into nodes and edges.

Runs after the deterministic tier. Merge is first-writer-wins, so running
second is what guarantees a curated edge can never overwrite a hand-written
one — ordering is the precedence mechanism, not a flag.

An ill-typed edge in a pack fails the build instead of being dropped. The
deterministic tier filters silently because its input is the whole corpus and
a stray tag should not stop a deploy; a pack is a file a human signed, and a
signed claim that cannot be stored is a mistake someone needs to hear about.
"""
from __future__ import annotations

from ..model import Document, Edge, Node
from ..ontology import type_of, validate_edge


class PackError(ValueError):
    pass


class PacksExtractor:
    name = "packs@1"
    tier = "curated"

    def run(self, docs: list[Document]):
        nodes: list[Node] = []
        edges: list[Edge] = []
        for d in docs:
            if d.kind != "entity-pack":
                continue
            pack = d.meta["pack"]
            prov = {"doc": d.id, "tier": self.tier, "extractor": self.name}

            for n in pack.get("nodes", []):
                if type_of(n["id"]) != n["type"]:
                    raise PackError(f"{d.id}: node {n['id']} declared {n['type']}, "
                                    f"but its id says {type_of(n['id'])}")
                urls = n.get("urls") or {}
                corpus = list(urls.get("corpus") or [])
                ext = urls.get("external") or {}
                # Re-serialised field by field, never passed through: a key
                # reordered in a hand-edited pack must not rewrite the artifact.
                out_urls = {k: v for k, v in (("wikipedia", ext.get("wikipedia")),
                                              ("docs", ext.get("docs")),
                                              ("corpus", corpus)) if v}
                nodes.append(Node(
                    id=n["id"], label=n["label"], type=n["type"],
                    url=corpus[0] if corpus else (ext.get("wikipedia") or ext.get("docs")),
                    aliases=tuple(n.get("aliases") or ()),
                    urls=out_urls,
                ))

            for e in pack.get("edges", []):
                problems = validate_edge(e["rel"], type_of(e["src"]), type_of(e["dst"]),
                                         scope=e.get("scope"), confidence=e.get("confidence"))
                if problems:
                    raise PackError(f"{d.id}: {e['src']} -{e['rel']}-> {e['dst']}: "
                                    + "; ".join(problems))
                edges.append(Edge(
                    e["src"], e["rel"], e["dst"], dict(prov),
                    scope=e.get("scope") or None,
                    confidence=e.get("confidence"),
                    sources=tuple(s["url"] for s in e.get("sources") or ()),
                ))
        return nodes, edges
