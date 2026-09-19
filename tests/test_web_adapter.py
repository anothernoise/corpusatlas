"""Tests for the web adapter, against a real local HTTP server rather than a
mocked urlopen — the parsing has to survive actual HTTP, not a fixture
someone wrote to already look parseable. Stdlib only, so this needs no test
dependency: http.server in a background thread, torn down after."""
import re
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
    "/private": b"<html><head><title>Private</title></head><body>shh</body></html>",
}

_SLOW_PATH = re.compile(r"^/slow/(\d+)$")
SLOW_DELAY = 0.2  # seconds each /slow/<n> page takes to respond

# Mutable test fixtures, reset by each test that uses them — module-level
# because the handler class is instantiated fresh per request by
# http.server, with no other way to hand it per-test configuration.
ROBOTS_TXT: dict[str, bytes | None] = {"body": None}   # None -> 404, i.e. "no robots.txt"
FLAKY_REMAINING: dict[str, int] = {}                   # path -> failures left before a 200


class _Handler(BaseHTTPRequestHandler):
    # HTTP/1.0 (the base class default) closes the connection after every
    # response regardless of what the client sends — testing that the
    # client-side connection pool reuses a socket needs a server that can
    # actually keep one open, which needs both HTTP/1.1 and a Content-Length
    # on every response (keep-alive has no other way to know where a body
    # ends, with no chunked encoding here).
    protocol_version = "HTTP/1.1"
    connection_count = 0

    def setup(self):
        _Handler.connection_count += 1
        super().setup()

    def _send(self, status, body=b"", content_type="text/html; charset=utf-8", headers=None):
        self.send_response(status)
        if body:
            self.send_header("Content-Type", content_type)
        # Always, even for an empty body: HTTP/1.1 keep-alive has no other
        # way to know where one response ends and the next begins, with no
        # chunked encoding here.
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path == "/robots.txt":
            body = ROBOTS_TXT["body"]
            self._send(200, body, "text/plain") if body is not None else self._send(404)
            return
        if self.path == "/redirect":
            self._send(301, headers={"Location": "/a"})
            return
        if self.path in FLAKY_REMAINING:
            if FLAKY_REMAINING[self.path] > 0:
                FLAKY_REMAINING[self.path] -= 1
                self._send(503)
                return
            self._send(200, b"<html><head><title>Flaky</title></head><body>ok</body></html>")
            return
        m = _SLOW_PATH.match(self.path)
        if m:
            time.sleep(SLOW_DELAY)
            body = f"<html><head><title>Slow {m.group(1)}</title></head><body></body></html>".encode()
            self._send(200, body)
            return
        body = PAGES.get(self.path)
        self._send(200, body) if body is not None else self._send(404)

    def log_message(self, *a):
        pass  # keep test output quiet


def _serve():
    # Threading, not plain HTTPServer: a single-threaded server would
    # serialise even concurrent client requests, which would defeat the
    # point of the concurrency test below — the bottleneck has to be able
    # to move to the client side for that test to mean anything.
    ROBOTS_TXT["body"] = None
    FLAKY_REMAINING.clear()
    _Handler.connection_count = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
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


def test_fetches_run_concurrently_not_one_at_a_time():
    """5 pages that each take SLOW_DELAY to answer: serial fetching takes
    ~5x SLOW_DELAY; concurrent fetching (the default max_workers=8) takes
    ~1x. A generous 2.5x bound tells the two apart without being flaky
    about exact scheduling."""
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        urls = [f"{base}/slow/{i}" for i in range(5)]
        start = time.monotonic()
        docs = list(WebAdapter(urls=urls).documents())
        elapsed = time.monotonic() - start
    finally:
        server.shutdown()

    assert len(docs) == 5
    assert elapsed < SLOW_DELAY * 2.5, f"took {elapsed:.2f}s — fetches don't look concurrent"


def test_output_order_matches_urls_order_regardless_of_fetch_order():
    """The first url is the slowest to respond; if documents() just yielded
    in completion order (the naive concurrent implementation) it would come
    back last instead of first."""
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        urls = [f"{base}/slow/9", f"{base}/a", f"{base}/b"]
        docs = list(WebAdapter(urls=urls).documents())
    finally:
        server.shutdown()

    assert [d.id for d in docs] == ["slow-9", "a", "b"]


def test_max_workers_is_configurable():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        urls = [f"{base}/slow/{i}" for i in range(4)]
        start = time.monotonic()
        docs = list(WebAdapter(urls=urls, max_workers=1).documents())
        elapsed = time.monotonic() - start
    finally:
        server.shutdown()

    assert len(docs) == 4
    # max_workers=1 is effectively the old serial behaviour.
    assert elapsed >= SLOW_DELAY * 3.5


# --- connection reuse, retries, robots.txt, redirects, dedup --------------

def test_persistent_connections_are_reused_not_reopened_per_request():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        urls = [f"{base}/a", f"{base}/b", f"{base}/private",
               f"{base}/slow/0", f"{base}/slow/1", f"{base}/slow/2"]
        docs = list(WebAdapter(urls=urls, max_workers=2, respect_robots=False).documents())
    finally:
        connections = _Handler.connection_count
        server.shutdown()

    assert len(docs) == 6
    # 2 workers, each keeping one persistent connection open across its
    # several fetches: nowhere near one connection per request (6).
    assert connections <= 3, f"{connections} connections for 6 requests — reuse doesn't look like it's working"


def test_retries_a_transient_failure_and_succeeds():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        FLAKY_REMAINING["/flaky"] = 2  # 503 twice, then 200
        docs = list(WebAdapter(urls=[f"{base}/flaky"], max_retries=2,
                               retry_backoff=0.01, respect_robots=False).documents())
    finally:
        server.shutdown()

    assert [d.id for d in docs] == ["flaky"]
    assert docs[0].title == "Flaky"


def test_retries_exhausted_still_skips_gracefully():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        FLAKY_REMAINING["/flaky2"] = 5  # more failures than retries allow
        docs = list(WebAdapter(urls=[f"{base}/a", f"{base}/flaky2"], max_retries=1,
                               retry_backoff=0.01, respect_robots=False).documents())
    finally:
        server.shutdown()

    assert [d.id for d in docs] == ["a"]  # flaky2 gave up, but didn't take "a" down with it


def test_robots_txt_disallow_skips_a_url():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        ROBOTS_TXT["body"] = b"User-agent: *\nDisallow: /private\n"
        docs = list(WebAdapter(urls=[f"{base}/a", f"{base}/private"]).documents())
    finally:
        server.shutdown()

    assert [d.id for d in docs] == ["a"]


def test_respect_robots_false_bypasses_the_check():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        ROBOTS_TXT["body"] = b"User-agent: *\nDisallow: /private\n"
        docs = list(WebAdapter(urls=[f"{base}/a", f"{base}/private"],
                               respect_robots=False).documents())
    finally:
        server.shutdown()

    assert {d.id for d in docs} == {"a", "private"}


def test_a_missing_robots_txt_is_treated_as_allow_everything():
    server = _serve()  # ROBOTS_TXT["body"] is None -> 404
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        docs = list(WebAdapter(urls=[f"{base}/a"]).documents())
    finally:
        server.shutdown()
    assert [d.id for d in docs] == ["a"]


def test_redirects_are_followed_transparently():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        docs = list(WebAdapter(urls=[f"{base}/redirect"], respect_robots=False).documents())
    finally:
        server.shutdown()

    # Identity follows the configured url (/redirect); content follows
    # wherever it actually redirected to (/a's title).
    assert [d.id for d in docs] == ["redirect"]
    assert docs[0].title == "Page A"


def test_urls_that_normalize_to_the_same_page_are_deduplicated():
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        adapter = WebAdapter(urls=[f"{base}/a", f"{base}/a/", f"{base}/a#section"],
                             respect_robots=False)
        assert adapter.urls == [f"{base}/a"]  # deduped at construction time
        docs = list(adapter.documents())
    finally:
        server.shutdown()

    assert [d.id for d in docs] == ["a"]
