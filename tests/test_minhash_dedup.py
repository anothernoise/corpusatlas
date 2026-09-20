"""Tests for MinHash LSH fuzzy entity resolution and deduplication."""
from corpusatlas.minhash import MinHash, LSHIndex, find_duplicate_candidates, merge_duplicate_entities


def test_minhash_jaccard_similarity_estimation():
    text1 = "PostgreSQL Relational Database"
    text2 = "Postgres Relational Database"
    text3 = "African Elephant Wildlife Biology"

    m1 = MinHash.from_text(text1, num_perm=64)
    m2 = MinHash.from_text(text2, num_perm=64)
    m3 = MinHash.from_text(text3, num_perm=64)

    sim_1_2 = m1.jaccard(m2)
    sim_1_3 = m1.jaccard(m3)

    assert sim_1_2 > 0.5, f"Expected high similarity between PostgreSQL and Postgres, got {sim_1_2}"
    assert sim_1_3 < 0.2, f"Expected low similarity between Database and Elephant, got {sim_1_3}"


def test_lsh_index_candidate_retrieval():
    nodes = [
        {"id": "tech:spark", "label": "Apache Spark Framework", "type": "Technology"},
        {"id": "tech:spark_dup", "label": "Apache Spark Framework System", "type": "Technology"},
        {"id": "tech:duckdb", "label": "DuckDB Database Engine", "type": "Technology"},
    ]

    candidates = find_duplicate_candidates(nodes, threshold=0.55)
    assert len(candidates) >= 1
    pair = candidates[0]
    matched_ids = {pair["node_a"], pair["node_b"]}
    assert matched_ids == {"tech:spark", "tech:spark_dup"}


def test_merge_duplicate_entities_repoints_edges():
    graph = {
        "nodes": [
            {"id": "tech:spark", "label": "Apache Spark", "type": "Technology", "aliases": []},
            {"id": "tech:spark_dup", "label": "Apache Spark™", "type": "Technology", "aliases": ["Spark"]},
            {"id": "tech:python", "label": "Python", "type": "Technology"},
        ],
        "edges": [
            {"src": "tech:python", "rel": "supports", "dst": "tech:spark_dup", "confidence": 0.9},
        ],
    }

    merged_graph = merge_duplicate_entities(graph, [("tech:spark", "tech:spark_dup")])
    remaining_node_ids = [n["id"] for n in merged_graph["nodes"]]
    assert "tech:spark" in remaining_node_ids
    assert "tech:spark_dup" not in remaining_node_ids

    # Edge should now point to canonical tech:spark
    edge = merged_graph["edges"][0]
    assert edge["dst"] == "tech:spark"

    # Aliases should be merged
    spark_node = next(n for n in merged_graph["nodes"] if n["id"] == "tech:spark")
    assert "Spark" in spark_node["aliases"]
