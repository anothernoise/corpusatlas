"""Tests for Datalog-Lite forward-chaining rule inference engine."""
from corpusatlas.datalog import DatalogRule, DatalogEngine, run_inference
from corpusatlas.model import Edge, Node


def test_transitive_inference():
    # A is_a B, B is_a C => A is_a C
    e1 = Edge(src="entity:dog", rel="is_a", dst="entity:canine", confidence=1.0)
    e2 = Edge(src="entity:canine", rel="is_a", dst="entity:mammal", confidence=1.0)
    e3 = Edge(src="entity:mammal", rel="is_a", dst="entity:animal", confidence=0.9)

    rule = DatalogRule(
        name="transitive_is_a",
        rule_type="transitive",
        rel="is_a",
        dampening=0.9,
    )

    engine = DatalogEngine([rule])
    inferred_edges = engine.infer(edges=[e1, e2, e3])

    pairs = {(e.src, e.rel, e.dst) for e in inferred_edges}
    assert ("entity:dog", "is_a", "entity:mammal") in pairs
    assert ("entity:canine", "is_a", "entity:animal") in pairs
    assert ("entity:dog", "is_a", "entity:animal") in pairs

    # Check confidence dampening: 1.0 * 1.0 * 0.9 * 0.9 * 0.9
    e_dog_mammal = next(e for e in inferred_edges if (e.src, e.dst) == ("entity:dog", "entity:mammal"))
    assert e_dog_mammal.confidence == 0.9
    assert e_dog_mammal.prov.get("rule") == "transitive_is_a"


def test_inverse_and_symmetric_inference():
    e1 = Edge(src="entity:paris", rel="located_in", dst="entity:france", confidence=1.0)
    rule_inv = DatalogRule(
        name="located_in_inverse",
        rule_type="inverse",
        rel="located_in",
        target_rel="contains_location",
        dampening=1.0,
    )
    e2 = Edge(src="entity:alice", rel="colleague_with", dst="entity:bob", confidence=0.8)
    rule_sym = DatalogRule(
        name="colleague_symmetric",
        rule_type="symmetric",
        rel="colleague_with",
        dampening=1.0,
    )

    engine = DatalogEngine([rule_inv, rule_sym])
    inferred = engine.infer([e1, e2])

    pairs = {(e.src, e.rel, e.dst) for e in inferred}
    assert ("entity:france", "contains_location", "entity:paris") in pairs
    assert ("entity:bob", "colleague_with", "entity:alice") in pairs
