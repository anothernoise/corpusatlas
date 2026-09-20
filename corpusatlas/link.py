"""Wikidata and remote taxonomy entity linker.

Enriches local knowledge graph entities with canonical Wikidata QIDs, descriptions,
and global semantic web URIs using the Wikidata search API.
Zero external dependencies (pure standard library urllib).
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Callable


def default_wikidata_fetcher(query: str, limit: int = 3) -> list[dict[str, Any]]:
    """Search Wikidata for candidate entities via REST API."""
    params = urllib.parse.urlencode({
        "action": "wbsearchentities",
        "search": query,
        "language": "en",
        "format": "json",
        "limit": limit,
    })
    url = f"https://www.wikidata.org/w/api.php?{params}"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "CorpusAtlas-EntityLinker/0.9.0 (https://corpusatlas.org)"},
    )

    try:
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("search", [])
    except Exception:
        return []


def link_entity_to_wikidata(
    node: dict[str, Any],
    fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
) -> dict[str, Any] | None:
    """Attempt to link a single node to its canonical Wikidata entity."""
    query = node.get("label", node.get("id", ""))
    if not query:
        return None

    run_fetch = fetcher or default_wikidata_fetcher
    candidates = run_fetch(query)

    if not candidates:
        return None

    # Pick top candidate
    top = candidates[0]
    qid = top.get("id")
    if not qid:
        return None

    updated = dict(node)
    updated["wikidata_id"] = qid
    if "description" in top:
        updated["wikidata_desc"] = top["description"]

    urls = dict(updated.get("urls", {}))
    urls["wikidata"] = f"http://www.wikidata.org/entity/{qid}"
    updated["urls"] = urls
    return updated


def annotate_graph_with_wikidata(
    graph_data: dict[str, Any],
    fetcher: Callable[[str], list[dict[str, Any]]] | None = None,
    max_nodes: int = 100,
) -> dict[str, Any]:
    """Annotate knowledge graph nodes with Wikidata QIDs."""
    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    new_nodes: list[dict[str, Any]] = []
    linked_count = 0

    for idx, n in enumerate(nodes):
        if idx < max_nodes and n.get("type") != "Document":
            linked = link_entity_to_wikidata(n, fetcher=fetcher)
            if linked is not None:
                new_nodes.append(linked)
                linked_count += 1
                continue
        new_nodes.append(dict(n))

    updated = dict(graph_data)
    updated["nodes"] = new_nodes
    updated["wikidata_linked_count"] = linked_count
    return updated
