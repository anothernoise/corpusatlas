"""A closed ontology.

Open-vocabulary extraction over a technical corpus produces a swamp. Fixing the
types up front turns extraction into classification and — more usefully — lets
every triple be typechecked before it reaches the graph.

On the radar relations: a RadarEntry is a *dated call*, not a technology. The
ring and the edition live on that node and are never projected onto the
Technology it names, because "Spark is Adopt" was true of one edition and
"Spark" is not a thing that has a ring. Keeping the claim on its own node is
what lets a reader see when it was made, and what it was before.

Three relations that look alike and must not become synonyms:

``COMPARES_TO``    Mechanical. Two options were scored on the same axes in one
                   scorecard. Says nothing about which is better, or for what.
``ALTERNATIVE_TO`` Editorial. One can stand in for the other *for a workload*,
                   so it always carries a ``scope``. Spark is an alternative to
                   Flink for stateful stream processing and to nothing much for
                   graph analytics; without the scope the edge is a slogan.
``COMPETES_WITH``  Commercial. Products or vendors chasing the same buyer.
"""
from __future__ import annotations

NODE_TYPES = {
    # The corpus, recovered deterministically.
    "Document", "Topic", "Technology", "Assessment", "RadarEntry",
    # The curated tier: what those technologies are made of and used for.
    "Concept", "Component", "Product", "Vendor", "Capability", "UseCase",
}

# Node ids carry their type, so a producer that only references a node — a
# pack pointing at tech:apache-kafka, say — can still be typechecked without
# seeing the producer that created it. Unprefixed ids are corpus documents.
ID_PREFIX = {
    "tech": "Technology", "topic": "Topic", "assessment": "Assessment",
    "radar": "RadarEntry", "concept": "Concept", "component": "Component",
    "product": "Product", "vendor": "Vendor", "capability": "Capability",
    "usecase": "UseCase",
}


def type_of(node_id: str) -> str:
    prefix, sep, _ = node_id.partition(":")
    return ID_PREFIX.get(prefix, "Document") if sep else "Document"


# Groups the relation table is written in. A Technology and a Product are the
# same kind of thing for most purposes — Databricks the product reads Parquet
# exactly as Spark the project does — and the scorecards already record some
# products as technologies, so the distinction is kept but rarely load-bearing.
TECHY = {"Technology", "Product"}
BUILDABLE = TECHY | {"Component"}
ACTORS = TECHY | {"Vendor"}
ABSTRACT = {"Concept", "Capability", "UseCase"}
ENTITIES = BUILDABLE | ABSTRACT | {"Vendor"}
PAGES = {"Document", "Assessment"}

# relation -> (allowed source types, allowed target types)
RELATIONS: dict[str, tuple[set[str], set[str]]] = {
    # --- corpus -------------------------------------------------------------
    "REFERENCES": ({"Document"}, {"Document"}),
    "ABOUT":      ({"Document"}, {"Topic"}),
    # An article covers a technology. Distinct from ABOUT, which points at a
    # subject: an article can be about "olap" while covering ClickHouse.
    "COVERS":     ({"Document"}, {"Technology"}),
    # Curated, entity -> page, graded by how central the entity is to the page.
    "PRIMARY_TOPIC_OF": (ENTITIES, PAGES),
    "DISCUSSED_IN":     (ENTITIES, PAGES),

    # --- radar --------------------------------------------------------------
    "ASSESSES":        ({"Assessment"}, {"Technology"}),
    "COMPARES_TO":     ({"Technology"}, {"Technology"}),
    "HAS_RADAR_ENTRY": ({"Technology"}, {"RadarEntry"}),
    "ASSESSED_IN":     ({"RadarEntry"}, {"Assessment"}),
    "DOCUMENTED_IN":   ({"RadarEntry"}, PAGES),

    # --- structure ----------------------------------------------------------
    "HAS_COMPONENT": (BUILDABLE, {"Component"}),
    "EXTENDS":       (BUILDABLE, BUILDABLE),
    "BUILT_ON":      (BUILDABLE, BUILDABLE),

    # --- concepts and capabilities ------------------------------------------
    "USES_CONCEPT":        (BUILDABLE, {"Concept"}),
    "IMPLEMENTS_CONCEPT":  (BUILDABLE, {"Concept"}),
    "SUPPORTS_CONCEPT":    (BUILDABLE, {"Concept"}),
    "PROVIDES_CAPABILITY": (BUILDABLE, {"Capability"}),
    "USED_FOR":            (BUILDABLE | {"Capability"}, {"UseCase"}),

    # --- dependencies and data flow -----------------------------------------
    # DEPENDS_ON is reserved for things that cannot be swapped out. An optional
    # integration is INTEGRATES_WITH, and treating one as the other is how a
    # graph ends up claiming Spark needs Hadoop.
    "DEPENDS_ON":      (BUILDABLE, BUILDABLE),
    "INTEGRATES_WITH": (BUILDABLE, BUILDABLE),
    "READS":           (BUILDABLE, BUILDABLE),
    "WRITES":          (BUILDABLE, BUILDABLE),
    "RUNS_ON":         (BUILDABLE, TECHY),

    # --- commercial ---------------------------------------------------------
    "SUPPORTS_TECHNOLOGY": (TECHY, {"Technology"}),
    "OFFERED_AS":          ({"Technology"}, TECHY),
    "MANAGED_BY":          ({"Technology"}, {"Vendor"}),
    "OWNED_BY":            (TECHY, {"Vendor"}),
    "COMPETES_WITH":       (ACTORS, ACTORS),

    # --- alternatives and lineage -------------------------------------------
    "ALTERNATIVE_TO": (BUILDABLE, BUILDABLE),
    "REPLACED_BY":    (BUILDABLE, BUILDABLE),
    "EVOLVED_FROM":   (BUILDABLE | {"Concept"}, BUILDABLE | {"Concept"}),
}

# How the renderer should offer the relations as filters. Ordered, and part of
# the ontology rather than the page, so a second consumer gets the same shape.
RELATION_GROUPS: dict[str, list[str]] = {
    "Corpus": ["REFERENCES", "ABOUT", "COVERS", "PRIMARY_TOPIC_OF", "DISCUSSED_IN"],
    "Radar": ["ASSESSES", "COMPARES_TO", "HAS_RADAR_ENTRY", "ASSESSED_IN", "DOCUMENTED_IN"],
    "Structure": ["HAS_COMPONENT", "EXTENDS", "BUILT_ON"],
    "Concepts": ["USES_CONCEPT", "IMPLEMENTS_CONCEPT", "SUPPORTS_CONCEPT",
                 "PROVIDES_CAPABILITY", "USED_FOR"],
    "Data flow": ["DEPENDS_ON", "INTEGRATES_WITH", "READS", "WRITES", "RUNS_ON"],
    "Commercial": ["SUPPORTS_TECHNOLOGY", "OFFERED_AS", "MANAGED_BY", "OWNED_BY",
                   "COMPETES_WITH"],
    "Alternatives": ["ALTERNATIVE_TO", "REPLACED_BY", "EVOLVED_FROM"],
}

# An alternative with no workload attached is not a claim anyone can check.
REQUIRES_SCOPE = {"ALTERNATIVE_TO"}
# Undirected in meaning: store one direction, and never both.
SYMMETRIC = {"COMPARES_TO", "INTEGRATES_WITH", "ALTERNATIVE_TO", "COMPETES_WITH"}
TIERS = {"deterministic", "curated", "extracted"}
# Three values, not a free float. Nobody can defend 0.8 over 0.85 on a reviewed
# edge, so the scale only distinguishes what a reviewer actually can.
#   1.0   stated in the project's own documentation, or in the article cited
#   0.75  well established, but the edge itself is a reviewer's judgement
#   0.5   partial, version-dependent, or contested
CONFIDENCE = {0.5, 0.75, 1.0}

assert set(RELATIONS) == {r for rs in RELATION_GROUPS.values() for r in rs}, \
    "every relation belongs to exactly one filter group"


def typecheck(rel: str, src_type: str, dst_type: str) -> bool:
    spec = RELATIONS.get(rel)
    if spec is None:
        return False
    allowed_src, allowed_dst = spec
    return src_type in allowed_src and dst_type in allowed_dst


def validate_edge(rel: str, src_type: str, dst_type: str, *,
                  scope: str | None = None, confidence: float | None = None) -> list[str]:
    """Every reason a curated edge is not shippable. Empty means it is."""
    problems = []
    if rel not in RELATIONS:
        problems.append(f"unknown relation {rel}")
    elif not typecheck(rel, src_type, dst_type):
        problems.append(f"{rel} does not go from {src_type} to {dst_type}")
    if rel in REQUIRES_SCOPE and not scope:
        problems.append(f"{rel} needs a scope")
    if confidence is not None and confidence not in CONFIDENCE:
        problems.append(f"confidence {confidence} is not one of {sorted(CONFIDENCE)}")
    return problems
