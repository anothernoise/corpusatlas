"""Inference engine for corpusatlas.
Extracts latent relationships (co-occurrence and taxonomy) from document corpora.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def infer_cooccurrence(nodes: list[dict[str, Any]],
                       edges: list[dict[str, Any]],
                       threshold: float = 0.5,
                       min_docs: int = 2) -> list[dict[str, Any]]:
    """Infers CO_OCCURS_WITH relationships between entities based on Jaccard document overlap."""
    # Map entity id -> set of documents it appears in
    entity_docs: dict[str, set[str]] = defaultdict(set)

    for e in edges:
        doc = e.get("doc")
        if doc:
            entity_docs[e["src"]].add(doc)
            entity_docs[e["dst"]].add(doc)

    for n in nodes:
        nid = n.get("id")
        if not nid:
            continue
        # Document references may also be in meta or url
        meta = n.get("meta") or {}
        if isinstance(meta, dict) and "doc" in meta:
            entity_docs[nid].add(str(meta["doc"]))
        if "url" in n and n["url"]:
            entity_docs[nid].add(str(n["url"]))

    # Existing edge pairs to avoid duplicate inferences
    existing_pairs = set()
    for e in edges:
        s, d = e.get("src"), e.get("dst")
        if s and d:
            existing_pairs.add((s, d))
            existing_pairs.add((d, s))

    entities = [n["id"] for n in nodes if n.get("id") and n["id"] in entity_docs]
    inferred: list[dict[str, Any]] = []

    for i in range(len(entities)):
        u = entities[i]
        docs_u = entity_docs[u]
        if not docs_u:
            continue
        for j in range(i + 1, len(entities)):
            v = entities[j]
            docs_v = entity_docs[v]
            if not docs_v:
                continue

            shared = docs_u & docs_v
            if len(shared) < min_docs:
                continue

            union = docs_u | docs_v
            jaccard = len(shared) / len(union) if union else 0.0

            if jaccard >= threshold and (u, v) not in existing_pairs:
                doc_list = sorted(list(shared))[:3]
                doc_str = ", ".join(doc_list) + ("..." if len(shared) > 3 else "")
                inferred.append({
                    "src": u,
                    "rel": "CO_OCCURS_WITH",
                    "dst": v,
                    "tier": "inferred",
                    "confidence": round(jaccard, 2),
                    "explanation": f"Co-occurs in {len(shared)} documents: {doc_str}",
                })

    return inferred
