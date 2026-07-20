"""A closed ontology.

Open-vocabulary extraction over a technical corpus produces a swamp. Fixing the
types up front turns extraction into classification and — more usefully — lets
every triple be typechecked before it reaches the graph.
"""
from __future__ import annotations

NODE_TYPES = {"Document", "Topic", "Technology", "Assessment"}

# relation -> (allowed source types, allowed target types)
RELATIONS: dict[str, tuple[set[str], set[str]]] = {
    "REFERENCES": ({"Document"}, {"Document"}),
    "ABOUT":      ({"Document"}, {"Topic"}),
    "ASSESSES":   ({"Assessment"}, {"Technology"}),
    "COMPARES_TO": ({"Technology"}, {"Technology"}),
    "COVERS":     ({"Document"}, {"Technology"}),
}


def typecheck(rel: str, src_type: str, dst_type: str) -> bool:
    spec = RELATIONS.get(rel)
    if spec is None:
        return False
    allowed_src, allowed_dst = spec
    return src_type in allowed_src and dst_type in allowed_dst
