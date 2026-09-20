"""Multi-format graph export engine.

Supports:
- Cypher (.cql) for Neo4j / Memgraph / AWS Neptune
- RDF Turtle (.ttl) for W3C semantic web / SPARQL triple-stores
- DuckDB / Parquet (.duckdb, .parquet, .sql, .csv) for fast analytical SQL queries
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Iterable

from .model import Edge, Node


def _escape_cypher_str(val: str) -> str:
    return val.replace("\\", "\\\\").replace("'", "\\'")


def _safe_iri_id(node_id: str) -> str:
    # Replace colons and slashes for compact Turtle IRIs
    return re.sub(r"[^a-zA-Z0-9_-]", "_", node_id)


def export_cypher(nodes: Iterable[Node], edges: Iterable[Edge], out_path: str | Path) -> None:
    """Export graph as Cypher query statements."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("// CorpusAtlas Cypher Export\n")
        f.write("CREATE CONSTRAINT IF NOT EXISTS FOR (n:Resource) REQUIRE n.id IS UNIQUE;\n\n")

        f.write("// Nodes\n")
        for n in nodes:
            label_esc = _escape_cypher_str(n.label)
            id_esc = _escape_cypher_str(n.id)
            type_label = re.sub(r"[^a-zA-Z0-9_]", "_", n.type)
            f.write(
                f"MERGE (n:Resource:{type_label} {{id: '{id_esc}'}}) "
                f"SET n.label = '{label_esc}', n.type = '{type_label}';\n"
            )

        f.write("\n// Edges\n")
        for e in edges:
            src_esc = _escape_cypher_str(e.src)
            dst_esc = _escape_cypher_str(e.dst)
            rel_name = re.sub(r"[^a-zA-Z0-9_]", "_", e.rel)
            f.write(
                f"MATCH (s:Resource {{id: '{src_esc}'}}), (d:Resource {{id: '{dst_esc}'}}) "
                f"MERGE (s)-[r:`{rel_name}`]->(d) "
                f"SET r.confidence = {e.confidence:.4f};\n"
            )


def export_turtle(nodes: Iterable[Node], edges: Iterable[Edge], out_path: str | Path) -> None:
    """Export graph as W3C RDF Turtle (.ttl)."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("@prefix ca: <https://corpusatlas.org/schema/> .\n")
        f.write("@prefix res: <https://corpusatlas.org/resource/> .\n")
        f.write("@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n")
        f.write("@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .\n\n")

        f.write("# Nodes\n")
        for n in nodes:
            nid = _safe_iri_id(n.id)
            ntype = re.sub(r"[^a-zA-Z0-9_]", "_", n.type)
            lbl = n.label.replace('"', '\\"')
            f.write(f"res:{nid} a ca:{ntype} ;\n")
            f.write(f'    rdfs:label "{lbl}" ;\n')
            f.write(f'    ca:id "{n.id}" .\n\n')

        f.write("# Edges\n")
        for e in edges:
            src = _safe_iri_id(e.src)
            dst = _safe_iri_id(e.dst)
            rel = re.sub(r"[^a-zA-Z0-9_]", "_", e.rel)
            f.write(f"res:{src} ca:{rel} res:{dst} .\n")


def export_duckdb(
    nodes: Iterable[Node],
    edges: Iterable[Edge],
    out_dir: str | Path,
    db_name: str = "corpusatlas.duckdb",
    build_parquet: bool = True,
) -> dict[str, str]:
    """Export graph to DuckDB SQL, CSV, and native .duckdb / .parquet if DuckDB CLI is installed.

    Returns dict of generated artifacts.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    nodes_csv = out / "nodes.csv"
    edges_csv = out / "edges.csv"
    sql_script = out / "import_duckdb.sql"
    db_path = out / db_name

    # Write nodes.csv
    with open(nodes_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "label", "type", "aliases", "meta"])
        for n in nodes:
            writer.writerow([
                n.id,
                n.label,
                n.type,
                json.dumps(list(n.aliases), ensure_ascii=False),
                json.dumps(n.meta, ensure_ascii=False),
            ])

    # Write edges.csv
    with open(edges_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["src", "rel", "dst", "confidence", "explanation", "prov"])
        for e in edges:
            writer.writerow([
                e.src,
                e.rel,
                e.dst,
                e.confidence,
                e.explanation,
                json.dumps(e.prov, ensure_ascii=False),
            ])

    # Build DuckDB SQL script
    parquet_nodes = out / "nodes.parquet"
    parquet_edges = out / "edges.parquet"

    sql_cmds = [
        "CREATE OR REPLACE TABLE nodes (",
        "    id VARCHAR PRIMARY KEY,",
        "    label VARCHAR,",
        "    type VARCHAR,",
        "    aliases VARCHAR,",
        "    meta VARCHAR",
        ");",
        "CREATE OR REPLACE TABLE edges (",
        "    src VARCHAR,",
        "    rel VARCHAR,",
        "    dst VARCHAR,",
        "    confidence DOUBLE,",
        "    explanation VARCHAR,",
        "    prov VARCHAR",
        ");",
        f"COPY nodes FROM '{nodes_csv.resolve()}' (HEADER TRUE);",
        f"COPY edges FROM '{edges_csv.resolve()}' (HEADER TRUE);",
    ]

    if build_parquet:
        sql_cmds.extend([
            f"COPY nodes TO '{parquet_nodes.resolve()}' (FORMAT PARQUET);",
            f"COPY edges TO '{parquet_edges.resolve()}' (FORMAT PARQUET);",
        ])

    sql_content = "\n".join(sql_cmds) + "\n"
    sql_script.write_text(sql_content, encoding="utf-8")

    result = {
        "nodes_csv": str(nodes_csv),
        "edges_csv": str(edges_csv),
        "sql_script": str(sql_script),
    }

    # Attempt to find duckdb binary
    duckdb_bin = shutil.which("duckdb") or "/opt/homebrew/bin/duckdb"
    if os.path.exists(duckdb_bin) and os.access(duckdb_bin, os.X_OK):
        try:
            # Execute duckdb directly to produce the database and parquet files
            subprocess.run(
                [duckdb_bin, str(db_path)],
                input=sql_content,
                text=True,
                check=True,
                capture_output=True,
            )
            result["duckdb_file"] = str(db_path)
            if build_parquet and parquet_nodes.exists():
                result["nodes_parquet"] = str(parquet_nodes)
                result["edges_parquet"] = str(parquet_edges)
        except Exception:
            pass

    return result
