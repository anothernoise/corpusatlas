"""Native Obsidian Canvas (.canvas) and Markdown Vault exporter.

Converts CorpusAtlas knowledge graphs into native Obsidian interactive canvases and
bi-directionally linked Markdown note collections. Zero external dependencies.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


TYPE_CANVAS_COLORS: dict[str, str] = {
    "Technology": "1",  # Red / Orange in Canvas
    "Component": "2",   # Orange / Yellow
    "Pattern": "3",     # Yellow / Green
    "Concept": "4",     # Green
    "Protocol": "5",    # Cyan / Blue
    "Organization": "6",# Purple
}


def export_obsidian_canvas(
    graph_data: dict[str, Any],
    out_path: str | Path,
    node_width: int = 260,
    node_height: int = 120,
) -> dict[str, Any]:
    """Exports graph data as an Obsidian Canvas JSON file (.canvas)."""
    out_file = Path(out_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    raw_nodes = graph_data.get("nodes", [])
    raw_edges = graph_data.get("edges", [])

    canvas_nodes = []
    for i, node in enumerate(raw_nodes):
        node_id = str(node.get("id", f"node_{i}"))
        label = node.get("label", node_id)
        ntype = node.get("type", "Technology")
        meta = node.get("meta", {})
        summary = meta.get("summary") or meta.get("desc") or ""

        # Use 2D layout coordinates if available, otherwise grid layout
        x = int(node.get("x", (i % 6) * (node_width + 80)))
        y = int(node.get("y", (i // 6) * (node_height + 80)))

        text_content = f"### {label}\n**Type**: `{ntype}`"
        if summary:
            text_content += f"\n\n{summary}"

        canvas_nodes.append({
            "id": node_id,
            "x": x,
            "y": y,
            "width": node_width,
            "height": node_height,
            "type": "text",
            "text": text_content,
            "color": TYPE_CANVAS_COLORS.get(ntype, "1"),
        })

    canvas_edges = []
    for j, edge in enumerate(raw_edges):
        src = str(edge.get("src", ""))
        dst = str(edge.get("dst", ""))
        rel = str(edge.get("rel", "related_to"))
        if not src or not dst:
            continue

        canvas_edges.append({
            "id": f"edge_{j}_{src}_{dst}",
            "fromNode": src,
            "fromSide": "right",
            "toNode": dst,
            "toSide": "left",
            "label": rel,
        })

    canvas_doc = {
        "nodes": canvas_nodes,
        "edges": canvas_edges,
    }

    out_file.write_text(json.dumps(canvas_doc, indent=2), encoding="utf-8")
    return canvas_doc


def export_obsidian_vault(
    graph_data: dict[str, Any],
    vault_dir: str | Path,
) -> int:
    """Exports graph nodes as an Obsidian Markdown vault with YAML frontmatter and wikilinks."""
    vdir = Path(vault_dir)
    vdir.mkdir(parents=True, exist_ok=True)

    raw_nodes = graph_data.get("nodes", [])
    raw_edges = graph_data.get("edges", [])

    # Index outgoing and incoming relations per node
    outgoing: dict[str, list[dict[str, Any]]] = {n["id"]: [] for n in raw_nodes if "id" in n}
    incoming: dict[str, list[dict[str, Any]]] = {n["id"]: [] for n in raw_nodes if "id" in n}

    for edge in raw_edges:
        s, d, r = edge.get("src"), edge.get("dst"), edge.get("rel")
        if s in outgoing:
            outgoing[s].append(edge)
        if d in incoming:
            incoming[d].append(edge)

    for node in raw_nodes:
        nid = node.get("id")
        if not nid:
            continue
        label = node.get("label", nid)
        ntype = node.get("type", "Technology")
        meta = node.get("meta", {})
        summary = meta.get("summary", "")

        note_file = vdir / f"{nid}.md"
        lines = [
            "---",
            f"id: \"{nid}\"",
            f"title: \"{label}\"",
            f"type: \"{ntype}\"",
            "tags:",
            f"  - \"knowledge-graph\"",
            f"  - \"type/{ntype.lower()}\"",
        ]

        for k, v in meta.items():
            if isinstance(v, (str, int, float, bool)):
                lines.append(f"{k}: \"{v}\"")
        lines.append("---")
        lines.append("")
        lines.append(f"# {label}")
        lines.append("")
        if summary:
            lines.append(f"> {summary}")
            lines.append("")

        out_links = outgoing.get(nid, [])
        if out_links:
            lines.append("## Outgoing Relationships")
            for e in out_links:
                lines.append(f"- **{e.get('rel')}** -> [[{e.get('dst')}]]")
            lines.append("")

        in_links = incoming.get(nid, [])
        if in_links:
            lines.append("## Incoming References")
            for e in in_links:
                lines.append(f"- **{e.get('rel')}** <- [[{e.get('src')}]]")
            lines.append("")

        note_file.write_text("\n".join(lines), encoding="utf-8")

    return len(raw_nodes)
