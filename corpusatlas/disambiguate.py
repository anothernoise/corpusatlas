"""Context-aware entity disambiguation for ambiguous names/homographs.

Resolves polysemous or shared mention forms (e.g. "Spark", "Apple", "Python")
by computing Jaccard/cosine overlap between document context words and
candidate entity profile keywords/types.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

_TOKEN_RE = re.compile(r"[a-z0-9_-]{3,}")


def tokenize(text: str) -> set[str]:
    """Extract lowercase tokens for bag-of-words similarity."""
    return set(_TOKEN_RE.findall(text.lower()))


class ContextDisambiguator:
    """Disambiguates candidate entities based on surrounding document context."""

    def __init__(self, candidates: Iterable[dict[str, Any]]):
        """Each candidate is expected to have:
        - id: str
        - type: str
        - keywords: list[str] or description: str
        """
        self._profiles: dict[str, set[str]] = {}
        for c in candidates:
            cid = c["id"]
            tokens = set()
            if "description" in c:
                tokens |= tokenize(c["description"])
            if "keywords" in c and isinstance(c["keywords"], list):
                for kw in c["keywords"]:
                    tokens |= tokenize(kw)
            if "type" in c:
                tokens.add(c["type"].lower())
            if "aliases" in c and isinstance(c["aliases"], (list, tuple)):
                for a in c["aliases"]:
                    tokens |= tokenize(a)
            self._profiles[cid] = tokens

    def disambiguate(
        self,
        candidate_ids: list[str],
        doc_text: str,
        threshold: float = 0.05,
    ) -> tuple[str | None, float]:
        """Return the best matching candidate_id and its score, or (None, 0.0) if below threshold."""
        if not candidate_ids:
            return None, 0.0
        if len(candidate_ids) == 1:
            return candidate_ids[0], 1.0

        doc_tokens = tokenize(doc_text)
        if not doc_tokens:
            return candidate_ids[0], 0.0

        best_id: str | None = None
        best_score = -1.0

        for cid in candidate_ids:
            profile = self._profiles.get(cid, set())
            if not profile:
                score = 0.0
            else:
                inter = len(doc_tokens & profile)
                union = len(doc_tokens | profile)
                score = inter / union if union > 0 else 0.0

            if score > best_score:
                best_score = score
                best_id = cid

        if best_score < threshold:
            return None, best_score

        return best_id, best_score
