"""Adapter for a directory of published HTML articles.

Reads the rendered pages rather than sources, because the published page is the
thing that is actually true — if a link was dropped in a template, the graph
should reflect what a reader sees.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from ..model import Document

SKIP = {"index", "topics", "start-here"}

_TITLE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
_DATE = re.compile(r'article:published_time"\s+content="([\d-]+)"')
_TAGS = re.compile(r'data-tags="([^"]+)"')
_LINK = re.compile(r'href="(?!http|/|#|\.\./|mailto:)([a-z0-9-]+)"')
_TAG_RE = re.compile(r"<[^>]+>")
# Consumes the rest of the opening tag too (any attributes after class=,
# through the closing >), not just the bare string — splitting on the string
# alone leaves a stray ">" as the first character of every article's body,
# which _TAG_RE can't strip because it isn't a complete <...> tag.
_ARTICLE_START = re.compile(r'class="article-content"[^>]*>')


def _text(fragment: str) -> str:
    return html.unescape(_TAG_RE.sub(" ", fragment)).strip()


class HtmlBlogAdapter:
    def __init__(self, path: str, url_base: str = "/blog/", index: str | None = None):
        self.path = Path(path)
        self.url_base = url_base
        # The card list carries the tags; the article pages do not.
        self.index = Path(index) if index else self.path / "index.html"

    def _tags_by_slug(self) -> dict[str, tuple[str, ...]]:
        if not self.index.exists():
            return {}
        s = self.index.read_text(encoding="utf-8")
        out: dict[str, tuple[str, ...]] = {}
        for m in re.finditer(r'data-tags="([^"]+)"\s*>\s*<a href="([a-z0-9-]+)"', s, re.S):
            out[m.group(2)] = tuple(t.strip() for t in m.group(1).split(",") if t.strip())
        return out

    def documents(self):
        tags = self._tags_by_slug()
        for f in sorted(self.path.glob("*.html")):
            slug = f.stem
            if slug in SKIP:
                continue
            s = f.read_text(encoding="utf-8")
            title_m = _TITLE.search(s)
            date_m = _DATE.search(s)
            body = _ARTICLE_START.split(s, maxsplit=1)[-1]
            links = {l for l in _LINK.findall(body) if l != slug and (self.path / f"{l}.html").exists()}
            yield Document(
                id=slug,
                title=_text(title_m.group(1)) if title_m else slug,
                url=f"{self.url_base}{slug}",
                kind="article",
                date=date_m.group(1) if date_m else None,
                text=_text(body),
                tags=tags.get(slug, ()),
                links=tuple(sorted(links)),
            )
