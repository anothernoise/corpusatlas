"""Adapter for a Logseq graph: outline-based markdown pages, page properties
written as `key:: value` lines rather than YAML frontmatter, and
[[wikilinks]] that Logseq treats as interchangeable with #hashtags — both
create the same kind of page reference, unlike Obsidian, where a wikilink
and a hashtag are visually and semantically distinct. Both count as tags
here for that reason.

Every line in a Logseq page is conventionally a bullet (`- content`), so
`plain_text()` strips the leading `- ` from each line — without it, every
sentence in the extracted text would start with a literal dash.

Page properties are read from `key:: value` lines at the very top of the
file, stopping at the first line that doesn't match — the common case when
properties are set on an otherwise-empty first block. A vault that puts
properties somewhere else in the page (mid-document, or nested under a
specific heading) will have that block's `key:: value` lines read as
ordinary bullet content instead, not as properties. Same crude-on-purpose
bar as the other markdown adapters here.

Deliberately not "a Roam adapter too": Roam's rough shape (outline,
[[links]], block references) is similar, but its actual export formats
(JSON, or a Roam-specific markdown flavour) haven't been tested against
this, so claiming support for a corpus this was never run on would be a
promise, not a fact.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..cache import CacheBucket, hash_bytes
from ..model import Document
from ..resolve import slug

_PROPERTY = re.compile(r"^([A-Za-z][\w-]*)::\s*(.*)$")
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")
# Same reasoning as the Obsidian adapter's tag regex: starts a word, first
# character is a letter, so "see #2" and a hex colour in a code fence mostly
# don't match.
_INLINE_TAG = re.compile(r"(?<!\S)#([A-Za-z][\w/-]*)")
_CODE_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`]*`")
_BULLET_MARKER = re.compile(r"^[ \t]*-[ \t]?", re.M)


def split_properties(raw: str) -> tuple[dict, str]:
    lines = raw.split("\n")
    props: dict[str, str] = {}
    i = 0
    while i < len(lines):
        m = _PROPERTY.match(lines[i].strip())
        if not m:
            break
        props[m.group(1)] = m.group(2).strip()
        i += 1
    return props, "\n".join(lines[i:])


def wikilink_targets(body: str) -> list[tuple[str, str]]:
    """Every [[target]] as (raw target title, display text)."""
    out = []
    for m in _WIKILINK.finditer(body):
        target = m.group(1).strip()
        out.append((target, (m.group(2) or target).strip()))
    return out


def plain_text(body: str) -> str:
    s = _CODE_FENCE.sub(" ", body)
    s = _INLINE_CODE.sub(" ", s)
    s = _WIKILINK.sub(lambda m: (m.group(2) or m.group(1)).strip(), s)
    s = _BULLET_MARKER.sub("", s)
    s = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


class LogseqAdapter:
    def __init__(self, path: str, url_base: str = "/notes/", recursive: bool = True,
                 cache: CacheBucket | None = None):
        self.path = Path(path)
        self.url_base = url_base
        self.recursive = recursive
        self._cache = cache

    def _files(self):
        pattern = "**/*.md" if self.recursive else "*.md"
        return sorted(self.path.glob(pattern))

    def documents(self):
        files = self._files()
        by_title = {f.stem.lower(): f.stem for f in files}

        if self._cache:
            # Same reasoning as the Obsidian adapter: wikilink resolution
            # depends on which stems exist at all, so the fingerprint is
            # the whole graph's file list, not any one file alone.
            self._cache.enter(tuple(f.stem for f in files))

        for f in files:
            raw_bytes = f.read_bytes()
            content_hash = hash_bytes(raw_bytes)
            cached = self._cache.get(str(f), content_hash) if self._cache else None
            if cached is not None:
                yield cached
                continue

            raw = raw_bytes.decode("utf-8")
            props, body = split_properties(raw)
            title = props.get("title") or f.stem

            tag_prop = [t.strip() for t in props.get("tags", "").split(",") if t.strip()]
            inline_tags = _INLINE_TAG.findall(body)
            tags = tuple(dict.fromkeys([*tag_prop, *inline_tags]))

            links = set()
            for target, _ in wikilink_targets(body):
                basename = target.rsplit("/", 1)[-1]
                resolved = by_title.get(target.lower()) or by_title.get(basename.lower())
                if resolved and resolved != f.stem:
                    links.add(resolved)

            date = props.get("date") or props.get("created")

            doc = Document(
                id=f.stem,
                title=title,
                url=f"{self.url_base}{slug(title)}",
                kind="article",
                date=date if isinstance(date, str) else None,
                text=plain_text(body),
                tags=tags,
                links=tuple(sorted(links)),
            )
            if self._cache:
                self._cache.put(str(f), content_hash, doc)
            yield doc

        if self._cache:
            self._cache.commit(tuple(f.stem for f in files))
