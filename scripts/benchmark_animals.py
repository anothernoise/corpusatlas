#!/usr/bin/env python3
"""Benchmark CorpusAtlas build performance on the 1,000 Wikipedia animals corpus.

Measures cold vs warm build execution time, memory allocation, and pipeline stages.

Usage:
    python3 scripts/benchmark_animals.py
"""
from __future__ import annotations

import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from corpusatlas import config as cfgmod
from corpusatlas.adapters import build as build_adapter
from corpusatlas.cache import BuildCache
from corpusatlas.emit import write_graph
from corpusatlas.extract import DeterministicExtractor, MentionsExtractor
from corpusatlas.merge import merge
from corpusatlas.ontology import Ontology
from corpusatlas.resolve import Resolver


def run_benchmark() -> None:
    config_path = ROOT / "corpora" / "animals" / "corpusatlas.toml"
    if not config_path.exists():
        print(f"Error: {config_path} not found.")
        print("Please run `python3 scripts/fetch_wikipedia_animals.py` first to generate the corpus.")
        sys.exit(1)

    cfg = cfgmod.load(config_path)
    schema = (cfg.get("ontology") or {}).get("schema")
    ontology = Ontology.from_toml(schema)
    out_path = ROOT / "viewer" / "graph.json"
    cache_path = ROOT / "corpora" / "animals" / ".cache.json"
    if cache_path.exists():
        cache_path.unlink()

    # 1. COLD BUILD
    print("==================================================================")
    print("=== 1. COLD BUILD BENCHMARK (1,000 Wikipedia Animal Articles) ===")
    print("==================================================================")
    tracemalloc.start()
    t0 = time.perf_counter()

    t_start = time.perf_counter()
    cache = BuildCache(cache_path)
    docs = []
    for spec in cfg.get("sources", []):
        docs.extend(build_adapter(spec, cache=cache).documents())
    cache.save()
    t_adapter = time.perf_counter() - t_start

    t_start = time.perf_counter()
    resolver = Resolver.from_config(cfg, ontology=ontology)
    t_resolver = time.perf_counter() - t_start

    t_start = time.perf_counter()
    det = DeterministicExtractor(resolver=resolver, ontology=ontology)
    det_out_nodes, det_out_edges = det.run(docs)
    det_nodes, det_edges = list(det_out_nodes), list(det_out_edges)
    t_det = time.perf_counter() - t_start

    t_start = time.perf_counter()
    mentions = MentionsExtractor(det_nodes, resolver=resolver, ontology=ontology)
    ment_out_nodes, ment_out_edges = mentions.run(docs)
    ment_nodes, ment_edges = list(ment_out_nodes), list(ment_out_edges)
    t_ment = time.perf_counter() - t_start

    t_start = time.perf_counter()
    nodes, edges = merge([det_nodes, ment_nodes], [det_edges, ment_edges], live_doc_ids={d.id for d in docs})
    t_merge = time.perf_counter() - t_start

    t_start = time.perf_counter()
    counts = write_graph(out_path, nodes, edges, sources=["Wikipedia Animals (1000)"], ontology=ontology)
    t_emit = time.perf_counter() - t_start

    t_cold = time.perf_counter() - t0
    _, peak_cold = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"Total Cold Duration:   {t_cold:.3f} s")
    print(f"Peak RAM Allocation:   {peak_cold / (1024 * 1024):.2f} MB")
    print(f"Output File Size:      {out_path.stat().st_size / (1024 * 1024):.2f} MB ({out_path.stat().st_size:,} bytes)")
    print(f"Compiled Graph:        {counts['nodes']:,} nodes, {counts['edges']:,} edges")
    print("Stage Breakdown:")
    print(f"  • Adapter parsing:   {t_adapter:.3f} s ({t_adapter / t_cold * 100:.1f}%)")
    print(f"  • Entity resolution: {t_resolver:.3f} s ({t_resolver / t_cold * 100:.1f}%)")
    print(f"  • Deterministic:     {t_det:.3f} s ({t_det / t_cold * 100:.1f}%)")
    print(f"  • Mentions scanning: {t_ment:.3f} s ({t_ment / t_cold * 100:.1f}%)")
    print(f"  • Graph merge:       {t_merge:.3f} s ({t_merge / t_cold * 100:.1f}%)")
    print(f"  • JSON emission:     {t_emit:.3f} s ({t_emit / t_cold * 100:.1f}%)")

    # 2. WARM BUILD (WITH CACHE)
    print("\n==================================================================")
    print("=== 2. WARM BUILD BENCHMARK (WITH WHOLE-CORPUS CACHE REUSE) ===")
    print("==================================================================")
    tracemalloc.start()
    t0_warm = time.perf_counter()

    t_start = time.perf_counter()
    cache_warm = BuildCache(cache_path)
    warm_docs = []
    for spec in cfg.get("sources", []):
        warm_docs.extend(build_adapter(spec, cache=cache_warm).documents())
    t_warm_adapter = time.perf_counter() - t_start

    resolver_warm = Resolver.from_config(cfg, ontology=ontology)
    det_out_nodes, det_out_edges = det.run(warm_docs)
    det_nodes, det_edges = list(det_out_nodes), list(det_out_edges)
    ment_out_nodes, ment_out_edges = mentions.run(warm_docs)
    ment_nodes, ment_edges = list(ment_out_nodes), list(ment_out_edges)
    nodes_w, edges_w = merge([det_nodes, ment_nodes], [det_edges, ment_edges], live_doc_ids={d.id for d in warm_docs})
    write_graph(out_path, nodes_w, edges_w, sources=["Wikipedia Animals (1000)"], ontology=ontology)

    t_warm = time.perf_counter() - t0_warm
    _, peak_warm = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"Total Warm Duration:   {t_warm:.3f} s")
    print(f"Warm Adapter Time:     {t_warm_adapter:.3f} s (Cache hit {cache_warm.hits}/{cache_warm.hits + cache_warm.misses} files)")
    print(f"Speedup Factor:        {t_cold / t_warm:.2f}x faster on rebuild")
    print(f"Peak RAM Allocation:   {peak_warm / (1024 * 1024):.2f} MB")


if __name__ == "__main__":
    run_benchmark()
