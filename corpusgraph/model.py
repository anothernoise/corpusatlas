"""The three types the whole pipeline agrees on.

Deliberately plain dataclasses: adapters, extractors and the merger all speak
these and nothing else, which is what lets an adapter be thirty lines.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(frozen=True)
class Document:
    """One unit of source material, normalised across every adapter."""
    id: str
    title: str
    url: str
    kind: str                      # article | assessment | book-chapter | note
    date: str | None = None
    text: str = ""
    tags: tuple[str, ...] = ()
    links: tuple[str, ...] = ()    # ids of other documents
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    type: str                      # Document | Topic | Technology | Assessment
    url: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, {}, ())}


@dataclass(frozen=True)
class Edge:
    src: str
    rel: str
    dst: str
    prov: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.src, self.rel, self.dst)

    def to_json(self) -> dict:
        return {"src": self.src, "rel": self.rel, "dst": self.dst, "prov": self.prov}
