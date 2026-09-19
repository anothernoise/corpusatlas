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
html_blog makes for a link outside its own directory.
"""
from __future__ import annotations

import re
import urllib.error
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from ..model import Document

_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "noscript", "template"}
_DATE_META = (
    re.compile(r'<meta[^>]+property="article:published_time"[^>]+content="([\d-]+)"', re.I),
    re.compile(r'<meta[^>]+name="date"[^>]+content="([\d-]+)"', re.I),
    re.compile(r'"datePublished"\s*:\s*"([\d-]+)'),
)


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


class WebAdapter:
    def __init__(self, urls: list[str] | None = None, url_list_file: str | None = None,
                 timeout: float = 10.0, user_agent: str = "corpusatlas/0.4.0"):
        given = list(urls or [])
        if url_list_file:
            with open(url_list_file, encoding="utf-8") as f:
                given += [line.strip() for line in f if line.strip() and not line.startswith("#")]
        if not given:
            raise ValueError("web adapter needs urls or url_list_file")
        self.urls = given
        self.timeout = timeout
        self.user_agent = user_agent

    def _fetch(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")

    def documents(self):
        by_url = {u: _slug(u) for u in self.urls}
        for url in self.urls:
            slug = by_url[url]
            try:
                html_src = self._fetch(url)
            except (urllib.error.URLError, TimeoutError, OSError) as err:
                print(f"  warning: web: {url} failed to fetch ({err}); skipped", flush=True)
                continue

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
                absolute = urljoin(url, href)
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
