"""A shared behavioural contract across the four adapters that read
distinct sources but produce the same Document shape: html_blog, obsidian,
logseq, web. Each has its own dedicated test file for what's specific to
it; this one is for the invariants every adapter has to hold regardless —
so that when one of the four changes, a drift in a rule the others still
honour shows up here instead of only being noticed by accident later.

entity_packs, radar_scorecards and radar_entries are deliberately not
included: they're structured-data adapters reading a project's own bespoke
JSON shapes, not "a source of prose with links" the way the other four are
— see docs/adapters.md's "Which one for what" for that distinction.
"""
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.adapters.html_blog import HtmlBlogAdapter
from corpusatlas.adapters.logseq import LogseqAdapter
from corpusatlas.adapters.obsidian import ObsidianAdapter
from corpusatlas.adapters.web import WebAdapter
from corpusatlas.model import Document


def _assert_conforms(docs: list[Document], adapter_name: str) -> None:
    ids = [d.id for d in docs]
    assert len(ids) == len(set(ids)), f"{adapter_name}: duplicate document ids in one batch: {ids}"
    for d in docs:
        assert d.id, f"{adapter_name}: a document with an empty id"
        assert d.title, f"{adapter_name}: {d.id!r} has an empty title"
        assert d.url, f"{adapter_name}: {d.id!r} has an empty url"
        assert d.kind == "article", f"{adapter_name}: {d.id!r} has kind {d.kind!r}, expected 'article'"
        assert isinstance(d.tags, tuple), f"{adapter_name}: {d.id!r}.tags is {type(d.tags).__name__}, not tuple"
        assert isinstance(d.links, tuple), f"{adapter_name}: {d.id!r}.links is {type(d.links).__name__}, not tuple"
        assert d.id not in d.links, f"{adapter_name}: {d.id!r} links to itself"
        assert len(d.links) == len(set(d.links)), f"{adapter_name}: {d.id!r} has duplicate links"


def test_html_blog_conforms():
    with tempfile.TemporaryDirectory() as d:
        blog = Path(d)
        (blog / "a.html").write_text(
            '<html><head><h1>A</h1></head><body><div class="article-content">'
            '<a href="a.html">self</a> <a href="b.html">to b</a></div></body></html>',
            encoding="utf-8")
        (blog / "b.html").write_text(
            '<html><head><h1>B</h1></head><body><div class="article-content">'
            'no links here</div></body></html>', encoding="utf-8")
        docs = list(HtmlBlogAdapter(str(blog)).documents())
    assert len(docs) == 2
    _assert_conforms(docs, "html_blog")


def test_obsidian_conforms():
    with tempfile.TemporaryDirectory() as d:
        vault = Path(d)
        (vault / "A.md").write_text("Links to [[A]] (self) and [[B]].", encoding="utf-8")
        (vault / "B.md").write_text("No links here.", encoding="utf-8")
        docs = list(ObsidianAdapter(str(vault)).documents())
    assert len(docs) == 2
    _assert_conforms(docs, "obsidian")


def test_logseq_conforms():
    with tempfile.TemporaryDirectory() as d:
        graph = Path(d)
        (graph / "A.md").write_text("- Links to [[A]] (self) and [[B]].", encoding="utf-8")
        (graph / "B.md").write_text("- No links here.", encoding="utf-8")
        docs = list(LogseqAdapter(str(graph)).documents())
    assert len(docs) == 2
    _assert_conforms(docs, "logseq")


def test_web_conforms():
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/a":
                body = (b'<html><head><title>A</title></head><body>'
                        b'<a href="/a">self</a> <a href="/b">to b</a></body></html>')
            elif self.path == "/b":
                body = b"<html><head><title>B</title></head><body>no links</body></html>"
            else:
                self.send_response(404); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        docs = list(WebAdapter(urls=[f"{base}/a", f"{base}/b"], respect_robots=False).documents())
    finally:
        server.shutdown()
    assert len(docs) == 2
    _assert_conforms(docs, "web")


def test_an_empty_source_yields_nothing_not_a_crash():
    """web is the one exception: it needs at least one url to be configured
    at all (ValueError, tested in test_web_adapter.py), since "empty" isn't
    a meaningful state for a plain list of urls the way an empty directory
    is for a directory adapter."""
    with tempfile.TemporaryDirectory() as d:
        empty = Path(d)
        assert list(HtmlBlogAdapter(str(empty)).documents()) == []
        assert list(ObsidianAdapter(str(empty)).documents()) == []
        assert list(LogseqAdapter(str(empty)).documents()) == []
