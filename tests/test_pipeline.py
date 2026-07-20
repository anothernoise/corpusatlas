"""Tests for the invariants that actually matter."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusgraph.model import Document, Edge, Node
from corpusgraph.extract import DeterministicExtractor
from corpusgraph.merge import merge
from corpusgraph.ontology import typecheck


def docs():
    return [
        Document(id="a", title="A", url="/blog/a", kind="article",
                 tags=("olap",), links=("b",)),
        Document(id="b", title="B", url="/blog/b", kind="article", tags=("olap",)),
        Document(id="assessment:x", title="X", url="/architecture-radar/x",
                 kind="assessment", meta={"platforms": ["ClickHouse", "StarRocks"]}),
    ]


def build(ds):
    ex = DeterministicExtractor()
    n, e = ex.run(ds)
    return merge([list(n)], [list(e)], live_doc_ids={d.id for d in ds})


def test_deterministic_tier_recovers_links_and_tags():
    nodes, edges = build(docs())
    rels = {(e.src, e.rel, e.dst) for e in edges}
    assert ("a", "REFERENCES", "b") in rels
    assert ("a", "ABOUT", "topic:olap") in rels
    assert ("assessment:x", "ASSESSES", "tech:clickhouse") in rels
    assert ("tech:clickhouse", "COMPARES_TO", "tech:starrocks") in rels


def test_every_edge_carries_provenance():
    _, edges = build(docs())
    assert edges
    for e in edges:
        assert e.prov.get("doc"), e
        assert e.prov.get("tier") == "deterministic"
        assert e.prov.get("extractor")


def test_ontology_rejects_ill_typed_triples():
    assert typecheck("ABOUT", "Document", "Topic")
    assert not typecheck("ABOUT", "Topic", "Document")     # wrong direction
    assert not typecheck("ASSESSES", "Document", "Topic")  # wrong types
    assert not typecheck("INVENTED", "Document", "Topic")  # unknown relation


def test_ill_typed_edges_never_reach_the_graph():
    # A tag edge from a Topic would be ill-typed; the extractor must not emit it.
    _, edges = build(docs())
    for e in edges:
        assert not e.src.startswith("topic:"), "topics must not be edge sources"


def test_retraction_drops_claims_from_deleted_documents():
    ds = docs()
    ex = DeterministicExtractor()
    n, e = ex.run(ds)
    # "a" is deleted from the corpus; its claims must not survive.
    nodes, edges = merge([list(n)], [list(e)], live_doc_ids={"b", "assessment:x"})
    assert all(edge.prov.get("doc") != "a" for edge in edges)


def test_dangling_edges_are_impossible():
    nodes, edges = build(docs())
    ids = set(nodes)
    for e in edges:
        assert e.src in ids and e.dst in ids


def test_isolated_nodes_are_pruned():
    ds = docs() + [Document(id="lonely", title="L", url="/blog/l", kind="article")]
    nodes, _ = build(ds)
    assert "lonely" not in nodes


def test_merge_is_idempotent():
    ds = docs()
    ex = DeterministicExtractor()
    n1, e1 = [list(x) for x in ex.run(ds)]
    n2, e2 = [list(x) for x in ex.run(ds)]
    once = build(ds)
    twice = merge([n1, n2], [e1, e2], live_doc_ids={d.id for d in ds})
    assert set(once[0]) == set(twice[0])
    assert {e.key for e in once[1]} == {e.key for e in twice[1]}
