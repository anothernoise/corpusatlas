"""Adapter for curated entity packs.

A pack is a JSON file describing one subject — its entities and the typed
relationships between them — in the extraction-spec format. Packs are drafted
offline, and every link and citation in them is machine-checked by
knowledge-base/validate_packs.py before a build.

Each pack is yielded as a Document. That is the whole trick: retraction,
provenance and the "every edge names its document" rule all key on document
ids, so a pack gets all three for free — delete the file and every claim it
made leaves the graph on the next build.
"""
from __future__ import annotations

import json
from pathlib import Path

from ..model import Document


class EntityPacksAdapter:
    def __init__(self, path: str, url_base: str = ""):
        self.path = Path(path)
        self.url_base = url_base

    def documents(self):
        for f in sorted(self.path.glob("*.json")):
            if f.name.endswith(".schema.json"):
                continue
            pack = json.loads(f.read_text(encoding="utf-8"))
            subject = pack.get("subject", {})
            yield Document(
                id=f"pack:{f.stem}",
                title=f"Entity pack: {subject.get('name', f.stem)}",
                url=f"{self.url_base}{f.name}",
                kind="entity-pack",
                date=(pack.get("authored") or {}).get("drafted"),
                meta={"pack": pack},
            )
