"""The three types the whole pipeline agrees on.

Deliberately plain dataclasses: adapters, extractors and the merger all speak
these and nothing else, which is what lets an adapter be thirty lines.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

_EMPTY: tuple[object, ...] = (None, {}, (), [], "")


@dataclass(frozen=True)
class Document:
    """One unit of source material, normalised across every adapter."""
    id: str
    title: str
    url: str
    kind: str                      # article | assessment | radar-entry | entity-pack
    date: str | None = None
    text: str = ""
    tags: tuple[str, ...] = ()
    links: tuple[str, ...] = ()    # ids of other documents
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    type: str                      # one of ontology.NODE_TYPES
    url: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    aliases: tuple[str, ...] = ()
    urls: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in _EMPTY}


@dataclass(frozen=True)
class Edge:
    src: str
    rel: str
    dst: str
    prov: dict[str, Any] = field(default_factory=dict)
    # Only meaningful on editorial relations; see ontology.REQUIRES_SCOPE.
    scope: str | None = None
    confidence: float | None = None
    # Evidence for the claim, as URLs. prov["doc"] is who made the claim;
    # sources are what it rests on. They are different questions.
    sources: tuple[str, ...] = ()
    # Why the claim holds, in a sentence — shown on the edge card.
    explanation: str | None = None

    @property
    def key(self) -> tuple[str, str, str, str]:
        # Scope is part of identity. "Spark is an alternative to Flink" for
        # streaming and for batch are two claims, and dedupe must not merge them.
        # `or ""` rather than None keeps keys sortable.
        return (self.src, self.rel, self.dst, self.scope or "")

    def to_json(self) -> dict:
        # Empty fields are omitted, so a deterministic edge serialises exactly
        # as it did before scope and confidence existed.
        d = {"src": self.src, "rel": self.rel, "dst": self.dst,
             "scope": self.scope, "confidence": self.confidence,
             "sources": list(self.sources), "explanation": self.explanation, "prov": self.prov}
        return {k: v for k, v in d.items() if v not in _EMPTY}
