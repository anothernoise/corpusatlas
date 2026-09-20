"""Tests for CorpusAtlas Model Context Protocol (MCP) server."""
import io
import json
import tempfile
from pathlib import Path
from corpusatlas.mcp_server import MCPServer


def _create_sample_graph(path: Path):
    path.write_text(json.dumps({
        "schema_version": 2,
        "counts": {"nodes": 3, "edges": 2},
        "nodes": [
            {"id": "tech:python", "label": "Python", "type": "Technology", "degree": 2},
            {"id": "tech:duckdb", "label": "DuckDB", "type": "Technology", "degree": 1},
            {"id": "doc:guide", "label": "Guide", "type": "Document", "degree": 1},
        ],
        "edges": [
            {"src": "tech:python", "rel": "uses", "dst": "tech:duckdb", "confidence": 0.95, "explanation": "Python has duckdb bindings"},
            {"src": "doc:guide", "rel": "mentions", "dst": "tech:python", "confidence": 1.0},
        ],
    }), encoding="utf-8")


def test_mcp_server_initialize_and_tools_list():
    with tempfile.TemporaryDirectory() as tmpdir:
        gpath = Path(tmpdir) / "graph.json"
        _create_sample_graph(gpath)

        server = MCPServer(graph_path=gpath)

        # 1. initialize request
        init_req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"clientInfo": {"name": "test-client", "version": "1.0"}},
        }
        res = server.handle_message(init_req)
        assert res["id"] == 1
        assert "capabilities" in res["result"]
        assert res["result"]["serverInfo"]["name"] == "corpusatlas"

        # 2. tools/list request
        list_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }
        res2 = server.handle_message(list_req)
        assert res2["id"] == 2
        tools = res2["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        assert "search_nodes" in tool_names
        assert "extract_context_ppr" in tool_names
        assert "traverse_subgraph" in tool_names
        assert "audit_graph" in tool_names


def test_mcp_server_tool_calls():
    with tempfile.TemporaryDirectory() as tmpdir:
        gpath = Path(tmpdir) / "graph.json"
        _create_sample_graph(gpath)

        server = MCPServer(graph_path=gpath)

        # Call search_nodes
        search_req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "search_nodes",
                "arguments": {"query": "python"},
            },
        }
        res = server.handle_message(search_req)
        assert res["id"] == 3
        text = res["result"]["content"][0]["text"]
        assert "tech:python" in text

        # Call extract_context_ppr
        ppr_req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "extract_context_ppr",
                "arguments": {"entity": "tech:python", "top_k": 5},
            },
        }
        res_ppr = server.handle_message(ppr_req)
        assert res_ppr["id"] == 4
        ppr_text = res_ppr["result"]["content"][0]["text"]
        assert "tech:python" in ppr_text or "tech:duckdb" in ppr_text

        # Call audit_graph
        audit_req = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "audit_graph",
                "arguments": {},
            },
        }
        res_audit = server.handle_message(audit_req)
        assert res_audit["id"] == 5
        audit_text = res_audit["result"]["content"][0]["text"]
        assert "gini" in audit_text.lower() or "centralization" in audit_text.lower()
