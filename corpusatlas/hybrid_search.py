"""Hybrid search engine combining lexical BM25 and graph structural PPR via Reciprocal Rank Fusion (RRF).

Enables natural-language keyword lookup with semantic multi-hop expansion over knowledge graphs,
resolving queries even when exact canonical entity IDs are not provided.
Zero external dependencies (pure standard library).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any, Iterable

from .context import personalized_pagerank


def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase alphanumeric words."""
    return re.findall(r"\w+", text.lower())


class BM25Ranker:
    """Okapi BM25 implementation for lexical keyword search over graph entities."""

    def __init__(
        self,
        corpus: Iterable[tuple[str, str]],
        k1: float = 1.5,
        b: float = 0.75,
    ):
        self.k1 = k1
        self.b = b
        self.doc_ids: list[str] = []
        self.doc_lens: list[int] = []
        self.doc_freqs: dict[str, int] = Counter()
        self.doc_term_counts: list[Counter[str]] = []

        for doc_id, text in corpus:
            tokens = tokenize(text)
            self.doc_ids.append(doc_id)
            d_len = len(tokens)
            self.doc_lens.append(d_len)
            counts = Counter(tokens)
            self.doc_term_counts.append(counts)
            for term in counts:
                self.doc_freqs[term] += 1

        self.N = len(self.doc_ids)
        self.avg_doc_len = (sum(self.doc_lens) / self.N) if self.N > 0 else 1.0

        # Precompute IDF
        self.idf: dict[str, float] = {}
        for term, df in self.doc_freqs.items():
            # Standard Lucene/Okapi smoothed IDF
            self.idf[term] = math.log(1.0 + (self.N - df + 0.5) / (df + 0.5))

    def search(self, query: str, limit: int = 100) -> list[tuple[str, float]]:
        """Search corpus with query and return (doc_id, score) in descending order."""
        tokens = tokenize(query)
        if not tokens or self.N == 0:
            return []

        scores: list[float] = [0.0] * self.N

        for term in tokens:
            if term not in self.idf:
                continue
            term_idf = self.idf[term]
            for i, counts in enumerate(self.doc_term_counts):
                tf = counts.get(term, 0)
                if tf == 0:
                    continue
                d_len = self.doc_lens[i]
                numerator = tf * (self.k1 + 1.0)
                denominator = tf + self.k1 * (1.0 - self.b + self.b * (d_len / self.avg_doc_len))
                scores[i] += term_idf * (numerator / denominator)

        ranked = [
            (self.doc_ids[i], scores[i])
            for i in range(self.N)
            if scores[i] > 0.0
        ]
        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked[:limit]


def reciprocal_rank_fusion(
    rankings: list[list[str]],
    k: int = 60,
) -> list[tuple[str, float]]:
    """Combine multiple ranked lists of document IDs using Reciprocal Rank Fusion (RRF)."""
    scores: dict[str, float] = {}
    for r_list in rankings:
        for rank, doc_id in enumerate(r_list, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)

    sorted_scores = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    return sorted_scores


def hybrid_graph_search(
    graph_data: dict[str, Any],
    query: str,
    top_k: int = 15,
    k_rrf: int = 60,
) -> dict[str, Any]:
    """Execute hybrid BM25 + PPR search over knowledge graph."""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    if not nodes:
        return {"nodes": [], "edges": [], "counts": {"nodes": 0, "edges": 0}}

    nodes_by_id = {n["id"]: n for n in nodes}

    # 1. Build documents for BM25
    edge_explanations: dict[str, list[str]] = {}
    for e in edges:
        expl = e.get("explanation")
        if expl:
            edge_explanations.setdefault(e["src"], []).append(expl)
            edge_explanations.setdefault(e["dst"], []).append(expl)

    corpus: list[tuple[str, str]] = []
    for n in nodes:
        nid = n["id"]
        label = n.get("label", nid)
        aliases = " ".join(n.get("aliases", []))
        meta_texts = []
        for k, v in n.get("meta", {}).items():
            if isinstance(v, (str, int, float)):
                meta_texts.append(str(v))
        expls = " ".join(edge_explanations.get(nid, []))
        doc_text = f"{label} {aliases} {' '.join(meta_texts)} {expls}"
        corpus.append((nid, doc_text))

    bm25 = BM25Ranker(corpus)
    bm25_hits = bm25.search(query, limit=top_k * 2)
    bm25_ranked = [doc_id for doc_id, _ in bm25_hits]

    # 2. Build adjacency for graph traversal
    adj: dict[str, dict[str, float]] = {n["id"]: {} for n in nodes}
    for e in edges:
        src, dst = e["src"], e["dst"]
        if src in adj and dst in adj:
            conf = float(e.get("confidence", 1.0))
            adj[src][dst] = max(adj[src].get(dst, 0.0), conf)
            adj[dst][src] = max(adj[dst].get(src, 0.0), conf * 0.5)

    # 3. If BM25 found seeds, run PPR from top seed nodes
    ppr_ranked: list[str] = []
    if bm25_ranked:
        aggregated_ppr: dict[str, float] = {}
        for rank, seed_id in enumerate(bm25_ranked[:3]):
            weight = 1.0 / (rank + 1.0)
            single_ppr = personalized_pagerank(nodes, edges, seed_id=seed_id)
            for nid, ppr_val in single_ppr.items():
                aggregated_ppr[nid] = aggregated_ppr.get(nid, 0.0) + ppr_val * weight
        sorted_ppr = sorted(aggregated_ppr.items(), key=lambda kv: kv[1], reverse=True)
        ppr_ranked = [nid for nid, _ in sorted_ppr if nid in nodes_by_id]

    # 4. Fuse rankings
    rankings_to_fuse = []
    if bm25_ranked:
        rankings_to_fuse.append(bm25_ranked)
    if ppr_ranked:
        rankings_to_fuse.append(ppr_ranked)

    if not rankings_to_fuse:
        return {"nodes": [], "edges": [], "counts": {"nodes": 0, "edges": 0}}

    fused = reciprocal_rank_fusion(rankings_to_fuse, k=k_rrf)
    top_node_ids = set(doc_id for doc_id, _ in fused[:top_k])

    result_nodes = [nodes_by_id[nid] for nid in top_node_ids if nid in nodes_by_id]
    result_edges = [
        e for e in edges
        if e["src"] in top_node_ids and e["dst"] in top_node_ids
    ]

    return {
        "query": query,
        "nodes": result_nodes,
        "edges": result_edges,
        "counts": {"nodes": len(result_nodes), "edges": len(result_edges)},
    }
