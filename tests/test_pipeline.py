"""Tests for the invariants that actually matter."""
import io
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.__main__ import cmd_validate
from corpusatlas.adapters.entity_packs import EntityPacksAdapter
from corpusatlas.emit import write_graph
from corpusatlas.extract import DeterministicExtractor, MentionsExtractor, PackError, PacksExtractor
from corpusatlas.merge import merge
from corpusatlas.model import Document, Edge, Node
from corpusatlas.ontology import CONTEXT_TYPES, ENTITY_TYPES, RELATIONS, SEMANTIC_RELATIONS, typecheck
from corpusatlas.resolve import RegistryError, Resolver

REGISTRY = [
    {"id": "apache-spark", "name": "Apache Spark", "type": "Technology", "aliases": ["Spark"],
     "options": ["Apache Spark"], "tags": ["spark"], "wikipedia_url": "https://en.wikipedia.org/wiki/Apache_Spark"},
    {"id": "apache-flink", "name": "Apache Flink", "type": "Technology", "options": ["Apache Flink"]},
    {"id": "clickhouse", "name": "ClickHouse", "type": "Technology", "options": ["ClickHouse"]},
    {"id": "apache-druid", "name": "Apache Druid", "type": "Technology", "options": ["Apache Druid", "Druid / Pinot"]},
    {"id": "apache-pinot", "name": "Apache Pinot", "type": "Technology", "options": ["Druid / Pinot"]},
    {"id": "snowflake", "name": "Snowflake", "type": "Product", "options": ["Snowflake"], "case_sensitive": True},
    {"id": "eval-driven-development", "name": "Eval-driven development", "type": "Concept", "radar": ["eval-driven"]},
    {"id": "microsoft", "name": "Microsoft", "type": "Company"},
]


def resolver():
    return Resolver(REGISTRY)


def corpus():
    """Two articles, a scorecard with a split option, and radar entries that
    join to entities in the three ways the radar layer has to handle."""
    return [
        Document(id="a", title="A", url="/blog/a", kind="article", tags=("spark", "olap"), links=("b",)),
        Document(id="b", title="B", url="/blog/b", kind="article", tags=("olap",)),
        Document(id="assessment:olap", title="OLAP", url="/architecture-radar/olap", kind="assessment",
                 meta={"platforms": ["ClickHouse", "Snowflake", "Druid / Pinot"]}),
        Document(id="radar:clickhouse", title="ClickHouse", url="/architecture-radar/olap", kind="radar-entry",
                 meta={"entry": "clickhouse", "ring": "trial", "quadrant": "platforms", "assessment": "olap",
                       "options": ["ClickHouse"], "documented_in": "assessment:olap",
                       "history": [{"date": "2026-07-08", "event": "added", "ring": "trial"}]}),
        Document(id="radar:druid-pinot", title="Druid / Pinot", url="/architecture-radar/olap", kind="radar-entry",
                 meta={"entry": "druid-pinot", "ring": "trial", "options": ["Apache Druid", "Druid / Pinot"],
                       "documented_in": "assessment:olap"}),
        Document(id="radar:eval-driven", title="Eval-driven development", url="/blog/a", kind="radar-entry",
                 meta={"entry": "eval-driven", "ring": "adopt", "options": [], "documented_in": "a"}),
    ]


def build(docs=None, r=None, live=None):
    docs = corpus() if docs is None else docs
    r = r or resolver()
    n1, e1 = DeterministicExtractor(resolver=r).run(docs)
    n2, e2 = PacksExtractor(resolver=r).run(docs)
    n3, e3 = MentionsExtractor(list(n1) + list(n2), resolver=r).run(docs)
    return merge([list(n1), list(n2), list(n3)], [list(e1), list(e2), list(e3)],
                 live_doc_ids=live if live is not None else {d.id for d in docs})


def rels(edges):
    return {(e.src, e.rel, e.dst) for e in edges}


# --- the deterministic tier ---------------------------------------------------

def test_deterministic_tier_recovers_links_tags_and_scorecards():
    _, edges = build()
    r = rels(edges)
    assert ("a", "REFERENCES", "b") in r
    assert ("a", "ABOUT", "topic:olap") in r
    assert ("a", "COVERS", "entity:apache-spark") in r
    assert ("assessment:olap", "ASSESSES", "entity:clickhouse") in r
    assert ("entity:clickhouse", "COMPARES_TO", "entity:snowflake") in r


def test_every_edge_carries_provenance_and_a_tier():
    _, edges = build()
    assert edges
    for e in edges:
        assert e.prov.get("doc") and e.prov.get("extractor"), e
        assert e.prov.get("tier") in {"deterministic", "curated", "extracted"}


def test_retraction_drops_claims_from_deleted_documents():
    docs = corpus()
    _, edges = build(docs, live={d.id for d in docs} - {"a"})
    assert all(e.prov.get("doc") != "a" for e in edges)


def test_dangling_edges_are_impossible_and_isolated_nodes_pruned():
    docs = corpus() + [Document(id="lonely", title="L", url="/blog/l", kind="article")]
    nodes, edges = build(docs)
    assert all(e.src in nodes and e.dst in nodes for e in edges)
    assert "lonely" not in nodes


def test_merge_is_idempotent():
    docs = corpus()
    det = DeterministicExtractor(resolver=resolver())
    n1, e1 = det.run(docs)
    n2, e2 = det.run(docs)
    live = {d.id for d in docs}
    once = merge([list(n1)], [list(e1)], live_doc_ids=live)
    twice = merge([list(n1), list(n2)], [list(e1), list(e2)], live_doc_ids=live)
    assert set(once[0]) == set(twice[0]) and {e.key for e in once[1]} == {e.key for e in twice[1]}


# --- the ontology --------------------------------------------------------------

def test_ontology_rejects_ill_typed_triples():
    assert typecheck("IMPLEMENTS", "Technology", "Concept")
    assert not typecheck("IMPLEMENTS", "Concept", "Technology")    # wrong direction
    assert not typecheck("INCLUDED_IN", "Technology", "Concept")   # wrong target
    assert not typecheck("INVENTED", "Technology", "Concept")      # unknown relation


def test_reads_and_writes_accept_a_component_target():
    # A storage subsystem (HDFS, a Component of Hadoop) is exactly the kind
    # of thing another technology reads and writes — the same reasoning
    # RUNS_ON already applies to a Component cluster manager.
    assert typecheck("READS", "Technology", "Component")
    assert typecheck("WRITES", "Technology", "Component")
    assert not typecheck("READS", "Concept", "Component")


def test_semantic_relations_never_touch_context_types():
    assert not ENTITY_TYPES & CONTEXT_TYPES
    for rel in SEMANTIC_RELATIONS:
        src, dst = RELATIONS[rel]
        assert not (src | dst) & CONTEXT_TYPES, rel


def test_validate_refuses_a_semantic_edge_on_a_context_node():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "g.json"
        p.write_text(json.dumps({
            "counts": {"nodes": 2, "edges": 1},
            "nodes": [{"id": "a", "type": "Document"}, {"id": "entity:x", "type": "Concept"}],
            "edges": [{"src": "a", "rel": "IMPLEMENTS", "dst": "entity:x",
                       "prov": {"doc": "a", "tier": "deterministic"}}]}))
        assert cmd_validate(type("Args", (), {"graph": str(p)})) == 1


# --- the registry ----------------------------------------------------------------

def test_registry_type_wins_and_ids_are_type_neutral():
    nodes, _ = build()
    assert nodes["entity:snowflake"].type == "Product"
    assert nodes["entity:snowflake"].label == "Snowflake"
    assert nodes["entity:apache-spark"].urls["wikipedia"].endswith("/Apache_Spark")


def test_a_split_option_fans_out_but_its_parts_are_not_compared():
    _, edges = build()
    r = rels(edges)
    compared = {frozenset((e.src, e.dst)) for e in edges if e.rel == "COMPARES_TO"}
    for part in ("entity:apache-druid", "entity:apache-pinot"):
        assert ("assessment:olap", "ASSESSES", part) in r
        assert frozenset((part, "entity:clickhouse")) in compared
        assert (part, "HAS_RADAR_ENTRY", "radar:druid-pinot") in r
    assert frozenset(("entity:apache-druid", "entity:apache-pinot")) not in compared


def test_comparisons_are_stored_once_per_pair():
    _, edges = build()
    pairs = [frozenset((e.src, e.dst)) for e in edges if e.rel == "COMPARES_TO"]
    assert len(pairs) == len(set(pairs))


def test_comparisons_carry_an_explanation_naming_the_assessment():
    _, edges = build()
    compared = next(e for e in edges if e.rel == "COMPARES_TO")
    assert compared.explanation == 'Both were scored on the same axes in the "OLAP" assessment.'


def test_radar_entry_joins_its_entity_assessment_and_page():
    _, edges = build()
    r = rels(edges)
    assert ("entity:clickhouse", "HAS_RADAR_ENTRY", "radar:clickhouse") in r
    assert ("radar:clickhouse", "ASSESSED_IN", "assessment:olap") in r
    assert ("radar:clickhouse", "DOCUMENTED_IN", "assessment:olap") in r


def test_a_practice_radar_entry_resolves_through_the_registry():
    _, edges = build()
    assert ("entity:eval-driven-development", "HAS_RADAR_ENTRY", "radar:eval-driven") in rels(edges)


def test_the_ring_stays_on_the_dated_entry_not_the_entity():
    nodes, _ = build()
    assert nodes["radar:clickhouse"].meta["ring"] == "trial"
    assert "ring" not in nodes["entity:clickhouse"].meta


def test_tags_and_radar_ids_resolve_only_through_the_table():
    r = resolver()
    assert r.resolve("spark", "tag") == ["entity:apache-spark"]
    assert r.resolve("olap", "tag") == []
    assert r.resolve("unknown-entry", "radar") == []
    assert r.resolve("Druid / Pinot", "option") == ["entity:apache-druid", "entity:apache-pinot"]
    assert r.resolve("Some New Engine", "option") == ["entity:some-new-engine"]


def test_the_registry_refuses_duplicates_and_non_entity_types():
    for bad in ([REGISTRY[0], REGISTRY[0]], [{"id": "x", "name": "X", "type": "Document"}]):
        try:
            Resolver(bad)
        except RegistryError:
            continue
        raise AssertionError(f"registry accepted {bad}")


# --- the curated tier --------------------------------------------------------------

def pack_doc(entities=None, relationships=None, doc_id="pack:spark"):
    return Document(id=doc_id, title="pack", url="/p", kind="entity-pack", meta={"pack": {
        "subject": {"id": "apache-spark", "name": "Apache Spark", "type": "Technology"},
        "authored": {"method": "model-drafted", "model": "m", "drafted": "2026-09-16"},
        "entities": entities if entities is not None else [
            {"id": "apache-spark", "name": "Spark (pack label)", "type": "Technology",
             "short_description": "Distributed engine.", "blog_url": "/blog/a"},
            {"id": "lazy-evaluation", "name": "Lazy evaluation", "type": "Concept"},
            {"id": "structured-streaming", "name": "Structured Streaming", "type": "Component"},
        ],
        "relationships": relationships if relationships is not None else [
            {"source_id": "lazy-evaluation", "relationship": "IMPLEMENTED_BY", "target_id": "apache-spark",
             "confidence": 0.95, "explanation": "Transformations are deferred."},
            {"source_id": "structured-streaming", "relationship": "COMPONENT_OF", "target_id": "apache-spark",
             "confidence": 0.99, "explanation": "Ships with Spark."},
        ],
    }})


def test_an_inverse_relation_is_stored_canonically_exactly_once():
    both = [
        {"source_id": "lazy-evaluation", "relationship": "IMPLEMENTED_BY", "target_id": "apache-spark",
         "confidence": 0.95, "explanation": "x"},
        {"source_id": "apache-spark", "relationship": "IMPLEMENTS", "target_id": "lazy-evaluation",
         "confidence": 0.95, "explanation": "x"},
    ]
    _, edges = build(corpus() + [pack_doc(relationships=both)])
    implements = [(e.src, e.dst) for e in edges if e.rel == "IMPLEMENTS"]
    assert implements == [("entity:apache-spark", "entity:lazy-evaluation")]
    _, edges = build(corpus() + [pack_doc()])
    assert ("entity:apache-spark", "HAS_COMPONENT", "entity:structured-streaming") in rels(edges)


def test_a_symmetric_relation_is_stored_once():
    both = [
        {"source_id": "apache-spark", "relationship": "ALTERNATIVE_TO", "target_id": "apache-flink",
         "confidence": 0.75, "explanation": "x"},
        {"source_id": "apache-flink", "relationship": "ALTERNATIVE_TO", "target_id": "apache-spark",
         "confidence": 0.75, "explanation": "x"},
    ]
    _, edges = build(corpus() + [pack_doc(relationships=both)])
    assert len([e for e in edges if e.rel == "ALTERNATIVE_TO"]) == 1


def test_a_pack_enriches_a_registered_entity_but_never_relabels_it():
    nodes, edges = build(corpus() + [pack_doc()])
    spark = nodes["entity:apache-spark"]
    assert spark.label == "Apache Spark"                      # the registry's, not the pack's
    assert spark.meta["description"] == "Distributed engine."
    assert spark.urls["wikipedia"].endswith("/Apache_Spark")
    assert ("entity:apache-spark", "PRIMARY_TOPIC_OF", "a") in rels(edges)


def test_curated_edges_carry_the_curated_tier_and_the_pack_as_document():
    _, edges = build(corpus() + [pack_doc()])
    curated = [e for e in edges if e.rel in ("IMPLEMENTS", "HAS_COMPONENT")]
    assert curated and all(e.prov["tier"] == "curated" and e.prov["doc"] == "pack:spark" for e in curated)


def test_deleting_a_pack_retracts_exactly_its_claims():
    docs = corpus() + [pack_doc()]
    nodes, edges = build(docs, live={d.id for d in docs} - {"pack:spark"})
    assert not [e for e in edges if e.prov.get("doc") == "pack:spark"]
    assert "entity:lazy-evaluation" not in nodes
    assert ("entity:clickhouse", "HAS_RADAR_ENTRY", "radar:clickhouse") in rels(edges)


def test_pack_urls_resolve_through_the_configured_prefixes():
    # A corpus that publishes articles somewhere other than /blog/ still joins
    # its packs to its documents — the prefixes are configuration, not a constant.
    pack = pack_doc(entities=[
        {"id": "apache-spark", "name": "Spark", "type": "Technology",
         "blog_url": "https://example.org/posts/a",
         "architecture_radar_url": "https://example.org/calls/olap"},
    ], relationships=[])
    ex = PacksExtractor(resolver=resolver(), site_url="https://example.org",
                        blog_prefix="/posts/", assessment_prefix="/calls/",
                        assessment_id_prefix="call:")
    _, edges = ex.run([pack])
    assert ("entity:apache-spark", "PRIMARY_TOPIC_OF", "a") in rels(edges)
    assert ("entity:apache-spark", "DISCUSSED_IN", "call:olap") in rels(edges)


def test_pack_url_prefixes_default_to_the_built_in_shape():
    cfg_built = PacksExtractor.from_config({}, resolver=resolver())
    _, edges = cfg_built.run([pack_doc()])
    assert ("entity:apache-spark", "PRIMARY_TOPIC_OF", "a") in rels(edges)


def test_a_pack_url_matching_no_prefix_is_reported_not_swallowed():
    pack = pack_doc(entities=[
        {"id": "apache-spark", "name": "Spark", "type": "Technology",
         "blog_url": "/elsewhere/a"},
    ], relationships=[])
    err = io.StringIO()
    stderr, sys.stderr = sys.stderr, err
    try:
        _, edges = PacksExtractor(resolver=resolver()).run([pack])
    finally:
        sys.stderr = stderr
    assert not [e for e in edges if e.rel == "PRIMARY_TOPIC_OF"]
    assert "/elsewhere/a" in err.getvalue()


def expect_pack_error(pack):
    try:
        PacksExtractor(resolver=resolver()).run([pack])
    except PackError:
        return
    raise AssertionError("expected the build to fail")


def test_a_type_conflict_with_the_registry_fails_the_build():
    expect_pack_error(pack_doc(entities=[{"id": "snowflake", "name": "Snowflake", "type": "Technology"}],
                               relationships=[]))


def test_an_ill_typed_semantic_edge_fails_the_build():
    expect_pack_error(pack_doc(relationships=[
        {"source_id": "lazy-evaluation", "relationship": "HAS_COMPONENT", "target_id": "apache-spark",
         "confidence": 1.0, "explanation": "x"}]))


def test_an_undeclared_endpoint_fails_the_build():
    expect_pack_error(pack_doc(relationships=[
        {"source_id": "apache-spark", "relationship": "IMPLEMENTS", "target_id": "made-up-concept",
         "confidence": 1.0, "explanation": "x"}]))


def test_confidence_and_explanation_are_required():
    base = {"source_id": "apache-spark", "relationship": "IMPLEMENTS", "target_id": "lazy-evaluation"}
    for bad in ({"confidence": 1.5, "explanation": "x"}, {"explanation": "x"}, {"confidence": 0.9}):
        expect_pack_error(pack_doc(relationships=[dict(base, **bad)]))


def test_packs_publish_without_any_signing_fields():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "spark.json").write_text(json.dumps({
            "subject": {"id": "apache-spark", "name": "Apache Spark", "type": "Technology"},
            "authored": {"method": "model-drafted", "model": "m", "drafted": "2026-09-16"},
            "entities": [], "relationships": []}))
        (Path(d) / "pack.schema.json").write_text("{}")
        assert [x.id for x in EntityPacksAdapter(d).documents()] == ["pack:spark"]


# --- the extracted tier --------------------------------------------------------------

def mentions(vocab, body, r=None):
    doc = Document(id="m", title="M", url="/blog/m", kind="article", text=body)
    _, edges = MentionsExtractor(vocab, resolver=r).run([doc])
    return {e.dst for e in edges}


def test_mentions_find_an_entity_never_tagged():
    vocab = [Node("entity:apache-spark", "Apache Spark", "Technology")]
    assert mentions(vocab, "We moved the job to Apache Spark last year.") == {"entity:apache-spark"}


def test_a_short_alias_needs_two_hits_even_when_the_name_is_long():
    vocab = [Node("entity:amazon-emr", "Amazon EMR", "CloudService", aliases=("EMR",))]
    assert mentions(vocab, "It ran on EMR.") == set()
    assert mentions(vocab, "It ran on EMR. EMR scaled out.") == {"entity:amazon-emr"}
    assert mentions(vocab, "It ran on Amazon EMR.") == {"entity:amazon-emr"}


def test_mentions_never_match_inside_another_word_or_compound():
    vocab = [Node("entity:apache-kafka", "Kafka", "Technology")]
    assert mentions(vocab, "Kafkaesque, and Kafka-like, twice: Kafkaesque Kafka-like.") == set()


def test_a_parenthetical_acronym_is_searched_for():
    vocab = [Node("entity:rdd", "Resilient distributed dataset (RDD)", "Concept")]
    assert mentions(vocab, "An RDD is immutable. Each RDD knows its lineage.") == {"entity:rdd"}


def test_the_registry_can_make_matching_case_sensitive():
    vocab = [Node("entity:snowflake", "Snowflake", "Product")]
    assert mentions(vocab, "A snowflake schema normalises. The snowflake schema is old.", resolver()) == set()
    assert mentions(vocab, "Snowflake and Snowflake again.", resolver()) == {"entity:snowflake"}


def test_companies_and_context_nodes_are_never_searched():
    vocab = [Node("entity:microsoft", "Microsoft", "Company"), Node("topic:olap", "olap", "Topic")]
    assert mentions(vocab, "Microsoft Microsoft Microsoft olap olap olap") == set()


def test_mentions_ignore_documents_that_are_not_articles():
    vocab = [Node("entity:apache-spark", "Apache Spark", "Technology")]
    doc = Document(id="assessment:x", title="X", url="/x", kind="assessment", text="Apache Spark Apache Spark")
    assert MentionsExtractor(vocab).run([doc])[1] == []


def test_mentions_never_override_a_tag_based_claim():
    docs = corpus()
    docs[0] = Document(id="a", title="A", url="/blog/a", kind="article", tags=("spark",),
                       text="Apache Spark and Apache Spark.")
    _, edges = build(docs)
    covers = [e for e in edges if (e.src, e.rel, e.dst) == ("a", "COVERS", "entity:apache-spark")]
    assert len(covers) == 1 and covers[0].prov["tier"] == "deterministic"


# --- the artifact ----------------------------------------------------------------

def test_a_plain_edge_serialises_exactly_as_before():
    e = Edge("a", "REFERENCES", "b", {"doc": "a", "tier": "deterministic"})
    assert e.to_json() == {"src": "a", "rel": "REFERENCES", "dst": "b",
                           "prov": {"doc": "a", "tier": "deterministic"}}


def test_the_artifact_is_byte_identical_and_self_describing():
    nodes, edges = build(corpus() + [pack_doc()])
    with tempfile.TemporaryDirectory() as d:
        a, b = Path(d) / "a.json", Path(d) / "b.json"
        write_graph(a, nodes, edges, sources=["x"])
        write_graph(b, dict(reversed(list(nodes.items()))), list(reversed(edges)), sources=["x"])
        assert a.read_bytes() == b.read_bytes()
        g = json.loads(a.read_text())
        assert set(g["entity_types"]) == ENTITY_TYPES
        assert g["inverse_labels"]["IMPLEMENTS"] == "IMPLEMENTED_BY"
        assert all(n["type"] in ENTITY_TYPES | CONTEXT_TYPES for n in g["nodes"])
        assert g["schema_version"] == 1
