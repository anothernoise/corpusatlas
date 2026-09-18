"""Adapter for the Architecture Radar scorecards.

The richest deterministic source on the site: typed entities (technologies),
typed relations (assessed-by, compared-with) and scores, all hand-authored.
Exactly the "structured data you already publish" case — no extraction needed.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..model import Document


class RadarScorecardsAdapter:
    def __init__(self, path: str):
        self.path = Path(path)

    def documents(self):
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        for slug, a in doc.get("assessments", {}).items():
            platforms = list(a.get("platforms", {}))
            yield Document(
                id=f"assessment:{slug}",
                title=a.get("title", slug),
                url=a.get("url", f"/architecture-radar/{slug}"),
                kind="assessment",
                date=a.get("published"),
                text=a.get("use_case", ""),
                meta={
                    "platforms": platforms,
                    "target": a.get("target"),
                    "category": a.get("category"),
                    "reviewed": a.get("reviewed"),
                    "verdict": a.get("verdict"),
                },
            )
