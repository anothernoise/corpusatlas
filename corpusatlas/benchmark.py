"""Automated micro-benchmarking and performance telemetry suite for CorpusAtlas.

Measures throughput of core zero-dependency graph algorithms:
- Barnes-Hut O(N log N) Quadtree force calculation
- Aho-Corasick linear-time multi-pattern matching
- Datalog-Lite forward-chaining fixpoint inference
Zero external dependencies.
"""
from __future__ import annotations

import datetime
import random
import time
from typing import Any

from .aho_corasick import AhoCorasick
from .datalog import DatalogEngine, DatalogRule
from .layout import compute_layout
from .model import Edge, Node


def benchmark_barnes_hut(num_nodes: int = 500, iterations: int = 10) -> dict[str, Any]:
    """Benchmark Barnes-Hut layout engine performance."""
    rng = random.Random(42)
    nodes = [
        {"id": f"node:{i}", "label": f"Node {i}", "x": rng.uniform(-100, 100), "y": rng.uniform(-100, 100)}
        for i in range(num_nodes)
    ]
    edges = [
        {"src": f"node:{rng.randint(0, num_nodes - 1)}", "dst": f"node:{rng.randint(0, num_nodes - 1)}"}
        for _ in range(num_nodes * 2)
    ]

    t0 = time.perf_counter()
    compute_layout(nodes, edges, iterations=iterations, use_barnes_hut=True, theta=0.5)
    elapsed = time.perf_counter() - t0

    dur_ms = elapsed * 1000.0
    iter_sec = (iterations / elapsed) if elapsed > 0 else 0.0

    return {
        "num_nodes": num_nodes,
        "num_edges": len(edges),
        "iterations": iterations,
        "duration_ms": round(dur_ms, 2),
        "iterations_per_sec": round(iter_sec, 2),
    }


def benchmark_aho_corasick(num_patterns: int = 1000, text_len: int = 50000) -> dict[str, Any]:
    """Benchmark Aho-Corasick multi-pattern keyword scanner."""
    rng = random.Random(42)
    vocab = ["apple", "banana", "cherry", "database", "python", "duckdb", "sqlite", "graph", "engine", "query"]
    patterns = [
        f"{rng.choice(vocab)}_{i}"
        for i in range(num_patterns)
    ]

    words = [rng.choice(patterns) if rng.random() < 0.1 else rng.choice(vocab) for _ in range(text_len // 8)]
    corpus_text = " ".join(words)

    t0 = time.perf_counter()
    ac = AhoCorasick()
    for p in patterns:
        ac.add_word(p, p)
    ac.build()
    build_time = time.perf_counter() - t0

    t1 = time.perf_counter()
    matches = list(ac.find_matches(corpus_text))
    scan_time = time.perf_counter() - t1

    chars_per_sec = (len(corpus_text) / scan_time) if scan_time > 0 else 0.0

    return {
        "num_patterns": num_patterns,
        "chars_scanned": len(corpus_text),
        "matches_found": len(matches),
        "trie_build_ms": round(build_time * 1000.0, 2),
        "scan_duration_ms": round(scan_time * 1000.0, 2),
        "chars_per_sec": round(chars_per_sec, 2),
    }


def benchmark_datalog(num_chains: int = 100) -> dict[str, Any]:
    """Benchmark Datalog-Lite forward-chaining fixpoint inference."""
    edges = []
    for i in range(num_chains):
        edges.append(Edge(src=f"item:{i}", rel="subclass_of", dst=f"item:{i+1}", confidence=1.0))

    rule = DatalogRule(name="subclass_transitive", rule_type="transitive", rel="subclass_of", dampening=1.0)
    engine = DatalogEngine([rule])

    t0 = time.perf_counter()
    inferred = engine.infer(edges, max_rounds=5)
    elapsed = time.perf_counter() - t0

    return {
        "initial_edges": len(edges),
        "inferred_edges": len(inferred),
        "duration_ms": round(elapsed * 1000.0, 2),
    }


def run_all_benchmarks(quick: bool = False) -> dict[str, Any]:
    """Execute all performance benchmarks and compile telemetry report."""
    nodes_count = 200 if quick else 1000
    patterns_count = 200 if quick else 2000
    text_len = 10000 if quick else 100000

    bh = benchmark_barnes_hut(num_nodes=nodes_count, iterations=10)
    ac = benchmark_aho_corasick(num_patterns=patterns_count, text_len=text_len)
    dl = benchmark_datalog(num_chains=50 if quick else 150)

    return {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "benchmarks": {
            "barnes_hut": bh,
            "aho_corasick": ac,
            "datalog": dl,
        },
    }
