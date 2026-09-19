"""Tests for the graphml and csv converters — both read a graph.json-shaped
dict, same as the real artifact after json.loads, not the internal
dataclasses. Node.to_json()/Edge.to_json() omit empty fields, so these
fixtures do too, deliberately: a converter that only works when every field
is present would fail on most real graphs, not just edge cases."""
import csv
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.csv_export import write_csv
from corpusatlas.graphml import write_graphml
from corpusatlas.neo4j_export import write_neo4j_csv
from corpusatlas.rdf_export import write_turtle

GRAPH = {
    "generated": "2026-09-19",
    "generator": "corpusatlas 0.4.0",
    "counts": {"nodes": 3, "edges": 2},
    "nodes": [
        {"id": "entity:a", "label": 'A & "the" <first>', "type": "Technology", "degree": 2,
         "url": "https://example.org/a"},
        {"id": "entity:b", "label": "B, comma-bearing", "type": "Concept", "degree": 1},
        {"id": "entity:c", "label": "C", "type": "Concept", "degree": 1},
    ],
    "edges": [
        {"src": "entity:a", "rel": "IMPLEMENTS", "dst": "entity:b",
         "confidence": 0.9, "explanation": 'Cites "a source", with a comma.'},
        {"src": "entity:a", "rel": "COMPLEMENTS", "dst": "entity:c"},
    ],
}


def test_graphml_round_trips_nodes_and_edges():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "out.graphml"
        write_graphml(path, GRAPH)
        tree = ET.parse(path)

    ns = "{http://graphml.graphdrawing.org/xmlns}"
    root = tree.getroot()
    g = root.find(f"{ns}graph")
    nodes = g.findall(f"{ns}node")
    edges = g.findall(f"{ns}edge")
    assert len(nodes) == 3
    assert len(edges) == 2

    a = next(n for n in nodes if n.get("id") == "entity:a")
    data = {d.get("key"): d.text for d in a.findall(f"{ns}data")}
    # Special characters must survive a real XML parse, not just look right
    # as a string — this is what an escaping bug would actually break.
    assert data["nlabel"] == 'A & "the" <first>'
    assert data["ntype"] == "Technology"
    assert data["ndegree"] == "2"
    assert data["nurl"] == "https://example.org/a"

    b = next(n for n in nodes if n.get("id") == "entity:b")
    b_data = {d.get("key"): d.text for d in b.findall(f"{ns}data")}
    assert "nurl" not in b_data  # optional field, absent on the node -> absent in the file

    a_to_b = next(e for e in edges if e.get("source") == "entity:a" and e.get("target") == "entity:b")
    e_data = {d.get("key"): d.text for d in a_to_b.findall(f"{ns}data")}
    assert e_data["erel"] == "IMPLEMENTS"
    assert e_data["econfidence"] == "0.9"
    assert e_data["eexplanation"] == 'Cites "a source", with a comma.'

    a_to_c = next(e for e in edges if e.get("source") == "entity:a" and e.get("target") == "entity:c")
    c_data = {d.get("key"): d.text for d in a_to_c.findall(f"{ns}data")}
    assert "econfidence" not in c_data


def test_graphml_declares_every_key_once_up_front():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "out.graphml"
        write_graphml(path, GRAPH)
        tree = ET.parse(path)
    ns = "{http://graphml.graphdrawing.org/xmlns}"
    keys = tree.getroot().findall(f"{ns}key")
    assert {k.get("id") for k in keys} == {
        "nlabel", "ntype", "ndegree", "nurl", "erel", "econfidence", "eexplanation", "escope",
    }


def test_csv_writes_a_nodes_and_edges_file_with_headers():
    with tempfile.TemporaryDirectory() as d:
        nodes_path, edges_path = write_csv(Path(d), GRAPH)
        with nodes_path.open(newline="", encoding="utf-8") as f:
            node_rows = list(csv.reader(f))
        with edges_path.open(newline="", encoding="utf-8") as f:
            edge_rows = list(csv.reader(f))

    assert node_rows[0] == ["id", "label", "type", "degree", "url"]
    assert len(node_rows) == 4  # header + 3 nodes
    assert edge_rows[0] == ["src", "rel", "dst", "confidence", "explanation", "scope"]
    assert len(edge_rows) == 3  # header + 2 edges


def test_csv_quoting_survives_commas_and_quotes_in_real_data():
    with tempfile.TemporaryDirectory() as d:
        nodes_path, edges_path = write_csv(Path(d), GRAPH)
        with nodes_path.open(newline="", encoding="utf-8") as f:
            node_rows = {row[0]: row for row in csv.reader(f)}
        with edges_path.open(newline="", encoding="utf-8") as f:
            edge_rows = list(csv.reader(f))[1:]

    # A naive comma-join would have split this label into two columns; the
    # stdlib csv module quoting is what keeps it one field.
    assert node_rows["entity:b"][1] == "B, comma-bearing"
    a_to_b = next(r for r in edge_rows if r[0] == "entity:a" and r[2] == "entity:b")
    assert a_to_b[4] == 'Cites "a source", with a comma.'


def test_csv_leaves_missing_optional_fields_blank_not_absent():
    with tempfile.TemporaryDirectory() as d:
        _, edges_path = write_csv(Path(d), GRAPH)
        with edges_path.open(newline="", encoding="utf-8") as f:
            rows = {(r[0], r[2]): r for r in list(csv.reader(f))[1:]}
    # a -> c has no confidence/explanation/scope; the row still has 6 columns.
    row = rows[("entity:a", "entity:c")]
    assert len(row) == 6
    assert row[3] == "" and row[4] == "" and row[5] == ""


# --- neo4j -------------------------------------------------------------

def test_neo4j_csv_uses_the_admin_import_header_convention():
    with tempfile.TemporaryDirectory() as d:
        nodes_path, rels_path = write_neo4j_csv(Path(d), GRAPH)
        with nodes_path.open(newline="", encoding="utf-8") as f:
            node_rows = list(csv.reader(f))
        with rels_path.open(newline="", encoding="utf-8") as f:
            rel_rows = list(csv.reader(f))

    assert node_rows[0] == ["id:ID", "label", ":LABEL", "degree:int", "url"]
    assert rel_rows[0] == [":START_ID", ":END_ID", ":TYPE", "confidence:float", "explanation", "scope"]
    assert len(node_rows) == 4   # header + 3 nodes
    assert len(rel_rows) == 3    # header + 2 edges


def test_neo4j_csv_maps_type_to_label_and_rel_to_type():
    with tempfile.TemporaryDirectory() as d:
        nodes_path, rels_path = write_neo4j_csv(Path(d), GRAPH)
        with nodes_path.open(newline="", encoding="utf-8") as f:
            nodes = {row[0]: row for row in list(csv.reader(f))[1:]}
        with rels_path.open(newline="", encoding="utf-8") as f:
            rels = list(csv.reader(f))[1:]

    assert nodes["entity:a"][2] == "Technology"  # :LABEL column, from node "type"
    a_to_b = next(r for r in rels if r[0] == "entity:a" and r[1] == "entity:b")
    assert a_to_b[2] == "IMPLEMENTS"  # :TYPE column, from edge "rel"


def test_neo4j_csv_quoting_survives_commas_and_quotes_and_missing_fields():
    with tempfile.TemporaryDirectory() as d:
        nodes_path, rels_path = write_neo4j_csv(Path(d), GRAPH)
        with nodes_path.open(newline="", encoding="utf-8") as f:
            nodes = {row[0]: row for row in list(csv.reader(f))[1:]}
        with rels_path.open(newline="", encoding="utf-8") as f:
            rels = list(csv.reader(f))[1:]

    assert nodes["entity:b"][1] == "B, comma-bearing"
    a_to_c = next(r for r in rels if r[0] == "entity:a" and r[1] == "entity:c")
    assert a_to_c[2] == "COMPLEMENTS"
    assert a_to_c[3] == ""  # no confidence on this edge — blank, not "None"


# --- turtle -----------------------------------------------------------------

def test_turtle_declares_every_node_as_a_typed_resource_with_a_label():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "out.ttl"
        write_turtle(path, GRAPH)
        text = path.read_text(encoding="utf-8")

    assert "<entity_a> a ca:Technology" in text
    assert "<entity_b> a ca:Concept" in text
    # The label's own quote and ampersand must be escaped, not break parsing.
    assert 'rdfs:label "A & \\"the\\" <first>"' in text


def test_turtle_writes_a_plain_triple_for_every_edge():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "out.ttl"
        write_turtle(path, GRAPH)
        text = path.read_text(encoding="utf-8")

    assert "<entity_a> ca:IMPLEMENTS <entity_b> ." in text
    assert "<entity_a> ca:COMPLEMENTS <entity_c> ." in text


def test_turtle_reifies_only_edges_that_actually_carry_metadata():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "out.ttl"
        write_turtle(path, GRAPH)
        text = path.read_text(encoding="utf-8")

    # entity:a -IMPLEMENTS-> entity:b has confidence + explanation: reified.
    assert "rdf:Statement" in text
    assert "ca:confidence 0.9" in text
    assert 'ca:explanation "Cites \\"a source\\", with a comma."' in text
    # entity:a -COMPLEMENTS-> entity:c carries nothing extra: exactly one
    # rdf:Statement block should exist in the whole file, not two.
    assert text.count("a rdf:Statement") == 1


def test_turtle_base_is_configurable():
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "out.ttl"
        write_turtle(path, GRAPH, base="https://example.org/kg/")
        text = path.read_text(encoding="utf-8")

    assert "@base <https://example.org/kg/> ." in text


def test_turtle_is_syntactically_well_formed_prefixed_blocks():
    """No real Turtle parser here (stdlib only) — instead, check the
    mechanical invariant a parser would actually enforce: every statement
    block is terminated by a line ending in " ." and nothing is left
    dangling on a trailing " ;"."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "out.ttl"
        write_turtle(path, GRAPH)
        lines = [l for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    blocks = [l for l in lines if not l.startswith("@")]
    assert blocks, "expected at least one statement"
    for l in blocks:
        assert l.rstrip().endswith((";", ".")), f"malformed line: {l!r}"
