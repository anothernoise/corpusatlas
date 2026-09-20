"""Tests for Tasks 2, 4, 5, 6, 7, and 10:
- Standalone Web Component export
- Dynamic visual subgraph filtering logic
- MkDocs & Obsidian native integrations
- Graph semantic projection (PCA 2D/3D from vector embeddings)
- LLM entity and triple extraction with schema validation
- Subgraph RBAC and node/edge redaction
"""
import json
import tempfile
from pathlib import Path

from corpusatlas.integrations.obsidian import export_obsidian_canvas, export_obsidian_vault
from corpusatlas.integrations.mkdocs_plugin import transform_markdown_fences
from corpusatlas.projection import pca_project_embeddings, compute_graph_semantic_projection
from corpusatlas.extract_llm import extract_entities_and_triples_from_text, parse_llm_json_response
from corpusatlas.rbac import redact_graph_by_role, RBACPolicy
from corpusatlas.ontology import Ontology


# ---- Task 5: Obsidian & MkDocs Tests ----

def test_obsidian_canvas_export():
    sample_graph = {
        "nodes": [
            {"id": "python", "label": "Python", "type": "Technology", "x": 100, "y": 200},
            {"id": "fastapi", "label": "FastAPI", "type": "Technology", "x": 300, "y": 400},
        ],
        "edges": [
            {"src": "fastapi", "rel": "built_with", "dst": "python"}
        ]
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "test.canvas"
        export_obsidian_canvas(sample_graph, out_path)
        assert out_path.exists()
        canvas_data = json.loads(out_path.read_text(encoding="utf-8"))
        assert "nodes" in canvas_data
        assert "edges" in canvas_data
        assert len(canvas_data["nodes"]) == 2
        assert len(canvas_data["edges"]) == 1
        assert canvas_data["edges"][0]["fromNode"] == "fastapi"
        assert canvas_data["edges"][0]["toNode"] == "python"
        assert canvas_data["edges"][0]["label"] == "built_with"


def test_obsidian_vault_export():
    sample_graph = {
        "nodes": [
            {"id": "python", "label": "Python", "type": "Technology", "meta": {"summary": "A language"}},
            {"id": "fastapi", "label": "FastAPI", "type": "Technology", "meta": {"summary": "A web framework"}},
        ],
        "edges": [
            {"src": "fastapi", "rel": "built_with", "dst": "python"}
        ]
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        vault_dir = Path(tmpdir) / "vault"
        export_obsidian_vault(sample_graph, vault_dir)
        py_note = vault_dir / "python.md"
        fa_note = vault_dir / "fastapi.md"
        assert py_note.exists()
        assert fa_note.exists()
        fa_content = fa_note.read_text(encoding="utf-8")
        assert "[[python]]" in fa_content
        assert "built_with" in fa_content


def test_mkdocs_markdown_fence_transformer():
    md = """# Architecture
Here is our knowledge map:

```corpusatlas
src: assets/graph.json
focus: python
height: 480px
theme: dark
```

End of document.
"""
    transformed = transform_markdown_fences(md)
    assert "<corpusatlas-graph" in transformed
    assert 'src="assets/graph.json"' in transformed
    assert 'focus="python"' in transformed
    assert 'height="480px"' in transformed
    assert 'theme="dark"' in transformed
    assert "```corpusatlas" not in transformed


# ---- Task 6: Semantic Projection Tests ----

def test_pca_project_embeddings_2d_and_3d():
    # 5 vectors of dimension 4
    vectors = [
        [1.0, 2.0, 0.5, 0.1],
        [1.2, 1.9, 0.4, 0.2],
        [-2.0, -1.5, 0.0, -0.5],
        [-1.8, -1.7, -0.1, -0.4],
        [0.0, 0.1, 3.0, 2.5],
    ]
    coords_2d = pca_project_embeddings(vectors, n_components=2)
    assert len(coords_2d) == 5
    for pt in coords_2d:
        assert len(pt) == 2
        assert isinstance(pt[0], float)
        assert isinstance(pt[1], float)

    coords_3d = pca_project_embeddings(vectors, n_components=3)
    assert len(coords_3d) == 5
    for pt in coords_3d:
        assert len(pt) == 3


def test_compute_graph_semantic_projection():
    sample_graph = {
        "nodes": [
            {"id": "n1", "label": "Node 1", "type": "Technology", "meta": {"vector": [1.0, 0.0, 0.5]}},
            {"id": "n2", "label": "Node 2", "type": "Technology", "meta": {"vector": [0.9, 0.1, 0.4]}},
            {"id": "n3", "label": "Node 3", "type": "Technology", "meta": {"vector": [-1.0, -0.5, 0.0]}},
        ],
        "edges": []
    }
    projected = compute_graph_semantic_projection(sample_graph)
    for node in projected["nodes"]:
        assert "semantic_x" in node["meta"]
        assert "semantic_y" in node["meta"]
        assert "semantic_z" in node["meta"]


# ---- Task 7: LLM Entity & Triple Extraction Tests ----

def test_parse_llm_json_response_and_validate_against_schema():
    raw_llm_output = """```json
{
  "entities": [
    {"id": "kafka", "label": "Apache Kafka", "type": "Technology"},
    {"id": "spark", "label": "Apache Spark", "type": "Technology"},
    {"id": "invalid_entity", "label": "Invalid", "type": "UnknownFakeType"}
  ],
  "relations": [
    {"src": "spark", "rel": "consumes", "dst": "kafka", "explanation": "Reads from Kafka topics"},
    {"src": "spark", "rel": "fake_rel_type", "dst": "kafka"}
  ]
}
```"""
    parsed = parse_llm_json_response(raw_llm_output)
    assert len(parsed["entities"]) == 3
    assert len(parsed["relations"]) == 2

    # Validate against built-in ontology
    ontology = Ontology()
    cleaned = ontology.filter_conforming_triples(parsed["entities"], parsed["relations"])
    # "UnknownFakeType" and "fake_rel_type" should be discarded
    valid_ids = {e["id"] for e in cleaned["entities"]}
    assert "kafka" in valid_ids
    assert "spark" in valid_ids
    assert "invalid_entity" not in valid_ids

    valid_rels = [r["rel"] for r in cleaned["relations"]]
    assert "consumes" in valid_rels
    assert "fake_rel_type" not in valid_rels


# ---- Task 10: Subgraph RBAC & Node Redaction Tests ----

def test_subgraph_rbac_redaction_removes_internal_nodes_and_dangling_edges():
    policy = RBACPolicy(
        roles={
            "public": {"clearance": 1, "allowed_visibilities": {"public"}},
            "internal": {"clearance": 2, "allowed_visibilities": {"public", "internal"}},
            "admin": {"clearance": 3, "allowed_visibilities": {"public", "internal", "confidential"}},
        }
    )

    sample_graph = {
        "nodes": [
            {"id": "pub_svc", "label": "Public API", "type": "Technology", "meta": {"visibility": "public"}},
            {"id": "int_db", "label": "Internal Database", "type": "Technology", "meta": {"visibility": "internal"}},
            {"id": "sec_vault", "label": "Secret Vault", "type": "Technology", "meta": {"visibility": "confidential"}},
        ],
        "edges": [
            {"src": "pub_svc", "rel": "reads_from", "dst": "int_db", "meta": {"visibility": "internal"}},
            {"src": "int_db", "rel": "authenticates_with", "dst": "sec_vault", "meta": {"visibility": "confidential"}},
        ]
    }

    # Redact for public role
    redacted_public, audit_pub = redact_graph_by_role(sample_graph, role="public", policy=policy)
    node_ids_pub = {n["id"] for n in redacted_public["nodes"]}
    assert node_ids_pub == {"pub_svc"}
    assert len(redacted_public["edges"]) == 0
    assert audit_pub["redacted_nodes_count"] == 2
    assert audit_pub["redacted_edges_count"] == 2

    # Redact for internal role
    redacted_int, audit_int = redact_graph_by_role(sample_graph, role="internal", policy=policy)
    node_ids_int = {n["id"] for n in redacted_int["nodes"]}
    assert node_ids_int == {"pub_svc", "int_db"}
    assert len(redacted_int["edges"]) == 1
    assert redacted_int["edges"][0]["src"] == "pub_svc"
    assert redacted_int["edges"][0]["dst"] == "int_db"


# ---- Task 2: Web Component Package Files Tests ----

def test_web_component_package_json_and_embed_module():
    pkg_json_path = Path("npm/corpusatlas-graph/package.json")
    assert pkg_json_path.exists()
    pkg_data = json.loads(pkg_json_path.read_text(encoding="utf-8"))
    assert pkg_data["name"] == "@corpusatlas/graph"
    assert "customElements" in pkg_data or "main" in pkg_data

    embed_js = Path("viewer/js/embed.js").read_text(encoding="utf-8")
    assert "class CorpusAtlasGraph extends HTMLElement" in embed_js
    assert "customElements.define('corpusatlas-graph'" in embed_js
