"""Tests for bi-temporal knowledge graph snapshot filtering and timeline extraction."""
from corpusatlas.temporal import filter_as_of, extract_timeline


def _create_temporal_graph():
    return {
        "nodes": [
            {"id": "entity:rome", "label": "Roman Empire", "type": "Concept", "valid_from": "-0027-01-01", "valid_to": "0476-09-04"},
            {"id": "entity:byzantium", "label": "Byzantine Empire", "type": "Concept", "valid_from": "0330-05-11", "valid_to": "1453-05-29"},
            {"id": "entity:modern_italy", "label": "Italy", "type": "Concept", "valid_from": "1861-03-17"},
        ],
        "edges": [
            {"src": "entity:rome", "rel": "precedes", "dst": "entity:byzantium", "valid_from": "0330-05-11"},
            {"src": "entity:rome", "rel": "precedes", "dst": "entity:modern_italy", "valid_from": "1861-03-17"},
        ],
    }


def test_filter_as_of_year_400():
    g = _create_temporal_graph()
    # In 0400, both Rome and Byzantium exist; Modern Italy does not
    snap = filter_as_of(g, as_of_date="0400-01-01")
    node_ids = {n["id"] for n in snap["nodes"]}
    assert "entity:rome" in node_ids
    assert "entity:byzantium" in node_ids
    assert "entity:modern_italy" not in node_ids
    assert len(snap["edges"]) == 1
    assert snap["edges"][0]["dst"] == "entity:byzantium"


def test_filter_as_of_year_1900():
    g = _create_temporal_graph()
    # In 1900, only Modern Italy exists
    snap = filter_as_of(g, as_of_date="1900-01-01")
    node_ids = {n["id"] for n in snap["nodes"]}
    assert "entity:modern_italy" in node_ids
    assert "entity:rome" not in node_ids
    assert "entity:byzantium" not in node_ids


def test_extract_timeline():
    g = _create_temporal_graph()
    timeline = extract_timeline(g)
    assert len(timeline) >= 3
    dates = [event["date"] for event in timeline]
    assert sorted(dates) == dates  # Check chronological ordering


def test_cli_as_of():
    import json
    import tempfile
    from pathlib import Path
    from corpusatlas.__main__ import main

    with tempfile.TemporaryDirectory() as tmpdir:
        g = _create_temporal_graph()
        input_file = Path(tmpdir) / "graph.json"
        output_file = Path(tmpdir) / "snapshot_400.json"
        input_file.write_text(json.dumps(g), encoding="utf-8")

        ret = main(["as-of", "--graph", str(input_file), "--date", "0400-01-01", "--out", str(output_file)])
        assert ret == 0
        assert output_file.exists()

        data = json.loads(output_file.read_text(encoding="utf-8"))
        assert data["counts"]["nodes"] == 2
        assert data["counts"]["edges"] == 1
        assert data["as_of"] == "0400-01-01"
