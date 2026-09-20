"""Tests for CorpusAtlas REST API daemon (serve-api)."""
import json
import tempfile
import threading
import urllib.request
import urllib.error
from pathlib import Path
from corpusatlas.rest_server import make_api_server


def _create_sample_graph(path: Path):
    path.write_text(json.dumps({
        "schema_version": 2,
        "counts": {"nodes": 3, "edges": 2},
        "nodes": [
            {"id": "tech:spark", "label": "Apache Spark", "type": "Technology", "degree": 2, "aliases": ["Spark"]},
            {"id": "tech:flink", "label": "Apache Flink", "type": "Technology", "degree": 1, "aliases": ["Flink"]},
            {"id": "doc:article", "label": "Comparison", "type": "Document", "degree": 1},
        ],
        "edges": [
            {"src": "tech:spark", "rel": "ALTERNATIVE_TO", "dst": "tech:flink", "confidence": 0.85, "explanation": "Both distributed stream processors"},
            {"src": "doc:article", "rel": "COVERS", "dst": "tech:spark", "confidence": 1.0},
        ],
    }), encoding="utf-8")


_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _request(url: str, headers: dict | None = None, method: str = "GET") -> tuple[int, dict, bytes]:
    req = urllib.request.Request(url, headers=headers or {}, method=method)
    try:
        with _opener.open(req, timeout=5.0) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def test_api_server_endpoints():
    with tempfile.TemporaryDirectory() as tmpdir:
        gpath = Path(tmpdir) / "graph.json"
        _create_sample_graph(gpath)

        # Start server on ephemeral port (port 0)
        server, host, port = make_api_server(gpath, host="127.0.0.1", port=0)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        base_url = f"http://{host}:{port}"

        try:
            # 1. GET / (health & metadata)
            status, headers, body = _request(f"{base_url}/")
            assert status == 200
            assert "application/json" in headers.get("Content-Type", "")
            data = json.loads(body.decode("utf-8"))
            assert data["status"] == "ok"
            assert data["counts"]["nodes"] == 3
            assert data["counts"]["edges"] == 2
            etag = headers.get("ETag")
            assert etag is not None

            # Test ETag caching (304 Not Modified)
            status_304, _, _ = _request(f"{base_url}/", headers={"If-None-Match": etag})
            assert status_304 == 304

            # 2. GET /stats
            status, _, body = _request(f"{base_url}/stats")
            assert status == 200
            stats = json.loads(body.decode("utf-8"))
            assert stats["nodes"] == 3
            assert stats["edges"] == 2

            # 3. GET /nodes (query and type filter)
            status, _, body = _request(f"{base_url}/nodes?query=flink")
            assert status == 200
            nodes = json.loads(body.decode("utf-8"))
            assert len(nodes) == 1
            assert nodes[0]["id"] == "tech:flink"

            # Filter by type
            status, _, body = _request(f"{base_url}/nodes?type=Document")
            assert status == 200
            doc_nodes = json.loads(body.decode("utf-8"))
            assert len(doc_nodes) == 1
            assert doc_nodes[0]["id"] == "doc:article"

            # 4. GET /nodes/<id>
            status, _, body = _request(f"{base_url}/nodes/tech:spark")
            assert status == 200
            spark_info = json.loads(body.decode("utf-8"))
            assert spark_info["node"]["id"] == "tech:spark"
            assert len(spark_info["outbound"]) == 1
            assert spark_info["outbound"][0]["dst"] == "tech:flink"
            assert len(spark_info["inbound"]) == 1
            assert spark_info["inbound"][0]["src"] == "doc:article"

            # 404 for nonexistent node
            status_404, _, _ = _request(f"{base_url}/nodes/tech:nonexistent")
            assert status_404 == 404

            # 5. GET /edges
            status, _, body = _request(f"{base_url}/edges?rel=ALTERNATIVE_TO")
            assert status == 200
            edges = json.loads(body.decode("utf-8"))
            assert len(edges) == 1
            assert edges[0]["src"] == "tech:spark"
            assert edges[0]["dst"] == "tech:flink"

            # 6. GET /context (PPR and hybrid)
            status, headers, body = _request(f"{base_url}/context?entity=tech:spark&algorithm=ppr&format=markdown")
            assert status == 200
            assert "text/markdown" in headers.get("Content-Type", "")
            md_text = body.decode("utf-8")
            assert "tech:spark" in md_text or "Apache Spark" in md_text

            # JSON context
            status, headers, body = _request(f"{base_url}/context?entity=tech:spark&algorithm=bfs&format=json")
            assert status == 200
            assert "application/json" in headers.get("Content-Type", "")
            ctx_data = json.loads(body.decode("utf-8"))
            assert "nodes" in ctx_data or "error" not in ctx_data

            # 7. GET /audit
            status, _, body = _request(f"{base_url}/audit")
            assert status == 200
            audit_data = json.loads(body.decode("utf-8"))
            assert "health_score" in audit_data or "degree_gini_coefficient" in audit_data

            # 8. CORS preflight (OPTIONS)
            status, headers, _ = _request(f"{base_url}/nodes", method="OPTIONS")
            assert status == 204
            assert headers.get("Access-Control-Allow-Origin") == "*"

        finally:
            server.shutdown()
            server.server_close()
