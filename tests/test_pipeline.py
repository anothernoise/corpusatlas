"""Tests for the invariants that actually matter."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusgraph.model import Document, Edge, Node
from corpusgraph.extract import DeterministicExtractor
from corpusgraph.merge import merge
from corpusgraph.ontology import typecheck
from corpusgraph.resolve import Resolver


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


# --- the radar layer: dated calls, and the alias table that grounds them -----

ALIASES = [
    {"canonical": "tech:apache-spark", "label": "Apache Spark", "tags": ["spark"]},
    {"canonical": "tech:duckdb", "label": "DuckDB", "radar": ["duckdb"]},
]


def radar_docs():
    """A scorecard, three radar entries that join to it in different ways, and
    one tagged article — the four shapes the radar layer has to handle."""
    return [
        Document(id="a", title="A", url="/blog/a", kind="article", tags=("spark", "olap")),
        Document(id="assessment:engines", title="Engines", url="/architecture-radar/engines",
                 kind="assessment", meta={"platforms": ["Apache Spark", "Apache Flink"]}),
        # Scored: joins to its technology through the scorecard option.
        Document(id="radar:apache-spark", title="Apache Spark",
                 url="/architecture-radar/engines", kind="radar-entry",
                 meta={"entry": "apache-spark", "ring": "adopt", "quadrant": "tools",
                       "assessment": "engines", "options": ["Apache Spark"],
                       "documented_in": "assessment:engines",
                       "history": [{"date": "2026-07-08", "event": "added", "ring": "adopt"}]}),
        # A practice: no scorecard, and no technology behind it.
        Document(id="radar:eval-driven", title="Eval-driven development",
                 url="/blog/a", kind="radar-entry",
                 meta={"entry": "eval-driven", "ring": "adopt", "options": [],
                       "documented_in": "a"}),
        # A technology with no scorecard: only the alias table can name it.
        Document(id="radar:duckdb", title="DuckDB", url="/blog/a", kind="radar-entry",
                 meta={"entry": "duckdb", "ring": "trial", "options": [],
                       "documented_in": "a"}),
    ]


def build_radar():
    ds = radar_docs()
    ex = DeterministicExtractor(resolver=Resolver(ALIASES))
    n, e = ex.run(ds)
    return merge([list(n)], [list(e)], live_doc_ids={d.id for d in ds})


def test_radar_entry_joins_its_technology_assessment_and_page():
    _, edges = build_radar()
    rels = {(e.src, e.rel, e.dst) for e in edges}
    assert ("tech:apache-spark", "HAS_RADAR_ENTRY", "radar:apache-spark") in rels
    assert ("radar:apache-spark", "ASSESSED_IN", "assessment:engines") in rels
    assert ("radar:apache-spark", "DOCUMENTED_IN", "assessment:engines") in rels


def test_a_practice_entry_never_invents_a_technology():
    nodes, edges = build_radar()
    assert not [e for e in edges if e.rel == "HAS_RADAR_ENTRY" and e.dst == "radar:eval-driven"]
    # It still reaches the graph, hanging from the page that argues it.
    assert "radar:eval-driven" in nodes
    assert ("radar:eval-driven", "DOCUMENTED_IN", "a") in {(e.src, e.rel, e.dst) for e in edges}


def test_the_alias_table_grounds_an_entry_with_no_scorecard():
    nodes, edges = build_radar()
    assert nodes["tech:duckdb"].type == "Technology"
    assert nodes["tech:duckdb"].label == "DuckDB"
    assert ("tech:duckdb", "HAS_RADAR_ENTRY", "radar:duckdb") in {(e.src, e.rel, e.dst) for e in edges}


def test_covers_fires_only_for_tags_the_table_calls_technologies():
    _, edges = build_radar()
    rels = {(e.src, e.rel, e.dst) for e in edges}
    assert ("a", "COVERS", "tech:apache-spark") in rels      # "spark" is a technology
    assert ("a", "ABOUT", "topic:olap") in rels              # "olap" is still a subject
    assert not [e for e in edges if e.rel == "COVERS" and e.dst != "tech:apache-spark"]


def test_the_ring_stays_on_the_dated_entry_not_the_technology():
    """"Adopt" was true of an edition. The technology has no ring, ever."""
    nodes, _ = build_radar()
    assert nodes["radar:apache-spark"].meta["ring"] == "adopt"
    assert "ring" not in nodes["tech:apache-spark"].meta
    assert nodes["radar:apache-spark"].meta["history"][0]["date"] == "2026-07-08"


def test_resolution_falls_back_to_slugging_but_never_guesses():
    bare = Resolver()
    assert bare.resolve("Apache Spark", "tech") == "tech:apache-spark"
    assert bare.resolve("Arrow / DataFusion", "tech") == "tech:arrow-datafusion"
    # Tags and radar entries are table-only: without an entry, no claim.
    assert bare.resolve("spark", "tag") is None
    assert bare.resolve("duckdb", "radar") is None
