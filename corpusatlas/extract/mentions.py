"""The extracted tier: deterministic mention-matching against the graph's own
entity vocabulary — every entity the registry defines, and every entity a
pack declares.

This is deliberately NOT "NER or an LLM over prose". Nothing here calls a
model or touches the network, so `corpusatlas build` still runs on a laptop
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

from ..aho_corasick import AhoCorasick
from ..model import Document, Edge, Node
from ..ontology import DEFAULT, Ontology
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

    def __init__(self, vocabulary: list[Node], resolver: Resolver | None = None,
                 ontology: Ontology = DEFAULT):
        resolver = resolver or Resolver()
        self._ac_ci = AhoCorasick(case_sensitive=False)
        self._ac_cs = AhoCorasick(case_sensitive=True)
        self._registered_entities: set[str] = set()

        seen: set[str] = set()
        for n in vocabulary:
            if n.type not in ontology.entity_types or n.type in NOT_MENTIONED or n.id in seen:
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

            self._registered_entities.add(n.id)
            is_cs = bool(reg.get("case_sensitive"))
            ac = self._ac_cs if is_cs else self._ac_ci

            for f in forms:
                is_long = len(f) >= LONG
                ac.add_word(f, (n.id, is_long))

        self._ac_ci.build()
        self._ac_cs.build()

    def run(self, docs: list[Document]):
        edges: list[Edge] = []
        for d in docs:
            if d.kind != "article" or not d.text:
                continue
            prov = {"doc": d.id, "tier": self.tier, "extractor": self.name, "via": "mention"}

            # Collect matches per entity: (start, end, is_long)
            entity_matches: dict[str, list[tuple[int, int, bool]]] = {}

            # Scan with case-insensitive automaton
            for start, end, _, payload in self._ac_ci.find_matches(d.text, word_boundaries=True):
                eid, is_long = payload
                entity_matches.setdefault(eid, []).append((start, end, is_long))

            # Scan with case-sensitive automaton
            for start, end, _, payload in self._ac_cs.find_matches(d.text, word_boundaries=True):
                eid, is_long = payload
                entity_matches.setdefault(eid, []).append((start, end, is_long))

            # Filter candidates in deterministic order
            for eid in sorted(entity_matches.keys()):
                matches = entity_matches[eid]
                # Check if any long form matched
                has_long = any(is_long for _, _, is_long in matches)
                if has_long:
                    edges.append(Edge(d.id, "COVERS", eid, dict(prov)))
                    continue

                # Count non-overlapping occurrences for short forms
                # Sort by end position (greedy interval scheduling)
                matches.sort(key=lambda m: (m[1], m[0]))
                count = 0
                last_end = -1
                for start, end, _ in matches:
                    if start >= last_end:
                        count += 1
                        last_end = end
                if count >= 2:
                    edges.append(Edge(d.id, "COVERS", eid, dict(prov)))

        return [], edges
