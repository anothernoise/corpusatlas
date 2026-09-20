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

from .model import Document, Edge, Node


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

    def __init__(self, path: Path | None, fine_grained: bool = False):
        self.path = path
        self.fine_grained = fine_grained
        self.hits = 0
        self.misses = 0
        self._lock = threading.Lock()
        self._data: dict[str, Any] = {}
        if path is not None and path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def bucket(self, key: str, fine_grained: bool | None = None) -> CacheBucket:
        fg = self.fine_grained if fine_grained is None else fine_grained
        return CacheBucket(self, key, self._data.get(key) or {}, fine_grained=fg)

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

    def __init__(self, cache: BuildCache, key: str, raw: dict, fine_grained: bool = False):
        self._cache = cache
        self._key = key
        self._prev_fingerprint = tuple(raw.get("fingerprint", ()))
        self._prev_files: dict[str, dict] = raw.get("files", {})
        self._new_files: dict[str, dict] = {}
        self._valid = False
        self.fine_grained = fine_grained

    def enter(self, fingerprint: tuple[str, ...]) -> None:
        """Call once per `documents()` run, before reading any file — this
        source's cache is only consulted at all if `fingerprint` (its own
        choice: file ids, an index page's hash, whatever else matters)
        matches exactly what the previous run recorded."""
        self._valid = fingerprint == self._prev_fingerprint

    def get(self, path: str, content_hash: str) -> Document | None:
        if not self._valid and not self.fine_grained:
            self._cache._record_miss()
            return None
        entry = self._prev_files.get(path)
        if not entry or entry.get("hash") != content_hash:
            self._cache._record_miss()
            return None
        self._cache._record_hit()
        self._new_files[path] = entry
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


class MerkleDAGCache:
    """Fine-grained Merkle-DAG cache for extractor tier claims.

    Tracks SHA256 hashes of input document contents, schema versions,
    and output claims (nodes & edges) to bypass extractor re-execution
    on unchanged documents.
    """

    def __init__(self, path: Path | None = None):
        self.path = path
        self._entries: dict[str, dict[str, Any]] = {}
        if path is not None and path.exists():
            try:
                self._entries = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._entries = {}

    def _claim_key(self, doc_id: str, doc_hash: str, tier_name: str) -> str:
        h = hashlib.sha256(f"{doc_id}:{doc_hash}:{tier_name}".encode("utf-8")).hexdigest()
        return f"{doc_id}:{h}"

    def get_claims(
        self, doc_id: str, doc_hash: str, tier_name: str
    ) -> tuple[list[dict], list[dict]] | None:
        key = self._claim_key(doc_id, doc_hash, tier_name)
        entry = self._entries.get(key)
        if entry:
            return entry.get("nodes", []), entry.get("edges", [])
        return None

    def put_claims(
        self,
        doc_id: str,
        doc_hash: str,
        tier_name: str,
        nodes: list[dict],
        edges: list[dict],
    ) -> None:
        key = self._claim_key(doc_id, doc_hash, tier_name)
        # Compute leaf Merkle hash over claims
        claims_bytes = json.dumps({"nodes": nodes, "edges": edges}, sort_keys=True).encode("utf-8")
        leaf_hash = hashlib.sha256(claims_bytes).hexdigest()
        self._entries[key] = {
            "doc_id": doc_id,
            "doc_hash": doc_hash,
            "tier": tier_name,
            "merkle_leaf": leaf_hash,
            "nodes": nodes,
            "edges": edges,
        }

    def compute_merkle_root(self) -> str:
        """Compute the Merkle tree root hash across all cached document claims."""
        if not self._entries:
            return hashlib.sha256(b"empty").hexdigest()

        # Sort leaves deterministically
        leaves = [
            e.get("merkle_leaf", "")
            for _, e in sorted(self._entries.items(), key=lambda kv: kv[0])
        ]
        curr = [bytes.fromhex(l) for l in leaves if l]
        if not curr:
            return hashlib.sha256(b"empty").hexdigest()

        while len(curr) > 1:
            next_level = []
            for i in range(0, len(curr), 2):
                left = curr[i]
                right = curr[i + 1] if i + 1 < len(curr) else left
                parent = hashlib.sha256(left + right).digest()
                next_level.append(parent)
            curr = next_level

        return curr[0].hex()

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self._entries, sort_keys=True, indent=2), encoding="utf-8")


def document_hash(doc: Document) -> str:
    payload = f"{doc.id}\0{doc.kind}\0{doc.url}\0{doc.date or ''}\0{doc.text}\0{','.join(doc.tags)}\0{','.join(doc.links)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def run_extractor_cached(
    extractor: Any,
    docs: list[Document],
    merkle: MerkleDAGCache | None = None
) -> tuple[list[Node], list[Edge], int, int]:
    """Run an extractor over documents, caching per-document claims in MerkleDAGCache.
    Returns (nodes, edges, hits, misses).
    """
    if merkle is None:
        out_n, out_e = extractor.run(docs)
        return list(out_n), list(out_e), 0, len(docs)

    hits = 0
    misses = 0
    cached_nodes: dict[str, Node] = {}
    cached_edges: dict[tuple, Edge] = {}

    all_cached = True
    for doc in docs:
        d_hash = document_hash(doc)
        cached = merkle.get_claims(doc.id, d_hash, extractor.name)
        if cached is None:
            all_cached = False
            break

    if all_cached and docs:
        for doc in docs:
            d_hash = document_hash(doc)
            cached = merkle.get_claims(doc.id, d_hash, extractor.name)
            if not cached:
                continue
            raw_nodes, raw_edges = cached
            for nd in raw_nodes:
                n = Node(
                    id=nd["id"],
                    label=nd.get("label", nd["id"]),
                    type=nd.get("type", "Technology"),
                    url=nd.get("url"),
                    meta=nd.get("meta", {}),
                    aliases=tuple(nd.get("aliases", ())),
                    urls=nd.get("urls", {})
                )
                cached_nodes[n.id] = n
            for ed in raw_edges:
                e = Edge(
                    src=ed["src"],
                    rel=ed["rel"],
                    dst=ed["dst"],
                    prov=ed.get("prov", {}),
                    scope=ed.get("scope"),
                    confidence=ed.get("confidence"),
                    sources=tuple(ed.get("sources", ())),
                    explanation=ed.get("explanation")
                )
                cached_edges[e.key] = e
            hits += 1
        return list(cached_nodes.values()), list(cached_edges.values()), hits, 0

    # Otherwise, execute extractor over full docs to maintain cross-document join integrity
    out_nodes, out_edges = extractor.run(docs)
    node_list = list(out_nodes)
    edge_list = list(out_edges)

    doc_edges: dict[str, list[Edge]] = {d.id: [] for d in docs}
    for e in edge_list:
        doc_id = e.prov.get("doc")
        if doc_id and doc_id in doc_edges:
            doc_edges[doc_id].append(e)

    for doc in docs:
        d_hash = document_hash(doc)
        merkle.put_claims(
            doc.id,
            d_hash,
            extractor.name,
            [n.to_json() for n in node_list if n.id == doc.id or n.type != "Document"],
            [e.to_json() for e in doc_edges.get(doc.id, [])]
        )
        misses += 1

    return node_list, edge_list, hits, misses


