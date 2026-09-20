"""Unit tests for Visual Graph Diff logic and file structures."""
from pathlib import Path
from corpusatlas.graph_delta import compute_graph_delta


def test_visual_diff_js_module_exists_and_exports_expected_functions():
    js_path = Path("viewer/js/diff.js")
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")
    assert "export function computeGraphDiff" in content
    assert "export function applyDiffFilter" in content
    assert "export function renderNodeAttributeDiff" in content
    assert "export function edgeKey" in content
    assert "console.log" not in content


def test_visual_diff_parity_with_python_delta():
    old_graph = {
        "nodes": [
            {"id": "s1", "label": "Service 1", "type": "Technology"},
            {"id": "db1", "label": "DB 1", "type": "Technology"},
        ],
        "edges": [
            {"src": "s1", "rel": "writes_to", "dst": "db1"},
        ]
    }

    new_graph = {
        "nodes": [
            {"id": "s1", "label": "Service 1 Updated", "type": "Technology"},
            {"id": "db1", "label": "DB 1", "type": "Technology"},
            {"id": "q1", "label": "Queue 1", "type": "Technology"},
        ],
        "edges": [
            {"src": "s1", "rel": "writes_to", "dst": "db1"},
            {"src": "s1", "rel": "publishes_to", "dst": "q1"},
        ]
    }

    delta = compute_graph_delta(old_graph, new_graph)
    assert len(delta.added_nodes) == 1
    assert delta.added_nodes[0]["id"] == "q1"
    assert len(delta.modified_nodes) == 1
    assert delta.modified_nodes[0]["id"] == "s1"
    assert len(delta.added_edges) == 1
    assert delta.added_edges[0]["rel"] == "publishes_to"


def test_app_js_has_no_bare_refresh_and_analytics_toolbar_grouped():
    import re
    app_js = Path("viewer/app.js").read_text(encoding="utf-8")
    # Verify no bare `refresh()` calls exist
    bare_refresh_matches = re.findall(r"(?<![a-zA-Z0-9_.])refresh\s*\(", app_js)
    assert not bare_refresh_matches, f"Found unexpected bare refresh() calls: {bare_refresh_matches}"

    html = Path("viewer/index.html").read_text(encoding="utf-8")
    assert "kb-analytics-group" in html
    assert "data-kb-clusters-btn" in html
    assert "data-kb-insights-btn" in html
    assert "data-kb-3d-toggle" in html
    assert "data-kb-timeline-btn" in html
    assert "data-kb-diff-toggle" in html
    assert "data-kb-share-modal" in html
    assert "data-kb-export-dropdown" in html
    assert "data-kb-export-menu" in html
    assert "kb-diff-filters" in html
    assert "kb-diff-filter-btn" in html


def test_ui_app_view3d_has_matrix_polyfill_and_flight_mode():
    v3d = Path("viewer/js/view3d.js").read_text(encoding="utf-8")
    assert "Object.prototype.determinantAffine" in v3d
    assert "determinantAffine" in v3d
    assert "startFlightMode" in v3d
    assert "stopFlightMode" in v3d
    assert "toggleFlightMode" in v3d
    assert "kb-3d-deck" in v3d
    assert "createNodeLabelSprite" in v3d
    assert "linkDirectionalParticles" in v3d
    assert "console.log" not in v3d

    html = Path("viewer/index.html").read_text(encoding="utf-8")
    assert "determinantAffine" in html
    assert "determinant3x3" in html
    assert "app.js?v=" in html


def test_view3d_has_draggable_deck_and_traversal_strategies():
    v3d = Path("viewer/js/view3d.js").read_text(encoding="utf-8")
    assert "data-kb-3d-deck" in v3d
    assert "data-kb-3d-drag-handle" in v3d
    assert "data-kb-3d-strategy" in v3d
    assert "data-kb-3d-speed" in v3d
    assert "data-kb-3d-telemetry" in v3d
    assert "data-kb-3d-progress" in v3d
    # Strategies support
    assert "edges" in v3d
    assert "cluster" in v3d
    assert "centrality" in v3d



