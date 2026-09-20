"""Tests for the CLI additions: ontology-check, init, and build --dry-run.
Driven through main(argv) with real argv lists where it matters (the
argparse wiring itself, not just the underlying function), and against real
files on disk — init's whole point is producing something actually
buildable, so the test proves that by building it.
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from corpusatlas.__main__ import cmd_init, cmd_ontology_check, cmd_registry_check, main
from test_web_adapter import SLOW_DELAY, _serve

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


def test_ontology_check_dot_renders_every_type_and_relation():
    with tempfile.TemporaryDirectory() as d:
        schema = write(Path(d) / "ontology.toml", GOOD_SCHEMA)

        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert main(["ontology-check", "--schema", str(schema), "--dot"]) == 0
        dot = buf.getvalue()

        assert dot.startswith("digraph ontology {")
        assert dot.count("{") == dot.count("}") == 1
        assert '"Dish";' in dot
        assert '"Ingredient";' in dot
        assert '"Document" [shape=ellipse' in dot  # context type, different shape
        assert '"Dish" -> "Ingredient" [label="USES_INGREDIENT"' in dot


def test_ontology_check_dot_still_fails_on_a_broken_schema():
    with tempfile.TemporaryDirectory() as d:
        schema = write(Path(d) / "ontology.toml", BAD_SCHEMA)
        assert main(["ontology-check", "--schema", str(schema), "--dot"]) == 1


def test_default_ontology_to_dot_is_well_formed():
    from corpusatlas.ontology import DEFAULT
    dot = DEFAULT.to_dot()
    assert dot.count("{") == dot.count("}") == 1
    assert dot.startswith("digraph ontology {") and dot.rstrip().endswith("}")
    for t in DEFAULT.entity_types | DEFAULT.context_types:
        assert f'"{t}"' in dot


# --- registry-check --------------------------------------------------------

GOOD_ENTITIES = """
[[entity]]
id = "apache-spark"
name = "Apache Spark"
type = "Technology"

[[entity]]
id = "olap"
name = "OLAP"
type = "Concept"
"""

DUPLICATE_ID_ENTITIES = """
[[entity]]
id = "apache-spark"
name = "Apache Spark"
type = "Technology"

[[entity]]
id = "apache-spark"
name = "Apache Spark Again"
type = "Technology"
"""

UNKNOWN_TYPE_ENTITIES = """
[[entity]]
id = "a-dish"
name = "A Dish"
type = "Dish"
"""


def test_registry_check_accepts_a_valid_registry():
    with tempfile.TemporaryDirectory() as d:
        entities = write(Path(d) / "entities.toml", GOOD_ENTITIES)
        assert cmd_registry_check(type("Args", (), {"entities": str(entities), "schema": None})) == 0


def test_registry_check_rejects_a_duplicate_id():
    with tempfile.TemporaryDirectory() as d:
        entities = write(Path(d) / "entities.toml", DUPLICATE_ID_ENTITIES)
        assert cmd_registry_check(type("Args", (), {"entities": str(entities), "schema": None})) == 1


def test_registry_check_rejects_a_type_the_ontology_does_not_declare():
    with tempfile.TemporaryDirectory() as d:
        entities = write(Path(d) / "entities.toml", UNKNOWN_TYPE_ENTITIES)
        assert cmd_registry_check(type("Args", (), {"entities": str(entities), "schema": None})) == 1


def test_registry_check_honours_a_custom_schema():
    # "Dish" isn't a DEFAULT entity type, but it is in this custom schema —
    # the same registry that fails against DEFAULT should pass here.
    with tempfile.TemporaryDirectory() as d:
        schema = write(Path(d) / "ontology.toml", GOOD_SCHEMA)
        entities = write(Path(d) / "entities.toml", UNKNOWN_TYPE_ENTITIES)
        args = type("Args", (), {"entities": str(entities), "schema": str(schema)})
        assert cmd_registry_check(args) == 0


def test_registry_check_through_the_real_cli_argv():
    with tempfile.TemporaryDirectory() as d:
        entities = write(Path(d) / "entities.toml", GOOD_ENTITIES)
        assert main(["registry-check", "--entities", str(entities)]) == 0
        bad = write(Path(d) / "bad.toml", DUPLICATE_ID_ENTITIES)
        assert main(["registry-check", "--entities", str(bad)]) == 1


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


# --- multiple sources load concurrently -------------------------------------

def test_multiple_sources_load_concurrently_not_one_after_another():
    """Two web sources, each hitting a single SLOW_DELAY endpoint with its
    own concurrency turned off (max_workers=1) so this measures cmd_build's
    cross-source concurrency specifically, not WebAdapter's internal kind."""
    server = _serve()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with tempfile.TemporaryDirectory() as d:
            config = Path(d) / "corpusatlas.toml"
            config.write_text(f'''
[[sources]]
type = "web"
urls = ["{base}/slow/0"]
max_workers = 1
respect_robots = false

[[sources]]
type = "web"
urls = ["{base}/slow/1"]
max_workers = 1
respect_robots = false
''', encoding="utf-8")
            out = Path(d) / "graph.json"
            start = time.monotonic()
            rc = main(["build", "--config", str(config), "--out", str(out), "--dry-run"])
            elapsed = time.monotonic() - start
    finally:
        server.shutdown()

    assert rc == 0
    # Serial would be ~2x SLOW_DELAY; concurrent sources should land near 1x.
    assert elapsed < SLOW_DELAY * 1.8, f"took {elapsed:.2f}s — sources don't look concurrent"


def test_a_single_source_skips_the_thread_pool_and_still_works():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        main(["init", "--dir", str(root)])
        (root / "notes").mkdir()
        write(root / "notes" / "A.md", "Solo note.")
        out = root / "graph.json"
        rc = main(["build", "--config", str(root / "corpusatlas.toml"), "--out", str(out)])
        assert rc == 0
        assert out.exists()


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


# --- diff --------------------------------------------------------------

def _build(root: Path, notes: dict[str, str], out: Path) -> None:
    main(["init", "--dir", str(root)])
    vault = root / "notes"
    vault.mkdir(exist_ok=True)
    for name, text in notes.items():
        write(vault / f"{name}.md", text)
    assert main(["build", "--config", str(root / "corpusatlas.toml"), "--out", str(out)]) == 0


def test_diff_reports_no_differences_for_an_identical_graph():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        graph = root / "graph.json"
        _build(root, {"A": "Just a note."}, graph)
        assert main(["diff", "--old", str(graph), "--new", str(graph)]) == 0


def test_diff_finds_an_added_node_and_edge():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        old = root / "old.json"
        _build(root, {"A": "Links to [[B]].", "B": "hi"}, old)

        write(root / "notes" / "C.md", "New note.")
        write(root / "notes" / "A.md", "Links to [[B]] and [[C]].")
        new = root / "new.json"
        assert main(["build", "--config", str(root / "corpusatlas.toml"), "--out", str(new)]) == 0

        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = main(["diff", "--old", str(old), "--new", str(new)])
        assert rc == 0
        out = buf.getvalue()
        assert "+ node C" in out
        assert "+ edge A -REFERENCES-> C" in out
        assert "1 nodes added, 0 removed, 0 changed" in out


def test_diff_json_output_is_machine_parseable():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        old = root / "old.json"
        _build(root, {"A": "Links to [[B]].", "B": "hi"}, old)
        write(root / "notes" / "B.md", "hi, revised")  # content change, not link/type/label
        new = root / "new.json"
        assert main(["build", "--config", str(root / "corpusatlas.toml"), "--out", str(new)]) == 0

        import io, contextlib, json as json_mod
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            main(["diff", "--old", str(old), "--new", str(new), "--json"])
        result = json_mod.loads(buf.getvalue())
        assert result["changed"] is False  # B's prose isn't a tracked field (no tags/links changed)
        assert result["nodes_added"] == result["nodes_removed"] == []


def test_diff_fail_on_change_gates_ci_style_usage():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        old = root / "old.json"
        # A lone, unlinked note produces zero graph nodes — the wikilink is
        # what actually gives the deterministic tier something to build a
        # node from, and it's the change this test needs to be real.
        _build(root, {"A": "Links to [[B]].", "B": "hi"}, old)

        # identical rebuild: --fail-on-change must not fail
        new_same = root / "new_same.json"
        assert main(["build", "--config", str(root / "corpusatlas.toml"), "--out", str(new_same)]) == 0
        assert main(["diff", "--old", str(old), "--new", str(new_same), "--fail-on-change"]) == 0

        # a real change: --fail-on-change must fail
        write(root / "notes" / "C.md", "A third note.")
        write(root / "notes" / "A.md", "Links to [[B]] and [[C]].")
        new_diff = root / "new_diff.json"
        assert main(["build", "--config", str(root / "corpusatlas.toml"), "--out", str(new_diff)]) == 0
        assert main(["diff", "--old", str(old), "--new", str(new_diff), "--fail-on-change"]) == 1
        # without the flag, the same real change is just reported, not a failure
        assert main(["diff", "--old", str(old), "--new", str(new_diff)]) == 0


# --- --json on stats and validate -------------------------------------------

def test_stats_json_matches_human_readable_counts():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        graph = root / "graph.json"
        _build(root, {"A": "Links to [[B]].", "B": "hi"}, graph)

        import io, contextlib, json as json_mod
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert main(["stats", "--graph", str(graph), "--json"]) == 0
        result = json_mod.loads(buf.getvalue())
        assert result["counts"] == {"nodes": 2, "edges": 1}
        assert result["schema_version"] == 1
        assert "by_type" in result and "most_connected" in result


def test_validate_json_reports_problems_as_a_list():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        graph = root / "graph.json"
        _build(root, {"A": "Just a note."}, graph)

        import io, contextlib, json as json_mod
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert main(["validate", "--graph", str(graph), "--json"]) == 0
        result = json_mod.loads(buf.getvalue())
        assert result == {"valid": True, "problems": []}


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
 
 
def test_viewer_performance_assets_and_optimizations():
    """Verify that viewer app.js contains the critical performance optimizations:
    Barnes-Hut ForceAtlas2, comparison edge budgeting, idle-pausing particles,
    and requestAnimationFrame-coalesced hover refreshes."""
    viewer_dir = Path(__file__).resolve().parents[1] / "viewer"
    app_js = viewer_dir / "app.js"
    assert app_js.exists(), "viewer/app.js must exist"
    content = app_js.read_text(encoding="utf-8")

    assert "barnesHutOptimize: true" in content
    assert "barnesHutTheta: 0.8" in content
    assert "hasMassiveComparisons" in content
    assert "ensureComparisonEdgesLoaded" in content
    assert "checkParticlesState" in content
    assert "hoverRaf = requestAnimationFrame" in content
    assert "updateParticlesCanvasSize" in content


def test_viewer_modular_js_architecture():
    """Verify that viewer JavaScript is organized into modular ES files adhering to best practices:
    zero external build tooling, ES module imports, functional patterns, and clean separation."""
    viewer_dir = Path(__file__).resolve().parents[1] / "viewer"
    js_dir = viewer_dir / "js"
    assert js_dir.is_dir(), "viewer/js/ directory must exist"

    expected_modules = {
        "constants.js": ["TYPE_COLOR", "getTypeColor", "DEFAULTS", "MINIMAP_SIZE"],
        "utils.js": ["esc", "relText", "fmtDate", "clamp", "hashSeed", "loadSettings"],
        "algorithms.js": ["bfsDist", "shortestPath", "computeMultiPath", "computeCommunitiesFallback", "computeCentrality"],
        "context.js": ["buildContext", "TIER_TITLE", "tierChip", "contextHtml", "nodePinHtml", "edgePinHtml", "pathHtml"],
        "layouts.js": ["fa2Settings", "computeLayoutPositions", "switchLayout"],
        "particles.js": ["createParticleController"],
        "minimap.js": ["createMinimapController"],
    }

    for mod_name, expected_exports in expected_modules.items():
        mod_path = js_dir / mod_name
        assert mod_path.exists(), f"viewer/js/{mod_name} must exist"
        mod_content = mod_path.read_text(encoding="utf-8")
        for sym in expected_exports:
            assert sym in mod_content, f"viewer/js/{mod_name} must define or export {sym}"

    app_js = viewer_dir / "app.js"
    app_content = app_js.read_text(encoding="utf-8")
    for mod_name in expected_modules.keys():
        assert f"./js/{mod_name}" in app_content, f"viewer/app.js must import from ./js/{mod_name}"

    index_html = viewer_dir / "index.html"
    index_content = index_html.read_text(encoding="utf-8")
    assert '<script type="module" src="app.js"></script>' in index_content

