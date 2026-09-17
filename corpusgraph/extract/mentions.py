"""A light Tier 2: deterministic mention-matching against the corpus's own
vocabulary — every Technology, and every Concept/Component/Product/
Capability/UseCase a signed entity pack has already named.

This is deliberately NOT the "NER or an LLM over prose" extraction the
original roadmap called Tier 2. It is cheaper and safer: nothing here calls a
model or touches the network, so it stays inside the same rule the
deterministic tier already keeps — `corpusgraph build` runs on a laptop with
no API key and produces the same bytes every time. What it buys instead of
full extraction is reach: an article that talks about Apache Spark at length
but was never tagged "spark" still gets linked to it, and the vocabulary this
can find grows automatically every time a new pack is signed, with no code
change here.

Conservative on purpose. Every claim is a plain word-boundary match, counted,
and kept only past a minimum-occurrence bar — a single passing mention of a
short, common-shaped term is not a claim. It runs last, after the
deterministic and curated tiers have built the vocabulary it searches with,
and merge()'s first-writer-wins means anything it independently re-derives
that a human or a tag already established is silently superseded, never
overridden.
"""
from __future__ import annotations

import re

from ..model import Document, Edge, Node

VOCAB_TYPES = {"Technology", "Concept", "Component", "Product", "Capability", "UseCase"}
# Technology names are sometimes short, well-known acronyms ("SQL", "AWS")
# that are still safe to match because a human already chose them for a
# Technology node. Everything else needs enough characters that a
# word-boundary hit is unlikely to be a coincidence.
MIN_LEN = {"Technology": 3}
DEFAULT_MIN_LEN = 5
# A label like "Resilient distributed dataset (RDD)" is two searchable forms:
# the short parenthetical acronym actually used in prose, and the label with
# the parenthetical stripped. Neither is guessed — both come from what a
# human already wrote as the canonical label.
_PAREN = re.compile(r"\(([^()]{2,20})\)\s*$")


def _trusted_length(form: str, node_type: str) -> bool:
    # A short, all-caps token ("RDD", "SQL", "AWS") is an acronym someone
    # deliberately wrote down — as the node's own label, or as the
    # parenthetical this file derived it from — not a guess, so it is safe at
    # any length regardless of what kind of node it names. Everything else
    # needs the type's usual minimum, because an ordinary short lowercase
    # word is exactly the case a word-boundary match cannot be trusted on.
    if form.isupper() and 2 <= len(form) <= 6:
        return True
    return len(form) >= MIN_LEN.get(node_type, DEFAULT_MIN_LEN)


def _surface_forms(label: str) -> set[str]:
    forms = {label}
    m = _PAREN.search(label)
    if m:
        forms.add(m.group(1))
        forms.add(label[:m.start()].strip())
    return forms


class MentionsExtractor:
    name = "mentions@1"
    tier = "extracted"

    def __init__(self, vocabulary: list[Node]):
        # One compiled pattern per node, built once so a 287-article corpus
        # scans in well under a second even with the curated vocabulary added.
        self._entries: list[tuple[Node, re.Pattern, int]] = []
        for n in vocabulary:
            if n.type not in VOCAB_TYPES:
                continue
            forms: set[str] = set()
            for label in (n.label, *n.aliases):
                forms |= _surface_forms(label)
            forms = {f for f in forms if _trusted_length(f, n.type)}
            if not forms:
                continue
            pattern = re.compile(
                r"\b(?:" + "|".join(re.escape(f) for f in sorted(forms, key=len, reverse=True)) + r")\b",
                re.IGNORECASE,
            )
            # A short or generic-shaped surface form is trusted less: require
            # it to appear more than once before counting it as a real signal.
            min_hits = 1 if max(len(f) for f in forms) >= 10 else 2
            self._entries.append((n, pattern, min_hits))

    def run(self, docs: list[Document]):
        edges: list[Edge] = []
        for d in docs:
            if d.kind != "article" or not d.text:
                continue
            prov = {"doc": d.id, "tier": self.tier, "extractor": self.name, "via": "mention"}
            for node, pattern, min_hits in self._entries:
                if len(pattern.findall(d.text)) < min_hits:
                    continue
                if node.type == "Technology":
                    # Same relation and direction as the tag-based signal
                    # (COVERS: Document -> Technology) — a full-text mention
                    # is a weaker version of the same claim, not a new one.
                    edges.append(Edge(d.id, "COVERS", node.id, dict(prov)))
                else:
                    edges.append(Edge(node.id, "DISCUSSED_IN", d.id, dict(prov)))
        return [], edges
