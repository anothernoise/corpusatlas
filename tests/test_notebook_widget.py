"""Unit tests for JupyterLab & VS Code interactive notebook widget."""
import tempfile
from pathlib import Path
from corpusatlas.notebook import show, to_html, NotebookViewerWidget


def test_notebook_widget_html_repr():
    graph = {
        "nodes": [
            {"id": "a", "label": "Node A", "type": "Technology"},
            {"id": "b", "label": "Node B", "type": "Technology"},
        ],
        "edges": [
            {"src": "a", "rel": "links_to", "dst": "b"},
        ]
    }

    widget = show(graph, height=500, width="100%", theme="dark")
    assert isinstance(widget, NotebookViewerWidget)
    html_repr = widget._repr_html_()
    assert "<iframe" in html_repr or "<corpusatlas-graph" in html_repr
    assert "Node A" in html_repr
    assert "Node B" in html_repr


def test_notebook_to_html_export():
    graph = {
        "nodes": [{"id": "x", "label": "X"}],
        "edges": []
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        out_file = Path(tmpdir) / "standalone_viewer.html"
        to_html(graph, out_file)
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "corpusatlas-graph" in content
