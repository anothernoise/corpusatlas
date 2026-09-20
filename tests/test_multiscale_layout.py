"""Unit tests for Multi-Scale Hierarchical LOD and 3D graph layout."""
from corpusatlas.layout import compute_layout, compute_multiscale_layout


def test_multiscale_layout_lod_assignment():
    nodes = [
        {"id": f"n{i}", "degree": i, "label": f"Node {i}", "type": "Technology"}
        for i in range(20)
    ]
    edges = [
        {"src": "n19", "dst": f"n{i}", "rel": "connects"} for i in range(19)
    ]

    res = compute_multiscale_layout(nodes, edges, iterations=20, dimensions=2)
    assert len(res) == 20
    for n in res:
        assert "x" in n and "y" in n
        assert "lod" in n
        assert n["lod"] in (0, 1, 2)

    # Highest degree node must be LOD 0 (backbone core)
    n19 = next(n for n in res if n["id"] == "n19")
    assert n19["lod"] == 0


def test_3d_layout_coordinates():
    nodes = [
        {"id": "a", "label": "A", "type": "Technology"},
        {"id": "b", "label": "B", "type": "Technology"},
        {"id": "c", "label": "C", "type": "Technology"},
    ]
    edges = [
        {"src": "a", "dst": "b", "rel": "rel1"},
        {"src": "b", "dst": "c", "rel": "rel2"},
    ]

    res = compute_layout(nodes, edges, iterations=15, three_d=True)
    assert len(res) == 3
    for n in res:
        assert "x" in n and "y" in n and "z" in n
        assert isinstance(n["z"], float)
