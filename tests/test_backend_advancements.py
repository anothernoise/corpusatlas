"""Comprehensive unit tests for the 10 backend advancements in CorpusAtlas.

Tests:
1. Barnes-Hut O(N log N) Quadtree force-directed layout
2. Aho-Corasick multi-pattern keyword automaton & mentions extraction
3. SQLite out-of-core pipeline store
4. Multi-format export (Cypher, Turtle, DuckDB/Parquet)
5. Spatial quadtree LOD tile generation
6. Personalized PageRank (PPR) Graph RAG subgraph extraction
7. Context-aware entity disambiguation
8. Declarative schema migration engine
9. Merkle-DAG incremental claims caching
10. Knowledge graph topological auditing & quality metrics
"""
import json
import tempfile
from pathlib import Path

from corpusatlas.aho_corasick import AhoCorasick
from corpusatlas.audit import audit_graph, compute_gini_coefficient, find_bridges, find_directed_cycles
from corpusatlas.cache import MerkleDAGCache
from corpusatlas.context import extract_rag_subgraph, personalized_pagerank
from corpusatlas.disambiguate import ContextDisambiguator
from corpusatlas.emit_tiles import generate_spatial_tiles
from corpusatlas.export import export_cypher, export_duckdb, export_turtle
from corpusatlas.extract.mentions import MentionsExtractor
from corpusatlas.layout import compute_layout
from corpusatlas.layout_bh import QuadTree
from corpusatlas.migrate import apply_migration
from corpusatlas.model import Document, Edge, Node
from corpusatlas.pipeline_store import SQLitePipelineStore


# 1. Barnes-Hut Quadtree
def test_barnes_hut_quadtree_force_calculation():
    tree = QuadTree((0.0, 0.0, 200.0, 200.0))
    for i in range(20):
        tree.insert(f"n{i}", float(i * 10), float(i * 10), weight=1.0)
    assert tree.root is not None

    # Compute repulsion on node 0
    fx, fy = tree.compute_force("n0", 0.0, 0.0, k=30.0, theta=0.5)
    assert isinstance(fx, float) and isinstance(fy, float)

    # Test full layout iteration
    nodes = [{"id": f"n{i}"} for i in range(20)]
    edges = [{"src": f"n{i}", "dst": f"n{i+1}"} for i in range(19)]
    layout_nodes = compute_layout(nodes, edges, iterations=10, use_barnes_hut=True)
    assert len(layout_nodes) == 20
    assert all("x" in n and "y" in n for n in layout_nodes)


# 2. Aho-Corasick Automaton
def test_aho_corasick_automaton_exact_and_word_boundaries():
    ac = AhoCorasick(case_sensitive=False)
    ac.add_word("apple", "fruit")
    ac.add_word("app", "tech")
    ac.add_word("pineapple", "tropical")
    ac.build()

    text = "An apple and a pineapple walked into an app store."
    matches = list(ac.find_matches(text, word_boundaries=True))
    matched_words = [m[2].lower() for m in matches]
    assert "apple" in matched_words
    assert "pineapple" in matched_words
    assert "app" in matched_words

    # Word boundary exclusion test: "app" inside "application" should not match if word_boundaries=True
    text2 = "running application"
    matches2 = list(ac.find_matches(text2, word_boundaries=True))
    assert not matches2


def test_mentions_extractor_with_aho_corasick():
    vocab = [
        Node("entity:spark", "Apache Spark", "Technology", aliases=("Spark",)),
        Node("entity:flink", "Apache Flink", "Technology"),
    ]
    docs = [
        Document(id="d1", title="D1", url="/1", kind="article", text="We benchmarked Apache Spark against engines."),
        Document(id="d2", title="D2", url="/2", kind="article", text="Spark and Spark again."),
        Document(id="d3", title="D3", url="/3", kind="article", text="Only one mention of Spark here."),
    ]
    extractor = MentionsExtractor(vocab)
    _, edges = extractor.run(docs)

    edge_tuples = {(e.prov["doc"], e.dst) for e in edges}
    assert ("d1", "entity:spark") in edge_tuples  # "Apache Spark" is long (>=10 chars) -> 1 hit qualifies
    assert ("d2", "entity:spark") in edge_tuples  # "Spark" appears twice -> 2 hits qualify
    assert ("d3", "entity:spark") not in edge_tuples  # 1 short hit does not qualify


# 3. SQLite Pipeline Store
def test_sqlite_pipeline_store_lifecycle_and_compaction():
    store = SQLitePipelineStore(":memory:")
    nodes_t1 = [Node("n1", "Node 1", "Concept"), Node("n2", "Node 2", "Concept")]
    nodes_t2 = [Node("n2", "Node 2 Overwrite", "Technology"), Node("n3", "Node 3", "Concept")]
    edges_t1 = [Edge("n1", "REL", "n2", confidence=1.0, prov={"doc": "d1"})]
    edges_t2 = [Edge("n2", "REL", "n3", confidence=0.9, prov={"doc": "d2"})]

    store.add_tier_nodes(nodes_t1, tier_order=1)
    store.add_tier_nodes(nodes_t2, tier_order=2)
    store.add_tier_edges(edges_t1, tier_order=1)
    store.add_tier_edges(edges_t2, tier_order=2)

    # First-writer-wins compaction with doc retraction
    node_cnt, edge_cnt = store.compact(live_doc_ids={"d1", "d2"})
    assert node_cnt == 3
    assert edge_cnt == 2

    # Verify first-writer won on n2
    final_nodes = {n.id: n for n in store.stream_nodes()}
    assert final_nodes["n2"].type == "Concept"  # tier 1 won over tier 2

    # Test doc retraction
    store.compact(live_doc_ids={"d1"})  # d2 retracted
    remaining_edges = list(store.stream_edges())
    assert len(remaining_edges) == 1
    assert remaining_edges[0].dst == "n2"

    with tempfile.TemporaryDirectory() as tmp:
        out_f = Path(tmp) / "graph.json"
        store.export_json(out_f, meta={"name": "test"})
        loaded = json.loads(out_f.read_text())
        assert loaded["meta"]["name"] == "test"
        assert len(loaded["nodes"]) == 2  # n3 pruned as isolated

    store.close()


# 4. Multi-Format Exporter
def test_multi_format_export_cypher_turtle_duckdb():
    nodes = [Node("entity:a", "Entity A", "Concept"), Node("entity:b", "Entity B", "Technology")]
    edges = [Edge("entity:a", "CONNECTS_TO", "entity:b", confidence=0.95)]

    with tempfile.TemporaryDirectory() as tmp:
        cql_file = Path(tmp) / "graph.cql"
        ttl_file = Path(tmp) / "graph.ttl"
        duck_dir = Path(tmp) / "duckdb"

        export_cypher(nodes, edges, cql_file)
        assert "MERGE (n:Resource:Concept {id: 'entity:a'})" in cql_file.read_text()
        assert "CONNECTS_TO" in cql_file.read_text()

        export_turtle(nodes, edges, ttl_file)
        assert "@prefix ca:" in ttl_file.read_text()
        assert "res:entity_a ca:CONNECTS_TO res:entity_b ." in ttl_file.read_text()

        duck_res = export_duckdb(nodes, edges, duck_dir)
        assert Path(duck_res["nodes_csv"]).exists()
        assert Path(duck_res["edges_csv"]).exists()
        assert Path(duck_res["sql_script"]).exists()


# 5. Spatial Quadtree Tiling
def test_spatial_quadtree_tiles():
    nodes = [
        Node(f"n{i}", f"Node {i}", "Concept", meta={"pos": [float(i * 50), float(i * 50)]})
        for i in range(10)
    ]
    edges = [Edge(f"n{i}", "REL", f"n{i+1}") for i in range(9)]

    with tempfile.TemporaryDirectory() as tmp:
        manifest = generate_spatial_tiles(nodes, edges, tmp, max_zoom=2)
        assert manifest["tile_count"] > 0
        assert (Path(tmp) / "manifest.json").exists()
        assert (Path(tmp) / "0" / "0_0.json").exists()


# 6. Personalized PageRank (PPR) Graph RAG
def test_personalized_pagerank_and_rag_extraction():
    nodes = [{"id": f"n{i}", "label": f"Node {i}", "type": "Concept"} for i in range(5)]
    edges = [
        {"src": "n0", "rel": "LINKS", "dst": "n1", "confidence": 1.0, "doc": "d1"},
        {"src": "n1", "rel": "LINKS", "dst": "n2", "confidence": 1.0, "doc": "d1"},
        {"src": "n2", "rel": "LINKS", "dst": "n3", "confidence": 1.0, "doc": "d2"},
        {"src": "n3", "rel": "LINKS", "dst": "n4", "confidence": 1.0, "doc": "d2"},
    ]

    # Compute PPR from n0
    scores = personalized_pagerank(nodes, edges, "n0", alpha=0.15)
    assert scores["n1"] > scores["n2"] > scores["n3"] > scores["n4"]
    assert scores["n0"] > scores["n4"]

    # Extract RAG subgraph
    rag = extract_rag_subgraph({"nodes": nodes, "edges": edges}, "n0", algorithm="ppr", top_k=2)
    selected = {n["id"] for n in rag["selected_nodes"]}
    assert "n0" in selected
    assert "n1" in selected


# 7. Context-Aware Disambiguation
def test_context_entity_disambiguator():
    candidates = [
        {
            "id": "entity:spark-engine",
            "type": "Technology",
            "description": "Distributed data processing engine for big data and machine learning.",
            "keywords": ["distributed", "dataframe", "rdd", "streaming"],
        },
        {
            "id": "entity:spark-biology",
            "type": "Concept",
            "description": "Calcium sparks in cellular physiology and cardiac muscle biology.",
            "keywords": ["calcium", "cellular", "cardiac", "physiology"],
        },
    ]
    disambiguator = ContextDisambiguator(candidates)

    doc_data = "We tuned RDD partitions and distributed dataframe executors on the cluster."
    best, score = disambiguator.disambiguate(["entity:spark-engine", "entity:spark-biology"], doc_data)
    assert best == "entity:spark-engine"
    assert score > 0.1

    doc_bio = "Observation of cardiac calcium release units in cellular membranes."
    best_bio, _ = disambiguator.disambiguate(["entity:spark-engine", "entity:spark-biology"], doc_bio)
    assert best_bio == "entity:spark-biology"


# 8. Declarative Schema Migration
def test_declarative_schema_migration():
    g = {
        "nodes": [
            {"id": "n1", "label": "N1", "type": "OldType"},
            {"id": "n2", "label": "N2", "type": "DropMe"},
            {"id": "n3", "label": "N3", "type": "Stay"},
        ],
        "edges": [
            {"src": "n1", "rel": "OLD_REL", "dst": "n3"},
            {"src": "n2", "rel": "OTHER", "dst": "n3"},
        ],
    }
    migrations = [
        {"action": "rename_type", "from": "OldType", "to": "NewType"},
        {"action": "rename_relation", "from": "OLD_REL", "to": "NEW_REL"},
        {"action": "drop_type", "from": "DropMe"},
    ]
    migrated = apply_migration(g, migrations)

    node_map = {n["id"]: n for n in migrated["nodes"]}
    assert "n2" not in node_map  # Dropped
    assert node_map["n1"]["type"] == "NewType"  # Renamed

    edge_rels = {e["rel"] for e in migrated["edges"]}
    assert "NEW_REL" in edge_rels
    assert "OLD_REL" not in edge_rels


# 9. Merkle-DAG Cache
def test_merkle_dag_claims_caching():
    with tempfile.TemporaryDirectory() as tmp:
        cache_p = Path(tmp) / "merkle.json"
        cache = MerkleDAGCache(cache_p)

        assert cache.get_claims("doc1", "hash_a", "det") is None

        # Store claims
        cache.put_claims(
            "doc1", "hash_a", "det",
            [{"id": "n1", "label": "N1"}],
            [{"src": "n1", "rel": "R", "dst": "n2"}]
        )
        root1 = cache.compute_merkle_root()
        assert root1 != "empty"

        cached = cache.get_claims("doc1", "hash_a", "det")
        assert cached is not None
        assert len(cached[0]) == 1  # 1 node
        assert len(cached[1]) == 1  # 1 edge

        # Saving and reloading
        cache.save()
        reloaded = MerkleDAGCache(cache_p)
        assert reloaded.compute_merkle_root() == root1


# 10. Knowledge Graph Quality & Topological Audit
def test_graph_auditing_engine():
    # Construct graph with a cycle and a bridge
    nodes = [{"id": f"n{i}", "degree": 2} for i in range(5)]
    edges = [
        # Triangle cycle: n0 -> n1 -> n2 -> n0
        {"src": "n0", "rel": "TAXON_OF", "dst": "n1", "confidence": 1.0},
        {"src": "n1", "rel": "TAXON_OF", "dst": "n2", "confidence": 1.0},
        {"src": "n2", "rel": "TAXON_OF", "dst": "n0", "confidence": 1.0},
        # Bridge to n3
        {"src": "n2", "rel": "CONNECTED", "dst": "n3", "confidence": 0.5},
        # n3 to n4
        {"src": "n3", "rel": "CONNECTED", "dst": "n4", "confidence": 1.0},
    ]

    report = audit_graph({"nodes": nodes, "edges": edges})
    assert report["node_count"] == 5
    assert report["edge_count"] == 5
    assert len(report["hierarchical_cycles"]) >= 1  # Cycle detected
    assert report["low_confidence_count"] == 1  # 0.5 confidence edge flagged
    assert report["bridge_edges_count"] >= 1  # Bridge detected

    # Gini coefficient test
    assert compute_gini_coefficient([5, 5, 5, 5]) == 0.0  # Perfect equality
    assert compute_gini_coefficient([0, 0, 0, 10]) > 0.7  # High concentration
