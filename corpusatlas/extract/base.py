"""The extractor seam.

Tier 1 (deterministic) ships today. Tier 2 (NER / LLM over prose) implements
this same protocol, and every edge records which tier produced it so a bad
model upgrade can never quietly poison the hand-authored layer.
"""
from __future__ import annotations

from typing import Iterable, Protocol

from ..model import Document, Edge, Node


class Extractor(Protocol):
    name: str
    tier: str  # "deterministic" | "extracted"

    def run(self, docs: list[Document]) -> tuple[Iterable[Node], Iterable[Edge]]:
        ...
