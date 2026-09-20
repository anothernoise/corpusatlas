"""Pagefind static chunked search index exporter.

Generates semantic HTML entity pages annotated with data-pagefind-* attributes,
enabling static sites to index graph entities, relations, descriptions, and ontology
filters with zero runtime servers.
"""
from __future__ import annotations

import html
import shutil
from pathlib import Path
from typing import Any, Dict, List


def _slugify(val: str) -> str:
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in val).strip("_")


def generate_pagefind_pages(
    graph: dict[str, Any],
    out_dir: Path | str,
    clean: bool = False
) -> int:
    """Generates Pagefind-ready static HTML documents for every entity node in graph.

    Returns the number of generated HTML pages.
    """
    out_path = Path(out_dir)
    if clean and out_path.exists():
        shutil.rmtree(out_path)
    out_path.mkdir(parents=True, exist_ok=True)

    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])

    # Index outbound and inbound edges per node
    out_edges: dict[str, list[dict]] = {}
    in_edges: dict[str, list[dict]] = {}
    for e in edges:
        s = e.get("src")
        d = e.get("dst")
        if s:
            out_edges.setdefault(s, []).append(e)
        if d:
            in_edges.setdefault(d, []).append(e)

    node_labels = {n["id"]: n.get("label", n["id"]) for n in nodes}

    count = 0
    for node in nodes:
        nid = node["id"]
        label = html.escape(str(node.get("label") or nid))
        ntype = html.escape(str(node.get("type") or "Entity"))
        desc = html.escape(str((node.get("meta") or {}).get("description") or ""))
        aliases = node.get("aliases") or []
        urls = node.get("urls") or {}

        # Build relations section
        rel_lines = []
        for e in out_edges.get(nid, []):
            dst_label = html.escape(node_labels.get(e.get("dst", ""), e.get("dst", "")))
            rel = html.escape(e.get("rel", ""))
            exp = html.escape(e.get("explanation") or "")
            rel_lines.append(f'<li><strong>{rel}</strong> &rarr; {dst_label}' + (f': <em>{exp}</em>' if exp else '') + '</li>')

        for e in in_edges.get(nid, []):
            src_label = html.escape(node_labels.get(e.get("src", ""), e.get("src", "")))
            rel = html.escape(e.get("rel", ""))
            exp = html.escape(e.get("explanation") or "")
            rel_lines.append(f'<li>{src_label} &rarr; <strong>{rel}</strong>' + (f': <em>{exp}</em>' if exp else '') + '</li>')

        relations_html = f"<ul>{''.join(rel_lines)}</ul>" if rel_lines else "<p>No relations recorded.</p>"

        # External URLs
        url_links = []
        for key, u in urls.items():
            if u:
                url_links.append(f'<a href="{html.escape(str(u))}">{html.escape(key)}</a>')
        urls_html = " &middot; ".join(url_links)

        # Aliases string
        alias_str = html.escape(", ".join(str(a) for a in aliases))

        doc_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title data-pagefind-meta="title">{label}</title>
  <meta name="description" content="{desc or label}">
</head>
<body data-pagefind-body>
  <article>
    <header>
      <h1 data-pagefind-meta="title">{label}</h1>
      <span data-pagefind-filter="type:{ntype}">Type: {ntype}</span>
      <span data-pagefind-filter="kind:entity">Entity</span>
      {f'<p class="aliases"><strong>Aliases:</strong> {alias_str}</p>' if alias_str else ''}
    </header>
    {f'<section class="description"><p>{desc}</p></section>' if desc else ''}
    <section class="relations">
      <h2>Relationships</h2>
      {relations_html}
    </section>
    {f'<footer class="links"><p>{urls_html}</p></footer>' if urls_html else ''}
  </article>
</body>
</html>
"""
        file_slug = _slugify(nid)
        file_path = out_path / f"{file_slug}.html"
        file_path.write_text(doc_html, encoding="utf-8")
        count += 1

    return count
