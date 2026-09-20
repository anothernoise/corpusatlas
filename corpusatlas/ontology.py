"""A closed ontology.

Open-vocabulary extraction over a technical corpus produces a swamp. Fixing the
types up front turns extraction into classification and — more usefully — lets
every triple be typechecked before it reaches the graph.

Two kinds of node, and the split is the whole design:

``entity_types``   What the graph is about: concepts, technologies, products and
                   their sub-kinds. These are the nodes a reader explores, and
                   the only nodes the renderer draws.
``context_types``  Where claims about entities were published: articles, radar
                   assessments, dated radar calls, tags. Evidence, not subjects.
                   They stay in the artifact so every edge can name its source,
                   and the renderer shows them as links on an entity's card.

The vocabulary is an ``Ontology`` value, not a set of module globals — see the
class below. ``DEFAULT`` is this package's own (14 entity types, 25 relations,
a data-and-infrastructure-architecture domain), and the module-level names
after it (``ENTITY_TYPES``, ``RELATIONS``, ``typecheck``, ...) are that default
bound to the top level, kept for anything already doing
``from corpusatlas.ontology import ENTITY_TYPES``. The pipeline itself
(extractors, the resolver, ``emit.write_graph``) takes an ``ontology=``
parameter and defaults to ``DEFAULT`` — never reaches for the module globals
directly — which is what lets a build actually use a different one.

A RadarEntry is a *dated call*, not a technology. Its ring and edition live on
that context node and are never projected onto the entity it names, because
"Spark is Adopt" was true of one edition and "Spark" has no ring. That
distinction — and the id-prefix scheme below — is structural, not vocabulary:
fixed for every ontology, not something a schema file chooses.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

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


class OntologyError(ValueError):
    """A schema is internally inconsistent — caught at load time, not
    mid-build. Same checks a bare ``assert`` used to make on the module's own
    fixed data; raised properly now that the data isn't always fixed."""


@dataclass(frozen=True, init=False)
class Ontology:
    """The entity/relation vocabulary a build typechecks against.

    Everything here is data — construct one directly in Python (``DEFAULT``
    below is built exactly this way) or load one from a TOML schema with
    :meth:`from_toml`. Nothing in the pipeline cares which.
    """
    entity_types: frozenset[str]
    context_types: frozenset[str]
    # relation -> (allowed source types, allowed target types)
    relations: dict[str, tuple[frozenset[str], frozenset[str]]]
    # Relations stored in one direction and read in either. A pack may author
    # the inverse ("Concept IMPLEMENTED_BY Technology"); extraction flips it,
    # so the same fact can never be stored twice.
    inverse: dict[str, str]
    # Filter groups for the canvas — every semantic relation belongs to
    # exactly one. Context relations aren't filterable edges (they're a
    # card's link sections), so they're listed separately, not grouped.
    relation_groups: dict[str, tuple[str, ...]]
    context_relations: tuple[str, ...]
    # Undirected in meaning: stored as one direction, never both.
    symmetric: frozenset[str]

    def __init__(
        self,
        entity_types: frozenset[str] | None = None,
        context_types: frozenset[str] | None = None,
        relations: dict[str, tuple[frozenset[str], frozenset[str]]] | None = None,
        inverse: dict[str, str] | None = None,
        relation_groups: dict[str, tuple[str, ...]] | None = None,
        context_relations: tuple[str, ...] | None = None,
        symmetric: frozenset[str] | None = None,
    ):
        if entity_types is None:
            default = globals().get("DEFAULT")
            if default is not None:
                object.__setattr__(self, "entity_types", default.entity_types)
                object.__setattr__(self, "context_types", default.context_types)
                object.__setattr__(self, "relations", default.relations)
                object.__setattr__(self, "inverse", default.inverse)
                object.__setattr__(self, "relation_groups", default.relation_groups)
                object.__setattr__(self, "context_relations", default.context_relations)
                object.__setattr__(self, "symmetric", default.symmetric)
                return
        object.__setattr__(self, "entity_types", entity_types or frozenset())
        object.__setattr__(self, "context_types", context_types or frozenset())
        object.__setattr__(self, "relations", relations or {})
        object.__setattr__(self, "inverse", inverse or {})
        object.__setattr__(self, "relation_groups", relation_groups or {})
        object.__setattr__(self, "context_relations", context_relations or ())
        object.__setattr__(self, "symmetric", symmetric or frozenset())
        self.__post_init__()

    def __post_init__(self):
        overlap = self.entity_types & self.context_types
        if overlap:
            raise OntologyError(f"types cannot be both entity and context: {sorted(overlap)}")
        semantic = self.semantic_relations
        declared = set(self.relations)
        context = set(self.context_relations)
        if semantic & context:
            raise OntologyError(f"relations cannot be both semantic and context: {sorted(semantic & context)}")
        if semantic | context != declared:
            missing = declared - semantic - context
            raise OntologyError(
                f"every relation must be in exactly one relation_group (semantic) or "
                f"context_relations: {sorted(missing)} is in neither")
        known = self.entity_types | self.context_types
        for name, (src, dst) in self.relations.items():
            unknown = (src | dst) - known
            if unknown:
                raise OntologyError(f"{name}: references undeclared type(s) {sorted(unknown)}")
        for target in self.inverse.values():
            if target not in self.relations:
                raise OntologyError(f"inverse names unknown relation {target!r}")

    @property
    def node_types(self) -> frozenset[str]:
        return self.entity_types | self.context_types

    @property
    def semantic_relations(self) -> frozenset[str]:
        return frozenset(r for rs in self.relation_groups.values() for r in rs)

    @property
    def inverse_label(self) -> dict[str, str]:
        return {v: k for k, v in self.inverse.items()}

    def filter_conforming_triples(
        self,
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
    ) -> dict[str, list[dict[str, Any]]]:
        """Filters extracted entities and relations to retain only schema-conforming ones."""
        valid_entities = []
        valid_entity_types: dict[str, str] = {}
        for ent in entities:
            etype = ent.get("type", "")
            eid = ent.get("id", "")
            if etype in self.entity_types and eid:
                valid_entities.append(ent)
                valid_entity_types[eid] = etype

        valid_relations = []
        rel_map = {k.lower(): k for k in self.relations}
        for rel in relations:
            rname = rel.get("rel", "")
            src = rel.get("src", "")
            dst = rel.get("dst", "")
            matched_key = rel_map.get(rname.lower())
            if not matched_key:
                continue
            if src in valid_entity_types and dst in valid_entity_types:
                rel_copy = dict(rel)
                rel_copy["rel"] = matched_key.lower()
                valid_relations.append(rel_copy)

        return {"entities": valid_entities, "relations": valid_relations}

    def to_dot(self) -> str:
        """A Graphviz DOT rendering of this ontology's own type/relation
        graph — the vocabulary itself, not any data built against it.
        `ontology-check --dot` exists because the command's normal output
        (counts, pass/fail) tells you a schema is internally consistent but
        not what it actually looks like — this is for a schema author
        checking the shape of what they wrote, the same way `stats`
        summarises a graph rather than just validating it.

        Entities are filled boxes, context types filled ellipses (matching
        the split the README and the viewer both draw); a relation gets one
        edge per concrete (source, target) pair it actually allows, dashed
        for a context relation (a claim's evidence link) and solid for a
        semantic one (a claim between two entities)."""
        lines = ["digraph ontology {", "  rankdir=LR;",
                 '  node [shape=box, style=filled, fontname="Helvetica", fillcolor="#cfe8ff"];']
        # Declared explicitly, not left to appear implicitly from an edge —
        # a type with no relations touching it (unusual, but valid) still
        # has to show up, or the diagram would silently under-report the
        # schema's own vocabulary.
        for t in sorted(self.entity_types):
            lines.append(f'  "{t}";')
        for t in sorted(self.context_types):
            lines.append(f'  "{t}" [shape=ellipse, fillcolor="#ffe6b3"];')
        for rel, (srcs, dsts) in sorted(self.relations.items()):
            style = "dashed" if rel in self.context_relations else "solid"
            for s in sorted(srcs):
                for d in sorted(dsts):
                    lines.append(f'  "{s}" -> "{d}" [label="{rel}", style={style}];')
        lines.append("}")
        return "\n".join(lines)

    def typecheck(self, rel: str, src_type: str, dst_type: str) -> bool:
        spec = self.relations.get(rel)
        if spec is None:
            return False
        allowed_src, allowed_dst = spec
        return src_type in allowed_src and dst_type in allowed_dst

    def canonical(self, rel: str, src: str, dst: str) -> tuple[str, str, str]:
        """Flip an inverse relation into its stored direction."""
        if rel in self.inverse:
            return self.inverse[rel], dst, src
        return rel, src, dst

    def validate_edge(self, rel: str, src_type: str, dst_type: str, *,
                      confidence: float | None = None) -> list[str]:
        """Every reason a curated edge is not shippable. Empty means it is."""
        problems = []
        if rel not in self.relations:
            problems.append(f"unknown relation {rel}")
        elif not self.typecheck(rel, src_type, dst_type):
            problems.append(f"{rel} does not go from {src_type} to {dst_type}")
        if confidence is not None and not (isinstance(confidence, (int, float)) and 0 <= confidence <= 1):
            problems.append(f"confidence {confidence!r} is not a number between 0 and 1")
        return problems

    def extend(self, *, entity_types=(), context_types=(),
              relations: dict[str, tuple[frozenset, frozenset]] | None = None,
              inverse: dict[str, str] | None = None,
              relation_groups: dict[str, tuple[str, ...]] | None = None,
              context_relations=(), symmetric=()) -> "Ontology":
        """A new Ontology with more types and relations layered on top of
        this one — for "DEFAULT plus three new types" rather than
        redeclaring an entire 14-type, 25-relation vocabulary to add three
        things to it. Every name here must be new: extending with a type or
        relation this ontology already has raises OntologyError rather than
        silently overwriting it — the same "fail loud on a conflict" rule
        packs.py already applies to a type redeclared with a different
        signature.
        """
        relations = relations or {}
        inverse = inverse or {}
        relation_groups = relation_groups or {}

        dup_types = (set(entity_types) | set(context_types)) & self.node_types
        if dup_types:
            raise OntologyError(f"extend: type(s) already declared: {sorted(dup_types)}")
        dup_rels = set(relations) & set(self.relations)
        if dup_rels:
            raise OntologyError(f"extend: relation(s) already declared: {sorted(dup_rels)}")

        merged_groups = {g: list(rs) for g, rs in self.relation_groups.items()}
        for g, rs in relation_groups.items():
            merged_groups.setdefault(g, [])
            merged_groups[g].extend(rs)

        return Ontology(
            entity_types=self.entity_types | frozenset(entity_types),
            context_types=self.context_types | frozenset(context_types),
            relations={**self.relations, **relations},
            inverse={**self.inverse, **inverse},
            relation_groups={g: tuple(rs) for g, rs in merged_groups.items()},
            context_relations=self.context_relations + tuple(context_relations),
            symmetric=self.symmetric | frozenset(symmetric),
        )

    @classmethod
    def from_toml(cls, path: str | Path) -> "Ontology":
        """A schema file: entity_types, context_types, and one [[relation]]
        table per relation — its signature, and whether it's a canvas filter
        (assigned to a `group`) or a card context relation (`context = true`).
        See docs/ontology-schema.md for the full shape and a worked example.

        `extends = "default"` at the top of the file means everything below
        is layered onto DEFAULT via :meth:`extend` rather than replacing it
        wholesale — "DEFAULT plus a few more types" as a schema file instead
        of a Python script. Only "default" is a recognised value today.
        """
        doc = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        extends = doc.get("extends")
        if extends is not None and extends != "default":
            raise OntologyError(f"{path}: extends {extends!r} is not recognised (only \"default\" is)")
        entity_types = frozenset(doc.get("entity_types") or ())
        context_types = frozenset(doc.get("context_types") or ())
        if not entity_types and not extends:
            raise OntologyError(f"{path}: entity_types is empty or missing")

        relations: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
        groups: dict[str, list[str]] = {}
        context_relations: list[str] = []
        inverse: dict[str, str] = {}
        symmetric: set[str] = set()

        for i, r in enumerate(doc.get("relation") or ()):
            name = r.get("name")
            if not name:
                raise OntologyError(f"{path}: relation #{i} has no name")
            if name in relations:
                raise OntologyError(f"{path}: relation {name!r} declared twice")
            relations[name] = (frozenset(r.get("source") or ()), frozenset(r.get("target") or ()))
            is_context = bool(r.get("context"))
            group = r.get("group")
            if is_context and group:
                raise OntologyError(f"{path}: {name!r} is both context=true and in group {group!r}")
            if is_context:
                context_relations.append(name)
            elif group:
                groups.setdefault(group, []).append(name)
            else:
                raise OntologyError(f"{path}: {name!r} needs either context=true or a group")
            if r.get("symmetric"):
                symmetric.add(name)
            if r.get("inverse"):
                inverse[r["inverse"]] = name

        relation_groups = {g: tuple(rs) for g, rs in groups.items()}
        if extends == "default":
            return DEFAULT.extend(
                entity_types=entity_types,
                context_types=context_types,
                relations=relations,
                inverse=inverse,
                relation_groups=relation_groups,
                context_relations=tuple(context_relations),
                symmetric=frozenset(symmetric),
            )
        return cls(
            entity_types=entity_types,
            context_types=context_types,
            relations=relations,
            inverse=inverse,
            relation_groups=relation_groups,
            context_relations=tuple(context_relations),
            symmetric=frozenset(symmetric),
        )


TECH_LIKE = frozenset({"Technology", "Component", "Product", "CloudService", "Language", "API",
                       "Protocol", "Standard", "FileFormat", "TableFormat"})
_ENTITY_TYPES = frozenset({
    "Concept", "ArchitecturePattern",
    "Technology", "Component", "Language", "API", "Protocol", "Standard",
    "FileFormat", "TableFormat",
    "Product", "CloudService", "Company",
    "UseCase",
})
# Scorecards compare patterns with tools ("Hand-rolled SQL" vs dbt), so the
# comparison relations accept the abstract kinds too.
_COMPARABLE = TECH_LIKE | {"Concept", "ArchitecturePattern"}

DEFAULT = Ontology(
    entity_types=_ENTITY_TYPES,
    context_types=frozenset({"Document", "Assessment", "RadarEntry", "Topic"}),
    relations={
        # --- semantic: drawn on the canvas ---------------------------------
        "IMPLEMENTS":        (TECH_LIKE, frozenset({"Concept", "ArchitecturePattern", "Protocol", "Standard"})),
        "SUPPORTS":          (TECH_LIKE, frozenset({"Concept", "Protocol", "Standard", "FileFormat",
                                                     "TableFormat", "Language", "API"})),
        "USES":              (TECH_LIKE, _ENTITY_TYPES - {"UseCase", "Company"}),
        "HAS_COMPONENT":     (TECH_LIKE, frozenset({"Component", "API"})),
        "BASED_ON":          (TECH_LIKE, TECH_LIKE | {"Concept", "Standard"}),
        "INCLUDED_IN":       (frozenset({"Technology", "Component"}), frozenset({"Product", "CloudService"})),
        # Component is a valid target as well as source: a storage subsystem
        # like HDFS is a Component of Hadoop, and it is exactly the kind of
        # thing another technology reads and writes — the same reasoning
        # RUNS_ON already applies to a cluster manager that is itself a
        # Component.
        "READS":             (TECH_LIKE, frozenset({"FileFormat", "TableFormat", "Technology", "Component", "CloudService"})),
        "WRITES":            (TECH_LIKE, frozenset({"FileFormat", "TableFormat", "Technology", "Component", "CloudService"})),
        "RUNS_ON":           (TECH_LIKE, frozenset({"Technology", "Component", "Product", "CloudService"})),
        # DEPENDS-style claims are deliberately absent: an optional
        # integration is INTEGRATES_WITH, and a graph that confuses the two
        # ends up claiming Spark needs Hadoop.
        "INTEGRATES_WITH":   (TECH_LIKE, TECH_LIKE),
        "CONSUMES":          (TECH_LIKE, TECH_LIKE),
        "MANAGED_BY":        (frozenset({"Technology"}), frozenset({"CloudService", "Product"})),
        "PROVIDED_BY":       (frozenset({"Product", "CloudService", "Technology"}), frozenset({"Company"})),
        "SUPPORTS_USE_CASE": (TECH_LIKE | {"Concept", "ArchitecturePattern"}, frozenset({"UseCase"})),
        "ALTERNATIVE_TO":    (_COMPARABLE, _COMPARABLE),
        "COMPLEMENTS":       (_COMPARABLE, _COMPARABLE),
        # Mechanical, from scorecards: two options were scored on the same
        # axes. Says nothing about which is better, or for what —
        # ALTERNATIVE_TO does.
        "COMPARES_TO":       (_COMPARABLE, _COMPARABLE),

        # --- context: shown as links on an entity's card, never drawn -----
        "COVERS":           (frozenset({"Document"}), _ENTITY_TYPES),
        "PRIMARY_TOPIC_OF": (_ENTITY_TYPES, frozenset({"Document", "Assessment"})),
        "DISCUSSED_IN":     (_ENTITY_TYPES, frozenset({"Document", "Assessment"})),
        "ASSESSES":         (frozenset({"Assessment"}), _COMPARABLE),
        "HAS_RADAR_ENTRY":  (_ENTITY_TYPES, frozenset({"RadarEntry"})),
        "ASSESSED_IN":      (frozenset({"RadarEntry"}), frozenset({"Assessment"})),
        "DOCUMENTED_IN":    (frozenset({"RadarEntry"}), frozenset({"Document", "Assessment"})),
        "ABOUT":            (frozenset({"Document"}), frozenset({"Topic"})),
        "REFERENCES":       (frozenset({"Document"}), frozenset({"Document"})),
    },
    inverse={"IMPLEMENTED_BY": "IMPLEMENTS", "COMPONENT_OF": "HAS_COMPONENT"},
    relation_groups={
        "Structure": ("HAS_COMPONENT", "BASED_ON", "INCLUDED_IN"),
        "Concepts": ("IMPLEMENTS", "SUPPORTS", "USES", "SUPPORTS_USE_CASE"),
        "Data flow": ("READS", "WRITES", "RUNS_ON", "INTEGRATES_WITH", "CONSUMES"),
        "Commercial": ("MANAGED_BY", "PROVIDED_BY"),
        "Alternatives": ("ALTERNATIVE_TO", "COMPLEMENTS", "COMPARES_TO"),
    },
    context_relations=("COVERS", "PRIMARY_TOPIC_OF", "DISCUSSED_IN", "ASSESSES", "HAS_RADAR_ENTRY",
                       "ASSESSED_IN", "DOCUMENTED_IN", "ABOUT", "REFERENCES"),
    symmetric=frozenset({"COMPARES_TO", "INTEGRATES_WITH", "ALTERNATIVE_TO", "COMPLEMENTS"}),
)

TIERS = {"deterministic", "curated", "extracted"}

# --- Back-compat: DEFAULT bound to the top level -----------------------------
# Anything already doing `from corpusatlas.ontology import ENTITY_TYPES` (this
# package's own tests included) keeps working unchanged — these always mean
# the default, data-and-infrastructure ontology. The pipeline itself never
# reads these; it takes `ontology=` and defaults to DEFAULT, which is what
# lets a build actually swap the vocabulary out.
ENTITY_TYPES = DEFAULT.entity_types
CONTEXT_TYPES = DEFAULT.context_types
NODE_TYPES = DEFAULT.node_types
RELATIONS = DEFAULT.relations
INVERSE = DEFAULT.inverse
INVERSE_LABEL = DEFAULT.inverse_label
RELATION_GROUPS = DEFAULT.relation_groups
CONTEXT_RELATIONS = DEFAULT.context_relations
SEMANTIC_RELATIONS = DEFAULT.semantic_relations
SYMMETRIC = DEFAULT.symmetric


def typecheck(rel: str, src_type: str, dst_type: str) -> bool:
    return DEFAULT.typecheck(rel, src_type, dst_type)


def canonical(rel: str, src: str, dst: str) -> tuple[str, str, str]:
    return DEFAULT.canonical(rel, src, dst)


def validate_edge(rel: str, src_type: str, dst_type: str, *,
                  confidence: float | None = None) -> list[str]:
    return DEFAULT.validate_edge(rel, src_type, dst_type, confidence=confidence)
