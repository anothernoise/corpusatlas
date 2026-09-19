"""Convert a built graph.json to Neo4j's bulk-import CSV format.

Same shape as graphml.py and csv_export.py: a converter over the shipped
artifact, not a second emitter, with the same lean column set (label, type,
degree, url on a node; confidence, explanation, scope on a relationship) —
graph.json stays the complete record.

The difference from the plain nodes.csv/edges.csv pair is the header
convention: Neo4j's own `:ID`, `:LABEL`, `:START_ID`, `:END_ID` and `:TYPE`
column-name suffixes, so the output loads directly with `neo4j-admin
database import full` — no column-mapping step first. A node's `type`
becomes its Neo4j label (`(:Technology {...})`), and an edge's `rel` becomes
its relationship type (`[:IMPLEMENTS]`), which is how you'd actually want to
query this once it's in Neo4j.
"""
from __future__ import annotations

import csv
from pathlib import Path

NODE_HEADER = ("id:ID", "label", ":LABEL", "degree:int", "url")
REL_HEADER = (":START_ID", ":END_ID", ":TYPE", "confidence:float", "explanation", "scope")


def write_neo4j_csv(out_dir: Path, graph: dict) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes_path = out_dir / "neo4j_nodes.csv"
    rels_path = out_dir / "neo4j_relationships.csv"

    with nodes_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(NODE_HEADER)
        for n in graph["nodes"]:
            w.writerow([n["id"], n.get("label") or "", n.get("type") or "",
                       n.get("degree") or 0, n.get("url") or ""])

    with rels_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(REL_HEADER)
        for e in graph["edges"]:
            confidence = e.get("confidence")
            w.writerow([e["src"], e["dst"], e["rel"],
                       confidence if confidence is not None else "",
                       e.get("explanation") or "", e.get("scope") or ""])

    return nodes_path, rels_path
