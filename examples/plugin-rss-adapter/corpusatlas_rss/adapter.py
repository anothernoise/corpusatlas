"""Example third-party corpusatlas adapter: a local RSS 2.0 or Atom feed
file, turned into Documents. This is a *template*, not a maintained
corpusatlas source — copy this package, rename it, and adapt `documents()`
to whatever your real feed actually contains.

Deliberately reads a local *file*, not a URL: fetching a feed over HTTP
well — retries, robots.txt, connection reuse, redirects — is a solved
problem already, and it's corpusatlas's own `web` adapter
(`corpusatlas.adapters.web.WebAdapter`). Duplicating that here would make
this example about HTTP instead of about the one thing worth showing: how
a *different* source shape (XML, not markdown or rendered HTML) becomes the
same `Document` shape every other adapter produces. A real deployment
fetches the feed first (with WebAdapter, or however you like) and points
this at the downloaded file.
"""
from __future__ import annotations

import re
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from corpusatlas.model import Document

_ATOM_NS = "{http://www.w3.org/2005/Atom}"


def _text(el, tag: str, ns: str = "") -> str:
    child = el.find(f"{ns}{tag}")
    return (child.text or "").strip() if child is not None and child.text else ""


def _rss_date(raw: str) -> str | None:
    """RSS 2.0's pubDate is RFC 822 ("Wed, 02 Oct 2002 15:00:00 GMT"), not
    the ISO 8601 every other date field in this pipeline expects — a plain
    string slice would silently produce garbage instead of a date."""
    try:
        return parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        return None


def _atom_date(raw: str) -> str | None:
    return raw[:10] if raw and raw[:4].isdigit() else None


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return s or "item"


class RssAdapter:
    """`path` is a local RSS 2.0 or Atom XML file. `url_base` is used only
    as a fallback when an item has no link of its own, which real feeds
    essentially never omit — present for parity with the other adapters'
    shape, not because it's expected to matter in practice."""

    def __init__(self, path: str, url_base: str = ""):
        self.path = Path(path)
        self.url_base = url_base

    def documents(self):
        root = ET.parse(self.path).getroot()
        items = root.findall(".//item") or root.findall(f".//{_ATOM_NS}entry")

        seen_slugs: set[str] = set()
        for item in items:
            is_atom = item.tag == f"{_ATOM_NS}entry"
            ns = _ATOM_NS if is_atom else ""
            title = _text(item, "title", ns) or "untitled"

            # A feed's own item ordering isn't guaranteed unique by title;
            # corpusatlas requires unique ids within one adapter's batch.
            slug = base_slug = _slug(title)
            n = 2
            while slug in seen_slugs:
                slug = f"{base_slug}-{n}"
                n += 1
            seen_slugs.add(slug)

            if is_atom:
                link_el = item.find(f"{ns}link")
                link = link_el.get("href", "") if link_el is not None else ""
                text = _text(item, "summary", ns) or _text(item, "content", ns)
                date = _atom_date(_text(item, "published", ns) or _text(item, "updated", ns))
            else:
                link = _text(item, "link")
                text = _text(item, "description")
                date = _rss_date(_text(item, "pubDate"))

            yield Document(
                id=slug,
                title=title,
                url=link or f"{self.url_base}{slug}",
                kind="article",
                date=date,
                text=text,
            )
