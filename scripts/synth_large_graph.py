#!/usr/bin/env python3
"""Builds a synthetic graph.json with many real entity-to-entity edges
(not context edges, which the viewer never draws — see its own "Entities
only" filter), for stress-testing the reference viewer at a node count no
real consumer has hit yet. Bypasses the adapter/extraction pipeline
entirely since only the shape of the artifact matters here, not how it
was produced.

    python3 scripts/synth_large_graph.py 5000 out.json
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.emit import write_graph
from corpusatlas.model import Node, Edge
from corpusatlas.ontology import DEFAULT

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("synthetic_graph.json")
EDGES_PER_NODE = 3

random.seed(0)  # reproducible

nodes = {}
for i in range(N):
    nid = f"entity:synthetic-{i}"
    nodes[nid] = Node(id=nid, label=f"Synthetic Entity {i}", type="Technology")

edges = []
seen = set()
for i in range(N):
    src = f"entity:synthetic-{i}"
    for _ in range(EDGES_PER_NODE):
        j = random.randrange(N)
        dst = f"entity:synthetic-{j}"
        if dst == src:
            continue
        key = tuple(sorted((src, dst)))
        if key in seen:
            continue
        seen.add(key)
        edges.append(Edge(src=src, rel="COMPARES_TO", dst=dst,
                          prov={"doc": "synthetic", "tier": "curated", "extractor": "synthetic"}))

write_graph(OUT, nodes, edges, sources=[f"synthetic ({N})"], ontology=DEFAULT)
print(f"wrote {OUT}: {len(nodes)} nodes, {len(edges)} edges")
