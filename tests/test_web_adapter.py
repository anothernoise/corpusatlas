"""Tests for the web adapter, against a real local HTTP server rather than a
mocked urlopen — the parsing has to survive actual HTTP, not a fixture
someone wrote to already look parseable. Stdlib only, so this needs no test
dependency: http.server in a background thread, torn down after."""
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.adapters.web import WebAdapter

PAGES = {
    "/a": b"""<html><head><title>Page A</title>
        <meta property="article:published_time" content="2026-01-02"></head>
        <body><nav>Home | About</nav>
        <script>trackEvent('view')</script>
        <h1>Page A</h1><p>This mentions <a href="/b">Page B</a> and
        <a href="https://example.org/elsewhere">something external</a>.</p>
        <footer>copyright nobody</footer></body></html>""",
    "/b": b"<html><head><title>Page B</title></head><body><p>Referenced by A.</p></body></html>",
}


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGES.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass  # keep test output quiet


def _serve():
    server = HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_web_adapter_extracts_title_date_text_and_in_batch_links():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        docs = list(WebAdapter(urls=[f"{base}/a", f"{base}/b"]).documents())
    finally:
        server.shutdown()

    by_id = {d.id: d for d in docs}
    assert set(by_id) == {"a", "b"}

    a = by_id["a"]
    assert a.title == "Page A"
    assert a.date == "2026-01-02"
    assert a.kind == "article"
    # nav, script and footer content must not leak into the extracted text.
    assert "trackEvent" not in a.text
    assert "Home" not in a.text
    assert "copyright nobody" not in a.text
    assert "This mentions Page B and something external" in a.text
    # /b is in the batch, so it becomes a link; the external URL is not.
    assert a.links == ("b",)

    b = by_id["b"]
    assert b.title == "Page B"
    assert b.date is None
    assert b.links == ()


def test_a_page_that_fails_to_fetch_is_skipped_not_fatal():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        docs = list(WebAdapter(urls=[f"{base}/a", f"{base}/missing"]).documents())
    finally:
        server.shutdown()
    assert [d.id for d in docs] == ["a"]


def test_urls_and_a_url_list_file_combine():
    import tempfile
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(f"# a comment, and a blank line above is skipped\n\n{base}/b\n")
            path = f.name
        docs = list(WebAdapter(urls=[f"{base}/a"], url_list_file=path).documents())
    finally:
        server.shutdown()
    assert {d.id for d in docs} == {"a", "b"}


def test_no_urls_at_all_is_a_configuration_error():
    try:
        WebAdapter()
    except ValueError:
        return
    raise AssertionError("expected a ValueError for an adapter with nothing to fetch")
