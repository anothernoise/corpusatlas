"""Adapter for the Architecture Radar entry list.

scorecards.json carries the scores; radar.json carries the *calls* — which ring
an entry sits in, in which edition, and every dated move between rings. That
history is the most defensible editorial data on the site and none of it was
reaching the graph.

A radar entry is its own document rather than an attribute of the technology it
names, because "Spark is Adopt" is a dated claim made in one edition and
"Spark" is not. Keeping them separate is what stops a 2026-Q3 ring leaking into
the graph as a timeless property of the technology.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..model import Document

# Where an entry's url points, and how the corpus ids documents under that
# prefix. The site's shape lives here in the adapter so the extractor never
# has to learn a URL layout.
DOC_PREFIXES = {
    "/architecture-radar/": "assessment:",
    "/blog/": "",
}


class RadarEntriesAdapter:
    def __init__(self, path: str, doc_prefixes: dict | None = None):
        self.path = Path(path)
        self.doc_prefixes = doc_prefixes or DOC_PREFIXES

    def _doc_id(self, url: str) -> str | None:
        for prefix, id_prefix in self.doc_prefixes.items():
            if url.startswith(prefix):
                return id_prefix + url[len(prefix):].strip("/")
        return None

    def documents(self):
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        edition = doc.get("edition")
        for e in doc.get("entries", []):
            sc = e.get("scorecard") or {}
            history = e.get("history", []) or []
            added = next((h["date"] for h in history if h.get("event") == "added"), None)
            yield Document(
                id=f"radar:{e['id']}",
                title=e["name"],
                url=e.get("url", ""),
                kind="radar-entry",
                date=added,
                meta={
                    "entry": e["id"],
                    "quadrant": e.get("quadrant"),
                    "ring": e.get("ring"),
                    "category": e.get("category"),
                    "reviewed": e.get("reviewed"),
                    "edition": edition,
                    # The scorecard join, when there is one: which assessment
                    # scored this entry and under which option names.
                    "assessment": sc.get("assessment"),
                    "options": list(sc.get("options") or []),
                    # The page that argues the call. Every entry has one.
                    "documented_in": self._doc_id(e.get("url", "")),
                    "history": history,
                },
            )
