#!/usr/bin/env python3
"""Not a test — a manual, documented investigation of two open questions
from the project's own "next steps" list: where does build time actually
go at a size well beyond any real corpusatlas.dev consumer today (~5,000
documents, shirokoff.ca is ~350), and how much memory does it use getting
there. Run it and update docs/DESIGN.md's size section with what it finds
rather than trusting last time's numbers — they drift as the code does.

    python3 scripts/profile_scale.py [n_docs]

Stdlib only: tracemalloc for peak Python-level allocation (portable),
time.perf_counter for wall time per pipeline stage.
"""
from __future__ import annotations

import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas import config as cfgmod
from corpusatlas.adapters.obsidian import ObsidianAdapter
from corpusatlas.emit import write_graph
from corpusatlas.extract import DeterministicExtractor, MentionsExtractor, PacksExtractor
from corpusatlas.merge import merge
from corpusatlas.ontology import DEFAULT
from corpusatlas.resolve import Resolver

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5000

# A handful of real-sounding entity names, repeated through the generated
# prose, so the mentions tier (word-boundary scanning against a vocabulary)
# has real work to do instead of a no-op over an empty registry.
ENTITY_NAMES = ["Apache Spark", "Apache Flink", "Kafka", "ClickHouse", "Snowflake",
                "Apache Iceberg", "dbt", "Airflow", "Trino", "DuckDB"]
PARAGRAPH = (" ".join(f"Notes on {n} and how it compares to the others." for n in ENTITY_NAMES)) * 3


def build_corpus(root: Path, n: int) -> Path:
    notes = root / "notes"
    notes.mkdir()
    for i in range(n):
        links = " ".join(f"[[Note {(i + off) % n}]]" for off in (1, 7, 13))
        (notes / f"Note {i}.md").write_text(f"# Note {i}\n\n{links}\n\n{PARAGRAPH}", encoding="utf-8")

    entities = root / "entities.toml"
    entities.write_text("\n".join(
        f'[[entity]]\nid = "{n.lower().replace(" ", "-")}"\nname = "{n}"\ntype = "Technology"\n'
        for n in ENTITY_NAMES
    ), encoding="utf-8")

    config = root / "corpusatlas.toml"
    config.write_text(
        '[[sources]]\ntype = "obsidian"\npath = "notes"\nurl_base = "/notes/"\n\n'
        '[ontology]\nentities = "entities.toml"\n',
        encoding="utf-8",
    )
    return config


def main() -> None:
    print(f"Synthetic corpus: {N} cross-linked notes, {len(ENTITY_NAMES)}-entity registry\n")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        config_path = build_corpus(root, N)

        tracemalloc.start()
        t0 = time.perf_counter()

        cfg = cfgmod.load(config_path)
        docs = list(ObsidianAdapter(**{k: v for k, v in cfg["sources"][0].items() if k != "type"}).documents())
        t1 = time.perf_counter()

        resolver = Resolver.from_config(cfg, ontology=DEFAULT)
        t2 = time.perf_counter()

        det = DeterministicExtractor(resolver=resolver, ontology=DEFAULT)
        det_nodes, det_edges = (list(x) for x in det.run(docs))
        t3 = time.perf_counter()

        packs = PacksExtractor.from_config(cfg, resolver=resolver, ontology=DEFAULT)
        pack_nodes, pack_edges = (list(x) for x in packs.run(docs))
        t4 = time.perf_counter()

        mentions = MentionsExtractor(det_nodes + pack_nodes, resolver=resolver, ontology=DEFAULT)
        ment_nodes, ment_edges = (list(x) for x in mentions.run(docs))
        t5 = time.perf_counter()

        nodes, edges = merge([det_nodes, pack_nodes, ment_nodes],
                             [det_edges, pack_edges, ment_edges],
                             live_doc_ids={doc.id for doc in docs})
        t6 = time.perf_counter()

        out = root / "graph.json"
        write_graph(out, nodes, edges, sources=["obsidian"], ontology=DEFAULT)
        t7 = time.perf_counter()

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        stages = [
            ("adapter: parse + yield Documents", t1 - t0),
            ("Resolver.from_config", t2 - t1),
            ("deterministic tier", t3 - t2),
            ("packs tier (empty)", t4 - t3),
            ("mentions tier", t5 - t4),
            ("merge", t6 - t5),
            ("write_graph (json)", t7 - t6),
        ]
        total = t7 - t0
        print(f"{'stage':<32} {'seconds':>8} {'% of total':>11}")
        for name, secs in stages:
            print(f"{name:<32} {secs:>8.3f} {secs / total * 100:>10.1f}%")
        print(f"{'TOTAL':<32} {total:>8.3f}")
        print(f"\nnodes={len(nodes)} edges={len(edges)} docs={len(docs)}")
        print(f"peak Python-level allocation (tracemalloc): {peak / 1e6:.1f} MB")
        print(f"graph.json size: {out.stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
