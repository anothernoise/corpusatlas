"""Declarative SHACL-style constraint validator for knowledge graph shapes and invariants.

Validates property presence, domain/range constraints, degree bounds, and cardinality
before publishing or deploying graphs. Zero external dependencies.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass
class NodeShape:
    """Constraints on nodes matching target_type."""

    target_type: str
    required_properties: list[str] = field(default_factory=list)
    min_degree: int | None = None
    max_degree: int | None = None
    regex_patterns: dict[str, str] = field(default_factory=dict)


@dataclass
class EdgeShape:
    """Constraints on edges matching rel."""

    rel: str
    source_type: str | None = None
    target_type: str | None = None
    min_count: int | None = None  # min out-edges of this type per source
    max_count: int | None = None  # max out-edges of this type per source
    min_confidence: float | None = None


class ShapeValidator:
    """Evaluates node and edge shape constraints against graph data."""

    def __init__(
        self,
        node_shapes: Iterable[NodeShape] = (),
        edge_shapes: Iterable[EdgeShape] = (),
    ):
        self.node_shapes = list(node_shapes)
        self.edge_shapes = list(edge_shapes)

    def validate_nodes(self, nodes: list[dict[str, Any]]) -> dict[str, Any]:
        """Validate nodes against configured NodeShapes."""
        violations: list[dict[str, Any]] = []

        for n in nodes:
            nid = n.get("id", "unknown")
            ntype = n.get("type")

            for shape in self.node_shapes:
                if shape.target_type and shape.target_type != ntype:
                    continue

                # Check required properties
                for prop in shape.required_properties:
                    val = n.get(prop)
                    if val is None or (isinstance(val, (str, list, dict)) and len(val) == 0):
                        violations.append({
                            "focus_node": nid,
                            "type": ntype,
                            "shape": shape.target_type,
                            "property": prop,
                            "message": f"Node '{nid}' of type '{ntype}' is missing required property '{prop}'",
                        })

                # Check degree
                degree = n.get("degree")
                if degree is not None:
                    if shape.min_degree is not None and degree < shape.min_degree:
                        violations.append({
                            "focus_node": nid,
                            "type": ntype,
                            "shape": shape.target_type,
                            "message": f"Node '{nid}' degree {degree} is below min_degree {shape.min_degree}",
                        })
                    if shape.max_degree is not None and degree > shape.max_degree:
                        violations.append({
                            "focus_node": nid,
                            "type": ntype,
                            "shape": shape.target_type,
                            "message": f"Node '{nid}' degree {degree} exceeds max_degree {shape.max_degree}",
                        })

                # Check regex patterns
                for prop, pattern in shape.regex_patterns.items():
                    val = str(n.get(prop, ""))
                    if not re.search(pattern, val):
                        violations.append({
                            "focus_node": nid,
                            "type": ntype,
                            "shape": shape.target_type,
                            "property": prop,
                            "message": f"Node '{nid}' property '{prop}' value '{val}' does not match pattern '{pattern}'",
                        })

        return {
            "conforms": len(violations) == 0,
            "violations": violations,
            "violation_count": len(violations),
        }

    def validate_edges(
        self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Validate edges against domain, range, and cardinality constraints."""
        nodes_by_id = {n["id"]: n for n in nodes}
        violations: list[dict[str, Any]] = []

        # Count per (src, rel) for cardinality checks
        rel_counts_per_src: dict[tuple[str, str], int] = defaultdict(int)

        for e in edges:
            src_id = e["src"]
            dst_id = e["dst"]
            rel = e["rel"]
            rel_counts_per_src[(src_id, rel)] += 1

            src_node = nodes_by_id.get(src_id)
            dst_node = nodes_by_id.get(dst_id)

            for shape in self.edge_shapes:
                if shape.rel != rel:
                    continue

                # Domain check (source type)
                if shape.source_type and src_node:
                    if src_node.get("type") != shape.source_type:
                        violations.append({
                            "edge": (src_id, rel, dst_id),
                            "message": f"Edge '{src_id} -[{rel}]-> {dst_id}' source type '{src_node.get('type')}' does not match required source type '{shape.source_type}'",
                        })

                # Range check (target type)
                if shape.target_type and dst_node:
                    if dst_node.get("type") != shape.target_type:
                        violations.append({
                            "edge": (src_id, rel, dst_id),
                            "message": f"Edge '{src_id} -[{rel}]-> {dst_id}' target type '{dst_node.get('type')}' does not match required target type '{shape.target_type}'",
                        })

                # Min confidence check
                conf = e.get("confidence")
                if conf is not None and shape.min_confidence is not None:
                    if float(conf) < shape.min_confidence:
                        violations.append({
                            "edge": (src_id, rel, dst_id),
                            "message": f"Edge '{src_id} -[{rel}]-> {dst_id}' confidence {conf} is below minimum {shape.min_confidence}",
                        })

        # Cardinality checks
        for shape in self.edge_shapes:
            if shape.max_count is not None:
                for (src_id, rel), count in rel_counts_per_src.items():
                    if rel == shape.rel and count > shape.max_count:
                        violations.append({
                            "focus_node": src_id,
                            "rel": rel,
                            "message": f"Node '{src_id}' has {count} '{rel}' edges, exceeding max_count {shape.max_count}",
                        })

        return {
            "conforms": len(violations) == 0,
            "violations": violations,
            "violation_count": len(violations),
        }

    def validate_graph(self, graph_data: dict[str, Any]) -> dict[str, Any]:
        """Run full shape validation across nodes and edges."""
        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])

        node_report = self.validate_nodes(nodes)
        edge_report = self.validate_edges(nodes, edges)

        all_violations = node_report["violations"] + edge_report["violations"]
        return {
            "conforms": len(all_violations) == 0,
            "violations": all_violations,
            "violation_count": len(all_violations),
        }
