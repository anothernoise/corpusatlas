"""Tests for a non-default Ontology actually taking effect through the whole
pipeline — not just the loader in isolation. A custom ontology that only
works at the Ontology.from_toml() level and silently falls back to DEFAULT
the moment it reaches an extractor would be a much worse bug than one that
fails loudly, so this drives real Document objects through
DeterministicExtractor, PacksExtractor, MentionsExtractor, merge and
write_graph with a domain that looks nothing like this package's own
(cooking, not data architecture) and checks the artifact reflects that
domain, not the default one.
"""
import json
import sys
import tempfile
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.emit import write_graph
from corpusatlas.extract import DeterministicExtractor, MentionsExtractor, PackError, PacksExtractor
from corpusatlas.merge import merge
from corpusatlas.model import Document
from corpusatlas.ontology import DEFAULT, Ontology, OntologyError
from corpusatlas.resolve import Resolver

# A domain that shares no type or relation names with DEFAULT, on purpose —
# a bug that leaks the default ontology in would otherwise be invisible.
RECIPES = Ontology(
    entity_types=frozenset({"Dish", "Ingredient"}),
    context_types=frozenset({"Document"}),
    relations={
        "USES_INGREDIENT": (frozenset({"Dish"}), frozenset({"Ingredient"})),
        "PAIRS_WITH": (frozenset({"Dish"}), frozenset({"Dish"})),
        "COVERS": (frozenset({"Document"}), frozenset({"Dish", "Ingredient"})),
    },
    relation_groups={"Composition": ("USES_INGREDIENT", "PAIRS_WITH")},
    context_relations=("COVERS",),
    symmetric=frozenset({"PAIRS_WITH"}),
)

RECIPES_TOML = textwrap.dedent("""
    entity_types = ["Dish", "Ingredient"]
    context_types = ["Document"]

    [[relation]]
    name = "USES_INGREDIENT"
    source = ["Dish"]
    target = ["Ingredient"]
    group = "Composition"

    [[relation]]
    name = "PAIRS_WITH"
    source = ["Dish"]
    target = ["Dish"]
    group = "Composition"
    symmetric = true

    [[relation]]
    name = "COVERS"
    source = ["Document"]
    target = ["Dish", "Ingredient"]
    context = true
""")


def write_toml(text: str) -> str:
    with tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False) as f:
        f.write(text)
        return f.name


# --- Ontology construction and validation ------------------------------------

def test_a_well_formed_ontology_constructs_without_error():
    assert RECIPES.semantic_relations == {"USES_INGREDIENT", "PAIRS_WITH"}
    assert RECIPES.typecheck("USES_INGREDIENT", "Dish", "Ingredient")
    assert not RECIPES.typecheck("USES_INGREDIENT", "Ingredient", "Dish")


def test_from_toml_matches_the_equivalent_python_construction():
    loaded = Ontology.from_toml(write_toml(RECIPES_TOML))
    assert loaded.entity_types == RECIPES.entity_types
    assert loaded.context_types == RECIPES.context_types
    assert loaded.relations == RECIPES.relations
    assert loaded.relation_groups == RECIPES.relation_groups
    assert loaded.context_relations == RECIPES.context_relations
    assert loaded.symmetric == RECIPES.symmetric


def test_a_relation_neither_context_nor_grouped_is_rejected():
    bad = textwrap.dedent("""
        entity_types = ["Dish", "Ingredient"]

        [[relation]]
        name = "USES_INGREDIENT"
        source = ["Dish"]
        target = ["Ingredient"]
    """)
    try:
        Ontology.from_toml(write_toml(bad))
    except OntologyError as e:
        assert "USES_INGREDIENT" in str(e)
        return
    raise AssertionError("expected OntologyError")


def test_a_relation_referencing_an_undeclared_type_is_rejected():
    try:
        Ontology(entity_types=frozenset({"Dish"}), context_types=frozenset(),
                relations={"BAD": (frozenset({"Dish"}), frozenset({"Nonexistent"}))},
                relation_groups={"G": ("BAD",)})
    except OntologyError as e:
        assert "Nonexistent" in str(e)
        return
    raise AssertionError("expected OntologyError")


def test_entity_and_context_types_cannot_overlap():
    try:
        Ontology(entity_types=frozenset({"Thing"}), context_types=frozenset({"Thing"}))
    except OntologyError:
        return
    raise AssertionError("expected OntologyError")


def test_a_relation_cannot_be_both_semantic_and_context():
    try:
        Ontology(entity_types=frozenset({"Dish"}), context_types=frozenset(),
                relations={"X": (frozenset({"Dish"}), frozenset({"Dish"}))},
                relation_groups={"G": ("X",)}, context_relations=("X",))
    except OntologyError:
        return
    raise AssertionError("expected OntologyError")


def test_an_inverse_naming_an_unknown_relation_is_rejected():
    try:
        Ontology(entity_types=frozenset({"Dish"}), context_types=frozenset(),
                relations={"X": (frozenset({"Dish"}), frozenset({"Dish"}))},
                relation_groups={"G": ("X",)}, inverse={"Y": "NOT_X"})
    except OntologyError as e:
        assert "NOT_X" in str(e)
        return
    raise AssertionError("expected OntologyError")


# --- the ontology actually reaching every stage of the pipeline -------------

def recipe_corpus():
    return [
        Document(id="pack:pasta", title="pasta pack", url="/p", kind="entity-pack", meta={"pack": {
            "subject": {"id": "carbonara", "name": "Carbonara", "type": "Dish"},
            "authored": {"method": "test", "model": "test", "drafted": "2026-01-01"},
            "entities": [
                {"id": "carbonara", "name": "Carbonara", "type": "Dish"},
                {"id": "guanciale", "name": "Guanciale", "type": "Ingredient"},
                {"id": "cacio-e-pepe", "name": "Cacio e pepe", "type": "Dish"},
            ],
            "relationships": [
                {"source_id": "carbonara", "relationship": "USES_INGREDIENT", "target_id": "guanciale",
                 "confidence": 0.99, "explanation": "It's the defining ingredient."},
                {"source_id": "carbonara", "relationship": "PAIRS_WITH", "target_id": "cacio-e-pepe",
                 "confidence": 0.7, "explanation": "Both Roman pasta classics."},
            ],
        }}),
        Document(id="article:roman-pasta", title="Roman pasta, four ways", url="/blog/roman-pasta",
                kind="article",
                text="Carbonara is the one people get wrong most often. Good Carbonara has no cream."),
    ]


def test_a_pack_relationship_the_default_ontology_has_never_heard_of_builds_cleanly():
    docs = recipe_corpus()
    resolver = Resolver(ontology=RECIPES)
    pack_nodes, pack_edges = PacksExtractor(resolver=resolver, ontology=RECIPES).run(docs)
    rels = {(e.src, e.rel, e.dst) for e in pack_edges}
    assert ("entity:carbonara", "USES_INGREDIENT", "entity:guanciale") in rels
    # PAIRS_WITH is symmetric and stored one direction only, sorted.
    assert (("entity:carbonara", "PAIRS_WITH", "entity:cacio-e-pepe") in rels
            or ("entity:cacio-e-pepe", "PAIRS_WITH", "entity:carbonara") in rels)


def test_the_default_ontology_would_have_rejected_the_same_relationship():
    # Not a hypothetical: USES_INGREDIENT isn't in DEFAULT.relations at all,
    # so building the same pack against the default ontology must fail —
    # proof the two ontologies are actually different, not that RECIPES
    # happens to be a superset.
    docs = recipe_corpus()
    try:
        PacksExtractor(resolver=Resolver(), ontology=DEFAULT).run(docs)
    except PackError as e:
        assert "USES_INGREDIENT" in str(e)
        return
    raise AssertionError("expected the default ontology to reject an unknown relation")


def test_full_pipeline_with_a_custom_ontology_emits_the_custom_vocabulary():
    docs = recipe_corpus()
    resolver = Resolver(ontology=RECIPES)
    det_nodes, det_edges = DeterministicExtractor(resolver=resolver, ontology=RECIPES).run(docs)
    pack_nodes, pack_edges = PacksExtractor(resolver=resolver, ontology=RECIPES).run(docs)
    ment_nodes, ment_edges = MentionsExtractor(list(det_nodes) + list(pack_nodes), resolver=resolver,
                                               ontology=RECIPES).run(docs)
    nodes, edges = merge([det_nodes, pack_nodes, ment_nodes], [det_edges, pack_edges, ment_edges],
                         live_doc_ids={d.id for d in docs})

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "graph.json"
        write_graph(out, nodes, edges, sources=["entity_packs (1)", "html_blog (1)"], ontology=RECIPES)
        payload = json.loads(out.read_text())

    assert payload["entity_types"] == ["Dish", "Ingredient"]
    assert payload["context_types"] == ["Document"]
    assert payload["relation_groups"] == {"Composition": ["USES_INGREDIENT", "PAIRS_WITH"]}
    # Mentions found "Carbonara" (mentioned twice) in the article text via the
    # entity's own name, and COVERS is a context relation in this ontology
    # too — same relation name as DEFAULT's, independently declared here.
    assert payload["context_relations"] == ["COVERS"]
    assert any(e["src"] == "article:roman-pasta" and e["rel"] == "COVERS" and e["dst"] == "entity:carbonara"
              for e in payload["edges"])


def test_cmd_validate_accepts_an_artifact_built_from_a_custom_ontology():
    from corpusatlas.__main__ import cmd_validate

    docs = recipe_corpus()
    resolver = Resolver(ontology=RECIPES)
    det_nodes, det_edges = DeterministicExtractor(resolver=resolver, ontology=RECIPES).run(docs)
    pack_nodes, pack_edges = PacksExtractor(resolver=resolver, ontology=RECIPES).run(docs)
    nodes, edges = merge([det_nodes, pack_nodes], [det_edges, pack_edges],
                         live_doc_ids={d.id for d in docs})

    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "graph.json"
        write_graph(out, nodes, edges, sources=["entity_packs (1)"], ontology=RECIPES)

        class Args:
            graph = str(out)
        assert cmd_validate(Args()) == 0
