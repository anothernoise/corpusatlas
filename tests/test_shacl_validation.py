"""Tests for declarative SHACL-style graph constraint validation."""
from corpusatlas.shacl import NodeShape, EdgeShape, ShapeValidator


def test_shacl_node_shape_validation():
    # Shape requires Document nodes to have non-empty url
    doc_shape = NodeShape(
        target_type="Document",
        required_properties=["label", "url"],
    )
    validator = ShapeValidator(node_shapes=[doc_shape])

    valid_node = {"id": "doc:1", "type": "Document", "label": "Doc 1", "url": "https://example.com/1"}
    invalid_node = {"id": "doc:2", "type": "Document", "label": "Doc 2"}  # missing url

    report = validator.validate_nodes([valid_node, invalid_node])
    assert not report["conforms"]
    assert len(report["violations"]) == 1
    v = report["violations"][0]
    assert v["focus_node"] == "doc:2"
    assert "url" in v["message"]


def test_shacl_edge_shape_domain_range_and_cardinality():
    # Edge shape: 'implements' must be from Technology to Concept, max 2 per source
    edge_shape = EdgeShape(
        rel="implements",
        source_type="Technology",
        target_type="Concept",
        max_count=2,
    )
    validator = ShapeValidator(edge_shapes=[edge_shape])

    nodes = [
        {"id": "tech:1", "type": "Technology", "label": "Tech 1"},
        {"id": "concept:1", "type": "Concept", "label": "Concept 1"},
        {"id": "doc:1", "type": "Document", "label": "Doc 1"},
    ]
    edges = [
        # Valid edge
        {"src": "tech:1", "rel": "implements", "dst": "concept:1"},
        # Invalid range: dst is Document, not Concept!
        {"src": "tech:1", "rel": "implements", "dst": "doc:1"},
    ]

    report = validator.validate_edges(nodes, edges)
    assert not report["conforms"]
    assert len(report["violations"]) == 1
    assert "target type" in report["violations"][0]["message"].lower()
