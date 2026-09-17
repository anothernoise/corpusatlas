"""Adapter for curated entity packs.

A pack is a reviewed JSON file describing one technology: its concepts,
components, capabilities, alternatives and the pages that discuss it. Drafted
offline with a model, corrected and signed by a human, committed as a file.

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
    def __init__(self, path: str, url_base: str = "", include_drafts: bool = False):
        self.path = Path(path)
        self.url_base = url_base
        # A pack nobody has signed is a model's draft, and the whole point of
        # this tier is that a person stands behind every claim in it. Drafts
        # stay out of the published graph unless explicitly asked for, which
        # is what a local preview of an unreviewed pack does.
        self.include_drafts = include_drafts

    def documents(self):
        for f in sorted(self.path.glob("*.json")):
            if f.name.endswith(".schema.json"):
                continue
            pack = json.loads(f.read_text(encoding="utf-8"))
            authored = pack.get("authored", {})
            signed = bool(authored.get("reviewed") and authored.get("reviewed_by"))
            if not signed and not self.include_drafts:
                continue
            target = pack.get("target", {})
            yield Document(
                id=f"pack:{f.stem}",
                title=f"Entity pack: {target.get('label', f.stem)}",
                url=f"{self.url_base}{f.name}",
                kind="entity-pack",
                date=authored.get("reviewed"),
                meta={"pack": pack},
            )
