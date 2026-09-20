"""Tests for Wikidata entity linker."""
from corpusatlas.link import link_entity_to_wikidata, annotate_graph_with_wikidata


def test_link_entity_with_mock_client():
    def mock_fetcher(query: str):
        if "python" in query.lower():
            return [
                {
                    "id": "Q28865",
                    "label": "Python",
                    "description": "general-purpose, high-level programming language",
                    "url": "http://www.wikidata.org/entity/Q28865",
                }
            ]
        return []

    node = {"id": "tech:python", "label": "Python", "type": "Technology", "urls": {}}
    linked = link_entity_to_wikidata(node, fetcher=mock_fetcher)

    assert linked is not None
    assert linked["wikidata_id"] == "Q28865"
    assert "wikidata" in linked["urls"]
    assert "Q28865" in linked["urls"]["wikidata"]


def test_annotate_graph_with_wikidata():
    def mock_fetcher(query: str):
        if "duckdb" in query.lower():
            return [{"id": "Q113331908", "label": "DuckDB", "description": "Columnar SQL database"}]
        return []

    graph = {
        "nodes": [
            {"id": "tech:duckdb", "label": "DuckDB", "type": "Technology", "urls": {}},
            {"id": "custom:unknown", "label": "NonExistentThingXYZ", "type": "Concept", "urls": {}},
        ],
        "edges": [],
    }

    annotated = annotate_graph_with_wikidata(graph, fetcher=mock_fetcher)
    nodes_by_id = {n["id"]: n for n in annotated["nodes"]}
    assert nodes_by_id["tech:duckdb"].get("wikidata_id") == "Q113331908"
    assert "wikidata_id" not in nodes_by_id["custom:unknown"]
