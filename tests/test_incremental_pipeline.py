"""Tests for fine-grained incremental cache invalidation and MerkleDAG extractor wiring."""
import tempfile
from pathlib import Path
from corpusatlas.cache import BuildCache, MerkleDAGCache
from corpusatlas.model import Document, Node, Edge


def test_fine_grained_file_cache_reuse_on_file_addition():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "cache.json"
        cache = BuildCache(cache_path)
        bucket = cache.bucket("html_blog:/test")

        # Initial run with file1
        bucket.enter(("file1",))
        doc1 = Document(id="doc1", title="Doc 1", url="/doc1", kind="article", date="2026-01-01", text="Hello world", tags=("tech",), links=())
        bucket.put("/test/file1.md", "hash_111", doc1)
        bucket.commit(("file1",))
        cache.save()

        # Second run: file2 is added, but file1 has unchanged content hash "hash_111"
        reloaded = BuildCache(cache_path, fine_grained=True)
        bucket2 = reloaded.bucket("html_blog:/test")
        bucket2.enter(("file1", "file2"))

        # Fine-grained cache MUST hit doc1 even though fingerprint changed ("file1" -> "file1", "file2")
        cached_doc1 = bucket2.get("/test/file1.md", "hash_111")
        assert cached_doc1 is not None
        assert cached_doc1.id == "doc1"
        assert cached_doc1.title == "Doc 1"
        assert reloaded.hits == 1
        assert reloaded.misses == 0


def test_merkle_dag_extractor_caching_and_bypass():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "merkle.json"
        merkle = MerkleDAGCache(cache_path)

        doc = Document(id="doc_a", title="Doc A", url="/doc_a", kind="article", date="2026-01-01", text="Spark and Kafka", tags=("spark",), links=())
        doc_hash = "sha_content_a"

        # Initially no claims cached
        cached = merkle.get_claims(doc.id, doc_hash, "deterministic")
        assert cached is None

        # Store claims
        nodes = [{"id": "tech:spark", "label": "Spark", "type": "Technology"}]
        edges = [{"src": "tech:spark", "rel": "compares_with", "dst": "tech:kafka"}]
        merkle.put_claims(doc.id, doc_hash, "deterministic", nodes, edges)
        merkle.save()

        # Reload and retrieve
        reloaded = MerkleDAGCache(cache_path)
        got_nodes, got_edges = reloaded.get_claims(doc.id, doc_hash, "deterministic")
        assert len(got_nodes) == 1
        assert got_nodes[0]["id"] == "tech:spark"
        assert len(got_edges) == 1
        assert got_edges[0]["src"] == "tech:spark"


def test_run_extractor_cached_end_to_end():
    from corpusatlas.cache import run_extractor_cached
    from corpusatlas.extract.deterministic import DeterministicExtractor
    from corpusatlas.resolve import Resolver

    with tempfile.TemporaryDirectory() as tmpdir:
        merkle_path = Path(tmpdir) / "merkle.json"
        merkle = MerkleDAGCache(merkle_path)
        det = DeterministicExtractor(Resolver())

        doc1 = Document(id="d1", title="Doc 1", url="/d1", kind="article", tags=("python", "spark"), links=("d2",))
        doc2 = Document(id="d2", title="Doc 2", url="/d2", kind="article", tags=("python",), links=())

        # First run: both documents extracted (2 misses, 0 hits)
        nodes1, edges1, hits1, misses1 = run_extractor_cached(det, [doc1, doc2], merkle)
        assert hits1 == 0
        assert misses1 == 2
        merkle.save()

        # Second run: unchanged documents (2 hits, 0 misses)
        merkle2 = MerkleDAGCache(merkle_path)
        nodes2, edges2, hits2, misses2 = run_extractor_cached(det, [doc1, doc2], merkle2)
        assert hits2 == 2
        assert misses2 == 0
        assert len(nodes1) == len(nodes2)
        assert len(edges1) == len(edges2)


def test_github_adapter_since_cursor():
    import json
    from corpusatlas.adapters.github import GitHubAdapter

    with tempfile.TemporaryDirectory() as tmpdir:
        data_file = Path(tmpdir) / "issues.json"
        cursor_file = Path(tmpdir) / ".cursor"
        issues = [
            {"number": 1, "title": "Old Issue", "body": "old", "created_at": "2025-01-01T00:00:00Z", "updated_at": "2025-01-01T10:00:00Z"},
            {"number": 2, "title": "New Issue", "body": "new", "created_at": "2026-09-01T00:00:00Z", "updated_at": "2026-09-01T10:00:00Z"},
        ]
        data_file.write_text(json.dumps(issues), encoding="utf-8")

        # Initial run: all items yielded, cursor written
        ad1 = GitHubAdapter(data_file, repo="test/repo", cursor_file=cursor_file)
        docs1 = list(ad1.documents())
        assert len(docs1) == 2
        assert cursor_file.exists()
        assert "2026-09-01" in cursor_file.read_text()

        # Subsequent run: since cursor is 2026-09-01, older issue is skipped
        ad2 = GitHubAdapter(data_file, repo="test/repo", since="2026-06-01T00:00:00Z")
        docs2 = list(ad2.documents())
        assert len(docs2) == 1
        assert docs2[0].id == "github:test/repo#2"


def test_web_adapter_conditional_304_cache():
    from corpusatlas.adapters.web import WebAdapter

    http_cache = {
        "http://example.com/cached": {
            "etag": '"abc123etag"',
            "last_modified": "Wed, 21 Oct 2025 07:28:00 GMT",
            "body": "<html><head><title>Cached Page</title></head><body>Cached Body</body></html>",
        }
    }
    adapter = WebAdapter(urls=["http://example.com/cached"], http_cache=http_cache, respect_robots=False)

    # Mock response returning 304
    class DummyResp:
        status = 304
        reason = "Not Modified"
        def read(self):
            return b""
        def getheader(self, name, default=None):
            return default

    class DummyConn:
        def request(self, method, path, headers=None):
            assert headers.get("If-None-Match") == '"abc123etag"'
            assert headers.get("If-Modified-Since") == "Wed, 21 Oct 2025 07:28:00 GMT"
        def getresponse(self):
            return DummyResp()

    adapter._pool.get = lambda scheme, netloc: DummyConn()
    docs = list(adapter.documents())
    assert len(docs) == 1
    assert docs[0].title == "Cached Page"
    assert "Cached Body" in docs[0].text


def test_graph_delta_incremental_maintenance():
    from corpusatlas.graph_delta import compute_graph_delta, apply_delta_to_graph, update_degrees_incrementally, detect_affected_communities

    old_graph = {
        "nodes": [
            {"id": "s1", "label": "Service 1", "type": "Technology", "degree": 1},
            {"id": "db1", "label": "DB 1", "type": "Technology", "degree": 1},
        ],
        "edges": [
            {"src": "s1", "rel": "writes_to", "dst": "db1"},
        ]
    }

    new_graph = {
        "nodes": [
            {"id": "s1", "label": "Service 1 (v2)", "type": "Technology", "degree": 2},
            {"id": "db1", "label": "DB 1", "type": "Technology", "degree": 1},
            {"id": "q1", "label": "Queue 1", "type": "Technology", "degree": 1},
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

    # Incremental degree update
    nodes_copy = [{"id": "s1", "degree": 1}, {"id": "db1", "degree": 1}, {"id": "q1", "degree": 0}]
    update_degrees_incrementally(nodes_copy, delta.added_edges, delta.removed_edges)
    by_id = {n["id"]: n["degree"] for n in nodes_copy}
    assert by_id["s1"] == 2
    assert by_id["db1"] == 1
    assert by_id["q1"] == 1

    # Community impact detection
    comm_map = {"s1": 10, "db1": 10, "q1": 20}
    affected = detect_affected_communities(delta, comm_map)
    assert affected == {10, 20}

    # Applying delta produces identical state
    reconstructed = apply_delta_to_graph(old_graph, delta)
    reconstructed_ids = {n["id"] for n in reconstructed["nodes"]}
    assert reconstructed_ids == {"s1", "db1", "q1"}


def test_cmd_build_merkle_cache():
    import argparse
    from corpusatlas.__main__ import cmd_build

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        cfg_path = tmp / "corpusatlas.toml"
        obs_dir = tmp / "vault"
        obs_dir.mkdir()
        (obs_dir / "Alpha.md").write_text("# Alpha\nTag: #tech\nLinks to [[Beta]]", encoding="utf-8")
        (obs_dir / "Beta.md").write_text("# Beta\nTag: #tech\nContent here", encoding="utf-8")

        cfg_path.write_text(f"""
[[sources]]
type = "obsidian"
path = "{obs_dir}"
""", encoding="utf-8")

        out_graph = tmp / "graph.json"
        cache_path = tmp / "cache.json"
        merkle_path = tmp / "merkle.json"

        args1 = argparse.Namespace(
            config=str(cfg_path),
            out=str(out_graph),
            dry_run=False,
            layout=False,
            cache=str(cache_path),
            fine_cache=True,
            merkle_cache=str(merkle_path),
            store="memory",
            db_path=None
        )

        res1 = cmd_build(args1)
        assert res1 == 0
        assert out_graph.exists()
        assert merkle_path.exists()

        # Run 2: rebuild with warm cache
        res2 = cmd_build(args1)
        assert res2 == 0





