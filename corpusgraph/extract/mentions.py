"""The extracted tier: deterministic mention-matching against the graph's own
entity vocabulary — every entity the registry defines, and every entity a
pack declares.

This is deliberately NOT "NER or an LLM over prose". Nothing here calls a
model or touches the network, so `corpusgraph build` still runs on a laptop
with no API key and produces the same bytes every time. What it buys is
reach: an article that discusses Apache Spark at length but was never tagged
"spark" still gets linked to it, and the vocabulary grows every time the
registry or a pack gains an entity, with no code change here.

Conservative on purpose. Every claim is a word-boundary match, counted, and
kept only past a minimum-occurrence bar. Where a name is also an ordinary
word the registry narrows it: `case_sensitive` (Snowflake the product, not a
snowflake schema) and `mention_forms` (the exact spellings to look for). It
runs last, and merge()'s first-writer-wins means anything it re-derives that a
tag or a pack already established is superseded, never overridden.
"""
from __future__ import annotations

import re

from ..model import Document, Edge, Node
from ..ontology import ENTITY_TYPES
from ..resolve import Resolver

# A company named in passing is not a subject the article covers — "runs on
# Google Cloud" says nothing about Google — so companies are never searched.
NOT_MENTIONED = {"Company"}

# Long names are distinctive enough on their own; short ones are not.
MIN_LEN = 5   # shortest form searched at all (acronyms excepted)
LONG = 10     # a form this long counts after a single hit
# A label like "Resilient distributed dataset (RDD)" yields two more searchable
# forms: the acronym people actually write, and the label without it. Neither
# is guessed — both come from what someone already wrote as the name.
_PAREN = re.compile(r"\(([^()]{2,20})\)\s*$")


def _trusted(form: str) -> bool:
    # A short all-caps token ("RDD", "SQL", "MCP") is an acronym someone wrote
    # down on purpose, so it is safe at any length; an ordinary short word is
    # exactly what a word-boundary match cannot be trusted on.
    return (form.isupper() and 2 <= len(form) <= 6) or len(form) >= MIN_LEN


def surface_forms(label: str) -> set[str]:
    forms = {label}
    m = _PAREN.search(label)
    if m:
        forms.add(m.group(1))
        forms.add(label[:m.start()].strip())
    return forms


class MentionsExtractor:
    name = "mentions@2"
    tier = "extracted"

    def __init__(self, vocabulary: list[Node], resolver: Resolver | None = None):
        resolver = resolver or Resolver()
        # One compiled pattern per entity, built once, so a few hundred
        # articles scan in a second or two.
        self._entries: list[tuple[str, re.Pattern, int]] = []
        seen: set[str] = set()
        for n in vocabulary:
            if n.type not in ENTITY_TYPES or n.type in NOT_MENTIONED or n.id in seen:
                continue
            seen.add(n.id)
            reg = resolver.entity(n.id) or {}
            if reg.get("mention_forms"):
                forms = set(reg["mention_forms"])
            else:
                forms = set()
                for label in (n.label, *n.aliases):
                    forms |= surface_forms(label)
            forms = {f for f in forms if _trusted(f)}
            if not forms:
                continue
            flags = 0 if reg.get("case_sensitive") else re.IGNORECASE
            # Judged per form, not per entity: one hit on a long, distinctive
            # name ("Amazon EMR") is a claim, but a short alias of the same
            # entity ("EMR") has to show up twice on its own merits.
            long_forms = {f for f in forms if len(f) >= LONG}
            self._entries.append((n.id, _pattern(long_forms, flags), _pattern(forms, flags)))
        self._entries.sort(key=lambda x: x[0])

    def run(self, docs: list[Document]):
        edges: list[Edge] = []
        for d in docs:
            if d.kind != "article" or not d.text:
                continue
            prov = {"doc": d.id, "tier": self.tier, "extractor": self.name, "via": "mention"}
            for eid, long_pattern, any_pattern in self._entries:
                if (long_pattern and long_pattern.search(d.text)) or len(any_pattern.findall(d.text)) >= 2:
                    edges.append(Edge(d.id, "COVERS", eid, dict(prov)))
        return [], edges


def _pattern(forms: set[str], flags: int) -> re.Pattern | None:
    if not forms:
        return None
    alternatives = "|".join(re.escape(f) for f in sorted(forms, key=lambda f: (-len(f), f)))
    return re.compile(r"(?<![\w-])(?:" + alternatives + r")(?![\w-])", flags)
