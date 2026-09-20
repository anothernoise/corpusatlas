"""Tests for Phase 4: Enterprise Ingestion Connectors (GitHub, Notion, Confluence)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from corpusatlas.adapters import build as build_adapter
from corpusatlas.adapters.confluence import ConfluenceAdapter
from corpusatlas.adapters.github import GitHubAdapter
from corpusatlas.adapters.notion import NotionAdapter


def test_github_adapter_from_json_export():
    payload = [
        {
            "number": 101,
            "title": "Support Spark Streaming ingestion",
            "html_url": "https://github.com/acme/data-platform/issues/101",
            "body": "We need to connect Spark Streaming with Kafka. See #99 for details.",
            "created_at": "2026-03-15T10:00:00Z",
            "user": {"login": "octocat"},
            "state": "open",
            "labels": [{"name": "enhancement"}, {"name": "streaming"}],
        },
        {
            "number": 102,
            "title": "Fix Postgres connection timeout",
            "html_url": "https://github.com/acme/data-platform/pull/102",
            "pull_request": {},
            "body": "Resolves connection leak in PostgreSQL client pool.",
            "created_at": "2026-03-16T12:00:00Z",
            "user": {"login": "monalisa"},
            "state": "closed",
            "labels": [{"name": "bug"}],
        },
    ]

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        path = f.name

    adapter = GitHubAdapter(path=path, repo="acme/data-platform")
    docs = list(adapter.documents())

    assert len(docs) == 2
    issue_doc = docs[0]
    assert issue_doc.id == "github:acme/data-platform#101"
    assert issue_doc.kind == "issue"
    assert "Spark Streaming" in issue_doc.title
    assert issue_doc.date == "2026-03-15"
    assert "enhancement" in issue_doc.tags
    assert issue_doc.meta["author"] == "octocat"
    assert issue_doc.meta["state"] == "open"

    pr_doc = docs[1]
    assert pr_doc.id == "github:acme/data-platform#102"
    assert pr_doc.kind == "pull-request"
    assert pr_doc.meta["state"] == "closed"


def test_notion_adapter_from_export_directory():
    with tempfile.TemporaryDirectory() as td:
        p1 = Path(td) / "Architecture Guidelines 12345.md"
        p1.write_text("""---
title: Architecture Guidelines
date: 2026-01-20
tags: [architecture, standards]
author: Chief Architect
---
# Architecture Guidelines
All services must use gRPC or REST with OpenAPI contracts.
""", encoding="utf-8")

        p2 = Path(td) / "Data Lakehouse Strategy 67890.md"
        p2.write_text("""# Data Lakehouse Strategy
Adopt Iceberg and DuckDB for ad-hoc analytical workloads.
""", encoding="utf-8")

        adapter = NotionAdapter(path=td)
        docs = list(adapter.documents())

        assert len(docs) == 2
        titles = {d.title for d in docs}
        assert "Architecture Guidelines" in titles
        assert "Data Lakehouse Strategy" in titles
        doc1 = next(d for d in docs if d.title == "Architecture Guidelines")
        assert doc1.date == "2026-01-20"
        assert "standards" in doc1.tags
        assert "gRPC" in doc1.text


def test_confluence_adapter_from_export_directory():
    with tempfile.TemporaryDirectory() as td:
        p1 = Path(td) / "Platform-Overview.html"
        p1.write_text("""<!DOCTYPE html>
<html>
<head><title>Platform Overview - Confluence</title></head>
<body>
<div id="main-content">
  <h1>Platform Overview</h1>
  <p>Our core platform relies on <strong>Kubernetes</strong> and <strong>Prometheus</strong>.</p>
</div>
</body>
</html>
""", encoding="utf-8")

        adapter = ConfluenceAdapter(path=td, space_key="ENG")
        docs = list(adapter.documents())

        assert len(docs) == 1
        d = docs[0]
        assert d.id == "confluence:ENG/Platform-Overview"
        assert d.title == "Platform Overview"
        assert d.kind == "confluence-page"
        assert "Kubernetes" in d.text
        assert "Prometheus" in d.text


def test_adapters_registered_and_buildable():
    spec_gh = {"type": "github", "path": "/dev/null"}
    spec_notion = {"type": "notion", "path": "/dev/null"}
    spec_confluence = {"type": "confluence", "path": "/dev/null"}

    a_gh = build_adapter(spec_gh)
    a_notion = build_adapter(spec_notion)
    a_confluence = build_adapter(spec_confluence)

    assert isinstance(a_gh, GitHubAdapter)
    assert isinstance(a_notion, NotionAdapter)
    assert isinstance(a_confluence, ConfluenceAdapter)
