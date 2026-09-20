"""The extractor seam.

Three tiers ship today, each implementing this protocol: deterministic
(author-authored structure), curated (entity packs) and extracted
(mention-matching against the graph's own vocabulary, deliberately not NER or
an LLM over prose — see mentions.py). Every edge records which tier produced
it so a future model-based extractor can never quietly poison the
hand-authored layers that ran before it.
"""
from __future__ import annotations

from typing import Iterable, Protocol

from ..model import Document, Edge, Node


class Extractor(Protocol):
    name: str
    tier: str  # one of ontology.TIERS: "deterministic" | "curated" | "extracted"

    def run(self, docs: list[Document]) -> tuple[Iterable[Node], Iterable[Edge]]:
        ...
