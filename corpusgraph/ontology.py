"""A closed ontology.

Open-vocabulary extraction over a technical corpus produces a swamp. Fixing the
types up front turns extraction into classification and — more usefully — lets
every triple be typechecked before it reaches the graph.

Two kinds of node, and the split is the whole design:

``ENTITY_TYPES``   What the graph is about: concepts, technologies, products and
                   their sub-kinds. These are the nodes a reader explores, and
                   the only nodes the renderer draws.
``CONTEXT_TYPES``  Where claims about entities were published: articles, radar
                   assessments, dated radar calls, tags. Evidence, not subjects.
                   They stay in the artifact so every edge can name its source,
                   and the renderer shows them as links on an entity's card.

Core distinction, from the extraction spec:
  Concept    a general idea, principle or computational model
  Technology a concrete implementation of one or more concepts
  Product    a packaged commercial or managed offering built on technologies
  Component  a subsystem of a larger technology or product
None of these is a strict hierarchy; typed relationships carry the structure.

A RadarEntry is a *dated call*, not a technology. Its ring and edition live on
that context node and are never projected onto the entity it names, because
"Spark is Adopt" was true of one edition and "Spark" has no ring.
"""
from __future__ import annotations

ENTITY_TYPES = {
    "Concept", "ArchitecturePattern",
    "Technology", "Component", "Language", "API", "Protocol", "Standard",
    "FileFormat", "TableFormat",
    "Product", "CloudService", "Company",
    "UseCase",
}
CONTEXT_TYPES = {"Document", "Assessment", "RadarEntry", "Topic"}
NODE_TYPES = ENTITY_TYPES | CONTEXT_TYPES

# Context ids carry their type in a prefix; unprefixed ids are articles. Entity
# ids are type-neutral ("entity:<slug>"), so reclassifying Snowflake from a
# Technology to a Product never changes its id — an entity's type comes from
# the registry or the pack that declares it, never from its id.
ENTITY_PREFIX = "entity:"
CONTEXT_PREFIX = {"assessment": "Assessment", "radar": "RadarEntry", "topic": "Topic"}


def is_entity_id(node_id: str) -> bool:
    return node_id.startswith(ENTITY_PREFIX)


def context_type_of(node_id: str) -> str | None:
    """The type of a context id, or None for an entity id."""
    if is_entity_id(node_id):
        return None
    prefix, sep, _ = node_id.partition(":")
    return CONTEXT_PREFIX.get(prefix, "Document") if sep else "Document"


TECH_LIKE = {"Technology", "Component", "Product", "CloudService", "Language", "API",
             "Protocol", "Standard", "FileFormat", "TableFormat"}
# Scorecards compare patterns with tools ("Hand-rolled SQL" vs dbt), so the
# comparison relations accept the abstract kinds too.
COMPARABLE = TECH_LIKE | {"Concept", "ArchitecturePattern"}

# relation -> (allowed source types, allowed target types)
RELATIONS: dict[str, tuple[set[str], set[str]]] = {
    # --- semantic: drawn on the canvas ---------------------------------------
    "IMPLEMENTS":        (TECH_LIKE, {"Concept", "ArchitecturePattern", "Protocol", "Standard"}),
    "SUPPORTS":          (TECH_LIKE, {"Concept", "Protocol", "Standard", "FileFormat",
                                      "TableFormat", "Language", "API"}),
    "USES":              (TECH_LIKE, ENTITY_TYPES - {"UseCase", "Company"}),
    "HAS_COMPONENT":     (TECH_LIKE, {"Component", "API"}),
    "BASED_ON":          (TECH_LIKE, TECH_LIKE | {"Concept", "Standard"}),
    "INCLUDED_IN":       ({"Technology", "Component"}, {"Product", "CloudService"}),
    "READS":             (TECH_LIKE, {"FileFormat", "TableFormat", "Technology", "CloudService"}),
    "WRITES":            (TECH_LIKE, {"FileFormat", "TableFormat", "Technology", "CloudService"}),
    "RUNS_ON":           (TECH_LIKE, {"Technology", "Component", "Product", "CloudService"}),
    # DEPENDS-style claims are deliberately absent: an optional integration is
    # INTEGRATES_WITH, and a graph that confuses the two ends up claiming Spark
    # needs Hadoop.
    "INTEGRATES_WITH":   (TECH_LIKE, TECH_LIKE),
    "MANAGED_BY":        ({"Technology"}, {"CloudService", "Product"}),
    "PROVIDED_BY":       ({"Product", "CloudService", "Technology"}, {"Company"}),
    "SUPPORTS_USE_CASE": (TECH_LIKE | {"Concept", "ArchitecturePattern"}, {"UseCase"}),
    "ALTERNATIVE_TO":    (COMPARABLE, COMPARABLE),
    "COMPLEMENTS":       (COMPARABLE, COMPARABLE),
    # Mechanical, from scorecards: two options were scored on the same axes.
    # Says nothing about which is better, or for what — ALTERNATIVE_TO does.
    "COMPARES_TO":       (COMPARABLE, COMPARABLE),

    # --- context: shown as links on an entity's card, never drawn ------------
    "COVERS":           ({"Document"}, ENTITY_TYPES),
    "PRIMARY_TOPIC_OF": (ENTITY_TYPES, {"Document", "Assessment"}),
    "DISCUSSED_IN":     (ENTITY_TYPES, {"Document", "Assessment"}),
    "ASSESSES":         ({"Assessment"}, COMPARABLE),
    "HAS_RADAR_ENTRY":  (ENTITY_TYPES, {"RadarEntry"}),
    "ASSESSED_IN":      ({"RadarEntry"}, {"Assessment"}),
    "DOCUMENTED_IN":    ({"RadarEntry"}, {"Document", "Assessment"}),
    "ABOUT":            ({"Document"}, {"Topic"}),
    "REFERENCES":       ({"Document"}, {"Document"}),
}

# Relations stored in one direction and read in either. A pack may author the
# inverse ("Concept IMPLEMENTED_BY Technology"); extraction flips it, so the
# same fact can never be stored twice. The renderer shows the inverse label
# when the entity in view is the target.
INVERSE = {"IMPLEMENTED_BY": "IMPLEMENTS", "COMPONENT_OF": "HAS_COMPONENT"}
INVERSE_LABEL = {v: k for k, v in INVERSE.items()}

# Filter groups for the canvas. Context relations are not filterable edges —
# they are the card's link sections — so they are listed separately.
RELATION_GROUPS: dict[str, list[str]] = {
    "Structure": ["HAS_COMPONENT", "BASED_ON", "INCLUDED_IN"],
    "Concepts": ["IMPLEMENTS", "SUPPORTS", "USES", "SUPPORTS_USE_CASE"],
    "Data flow": ["READS", "WRITES", "RUNS_ON", "INTEGRATES_WITH"],
    "Commercial": ["MANAGED_BY", "PROVIDED_BY"],
    "Alternatives": ["ALTERNATIVE_TO", "COMPLEMENTS", "COMPARES_TO"],
}
CONTEXT_RELATIONS = ["COVERS", "PRIMARY_TOPIC_OF", "DISCUSSED_IN", "ASSESSES", "HAS_RADAR_ENTRY",
                     "ASSESSED_IN", "DOCUMENTED_IN", "ABOUT", "REFERENCES"]
SEMANTIC_RELATIONS = {r for rs in RELATION_GROUPS.values() for r in rs}

# Undirected in meaning: store one direction, and never both.
SYMMETRIC = {"COMPARES_TO", "INTEGRATES_WITH", "ALTERNATIVE_TO", "COMPLEMENTS"}
TIERS = {"deterministic", "curated", "extracted"}

assert SEMANTIC_RELATIONS | set(CONTEXT_RELATIONS) == set(RELATIONS), \
    "every relation is either a canvas filter or a card context relation"
assert not SEMANTIC_RELATIONS & set(CONTEXT_RELATIONS)
assert not ENTITY_TYPES & CONTEXT_TYPES


def typecheck(rel: str, src_type: str, dst_type: str) -> bool:
    spec = RELATIONS.get(rel)
    if spec is None:
        return False
    allowed_src, allowed_dst = spec
    return src_type in allowed_src and dst_type in allowed_dst


def canonical(rel: str, src: str, dst: str) -> tuple[str, str, str]:
    """Flip an inverse relation into its stored direction."""
    if rel in INVERSE:
        return INVERSE[rel], dst, src
    return rel, src, dst


def validate_edge(rel: str, src_type: str, dst_type: str, *,
                  confidence: float | None = None) -> list[str]:
    """Every reason a curated edge is not shippable. Empty means it is."""
    problems = []
    if rel not in RELATIONS:
        problems.append(f"unknown relation {rel}")
    elif not typecheck(rel, src_type, dst_type):
        problems.append(f"{rel} does not go from {src_type} to {dst_type}")
    if confidence is not None and not (isinstance(confidence, (int, float)) and 0 <= confidence <= 1):
        problems.append(f"confidence {confidence!r} is not a number between 0 and 1")
    return problems
