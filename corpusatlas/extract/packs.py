"""The curated tier: entity packs, turned into typed entities and relationships.

A pack describes one subject in the extraction-spec format:

    {"subject": {...}, "authored": {...},
     "entities": [{"id", "name", "type", "short_description", "aliases",
                   "canonical_url", "wikipedia_url", "wikipedia_checked",
                   "blog_url", "related_blog_urls", "architecture_radar_url",
                   "tags", "classification_notes"}],
     "relationships": [{"source_id", "relationship", "target_id",
                        "confidence", "explanation", "sources"}]}

Runs after the deterministic tier. Merge is first-writer-wins, so running
second is what guarantees a pack can add to an entity the registry defines
but never relabel or retype it — ordering is the precedence mechanism.

An ill-typed or undeclared relationship fails the build instead of being
dropped. The deterministic tier filters silently because its input is the
whole corpus; a pack is a file someone wrote on purpose, and a claim in it
that cannot be stored is a mistake someone needs to hear about.
"""
from __future__ import annotations

import re
import sys

from ..model import Document, Edge, Node
from ..ontology import DEFAULT, Ontology
from ..resolve import Resolver, entity_id

BLOG_PREFIX = "/blog/"
ASSESSMENT_PREFIX = "/architecture-radar/"
ASSESSMENT_ID_PREFIX = "assessment:"


class PackError(ValueError):
    pass


def url_matcher(prefix: str, *, site_url: str | None = None, id_prefix: str = ""):
    """Turn the URLs a pack cites into the document ids the graph joins on.

    Which URLs a corpus publishes is the corpus's business, so the shape is
    configuration rather than a constant — see [packs] in the config file.
    """
    site = re.escape(site_url.rstrip("/")) if site_url else ""
    pattern = re.compile(rf"^(?:{site})?{re.escape(prefix)}([a-z0-9-]+)/?$")

    def doc_id(url: str | None) -> str | None:
        m = pattern.match(url or "")
        return f"{id_prefix}{m.group(1)}" if m else None

    return doc_id


class PacksExtractor:
    name = "packs@2"
    tier = "curated"

    def __init__(self, resolver: Resolver | None = None, *,
                 site_url: str | None = None,
                 blog_prefix: str = BLOG_PREFIX,
                 assessment_prefix: str = ASSESSMENT_PREFIX,
                 assessment_id_prefix: str = ASSESSMENT_ID_PREFIX,
                 ontology: Ontology = DEFAULT):
        self.resolver = resolver or Resolver()
        self.ontology = ontology
        self.blog_doc_id = url_matcher(blog_prefix, site_url=site_url)
        self.assessment_doc_id = url_matcher(assessment_prefix, site_url=site_url,
                                             id_prefix=assessment_id_prefix)

    @classmethod
    def from_config(cls, cfg: dict, resolver: Resolver | None = None,
                    ontology: Ontology = DEFAULT) -> "PacksExtractor":
        p = cfg.get("packs") or {}
        return cls(resolver=resolver,
                   site_url=p.get("site_url"),
                   blog_prefix=p.get("blog_prefix", BLOG_PREFIX),
                   assessment_prefix=p.get("assessment_prefix", ASSESSMENT_PREFIX),
                   assessment_id_prefix=p.get("assessment_id_prefix", ASSESSMENT_ID_PREFIX),
                   ontology=ontology)

    def run(self, docs: list[Document]):
        nodes: list[Node] = []
        edges: list[Edge] = []
        for d in docs:
            if d.kind != "entity-pack":
                continue
            pack = d.meta["pack"]
            prov = {"doc": d.id, "tier": self.tier, "extractor": self.name}
            declared: dict[str, str] = {}
            unmatched: list[str] = []

            for e in pack.get("entities", []):
                eid = entity_id(e["id"])
                registered = self.resolver.type(eid)
                if registered and registered != e["type"]:
                    raise PackError(f"{d.id}: {e['id']} is a {registered} in the registry, "
                                    f"but the pack declares {e['type']}")
                declared[eid] = e["type"]
                # Re-serialised field by field, never passed through: a key
                # reordered in a hand-edited pack must not rewrite the artifact.
                urls = {k: v for k, v in (("wikipedia", e.get("wikipedia_url")),
                                          ("canonical", e.get("canonical_url"))) if v}
                meta = {k: v for k, v in (("description", e.get("short_description")),
                                          ("notes", e.get("classification_notes"))) if v}
                nodes.append(Node(id=eid, label=e["name"], type=e["type"],
                                  aliases=tuple(e.get("aliases") or ()), urls=urls, meta=meta))

                page = dict(prov, via="pack-url")
                # Order matters: it is the order these edges reach merge, and
                # so the order they reach the artifact.
                cites = [("blog_url", "PRIMARY_TOPIC_OF", self.blog_doc_id, e.get("blog_url"))]
                cites += [("related_blog_urls", "DISCUSSED_IN", self.blog_doc_id, u)
                          for u in e.get("related_blog_urls") or ()]
                cites.append(("architecture_radar_url", "DISCUSSED_IN", self.assessment_doc_id,
                              e.get("architecture_radar_url")))
                for field, rel, match, cited in cites:
                    if not cited:
                        continue
                    doc_id = match(cited)
                    if doc_id:
                        edges.append(Edge(eid, rel, doc_id, dict(page)))
                    else:
                        unmatched.append(f"{e['id']}: {field} {cited}")

            # A URL that matches no prefix yields no edge. That is silent data
            # loss when the prefixes are simply misconfigured, so say so.
            for line in unmatched:
                print(f"  warning: {d.id}: {line} matched no [packs] prefix", file=sys.stderr)

            seen: set[tuple] = set()
            for rel_spec in pack.get("relationships", []):
                raw = (rel_spec["source_id"], rel_spec["relationship"], rel_spec["target_id"])
                rel, src, dst = self.ontology.canonical(rel_spec["relationship"],
                                          entity_id(rel_spec["source_id"]),
                                          entity_id(rel_spec["target_id"]))
                where = f"{d.id}: {raw[0]} -{raw[1]}-> {raw[2]}"
                if rel not in self.ontology.semantic_relations:
                    raise PackError(f"{where}: {rel} is not a semantic relation")
                types = []
                for end in (src, dst):
                    t = declared.get(end) or self.resolver.type(end)
                    if not t:
                        raise PackError(f"{where}: {end} is declared neither in the pack "
                                        f"nor in the entity registry")
                    types.append(t)
                problems = self.ontology.validate_edge(rel, *types, confidence=rel_spec.get("confidence"))
                if rel_spec.get("confidence") is None:
                    problems.append("confidence is required")
                if not rel_spec.get("explanation"):
                    problems.append("explanation is required")
                if problems:
                    raise PackError(f"{where}: " + "; ".join(problems))
                if rel in self.ontology.symmetric:
                    src, dst = sorted((src, dst))
                if (src, rel, dst) in seen:
                    continue
                seen.add((src, rel, dst))
                edges.append(Edge(
                    src, rel, dst, dict(prov),
                    scope=rel_spec.get("scope") or None,
                    confidence=rel_spec["confidence"],
                    sources=tuple(s["url"] if isinstance(s, dict) else s
                                  for s in rel_spec.get("sources") or ()),
                    explanation=rel_spec["explanation"],
                ))
        return nodes, edges
