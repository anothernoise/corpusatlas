"""Adapter for an Obsidian vault: a directory of markdown notes joined by
[[wikilinks]], the deterministic tier's favourite kind of source, since a
wikilink is a human choosing to connect two notes on purpose — exactly the
REFERENCES edge the deterministic tier exists to recover.

A note's id is its filename stem, not a slug of it — Obsidian's own link
resolution works the same way: `[[Apache Spark]]` names a note by its exact
title, and titles routinely have spaces and mixed case. `url` is a slug of
the title instead, since that field is meant to be a publishable path and
nothing downstream needs it to match the filename.

Frontmatter parsing is a hand-rolled subset of YAML — `key: value`,
`key: [a, b, c]`, and a `key:` header followed by `- item` lines — not a real
YAML parser. That covers how Obsidian itself writes frontmatter (tags,
aliases, dates) and most vaults never go further than that; a note with
nested maps or multi-line strings in its frontmatter will have that part
silently ignored rather than misparsed. Same crude-on-purpose bar as the web
adapter: good enough to join and mention-scan, not a spec-complete parser.

Vault-wide note titles are assumed unique. Obsidian itself allows two notes
with the same filename in different folders (resolved by configurable
link-resolution rules); this adapter does not replicate that — a duplicate
stem silently shadows an earlier one in wikilink resolution. Namespace your
notes if that matters to you.
"""
from __future__ import annotations

import re
from pathlib import Path

from ..cache import CacheBucket, hash_bytes
from ..model import Document
from ..resolve import slug

_FRONTMATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.S)
_LIST_ITEM = re.compile(r"^\s*-\s+(.*)$")
_KEY_VALUE = re.compile(r"^([A-Za-z_][\w-]*):\s*(.*)$")
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]+))?\]\]")
# A tag starts a word (not mid-token, so "see #2" and a hex colour in a code
# fence mostly don't match) and its first character is a letter, which is
# how Obsidian itself distinguishes a tag from an issue number.
_INLINE_TAG = re.compile(r"(?<!\S)#([A-Za-z][\w/-]*)")
_CODE_FENCE = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`[^`]*`")


def _parse_frontmatter(text: str) -> dict:
    out: dict[str, object] = {}
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = _KEY_VALUE.match(lines[i])
        if not m:
            i += 1
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith("[") and val.endswith("]"):
            out[key] = [v.strip().strip("\"'") for v in val[1:-1].split(",") if v.strip()]
        elif val:
            out[key] = val.strip("\"'")
        else:
            items, j = [], i + 1
            while j < len(lines):
                item = _LIST_ITEM.match(lines[j])
                if not item:
                    break
                items.append(item.group(1).strip().strip("\"'"))
                j += 1
            if items:
                out[key] = items
                i = j - 1
        i += 1
    return out


def _as_list(v) -> list[str]:
    if v is None:
        return []
    return list(v) if isinstance(v, list) else [v]


def split_frontmatter(raw: str) -> tuple[dict, str]:
    m = _FRONTMATTER.match(raw)
    if not m:
        return {}, raw
    return _parse_frontmatter(m.group(1)), raw[m.end():]


def wikilink_targets(body: str) -> list[tuple[str, str]]:
    """Every [[target]] as (raw target title, display text) — display falls
    back to the target when the link has no `|alias`."""
    out = []
    for m in _WIKILINK.finditer(body):
        target = m.group(1).strip()
        out.append((target, (m.group(2) or target).strip()))
    return out


def plain_text(body: str) -> str:
    """Readable prose for mention-scanning: code stripped (so a variable
    name in a fence can't look like an entity mention), wikilinks reduced to
    their display text, heading/emphasis markup removed."""
    s = _CODE_FENCE.sub(" ", body)
    s = _INLINE_CODE.sub(" ", s)
    s = _WIKILINK.sub(lambda m: (m.group(2) or m.group(1)).strip(), s)
    s = re.sub(r"^#{1,6}\s+", "", s, flags=re.M)
    s = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", s)
    return re.sub(r"\s+", " ", s).strip()


class ObsidianAdapter:
    def __init__(self, path: str, url_base: str = "/vault/", recursive: bool = True,
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
            # Wikilink resolution depends on which stems exist at all, not
            # just on any one file's own content — adding or removing a
            # note can change what an unchanged file's [[link]] resolves
            # to, so the fingerprint is the whole vault's file list.
            self._cache.enter(tuple(f.stem for f in files))

        for f in files:
            raw_bytes = f.read_bytes()
            content_hash = hash_bytes(raw_bytes)
            cached = self._cache.get(str(f), content_hash) if self._cache else None
            if cached is not None:
                yield cached
                continue

            raw = raw_bytes.decode("utf-8")
            fm, body = split_frontmatter(raw)
            title = fm.get("title") or f.stem

            tags = tuple(dict.fromkeys([
                *(t.lstrip("#") for t in _as_list(fm.get("tags"))),
                *_INLINE_TAG.findall(body),
            ]))

            links = set()
            for target, _ in wikilink_targets(body):
                # A wikilink may be folder-qualified ("Projects/My Pipeline")
                # when the vault has ambiguous filenames; by_title only ever
                # holds bare stems, so match on the link's own basename too.
                basename = target.rsplit("/", 1)[-1]
                resolved = by_title.get(target.lower()) or by_title.get(basename.lower())
                if resolved and resolved != f.stem:
                    links.add(resolved)

            date = fm.get("date") or fm.get("created")

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
