"""MinHash and Locality-Sensitive Hashing (LSH) for fuzzy entity resolution and deduplication.

Enables zero-dependency blocking and clustering of duplicate entity candidates before
or after graph build to prevent knowledge graph fragmentation from typographical variations.
Zero external dependencies.
"""
from __future__ import annotations

import random
import re
from collections import defaultdict
from typing import Any, Iterable


_MERSENNE_PRIME = 2147483647  # 2^31 - 1


def _generate_hash_params(num_perm: int, seed: int = 42) -> tuple[list[int], list[int]]:
    """Generate deterministic pseudo-random coefficients (a, b) for universal hashing."""
    rng = random.Random(seed)
    a = [rng.randint(1, _MERSENNE_PRIME - 1) for _ in range(num_perm)]
    b = [rng.randint(0, _MERSENNE_PRIME - 1) for _ in range(num_perm)]
    return a, b


def _str_to_hash(s: str) -> int:
    """Compute 32-bit FNV-1a hash of string."""
    h = 2166136261
    for char in s.encode("utf-8"):
        h = ((h ^ char) * 16777619) & 0x7FFFFFFF
    return h


def get_shingles(text: str, k: int = 3) -> set[str]:
    """Extract character k-shingles from normalized text."""
    clean = re.sub(r"\s+", " ", text.lower().strip())
    if len(clean) < k:
        return {clean}
    return {clean[i : i + k] for i in range(len(clean) - k + 1)}


class MinHash:
    """MinHash signature representation."""

    def __init__(self, num_perm: int = 64, digest: list[int] | None = None):
        self.num_perm = num_perm
        self.a, self.b = _generate_hash_params(num_perm)
        self.digest = digest if digest is not None else [_MERSENNE_PRIME] * num_perm

    @classmethod
    def from_text(cls, text: str, k: int = 3, num_perm: int = 64) -> MinHash:
        shingles = get_shingles(text, k=k)
        mh = cls(num_perm=num_perm)
        mh.update(shingles)
        return mh

    def update(self, tokens: Iterable[str]) -> None:
        """Update digest with tokens."""
        for token in tokens:
            x = _str_to_hash(token)
            for i in range(self.num_perm):
                val = (self.a[i] * x + self.b[i]) % _MERSENNE_PRIME
                if val < self.digest[i]:
                    self.digest[i] = val

    def jaccard(self, other: MinHash) -> float:
        """Estimate Jaccard similarity between two MinHash signatures."""
        if self.num_perm != other.num_perm:
            raise ValueError("MinHash signatures must have the same number of permutations")
        matches = sum(1 for x, y in zip(self.digest, other.digest) if x == y)
        return matches / self.num_perm


class LSHIndex:
    """Locality-Sensitive Hashing index for fast nearest-neighbor candidate pairing."""

    def __init__(self, num_perm: int = 64, num_bands: int = 16):
        if num_perm % num_bands != 0:
            raise ValueError("num_perm must be divisible by num_bands")
        self.num_perm = num_perm
        self.num_bands = num_bands
        self.rows_per_band = num_perm // num_bands
        # (band_idx, band_hash) -> list of doc_ids
        self.buckets: dict[tuple[int, tuple[int, ...]], list[str]] = defaultdict(list)
        self.signatures: dict[str, MinHash] = {}

    def insert(self, doc_id: str, minhash: MinHash) -> None:
        self.signatures[doc_id] = minhash
        for band in range(self.num_bands):
            start = band * self.rows_per_band
            end = start + self.rows_per_band
            band_key = tuple(minhash.digest[start:end])
            self.buckets[(band, band_key)].append(doc_id)

    def query_candidates(self) -> set[tuple[str, str]]:
        """Find all candidate collision pairs across all bands."""
        candidates = set()
        for bucket in self.buckets.values():
            if len(bucket) > 1:
                for i in range(len(bucket)):
                    for j in range(i + 1, len(bucket)):
                        pair = (min(bucket[i], bucket[j]), max(bucket[i], bucket[j]))
                        candidates.add(pair)
        return candidates


def find_duplicate_candidates(
    nodes: list[dict[str, Any]],
    threshold: float = 0.6,
    num_perm: int = 64,
    num_bands: int = 16,
) -> list[dict[str, Any]]:
    """Scan nodes and find duplicate entity candidates based on MinHash LSH similarity."""
    lsh = LSHIndex(num_perm=num_perm, num_bands=num_bands)

    for n in nodes:
        nid = n["id"]
        label = n.get("label", nid)
        aliases = " ".join(n.get("aliases", []))
        text = f"{label} {aliases}"
        mh = MinHash.from_text(text, num_perm=num_perm)
        lsh.insert(nid, mh)

    candidates = lsh.query_candidates()
    duplicates: list[dict[str, Any]] = []

    for id_a, id_b in candidates:
        mh_a = lsh.signatures[id_a]
        mh_b = lsh.signatures[id_b]
        sim = mh_a.jaccard(mh_b)
        if sim >= threshold:
            duplicates.append({
                "node_a": id_a,
                "node_b": id_b,
                "estimated_jaccard": round(sim, 4),
            })

    duplicates.sort(key=lambda x: x["estimated_jaccard"], reverse=True)
    return duplicates


def merge_duplicate_entities(
    graph_data: dict[str, Any],
    merge_pairs: list[tuple[str, str]],
) -> dict[str, Any]:
    """Merge duplicate entities into canonical nodes and repoint relationships."""
    canonical_map: dict[str, str] = {}
    for canonical, duplicate in merge_pairs:
        canonical_map[duplicate] = canonical

    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    # Merge nodes
    new_nodes_by_id: dict[str, dict[str, Any]] = {}
    for n in nodes:
        nid = n["id"]
        if nid in canonical_map:
            canon_id = canonical_map[nid]
            if canon_id in new_nodes_by_id:
                # Merge aliases
                existing_aliases = set(new_nodes_by_id[canon_id].get("aliases", []))
                existing_aliases.update(n.get("aliases", []))
                existing_aliases.add(n.get("label", nid))
                new_nodes_by_id[canon_id]["aliases"] = sorted(list(existing_aliases))
            continue
        new_nodes_by_id[nid] = dict(n)

    # Repoint edges
    new_edges: list[dict[str, Any]] = []
    seen_edge_keys = set()

    for e in edges:
        src = canonical_map.get(e["src"], e["src"])
        dst = canonical_map.get(e["dst"], e["dst"])
        if src == dst:
            continue  # Avoid self-loops introduced by merging

        key = (src, e["rel"], dst)
        if key not in seen_edge_keys:
            seen_edge_keys.add(key)
            edge_copy = dict(e)
            edge_copy["src"] = src
            edge_copy["dst"] = dst
            new_edges.append(edge_copy)

    updated = dict(graph_data)
    updated["nodes"] = list(new_nodes_by_id.values())
    updated["edges"] = new_edges
    updated["counts"] = {
        "nodes": len(updated["nodes"]),
        "edges": len(updated["edges"]),
    }
    return updated
