"""Optional on-disk cache of parsed Documents, keyed by content hash — lets
a rebuild skip re-parsing files that haven't changed. Opt-in only: no
`--cache` path, no behaviour change from any build before this existed.

Deliberately scoped to the file-reading adapters (`html_blog`, `obsidian`,
`logseq`): that's where the real cost sits on a large corpus — regex-driven
HTML/markdown parsing over every file, every build, whether or not it
changed. Extraction itself (deterministic/packs/mentions, over the full
Document set) is never cached — it's fast, pure computation, and it has to
see every document at once anyway to dedupe entities and resolve wikilinks
correctly, so there is nothing incremental to safely gain there.

Correctness over cleverness. A cached file is only trusted if the whole
source's *fingerprint* — every file id currently in it, plus anything else
that could change what an unchanged file resolves to (an index page's tags,
for instance) — matches what produced the cache. One added, removed or
renamed file anywhere in a source invalidates every entry for that source,
not just the file that changed: coarse, but it means a stale cache can never
silently miss a case where one file's change should have affected another's
(a new note a dangling wikilink now resolves to, a re-tagged index page). A
build with `--cache` is allowed to be no faster than expected; it must never
be allowed to be wrong. See docs/DESIGN.md.
"""
from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .model import Document


def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BuildCache:
    """The whole on-disk cache: one JSON file, one independent bucket per
    adapter source (keyed by the caller's own choice of string, e.g.
    "html_blog:/abs/path/to/blog" — distinct sources never collide as long
    as the key does).

    A single BuildCache is shared across every source in a build, and
    `cmd_build` may run those sources' adapters concurrently (one thread per
    source) — each source's own CacheBucket is only ever touched by the one
    thread running that source, but the hit/miss counters and the on-disk
    `_data` dict are genuinely shared, hence the lock."""

    def __init__(self, path: Path | None):
        self.path = path
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        if path is not None and path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def bucket(self, key: str) -> CacheBucket:
        return CacheBucket(self, key, self._data.get(key) or {})

    def _record_hit(self) -> None:
        with self._lock:
            self.hits += 1

    def _record_miss(self) -> None:
        with self._lock:
            self.misses += 1

    def _commit_bucket(self, key: str, raw: dict) -> None:
        with self._lock:
            self._data[key] = raw

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._data, sort_keys=True), encoding="utf-8")


class CacheBucket:
    """One adapter source's slice of the cache: per-file content hash and
    serialised Document, guarded by a fingerprint covering everything else
    that run's documents could have depended on."""

    def __init__(self, cache: BuildCache, key: str, raw: dict):
        self._cache = cache
        self._key = key
        self._prev_fingerprint = tuple(raw.get("fingerprint", ()))
        self._prev_files: dict[str, dict] = raw.get("files", {})
        self._new_files: dict[str, dict] = {}
        self._valid = False

    def enter(self, fingerprint: tuple[str, ...]) -> None:
        """Call once per `documents()` run, before reading any file — this
        source's cache is only consulted at all if `fingerprint` (its own
        choice: file ids, an index page's hash, whatever else matters)
        matches exactly what the previous run recorded."""
        self._valid = fingerprint == self._prev_fingerprint

    def get(self, path: str, content_hash: str) -> Document | None:
        if not self._valid:
            self._cache._record_miss()
            return None
        entry = self._prev_files.get(path)
        if not entry or entry.get("hash") != content_hash:
            self._cache._record_miss()
            return None
        self._cache._record_hit()
        data = dict(entry["document"])
        data["tags"] = tuple(data.get("tags") or ())
        data["links"] = tuple(data.get("links") or ())
        return Document(**data)

    def put(self, path: str, content_hash: str, document: Document) -> None:
        self._new_files[path] = {"hash": content_hash, "document": asdict(document)}

    def commit(self, fingerprint: tuple[str, ...]) -> None:
        """Call once, after every document for this source has been
        produced — this run's fingerprint and file table become what the
        next run is checked against."""
        self._cache._commit_bucket(self._key, {
            "fingerprint": list(fingerprint),
            "files": self._new_files,
        })
