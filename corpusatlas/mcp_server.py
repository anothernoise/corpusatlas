"""Model Context Protocol (MCP) server for CorpusAtlas.

Enables Claude Desktop, Cursor, Antigravity, and other MCP-compliant AI agents
to query, search, traverse, and inspect knowledge graphs with zero external dependencies.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .audit import audit_graph
from .context import extract_rag_subgraph, format_rag_markdown


class MCPServer:
    """Standard-library Model Context Protocol server exposing CorpusAtlas graph operations."""

    def __init__(self, graph_path: str | Path):
        self.graph_path = Path(graph_path)
        self.data: dict[str, Any] = {}
        self.nodes_by_id: dict[str, dict[str, Any]] = {}
        self.edges_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self._load_graph()

    def _load_graph(self) -> None:
        if self.graph_path.exists():
            self.data = json.loads(self.graph_path.read_text(encoding="utf-8"))
            for n in self.data.get("nodes", []):
                self.nodes_by_id[n["id"]] = n
            for e in self.data.get("edges", []):
                key = (e["src"], e["dst"])
                self.edges_by_pair.setdefault(key, []).append(e)

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "search_nodes",
                "description": "Search knowledge graph nodes by label, id, or keywords.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query or keyword"},
                        "type_filter": {"type": "string", "description": "Filter by node type (e.g., Technology, Document)"},
                        "limit": {"type": "integer", "description": "Maximum number of results (default 10)", "default": 10},
                    },
                    "required": ["query"],
                },
            },
            {
                "name": "extract_context_ppr",
                "description": "Extract a dense Graph RAG semantic context around an entity using Personalized PageRank (PPR).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string", "description": "Target entity ID"},
                        "top_k": {"type": "integer", "description": "Number of top nodes to include (default 15)", "default": 15},
                    },
                    "required": ["entity"],
                },
            },
            {
                "name": "traverse_subgraph",
                "description": "Extract a multi-hop BFS neighborhood around an entity.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "entity": {"type": "string", "description": "Starting node ID"},
                        "depth": {"type": "integer", "description": "Traversal depth: 1 or 2", "default": 1},
                    },
                    "required": ["entity"],
                },
            },
            {
                "name": "audit_graph",
                "description": "Run topological audit checking Gini centralization, bridge bottlenecks, and cycles.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
            {
                "name": "get_provenance",
                "description": "Retrieve claim evidence, document provenance, and explanation for an edge between two entities.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "src": {"type": "string", "description": "Source node ID"},
                        "dst": {"type": "string", "description": "Destination node ID"},
                    },
                    "required": ["src", "dst"],
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        if name == "search_nodes":
            q = str(arguments.get("query", "")).lower()
            t_filt = arguments.get("type_filter")
            limit = int(arguments.get("limit", 10))
            matches = []
            for nid, n in self.nodes_by_id.items():
                if t_filt and n.get("type") != t_filt:
                    continue
                label = n.get("label", nid).lower()
                aliases = " ".join(n.get("aliases", [])).lower()
                if q in nid.lower() or q in label or q in aliases:
                    matches.append(n)
                if len(matches) >= limit:
                    break
            return json.dumps(matches, indent=2, ensure_ascii=False)

        elif name == "extract_context_ppr":
            entity = str(arguments.get("entity", ""))
            top_k = int(arguments.get("top_k", 15))
            sub = extract_rag_subgraph(self.data, entity, algorithm="ppr", top_k=top_k)
            if "error" in sub:
                return str(sub["error"])
            return format_rag_markdown(sub)

        elif name == "traverse_subgraph":
            entity = str(arguments.get("entity", ""))
            depth = int(arguments.get("depth", 1))
            sub = extract_rag_subgraph(self.data, entity, algorithm="bfs", depth=depth)
            if "error" in sub:
                return str(sub["error"])
            return format_rag_markdown(sub)

        elif name == "audit_graph":
            audit_res = audit_graph(self.data)
            return json.dumps(audit_res, indent=2)

        elif name == "get_provenance":
            src = str(arguments.get("src", ""))
            dst = str(arguments.get("dst", ""))
            edges = self.edges_by_pair.get((src, dst), [])
            if not edges:
                return f"No direct edges found from '{src}' to '{dst}'."
            return json.dumps(edges, indent=2, ensure_ascii=False)

        else:
            raise ValueError(f"Unknown tool '{name}'")

    def handle_message(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """Handle incoming JSON-RPC 2.0 message."""
        msg_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params", {})

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": "corpusatlas",
                        "version": __version__,
                    },
                },
            }

        elif method == "notifications/initialized":
            return None

        elif method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}

        elif method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {"tools": self.list_tools()},
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            try:
                res_text = self.call_tool(tool_name, tool_args)
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": res_text}],
                        "isError": False,
                    },
                }
            except Exception as ex:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {ex}"}],
                        "isError": True,
                    },
                }

        else:
            if msg_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            return None

    def serve_stdio(self) -> None:
        """Run standard I/O loop processing JSON-RPC messages from stdin."""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
                response = self.handle_message(msg)
                if response is not None:
                    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
            except Exception as e:
                err = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"},
                }
                sys.stdout.write(json.dumps(err) + "\n")
                sys.stdout.flush()
