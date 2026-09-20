"""Sub-Graph Role-Based Access Control (RBAC) & Node Redaction Engine.

Enables policy-driven redaction of sensitive nodes, edges, and metadata attributes based on
declarative access tiers (e.g., public vs internal vs confidential vs restricted).
Zero external runtime dependencies.
"""
from __future__ import annotations

import copy
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_VISIBILITY = "internal"

# Standard clearance hierarchy: public (1) < internal (2) < confidential (3) < restricted (4)
CLEARANCE_LEVELS: dict[str, int] = {
    "public": 1,
    "internal": 2,
    "confidential": 3,
    "restricted": 4,
}


@dataclass(frozen=True)
class RBACPolicy:
    """Security policy defining user roles and allowed visibility levels."""
    roles: dict[str, dict[str, Any]] = field(default_factory=lambda: {
        "public": {
            "clearance": 1,
            "allowed_visibilities": {"public"},
            "mask_attributes": {"email", "internal_url", "revenue", "owner_secret"},
        },
        "internal": {
            "clearance": 2,
            "allowed_visibilities": {"public", "internal"},
            "mask_attributes": {"owner_secret"},
        },
        "admin": {
            "clearance": 4,
            "allowed_visibilities": {"public", "internal", "confidential", "restricted"},
            "mask_attributes": set(),
        },
    })

    @classmethod
    def from_toml(cls, path: str | Path) -> "RBACPolicy":
        content = Path(path).read_text(encoding="utf-8")
        doc = tomllib.loads(content)
        raw_roles = doc.get("roles", {})
        parsed_roles = {}
        for role_name, role_cfg in raw_roles.items():
            parsed_roles[role_name] = {
                "clearance": role_cfg.get("clearance", 1),
                "allowed_visibilities": set(role_cfg.get("allowed_visibilities", ["public"])),
                "mask_attributes": set(role_cfg.get("mask_attributes", [])),
            }
        return cls(roles=parsed_roles)


def get_element_visibility(element: dict[str, Any]) -> str:
    """Extracts visibility label from an element or its metadata."""
    if "visibility" in element:
        return str(element["visibility"]).lower()
    meta = element.get("meta", {})
    if isinstance(meta, dict) and "visibility" in meta:
        return str(meta["visibility"]).lower()
    return DEFAULT_VISIBILITY


def redact_graph_by_role(
    graph_data: dict[str, Any],
    role: str = "public",
    policy: RBACPolicy | None = None,
    drop_dangling_edges: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Filters and redacts graph nodes, edges, and attributes based on role clearance."""
    pol = policy or RBACPolicy()
    role_cfg = pol.roles.get(role)
    if not role_cfg:
        # Fallback to strictest policy (public)
        role_cfg = pol.roles.get("public", {
            "clearance": 1,
            "allowed_visibilities": {"public"},
            "mask_attributes": set(),
        })

    allowed_vis = role_cfg.get("allowed_visibilities", {"public"})
    mask_attrs = role_cfg.get("mask_attributes", set())

    raw_nodes = graph_data.get("nodes", [])
    raw_edges = graph_data.get("edges", [])

    filtered_nodes: list[dict[str, Any]] = []
    retained_node_ids: set[str] = set()
    redacted_nodes_count = 0

    for node in raw_nodes:
        vis = get_element_visibility(node)
        if vis in allowed_vis:
            # Clone and mask sensitive attributes
            clean_node = copy.deepcopy(node)
            meta = clean_node.get("meta", {})
            if isinstance(meta, dict):
                for attr in mask_attrs:
                    if attr in meta:
                        del meta[attr]
            filtered_nodes.append(clean_node)
            retained_node_ids.add(str(node.get("id", "")))
        else:
            redacted_nodes_count += 1

    filtered_edges: list[dict[str, Any]] = []
    redacted_edges_count = 0

    for edge in raw_edges:
        vis = get_element_visibility(edge)
        src = str(edge.get("src", ""))
        dst = str(edge.get("dst", ""))

        # Check edge visibility
        if vis not in allowed_vis:
            redacted_edges_count += 1
            continue

        # Check dangling edge status
        if drop_dangling_edges:
            if src not in retained_node_ids or dst not in retained_node_ids:
                redacted_edges_count += 1
                continue

        filtered_edges.append(copy.deepcopy(edge))

    redacted_graph = copy.deepcopy(graph_data)
    redacted_graph["nodes"] = filtered_nodes
    redacted_graph["edges"] = filtered_edges

    audit_report = {
        "role": role,
        "allowed_visibilities": sorted(allowed_vis),
        "initial_nodes_count": len(raw_nodes),
        "retained_nodes_count": len(filtered_nodes),
        "redacted_nodes_count": redacted_nodes_count,
        "initial_edges_count": len(raw_edges),
        "retained_edges_count": len(filtered_edges),
        "redacted_edges_count": redacted_edges_count,
    }

    return redacted_graph, audit_report
