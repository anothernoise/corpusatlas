"""Zero-dependency REST API daemon for CorpusAtlas knowledge graphs.

Provides an HTTP interface for searching nodes, filtering edges, extracting
Graph RAG contexts, running topological audits, and retrieving graph stats.
"""
from __future__ import annotations

import hashlib
import json
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from . import __version__
from .audit import audit_graph
from .context import extract_rag_subgraph, format_rag_markdown
from .hybrid_search import hybrid_graph_search


class GraphAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler routing REST endpoints for a loaded knowledge graph."""

    # Set by the server factory
    graph_data: dict[str, Any] = {}
    nodes_by_id: dict[str, dict[str, Any]] = {}
    outbound_edges: dict[str, list[dict[str, Any]]] = {}
    inbound_edges: dict[str, list[dict[str, Any]]] = {}
    graph_etag: str = ""

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr logging during normal operation."""
        return

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")

    def do_OPTIONS(self) -> None:
        """Handle CORS preflight requests."""
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _send_json(self, status: int, data: Any, check_etag: bool = False) -> None:
        raw_body = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
        if check_etag:
            etag = self.graph_etag
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self._send_cors_headers()
                self.end_headers()
                return

        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw_body)))
        if check_etag:
            self.send_header("ETag", self.graph_etag)
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw_body)

    def _send_text(self, status: int, text: str, content_type: str = "text/plain") -> None:
        raw_body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(raw_body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(raw_body)

    def do_GET(self) -> None:
        """Dispatch incoming GET requests."""
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        # 1. Health & Root Info
        if path == "":
            res = {
                "status": "ok",
                "service": "corpusatlas",
                "version": __version__,
                "counts": self.graph_data.get("counts", {
                    "nodes": len(self.nodes_by_id),
                    "edges": sum(len(e) for e in self.outbound_edges.values()),
                }),
                "metadata": {k: v for k, v in self.graph_data.items() if k not in ("nodes", "edges")},
            }
            self._send_json(200, res, check_etag=True)
            return

        # 2. Stats endpoint
        if path == "/stats":
            stats = {
                "nodes": len(self.nodes_by_id),
                "edges": sum(len(e) for e in self.outbound_edges.values()),
                "entity_types": self.graph_data.get("entity_types", []),
            }
            type_counts: dict[str, int] = {}
            for n in self.nodes_by_id.values():
                t = n.get("type", "Unknown")
                type_counts[t] = type_counts.get(t, 0) + 1
            stats["types"] = type_counts
            self._send_json(200, stats)
            return

        # 3. Nodes endpoint: /nodes or /nodes/<id>
        if path == "/nodes":
            q = query.get("query", [""])[0].lower()
            t_filter = query.get("type", [None])[0]
            limit = int(query.get("limit", [100])[0])
            offset = int(query.get("offset", [0])[0])

            matched = []
            for nid, n in self.nodes_by_id.items():
                if t_filter and n.get("type") != t_filter:
                    continue
                if q:
                    label = n.get("label", nid).lower()
                    aliases = " ".join(n.get("aliases", [])).lower()
                    if q not in nid.lower() and q not in label and q not in aliases:
                        continue
                matched.append(n)

            paginated = matched[offset: offset + limit]
            self._send_json(200, paginated)
            return

        if path.startswith("/nodes/"):
            node_id = urllib.parse.unquote(path[len("/nodes/"):])
            node = self.nodes_by_id.get(node_id)
            if not node:
                self._send_json(404, {"error": f"Node not found: {node_id}"})
                return
            res = {
                "node": node,
                "outbound": self.outbound_edges.get(node_id, []),
                "inbound": self.inbound_edges.get(node_id, []),
            }
            self._send_json(200, res)
            return

        # 4. Edges endpoint: /edges
        if path == "/edges":
            src_filter = query.get("src", [None])[0]
            dst_filter = query.get("dst", [None])[0]
            rel_filter = query.get("rel", [None])[0]
            limit = int(query.get("limit", [200])[0])
            offset = int(query.get("offset", [0])[0])

            all_edges = self.graph_data.get("edges", [])
            matched = []
            for e in all_edges:
                if src_filter and e.get("src") != src_filter:
                    continue
                if dst_filter and e.get("dst") != dst_filter:
                    continue
                if rel_filter and e.get("rel") != rel_filter:
                    continue
                matched.append(e)

            paginated = matched[offset: offset + limit]
            self._send_json(200, paginated)
            return

        # 5. Graph RAG Context endpoint: /context
        if path == "/context":
            entity = query.get("entity", [""])[0]
            if not entity:
                self._send_json(400, {"error": "Missing required query parameter 'entity'"})
                return

            algo = query.get("algorithm", ["ppr"])[0]
            top_k = int(query.get("top_k", [15])[0])
            fmt = query.get("format", ["json"])[0]

            if algo == "hybrid":
                hybrid_res = hybrid_graph_search(self.graph_data, query=entity, top_k=top_k)
                if fmt == "markdown":
                    lines = [f"# Hybrid Context: {entity}\n"]
                    for n in hybrid_res.get("nodes", []):
                        lines.append(f"- **{n.get('label', n['id'])}** (`{n['id']}`)")
                    self._send_text(200, "\n".join(lines), content_type="text/markdown")
                    return
                self._send_json(200, hybrid_res)
                return

            sub = extract_rag_subgraph(self.graph_data, entity, algorithm=algo, top_k=top_k)
            if "error" in sub:
                self._send_json(404, sub)
                return

            if fmt == "markdown":
                md_text = format_rag_markdown(sub)
                self._send_text(200, md_text, content_type="text/markdown")
                return

            self._send_json(200, sub)
            return

        # 6. Audit endpoint: /audit
        if path == "/audit":
            audit_res = audit_graph(self.graph_data)
            self._send_json(200, audit_res)
            return

        # 404 Not Found
        self._send_json(404, {"error": f"Endpoint not found: {path}"})


def make_api_server(
    graph_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> tuple[ThreadingHTTPServer, str, int]:
    """Create and configure ThreadingHTTPServer with preloaded graph data."""
    p = Path(graph_path)
    raw_content = p.read_bytes()
    graph_data = json.loads(raw_content.decode("utf-8"))
    etag = f'"{hashlib.sha256(raw_content).hexdigest()[:16]}"'

    nodes_by_id = {n["id"]: n for n in graph_data.get("nodes", [])}
    outbound: dict[str, list[dict[str, Any]]] = {}
    inbound: dict[str, list[dict[str, Any]]] = {}

    for e in graph_data.get("edges", []):
        outbound.setdefault(e["src"], []).append(e)
        inbound.setdefault(e["dst"], []).append(e)

    # Class-level bindings for the handler
    handler_cls = type(
        "ConfiguredGraphAPIHandler",
        (GraphAPIHandler,),
        {
            "graph_data": graph_data,
            "nodes_by_id": nodes_by_id,
            "outbound_edges": outbound,
            "inbound_edges": inbound,
            "graph_etag": etag,
        },
    )

    server = ThreadingHTTPServer((host, port), handler_cls)
    actual_host, actual_port = server.server_address[:2]
    return server, actual_host, actual_port


def run_api_server(
    graph_path: str | Path,
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    """Run foreground REST API server listening until interrupted."""
    server, actual_host, actual_port = make_api_server(graph_path, host, port)
    print(f"CorpusAtlas REST API running at http://{actual_host}:{actual_port}/")
    print("Press Ctrl+C to terminate.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()
