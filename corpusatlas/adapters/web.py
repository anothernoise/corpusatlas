"""Adapter for a plain list of web pages, fetched at build time.

Every other adapter reads local files; this one makes a network request per
URL, which is a real behaviour change worth naming plainly: a build using it
is no longer reproducible from the checkout alone, and it fails if a page is
down. Use it when the corpus genuinely lives outside your own repo (a public
wiki, docs hosted elsewhere, a page you don't control) — not as a substitute
for html_blog when the pages are yours.

Extraction is deliberately crude, and honestly so: a <title>, a best-effort
publish date from common meta tags, and the page's visible text with script,
style, nav, header and footer stripped. That is far short of real content
extraction (Readability.js and friends exist for a reason) — it is "good
enough to mention-scan and link", not "good enough to read". A page that
buries its content in nav-like markup will extract worse text than an
article.

Links only connect within the batch: an href to a page not also in `urls`
becomes a dead end (dropped, not a broken graph reference) — the same choice
html_blog makes for a link outside its own directory. Two configured urls
that differ only in scheme case, a trailing slash or a fragment resolve to
the same document (`_normalize()`), so a link written either way still joins.

Fetches happen concurrently (`max_workers` threads, stdlib
`ThreadPoolExecutor` — this is I/O-bound waiting on sockets, not CPU work,
so the GIL isn't a concern), but `documents()` still yields in `urls`' own
order regardless of which response comes back first: fetch order and output
order are two different things, and only the second has to be deterministic.

A profile of 100 real pages (see the project's own benchmarking) found
fetching costs about 6x what parsing does even at 8-way concurrency, and a
fresh TLS handshake per request is a real share of that — `_ConnectionPool`
keeps one persistent connection per (worker thread, host) instead of
reconnecting every time. `_fetch` also retries a transient failure
(`max_retries`, small backoff) and follows redirects itself, since bypassing
`urlopen` for connection reuse means giving up its automatic handling of
both.

Polite by default: `respect_robots=True` fetches and caches each host's
robots.txt once, skips a URL robots.txt disallows for this adapter's user
agent (with a warning, the same as a fetch failure), and honours a
`Crawl-delay` directive by spacing requests to that host at least that far
apart — across every worker thread, not per-thread, since the delay is a
promise to the site, not to any one connection. A host with no robots.txt,
or one with nothing relevant in it, is unaffected either way.
"""
from __future__ import annotations

import email.message
import http.client
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from .. import __version__
from ..model import Document

_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "noscript", "template"}
_DATE_META = (
    re.compile(r'<meta[^>]+property="article:published_time"[^>]+content="([\d-]+)"', re.I),
    re.compile(r'<meta[^>]+name="date"[^>]+content="([\d-]+)"', re.I),
    re.compile(r'"datePublished"\s*:\s*"([\d-]+)'),
)
_REDIRECT_CODES = (301, 302, 303, 307, 308)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class _TextExtractor(HTMLParser):
    """Visible text only: skips script/style/nav/header/footer content and
    collapses whitespace, so a build-time mention scan sees roughly what a
    reader would, not a page's chrome or its inline JavaScript."""

    def __init__(self):
        super().__init__()
        self.title = ""
        self.links: set[str] = set()
        self._skip_depth = 0
        self._in_title = False
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.add(href)

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data
        else:
            stripped = data.strip()
            if stripped:
                self._chunks.append(stripped)

    @property
    def text(self) -> str:
        return " ".join(self._chunks)


def _slug(url: str) -> str:
    path = urlparse(url).path.strip("/")
    slug = re.sub(r"[^a-z0-9]+", "-", (path or urlparse(url).netloc).lower()).strip("-")
    return slug or re.sub(r"[^a-z0-9]+", "-", url.lower()).strip("-")


def _normalize(url: str) -> str:
    """Two urls that a browser would treat as the same page collapse to one
    key: lowercase scheme/host, no trailing slash (except the bare root), no
    fragment. Used only for identity — the Document's own `url` field, and
    what actually gets fetched, keep the form the config or the page wrote."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _charset_of(content_type: str | None) -> str:
    if not content_type:
        return "utf-8"
    msg = email.message.Message()
    msg["content-type"] = content_type
    return msg.get_content_charset() or "utf-8"


class _ConnectionPool:
    """One persistent HTTP(S) connection per (worker thread, host), so
    keep-alive actually pays off across the several fetches one thread makes
    over a build instead of paying a fresh TCP+TLS handshake every time.
    Thread-local because http.client connections aren't safe to share
    across threads, and each ThreadPoolExecutor worker only ever runs one
    fetch at a time anyway."""

    def __init__(self, timeout: float):
        self.timeout = timeout
        self._local = threading.local()

    def _conns(self) -> dict[tuple[str, str], http.client.HTTPConnection]:
        conns = getattr(self._local, "conns", None)
        if conns is None:
            conns = self._local.conns = {}
        return conns

    def get(self, scheme: str, netloc: str) -> http.client.HTTPConnection:
        conns = self._conns()
        key = (scheme, netloc)
        conn = conns.get(key)
        if conn is None:
            cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
            conn = cls(netloc, timeout=self.timeout)
            conns[key] = conn
        return conn

    def drop(self, scheme: str, netloc: str) -> None:
        """The cached connection turned out to be stale (the server closed
        it) — discard it so the next attempt opens a fresh one instead of
        retrying the same broken socket."""
        conn = self._conns().pop((scheme, netloc), None)
        if conn is not None:
            conn.close()


class _RobotsCache:
    """Fetches and parses each host's robots.txt at most once per build,
    shared (with a lock) across every worker thread. A host with no
    robots.txt, or one this can't reach, is treated as allow-everything —
    the same as not checking at all, which is what happens when
    respect_robots=False."""

    def __init__(self, user_agent: str, timeout: float):
        self.user_agent = user_agent
        self.timeout = timeout
        self._parsers: dict[str, RobotFileParser] = {}
        self._lock = threading.Lock()
        self._last_request: dict[str, float] = {}
        self._throttle_lock = threading.Lock()

    def _parser_for(self, scheme: str, netloc: str) -> RobotFileParser:
        key = f"{scheme}://{netloc}"
        with self._lock:
            parser = self._parsers.get(key)
            if parser is not None:
                return parser
            parser = RobotFileParser()
            parser.set_url(f"{key}/robots.txt")
            try:
                req = urllib.request.Request(f"{key}/robots.txt",
                                             headers={"User-Agent": self.user_agent})
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
                parser.parse(text.splitlines())
            except Exception:
                parser.parse([])  # no robots.txt, or unreachable — allow everything
            self._parsers[key] = parser
            return parser

    def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        return self._parser_for(parts.scheme, parts.netloc).can_fetch(self.user_agent, url)

    def wait_for_turn(self, url: str) -> None:
        """Blocks the calling thread until this host's Crawl-delay (if any)
        has elapsed since the last request to it — across all threads, since
        the delay is a promise to the site, not to one connection."""
        parts = urlsplit(url)
        delay = self._parser_for(parts.scheme, parts.netloc).crawl_delay(self.user_agent)
        if not delay:
            return
        host = parts.netloc
        with self._throttle_lock:
            wait = self._last_request.get(host, 0.0) + float(delay) - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last_request[host] = time.monotonic()


class WebAdapter:
    def __init__(self, urls: list[str] | None = None, url_list_file: str | None = None,
                 timeout: float = 10.0, user_agent: str = f"corpusatlas/{__version__}",
                 max_workers: int = 8, max_retries: int = 2, retry_backoff: float = 0.5,
                 respect_robots: bool = True):
        given = list(urls or [])
        if url_list_file:
            with open(url_list_file, encoding="utf-8") as f:
                given += [line.strip() for line in f if line.strip() and not line.startswith("#")]
        if not given:
            raise ValueError("web adapter needs urls or url_list_file")
        # Dedupe by normalized identity, keeping the first-seen spelling —
        # two configured urls a browser would treat as the same page must
        # become one fetch and one document, not two.
        seen: dict[str, str] = {}
        for u in given:
            seen.setdefault(_normalize(u), u)
        self.urls = list(seen.values())
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_workers = max_workers
        self.max_retries = max_retries
        self.retry_backoff = retry_backoff
        self.respect_robots = respect_robots
        self._pool = _ConnectionPool(timeout)
        self._robots = _RobotsCache(user_agent, timeout) if respect_robots else None

    def _request_once(self, url: str) -> str:
        parts = urlsplit(url)
        conn = self._pool.get(parts.scheme, parts.netloc)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        try:
            conn.request("GET", path, headers={"User-Agent": self.user_agent,
                                               "Connection": "keep-alive"})
            resp = conn.getresponse()
            body = resp.read()
        except (http.client.HTTPException, OSError):
            # The pooled connection may have gone stale (the server closed
            # an idle keep-alive socket) — drop it so the retry loop in
            # _fetch opens a fresh one instead of reusing the same break.
            self._pool.drop(parts.scheme, parts.netloc)
            raise

        if resp.status in _REDIRECT_CODES:
            location = resp.getheader("Location")
            if not location:
                raise urllib.error.URLError(f"redirect from {url} with no Location header")
            return self._request_once(urljoin(url, location))
        if resp.status in _RETRYABLE_STATUS:
            raise urllib.error.URLError(f"{resp.status} {resp.reason}")
        if resp.status >= 400:
            raise urllib.error.HTTPError(url, resp.status, resp.reason, resp.headers, None)

        return body.decode(_charset_of(resp.getheader("Content-Type")), errors="replace")

    def _fetch(self, url: str) -> str:
        if self._robots is not None:
            self._robots.wait_for_turn(url)
        last_err: Exception = urllib.error.URLError("no attempt made")
        for attempt in range(self.max_retries + 1):
            try:
                return self._request_once(url)
            except (http.client.HTTPException, OSError, urllib.error.URLError) as err:
                last_err = err
                if attempt < self.max_retries:
                    time.sleep(self.retry_backoff * (2 ** attempt))
        raise last_err

    def _fetch_all(self) -> list[tuple[str, str | None]]:
        """One (url, html-or-None) pair per url, in `self.urls`' order — a
        failed fetch, or one robots.txt disallows, is None rather than an
        exception, so one bad page can't take the rest of a concurrent batch
        down with it."""
        to_fetch = []
        out: dict[str, str | None] = {}
        for url in self.urls:
            if self._robots is not None and not self._robots.allowed(url):
                print(f"  warning: web: {url} disallowed by robots.txt; skipped", flush=True)
                out[url] = None
            else:
                to_fetch.append(url)

        workers = max(1, min(self.max_workers, len(to_fetch) or 1))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(self._fetch, url) for url in to_fetch]
            for url, future in zip(to_fetch, futures):
                try:
                    out[url] = future.result()
                except (urllib.error.URLError, TimeoutError, OSError) as err:
                    print(f"  warning: web: {url} failed to fetch ({err}); skipped", flush=True)
                    out[url] = None

        return [(url, out[url]) for url in self.urls]

    def documents(self):
        by_url = {_normalize(u): _slug(u) for u in self.urls}
        for url, html_src in self._fetch_all():
            if html_src is None:
                continue
            slug = by_url[_normalize(url)]

            parser = _TextExtractor()
            parser.feed(html_src)

            date = None
            for pattern in _DATE_META:
                m = pattern.search(html_src)
                if m:
                    date = m.group(1)
                    break

            links = set()
            for href in parser.links:
                absolute = _normalize(urljoin(url, href))
                if absolute in by_url and by_url[absolute] != slug:
                    links.add(by_url[absolute])

            yield Document(
                id=slug,
                title=parser.title.strip() or slug,
                url=url,
                kind="article",
                date=date,
                text=parser.text,
                links=tuple(sorted(links)),
            )
