"""Disk-backed SQLite pipeline store for out-of-core graph processing.

Enables streaming ingest, deduplication, retraction, and JSON serialization
without loading hundreds of thousands of nodes/edges into Python heap.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Iterator

from .model import Edge, Node


class SQLitePipelineStore:
    """Out-of-core relational store for CorpusAtlas graph pipeline tiers."""

    def __init__(self, db_path: str | Path = ":memory:"):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA synchronous = OFF;")
        self.conn.execute("PRAGMA journal_mode = MEMORY;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS raw_nodes (
                    id TEXT,
                    label TEXT,
                    type TEXT,
                    aliases_json TEXT,
                    meta_json TEXT,
                    tier_order INTEGER
                );

                CREATE TABLE IF NOT EXISTS raw_edges (
                    src TEXT,
                    rel TEXT,
                    dst TEXT,
                    confidence REAL,
                    explanation TEXT,
                    prov_json TEXT,
                    tier_order INTEGER
                );

                CREATE INDEX IF NOT EXISTS idx_raw_nodes_id ON raw_nodes(id);
                CREATE INDEX IF NOT EXISTS idx_raw_edges_src_dst ON raw_edges(src, dst);
            """)

    def close(self) -> None:
        self.conn.close()

    def add_tier_nodes(self, nodes: Iterable[Node], tier_order: int) -> None:
        """Add nodes emitted by an extractor tier."""
        rows = [
            (
                n.id,
                n.label,
                n.type,
                json.dumps(list(n.aliases), ensure_ascii=False),
                json.dumps(n.meta, ensure_ascii=False),
                tier_order,
            )
            for n in nodes
        ]
        with self.conn:
            self.conn.executemany(
                "INSERT INTO raw_nodes VALUES (?, ?, ?, ?, ?, ?)", rows
            )

    def add_tier_edges(self, edges: Iterable[Edge], tier_order: int) -> None:
        """Add edges emitted by an extractor tier."""
        rows = [
            (
                e.src,
                e.rel,
                e.dst,
                e.confidence,
                e.explanation,
                json.dumps(e.prov, ensure_ascii=False),
                tier_order,
            )
            for e in edges
        ]
        with self.conn:
            self.conn.executemany(
                "INSERT INTO raw_edges VALUES (?, ?, ?, ?, ?, ?, ?)", rows
            )

    def compact(self, live_doc_ids: set[str] | None = None) -> tuple[int, int]:
        """Perform first-writer-wins deduplication, doc retraction, and dangling edge pruning.

        Returns (node_count, edge_count).
        """
        with self.conn:
            # Create materialized deduplicated tables
            self.conn.executescript("""
                DROP TABLE IF EXISTS final_nodes;
                DROP TABLE IF EXISTS final_edges;

                CREATE TABLE final_nodes (
                    id TEXT PRIMARY KEY,
                    label TEXT,
                    type TEXT,
                    aliases_json TEXT,
                    meta_json TEXT
                );

                CREATE TABLE final_edges (
                    src TEXT,
                    rel TEXT,
                    dst TEXT,
                    confidence REAL,
                    explanation TEXT,
                    prov_json TEXT,
                    PRIMARY KEY (src, rel, dst)
                );
            """)

            # Deduplicate nodes: lowest tier_order wins
            # Using window function row_number()
            self.conn.execute("""
                INSERT INTO final_nodes
                SELECT id, label, type, aliases_json, meta_json
                FROM (
                    SELECT id, label, type, aliases_json, meta_json,
                           ROW_NUMBER() OVER (PARTITION BY id ORDER BY tier_order ASC) as rn
                    FROM raw_nodes
                ) WHERE rn = 1;
            """)

            # Deduplicate edges: lowest tier_order wins
            self.conn.execute("""
                INSERT INTO final_edges
                SELECT src, rel, dst, confidence, explanation, prov_json
                FROM (
                    SELECT src, rel, dst, confidence, explanation, prov_json,
                           ROW_NUMBER() OVER (PARTITION BY src, rel, dst ORDER BY tier_order ASC) as rn
                    FROM raw_edges
                ) WHERE rn = 1;
            """)

            # Retract edges whose prov.doc is not in live_doc_ids (if specified)
            if live_doc_ids is not None:
                # We filter in Python or via temporary table for scalability
                self.conn.execute("CREATE TEMP TABLE IF NOT EXISTS live_docs (doc_id TEXT PRIMARY KEY);")
                self.conn.execute("DELETE FROM live_docs;")
                self.conn.executemany("INSERT INTO live_docs VALUES (?)", [(d,) for d in live_doc_ids])
                self.conn.execute("""
                    DELETE FROM final_edges
                    WHERE json_extract(prov_json, '$.doc') IS NOT NULL
                      AND json_extract(prov_json, '$.doc') NOT IN (SELECT doc_id FROM live_docs);
                """)

            # Prune dangling edges (where src or dst not in final_nodes)
            self.conn.execute("""
                DELETE FROM final_edges
                WHERE src NOT IN (SELECT id FROM final_nodes)
                   OR dst NOT IN (SELECT id FROM final_nodes);
            """)

            # Prune isolated nodes (nodes with 0 edges)
            self.conn.execute("""
                DELETE FROM final_nodes
                WHERE id NOT IN (
                    SELECT src FROM final_edges
                    UNION
                    SELECT dst FROM final_edges
                );
            """)

            node_count = self.conn.execute("SELECT COUNT(*) FROM final_nodes").fetchone()[0]
            edge_count = self.conn.execute("SELECT COUNT(*) FROM final_edges").fetchone()[0]

        return node_count, edge_count

    def stream_nodes(self) -> Iterator[Node]:
        """Yield finalized Node objects in deterministic id order."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT id, label, type, aliases_json, meta_json FROM final_nodes ORDER BY id ASC")
        for row in cursor:
            nid, label, ntype, aliases_j, meta_j = row
            yield Node(
                id=nid,
                label=label,
                type=ntype,
                aliases=tuple(json.loads(aliases_j)),
                meta=json.loads(meta_j),
            )

    def stream_edges(self) -> Iterator[Edge]:
        """Yield finalized Edge objects in deterministic (src, rel, dst) order."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT src, rel, dst, confidence, explanation, prov_json FROM final_edges ORDER BY src ASC, rel ASC, dst ASC")
        for row in cursor:
            src, rel, dst, conf, expl, prov_j = row
            yield Edge(
                src=src,
                rel=rel,
                dst=dst,
                confidence=conf,
                explanation=expl,
                prov=json.loads(prov_j),
            )

    def export_json(self, out_path: str | Path, meta: dict[str, Any] | None = None) -> None:
        """Stream JSON artifact directly to disk with minimal memory overhead."""
        p = Path(out_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        meta = meta or {}

        with open(p, "w", encoding="utf-8") as f:
            f.write('{\n  "meta": ')
            f.write(json.dumps(meta, indent=2, ensure_ascii=False))
            f.write(',\n  "nodes": [\n')

            first = True
            for node in self.stream_nodes():
                if not first:
                    f.write(',\n')
                first = False
                f.write("    " + json.dumps(node.to_json(), ensure_ascii=False))

            f.write('\n  ],\n  "edges": [\n')

            first = True
            for edge in self.stream_edges():
                if not first:
                    f.write(',\n')
                first = False
                f.write("    " + json.dumps(edge.to_json(), ensure_ascii=False))

            f.write('\n  ]\n}\n')
