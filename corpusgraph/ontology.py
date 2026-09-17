"""A closed ontology.

Open-vocabulary extraction over a technical corpus produces a swamp. Fixing the
types up front turns extraction into classification and — more usefully — lets
every triple be typechecked before it reaches the graph.

On the radar relations: a RadarEntry is a *dated call*, not a technology. The
ring and the edition live on that node and are never projected onto the
Technology it names, because "Spark is Adopt" was true of one edition and
"Spark" is not a thing that has a ring. Keeping the claim on its own node is
what lets a reader see when it was made, and what it was before.
"""
from __future__ import annotations

NODE_TYPES = {"Document", "Topic", "Technology", "Assessment", "RadarEntry"}

# relation -> (allowed source types, allowed target types)
RELATIONS: dict[str, tuple[set[str], set[str]]] = {
    "REFERENCES": ({"Document"}, {"Document"}),
    "ABOUT":      ({"Document"}, {"Topic"}),
    "ASSESSES":   ({"Assessment"}, {"Technology"}),
    "COMPARES_TO": ({"Technology"}, {"Technology"}),
    # An article covers a technology. Distinct from ABOUT, which points at a
    # subject: an article can be about "olap" while covering ClickHouse.
    "COVERS":     ({"Document"}, {"Technology"}),
    # The radar's dated calls, and the two things each one rests on.
    "HAS_RADAR_ENTRY": ({"Technology"}, {"RadarEntry"}),
    "ASSESSED_IN":     ({"RadarEntry"}, {"Assessment"}),
    "DOCUMENTED_IN":   ({"RadarEntry"}, {"Document", "Assessment"}),
}


def typecheck(rel: str, src_type: str, dst_type: str) -> bool:
    spec = RELATIONS.get(rel)
    if spec is None:
        return False
    allowed_src, allowed_dst = spec
    return src_type in allowed_src and dst_type in allowed_dst
