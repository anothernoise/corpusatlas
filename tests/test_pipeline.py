"""Tests for the invariants that actually matter."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusgraph.adapters.entity_packs import EntityPacksAdapter
from corpusgraph.emit import write_graph
from corpusgraph.extract import DeterministicExtractor, MentionsExtractor, PackError, PacksExtractor
from corpusgraph.merge import merge
from corpusgraph.model import Document, Edge, Node
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


# --- the curated tier: signed packs, never overwriting what was hand-written ---

def pack_doc(doc_id="pack:spark", edges=None, nodes=None):
    return Document(id=doc_id, title="pack", url="/p", kind="entity-pack", meta={"pack": {
        "nodes": nodes if nodes is not None else [
            {"id": "tech:apache-spark", "type": "Technology", "label": "Spark (pack label)",
             "urls": {"external": {"wikipedia": "https://en.wikipedia.org/wiki/Apache_Spark"}}},
            {"id": "concept:lazy-evaluation", "type": "Concept", "label": "Lazy evaluation"},
        ],
        "edges": edges if edges is not None else [
            {"src": "tech:apache-spark", "rel": "USES_CONCEPT", "dst": "concept:lazy-evaluation",
             "confidence": 1.0, "sources": [{"type": "corpus", "url": "/blog/a"}]},
        ],
    }})


def build_curated(extra_docs=(), live=None):
    ds = radar_docs() + list(extra_docs)
    det = DeterministicExtractor(resolver=Resolver(ALIASES))
    n1, e1 = [list(x) for x in det.run(ds)]
    n2, e2 = [list(x) for x in PacksExtractor().run(ds)]
    return merge([n1, n2], [e1, e2], live_doc_ids=live if live is not None else {d.id for d in ds})


def test_scope_is_part_of_edge_identity():
    a = Edge("tech:x", "ALTERNATIVE_TO", "tech:y", {"doc": "p"}, scope="streaming")
    b = Edge("tech:x", "ALTERNATIVE_TO", "tech:y", {"doc": "p"}, scope="batch")
    _, edges = merge([[Node("tech:x", "X", "Technology"), Node("tech:y", "Y", "Technology")]],
                     [[a, b]], live_doc_ids={"p"})
    assert len(edges) == 2, "two scopes are two claims; dedupe must not merge them"


def test_a_plain_edge_serialises_exactly_as_before():
    e = Edge("a", "REFERENCES", "b", {"doc": "a", "tier": "deterministic"})
    assert e.to_json() == {"src": "a", "rel": "REFERENCES", "dst": "b",
                           "prov": {"doc": "a", "tier": "deterministic"}}


def test_curated_edges_carry_the_curated_tier_and_the_pack_as_document():
    _, edges = build_curated([pack_doc()])
    curated = [e for e in edges if e.rel == "USES_CONCEPT"]
    assert curated and all(e.prov["tier"] == "curated" and e.prov["doc"] == "pack:spark"
                           for e in curated)
    assert all(e.prov["tier"] == "deterministic" for e in edges if e.rel != "USES_CONCEPT")


def test_a_pack_enriches_an_existing_node_but_never_relabels_it():
    nodes, _ = build_curated([pack_doc()])
    spark = nodes["tech:apache-spark"]
    assert spark.label == "Apache Spark"                  # the scorecard's, not the pack's
    assert spark.urls["wikipedia"].endswith("/Apache_Spark")


def test_deleting_a_pack_retracts_exactly_its_claims():
    ds = radar_docs() + [pack_doc()]
    live = {d.id for d in ds} - {"pack:spark"}
    nodes, edges = build_curated([pack_doc()], live=live)
    assert not [e for e in edges if e.prov.get("doc") == "pack:spark"]
    assert "concept:lazy-evaluation" not in nodes          # nothing else held it up
    assert ("tech:apache-spark", "HAS_RADAR_ENTRY", "radar:apache-spark") in \
        {(e.src, e.rel, e.dst) for e in edges}             # deterministic claims untouched


def test_an_ill_typed_curated_edge_fails_the_build():
    bad = pack_doc(edges=[{"src": "concept:lazy-evaluation", "rel": "HAS_COMPONENT",
                           "dst": "tech:apache-spark", "confidence": 1.0, "sources": []}])
    try:
        PacksExtractor().run([bad])
    except PackError:
        return
    raise AssertionError("an ill-typed signed claim must not be dropped silently")


def test_an_alternative_without_scope_fails_the_build():
    bad = pack_doc(edges=[{"src": "tech:apache-spark", "rel": "ALTERNATIVE_TO",
                           "dst": "tech:apache-flink", "confidence": 1.0, "sources": []}])
    try:
        PacksExtractor().run([bad])
    except PackError:
        return
    raise AssertionError("ALTERNATIVE_TO without a scope is a slogan, not a claim")


def test_unsigned_packs_are_not_published():
    with tempfile.TemporaryDirectory() as d:
        for name, reviewed in (("signed", "2026-09-16"), ("draft", None)):
            (Path(d) / f"{name}.json").write_text(json.dumps({
                "target": {"id": "tech:x", "label": name, "type": "Technology"},
                "authored": {"reviewed": reviewed, "reviewed_by": reviewed and "a person"},
                "nodes": [], "edges": []}))
        (Path(d) / "pack.schema.json").write_text("{}")
        assert [x.id for x in EntityPacksAdapter(d).documents()] == ["pack:signed"]
        assert [x.id for x in EntityPacksAdapter(d, include_drafts=True).documents()] == \
            ["pack:draft", "pack:signed"]


def test_the_artifact_is_byte_identical_across_builds():
    nodes, edges = build_curated([pack_doc()])
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a.json", Path(d) / "b.json"
        write_graph(a, nodes, edges, sources=["x"])
        write_graph(b, dict(reversed(list(nodes.items()))), list(reversed(edges)), sources=["x"])
        assert a.read_bytes() == b.read_bytes()


# --- the extracted tier: deterministic mention-matching over article text ----

def mention_docs(body):
    return [
        Document(id="m", title="M", url="/blog/m", kind="article", text=body),
    ]


def test_mentions_finds_a_technology_never_tagged():
    vocab = [Node(id="tech:apache-spark", label="Apache Spark", type="Technology")]
    body = "Apache Spark schedules a DAG of stages. " * 2
    _, edges = MentionsExtractor(vocab).run(mention_docs(body))
    assert ("m", "COVERS", "tech:apache-spark") in {(e.src, e.rel, e.dst) for e in edges}
    assert edges[0].prov["tier"] == "extracted"


def test_mentions_requires_more_than_one_hit_for_a_short_form():
    vocab = [Node(id="tech:apache-kafka", label="Kafka", type="Technology")]
    body = "Kafka is mentioned exactly once here and never again."
    _, edges = MentionsExtractor(vocab).run(mention_docs(body))
    assert not edges, "a single passing mention of a short form must not become a claim"


def test_mentions_never_matches_a_substring_of_another_word():
    # "Spark" must not fire on "SparkNotes" or "sparking".
    vocab = [Node(id="tech:apache-spark", label="Spark", type="Technology")]
    body = "SparkNotes is unrelated, and sparking plugs are unrelated too. " * 2
    _, edges = MentionsExtractor(vocab).run(mention_docs(body))
    assert not edges


def test_mentions_finds_a_curated_concept_via_its_parenthetical_alias():
    # "Resilient distributed dataset (RDD)" should also match on "RDD" alone,
    # and on the label with the parenthetical stripped — both derived from
    # what a human already wrote, never guessed.
    vocab = [Node(id="concept:rdd", label="Resilient distributed dataset (RDD)", type="Concept")]
    body = "An RDD is immutable. RDDs recompute lost partitions from lineage."
    _, edges = MentionsExtractor(vocab).run(mention_docs(body))
    rels = {(e.src, e.rel, e.dst) for e in edges}
    assert ("concept:rdd", "DISCUSSED_IN", "m") in rels


def test_mentions_ignores_non_article_kinds():
    vocab = [Node(id="tech:apache-spark", label="Apache Spark", type="Technology")]
    docs = [Document(id="assessment:x", title="X", url="/architecture-radar/x",
                     kind="assessment", text="Apache Spark Apache Spark Apache Spark")]
    _, edges = MentionsExtractor(vocab).run(docs)
    assert not edges


def test_mentions_never_overrides_an_existing_tag_based_claim():
    # Same (src, rel, dst) as a deterministic COVERS edge merge() already
    # keeps — the extracted duplicate must be superseded, not conflict. The
    # assessment is what gives tech:apache-spark a real Technology node;
    # without one, DeterministicExtractor's own typecheck would already
    # drop the tag-based edge before mentions ever runs.
    ds = [
        Document(id="a", title="A", url="/blog/a", kind="article", tags=("spark",),
                 text="Apache Spark Apache Spark Apache Spark"),
        Document(id="assessment:x", title="X", url="/architecture-radar/x", kind="assessment",
                 meta={"platforms": ["Apache Spark"]}),
    ]
    resolver = Resolver([{"canonical": "tech:apache-spark", "label": "Apache Spark", "tags": ["spark"]}])
    det = DeterministicExtractor(resolver=resolver)
    det_nodes, det_edges = (list(x) for x in det.run(ds))
    ment_nodes, ment_edges = (list(x) for x in MentionsExtractor(det_nodes).run(ds))
    nodes, edges = merge([det_nodes, ment_nodes], [det_edges, ment_edges],
                         live_doc_ids={d.id for d in ds})
    covers = [e for e in edges if e.rel == "COVERS" and e.src == "a" and e.dst == "tech:apache-spark"]
    assert len(covers) == 1 and covers[0].prov["tier"] == "deterministic"


def test_mentions_output_is_idempotent():
    vocab = [Node(id="tech:apache-spark", label="Apache Spark", type="Technology"),
             Node(id="concept:shuffle", label="Shuffle", type="Concept")]
    body = "Apache Spark's shuffle moves data across the network. Shuffle is costly."
    ex = MentionsExtractor(vocab)
    _, e1 = ex.run(mention_docs(body))
    _, e2 = ex.run(mention_docs(body))
    assert {e.key for e in e1} == {e.key for e in e2} and len(e1) == len(e2)
