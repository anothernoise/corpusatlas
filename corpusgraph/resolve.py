"""Entity resolution: many written forms, one node id.

Without this every producer invents its own spelling and the graph quietly
grows two nodes for one thing. The table is deliberately small — slugging
handles the ordinary cases, so an entry here is an admission that a name is
genuinely ambiguous and a human had to decide.
"""
from __future__ import annotations

import tomllib
from pathlib import Path


def slug(s: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in s)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


class Resolver:
    """Maps a written form to a canonical node id.

    Three lookup kinds, because the same string means different things
    depending on where it was read:

    ``tech``   A platform or product name, as written in a scorecard or in
               prose. Falls back to slugging, so only awkward spellings need
               a table entry and the common case costs nothing.

    ``radar``  A radar entry id. Table-only, deliberately: an entry names a
               technology only when the table says which one, because half of
               them name practices ("Eval-driven development") that have no
               technology behind them at all.

    ``tag``    A controlled-vocabulary tag. Table-only for the same reason —
               "olap" is a subject and "spark" is a technology, and nothing in
               either string says which. Guessing here is how a tag vocabulary
               turns into a fake product catalogue.
    """

    def __init__(self, entities=()):
        self._label: dict[str, str] = {}
        self._tech: dict[str, str] = {}
        self._radar: dict[str, str] = {}
        self._tag: dict[str, str] = {}
        for e in entities:
            canon = e["canonical"]
            self._label[canon] = e.get("label", canon.split(":", 1)[-1])
            # The canonical id resolves to itself, so a producer can hand back
            # whatever it was given without checking which form it holds.
            self._tech[slug(canon.split(":", 1)[-1])] = canon
            for a in e.get("aliases", ()):
                self._tech[slug(a)] = canon
            for r in e.get("radar", ()):
                self._radar[r] = canon
            for t in e.get("tags", ()):
                self._tag[t] = canon

    @classmethod
    def from_config(cls, cfg: dict) -> "Resolver":
        path = (cfg.get("ontology") or {}).get("aliases")
        if not path:
            return cls()
        doc = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        return cls(doc.get("entity", []))

    def resolve(self, raw: str, kind: str = "tech") -> str | None:
        if kind == "tech":
            s = slug(raw)
            return self._tech.get(s, f"tech:{s}") if s else None
        if kind == "radar":
            return self._radar.get(raw)
        if kind == "tag":
            return self._tag.get(raw)
        raise ValueError(f"unknown resolution kind {kind!r}")

    def label(self, node_id: str) -> str | None:
        return self._label.get(node_id)
