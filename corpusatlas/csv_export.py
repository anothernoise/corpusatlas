"""Convert a built graph.json to a nodes.csv / edges.csv pair.

Same shape as graphml.py: a converter over the shipped artifact, not a
second emitter. The point of CSV over GraphML is reach, not fidelity — pandas,
a spreadsheet, a BI tool, `csv.reader` in five other languages — so this
keeps the same lean column set (see graphml.py) rather than trying to be the
complete record; graph.json still is that.

Uses the stdlib csv module rather than joining strings by hand: several
explanations already in this ecosystem's own entity packs contain literal
commas and double quotes, and getting quoting right by hand is exactly the
kind of thing that looks fine on the happy path and corrupts a row later.
"""
from __future__ import annotations

import csv
from pathlib import Path

NODE_FIELDS = ("id", "label", "type", "degree", "url")
EDGE_FIELDS = ("src", "rel", "dst", "confidence", "explanation", "scope")


def write_csv(out_dir: Path, graph: dict) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    nodes_path = out_dir / "nodes.csv"
    edges_path = out_dir / "edges.csv"

    with nodes_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(NODE_FIELDS)
        for n in graph["nodes"]:
            w.writerow([n.get(field, "") if n.get(field) is not None else "" for field in NODE_FIELDS])

    with edges_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(EDGE_FIELDS)
        for e in graph["edges"]:
            w.writerow([e.get(field, "") if e.get(field) is not None else "" for field in EDGE_FIELDS])

    return nodes_path, edges_path
