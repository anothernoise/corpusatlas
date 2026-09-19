"""Tests for the CLI additions: ontology-check, init, and build --dry-run.
Driven through main(argv) with real argv lists where it matters (the
argparse wiring itself, not just the underlying function), and against real
files on disk — init's whole point is producing something actually
buildable, so the test proves that by building it.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.__main__ import cmd_init, cmd_ontology_check, main

GOOD_SCHEMA = """
entity_types = ["Dish", "Ingredient"]
context_types = ["Document"]

[[relation]]
name = "USES_INGREDIENT"
source = ["Dish"]
target = ["Ingredient"]
group = "Composition"
"""

BAD_SCHEMA = """
entity_types = ["Dish"]

[[relation]]
name = "PAIRS_WITH"
source = ["Dish"]
target = ["Dish"]
"""


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# --- ontology-check -----------------------------------------------------

def test_ontology_check_accepts_a_valid_schema():
    with tempfile.TemporaryDirectory() as d:
        schema = write(Path(d) / "ontology.toml", GOOD_SCHEMA)
        assert cmd_ontology_check(type("Args", (), {"schema": str(schema)})) == 0


def test_ontology_check_rejects_a_broken_schema():
    with tempfile.TemporaryDirectory() as d:
        schema = write(Path(d) / "ontology.toml", BAD_SCHEMA)
        assert cmd_ontology_check(type("Args", (), {"schema": str(schema)})) == 1


def test_ontology_check_through_the_real_cli_argv():
    with tempfile.TemporaryDirectory() as d:
        schema = write(Path(d) / "ontology.toml", GOOD_SCHEMA)
        assert main(["ontology-check", "--schema", str(schema)]) == 0
        bad = write(Path(d) / "bad.toml", BAD_SCHEMA)
        assert main(["ontology-check", "--schema", str(bad)]) == 1


# --- init -----------------------------------------------------------------

def test_init_writes_a_config_and_an_entity_registry():
    with tempfile.TemporaryDirectory() as d:
        assert cmd_init(type("Args", (), {"dir": d})) == 0
        assert (Path(d) / "corpusatlas.toml").exists()
        assert (Path(d) / "entities.toml").exists()


def test_init_refuses_to_overwrite_existing_files():
    with tempfile.TemporaryDirectory() as d:
        assert cmd_init(type("Args", (), {"dir": d})) == 0
        assert cmd_init(type("Args", (), {"dir": d})) == 1  # second call: refuses


def test_init_scaffold_is_actually_buildable_end_to_end():
    # The whole point of `init` over copying example.toml: this has to run,
    # not just parse. Prove it by building it against two real notes.
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        assert main(["init", "--dir", str(root)]) == 0
        notes = root / "notes"
        notes.mkdir()
        write(notes / "Hello.md", "A first note, linking to [[World]].")
        write(notes / "World.md", "The other note.")

        out = root / "graph.json"
        rc = main(["build", "--config", str(root / "corpusatlas.toml"), "--out", str(out)])
        assert rc == 0
        assert out.exists()
        assert main(["validate", "--graph", str(out)]) == 0


# --- build --dry-run --------------------------------------------------------

def test_dry_run_reports_counts_and_writes_nothing():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        main(["init", "--dir", str(root)])
        notes = root / "notes"
        notes.mkdir()
        write(notes / "A.md", "Just a note.")

        out = root / "graph.json"
        rc = main(["build", "--config", str(root / "corpusatlas.toml"), "--dry-run"])
        assert rc == 0
        assert not out.exists()  # --dry-run with no --out at all: nothing to check against, but...

        # ...and even with --out given, --dry-run must not write it.
        rc = main(["build", "--config", str(root / "corpusatlas.toml"), "--out", str(out), "--dry-run"])
        assert rc == 0
        assert not out.exists()


def test_build_without_out_or_dry_run_fails_cleanly_not_a_crash():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        main(["init", "--dir", str(root)])
        (root / "notes").mkdir()
        rc = main(["build", "--config", str(root / "corpusatlas.toml")])
        assert rc == 1


# --- build --cache ---------------------------------------------------------

def test_build_cache_round_trips_through_the_real_cli_and_matches_uncached():
    """--cache must never change what gets built — a cold build, a warm
    (cached) rebuild, and an uncached build of the same corpus all have to
    produce the exact same graph.json bytes."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        main(["init", "--dir", str(root)])
        notes = root / "notes"
        notes.mkdir()
        write(notes / "Hello.md", "A first note, linking to [[World]].")
        write(notes / "World.md", "The other note.")
        config = str(root / "corpusatlas.toml")
        cache_path = root / "cache.json"

        uncached_out = root / "uncached.json"
        assert main(["build", "--config", config, "--out", str(uncached_out)]) == 0

        cold_out = root / "cold.json"
        assert main(["build", "--config", config, "--out", str(cold_out),
                    "--cache", str(cache_path)]) == 0
        assert cache_path.exists()

        warm_out = root / "warm.json"
        assert main(["build", "--config", config, "--out", str(warm_out),
                    "--cache", str(cache_path)]) == 0

        assert uncached_out.read_bytes() == cold_out.read_bytes() == warm_out.read_bytes()


def test_version_flag_is_wired_and_matches_the_package():
    import io
    import contextlib
    from corpusatlas import __version__

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        try:
            main(["--version"])
        except SystemExit as e:
            assert e.code == 0
        else:
            raise AssertionError("--version should exit")
    assert __version__ in out.getvalue()
