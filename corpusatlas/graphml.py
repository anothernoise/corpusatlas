"""Convert a built graph.json to GraphML, for Gephi, yEd, NetworkX or igraph.

Reads the artifact, not the internal Node/Edge dataclasses — this is a
converter over the shipped format, not a second emitter bolted onto the
build. Any graph.json this module ever wrote, old or new, can be converted;
nothing here re-runs extraction.

Deliberately lean: label, type and degree on a node; rel, confidence,
explanation and scope on an edge. Everything else in the artifact (urls,
aliases, meta, provenance) stays in graph.json — GraphML readers expect a
flat, typed attribute table, not nested JSON, and most of it is application
detail Gephi has no use for anyway.
"""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

_NS = "http://graphml.graphdrawing.org/xmlns"
ET.register_namespace("", _NS)

# (id, for, attr.name, attr.type)
_KEYS = [
    ("nlabel", "node", "label", "string"),
    ("ntype", "node", "type", "string"),
    ("ndegree", "node", "degree", "int"),
    ("nurl", "node", "url", "string"),
    ("erel", "edge", "rel", "string"),
    ("econfidence", "edge", "confidence", "double"),
    ("eexplanation", "edge", "explanation", "string"),
    ("escope", "edge", "scope", "string"),
]


def _data(parent, key, value):
    if value in (None, ""):
        return
    d = ET.SubElement(parent, f"{{{_NS}}}data", {"key": key})
    d.text = str(value)


def write_graphml(path: Path, graph: dict) -> None:
    root = ET.Element(f"{{{_NS}}}graphml")
    for key_id, for_, name, type_ in _KEYS:
        ET.SubElement(root, f"{{{_NS}}}key", {
            "id": key_id, "for": for_, "attr.name": name, "attr.type": type_,
        })

    g = ET.SubElement(root, f"{{{_NS}}}graph", {"id": "G", "edgedefault": "directed"})

    for n in graph["nodes"]:
        node_el = ET.SubElement(g, f"{{{_NS}}}node", {"id": n["id"]})
        _data(node_el, "nlabel", n.get("label"))
        _data(node_el, "ntype", n.get("type"))
        _data(node_el, "ndegree", n.get("degree"))
        _data(node_el, "nurl", n.get("url"))

    for e in graph["edges"]:
        edge_el = ET.SubElement(g, f"{{{_NS}}}edge", {"source": e["src"], "target": e["dst"]})
        _data(edge_el, "erel", e.get("rel"))
        _data(edge_el, "econfidence", e.get("confidence"))
        _data(edge_el, "eexplanation", e.get("explanation"))
        _data(edge_el, "escope", e.get("scope"))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    path.parent.mkdir(parents=True, exist_ok=True)
    body = ET.tostring(root, encoding="unicode")
    path.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n{body}\n', encoding="utf-8")
