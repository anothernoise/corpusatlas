"""Tests for performance telemetry and automated micro-benchmarking suite."""
from corpusatlas.benchmark import benchmark_barnes_hut, benchmark_aho_corasick, run_all_benchmarks


def test_benchmark_barnes_hut():
    report = benchmark_barnes_hut(num_nodes=100, iterations=5)
    assert report["num_nodes"] == 100
    assert report["iterations"] == 5
    assert report["duration_ms"] >= 0.0
    assert report["iterations_per_sec"] >= 0.0


def test_benchmark_aho_corasick():
    report = benchmark_aho_corasick(num_patterns=50, text_len=1000)
    assert report["num_patterns"] == 50
    assert report["chars_scanned"] > 0
    assert report["matches_found"] >= 0
    assert report["chars_per_sec"] >= 0.0


def test_run_all_benchmarks_quick():
    results = run_all_benchmarks(quick=True)
    assert "benchmarks" in results
    assert "barnes_hut" in results["benchmarks"]
    assert "aho_corasick" in results["benchmarks"]
    assert "timestamp" in results
