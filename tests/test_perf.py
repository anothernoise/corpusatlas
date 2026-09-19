"""Performance regression guards, not benchmarks — these assert *bounds*
loose enough to hold on a slow CI runner, not tight numbers that would make
this suite flaky. Two things worth guarding against silently regressing:

1. A full build staying roughly linear in corpus size — no accidental O(n²)
   creeping into an adapter or an extractor as the codebase grows.
2. --cache actually paying for itself: a warm rebuild of an unchanged
   corpus has to be meaningfully faster than a cold one, or the whole
   feature in cache.py isn't doing its job.

Web-adapter concurrency has its own timing tests in test_web_adapter.py
(test_fetches_run_concurrently_not_one_at_a_time and friends) — not
repeated here.
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.__main__ import main

N_DOCS = 400
# Real-ish size and shape: a title, a few wikilinks to other notes in the
# corpus (so the deterministic tier and cache fingerprinting both have
# actual work to do), and enough prose that html-tag/markdown parsing isn't
# trivially free.
PARAGRAPH = ("Apache Spark and Apache Flink are both stream processing "
            "engines that read from Kafka and write to object storage. ") * 20


def _write_corpus(root: Path, n: int = N_DOCS) -> Path:
    notes = root / "notes"
    notes.mkdir()
    for i in range(n):
        links = " ".join(f"[[Note {(i + 1) % n}]] [[Note {(i + 7) % n}]]" for _ in range(1))
        (notes / f"Note {i}.md").write_text(f"# Note {i}\n\n{links}\n\n{PARAGRAPH}", encoding="utf-8")
    config = root / "corpusatlas.toml"
    config.write_text(
        '[[sources]]\ntype = "obsidian"\npath = "notes"\nurl_base = "/notes/"\n',
        encoding="utf-8",
    )
    return config


def test_build_time_stays_roughly_linear_in_corpus_size():
    """400 synthetic, cross-linked notes build well inside a generous
    ceiling. This isn't a tight number — it exists to catch a real
    algorithmic regression (an accidental O(n²) somewhere), not to enforce
    a specific speed."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        config = _write_corpus(root)
        out = root / "graph.json"

        start = time.monotonic()
        rc = main(["build", "--config", str(config), "--out", str(out)])
        elapsed = time.monotonic() - start

    assert rc == 0
    assert elapsed < 20.0, f"build of {N_DOCS} docs took {elapsed:.1f}s — investigate before raising this bound"


def test_cache_warm_build_is_meaningfully_faster_than_cold():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        config = _write_corpus(root)
        out = root / "graph.json"
        cache = root / "cache.json"

        start = time.monotonic()
        rc_cold = main(["build", "--config", str(config), "--out", str(out), "--cache", str(cache)])
        cold_elapsed = time.monotonic() - start

        start = time.monotonic()
        rc_warm = main(["build", "--config", str(config), "--out", str(out), "--cache", str(cache)])
        warm_elapsed = time.monotonic() - start

    assert rc_cold == 0 and rc_warm == 0
    # Generous (not "2x faster") — the point is catching the cache doing
    # nothing at all, not enforcing a specific speedup ratio.
    assert warm_elapsed < cold_elapsed * 0.75, (
        f"cold {cold_elapsed:.2f}s vs warm {warm_elapsed:.2f}s — cache doesn't look like it's helping")
