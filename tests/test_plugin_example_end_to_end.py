"""Proves the corpusatlas.adapters entry-point mechanism end to end, with a
*real* separately installed package — not the fake in-process entry point
test_adapters_plugin.py uses to test adapters.build()'s own lookup logic in
isolation. This is slower (a fresh venv, two editable installs) and
deliberately so: test_adapters_plugin.py proves the lookup code is correct;
this proves the actual documented workflow — pip install a plugin package,
reference its `type` in a config, corpusatlas build resolves it — really
works, using examples/plugin-rss-adapter as that real package.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "plugin-rss-adapter"

FEED = """<?xml version="1.0"?>
<rss version="2.0">
<channel>
<title>Example Feed</title>
<item>
<title>Hello World</title>
<link>https://example.org/hello-world</link>
<description>A first post.</description>
<pubDate>Wed, 02 Oct 2002 15:00:00 GMT</pubDate>
</item>
</channel>
</rss>
"""


def test_the_example_plugin_package_installs_and_resolves_via_corpusatlas_build():
    if not EXAMPLE.exists():
        raise AssertionError(f"expected the example plugin package at {EXAMPLE}")

    with tempfile.TemporaryDirectory() as d:
        venv_dir = Path(d) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True,
                       capture_output=True, text=True)
        # A venv's executables live under Scripts\ with a .exe suffix on
        # Windows, bin/ with no suffix everywhere else.
        bin_dir = venv_dir / ("Scripts" if sys.platform == "win32" else "bin")
        suffix = ".exe" if sys.platform == "win32" else ""
        pip = str(bin_dir / f"pip{suffix}")
        corpusatlas_bin = str(bin_dir / f"corpusatlas{suffix}")

        # Installs corpusatlas itself too, since the example package
        # declares it as a dependency (dependencies=["corpusatlas"]).
        install = subprocess.run([pip, "install", "-q", "-e", str(ROOT), "-e", str(EXAMPLE)],
                                 capture_output=True, text=True)
        assert install.returncode == 0, f"pip install failed:\n{install.stdout}\n{install.stderr}"

        root = Path(d)
        (root / "feed.xml").write_text(FEED, encoding="utf-8")
        (root / "corpusatlas.toml").write_text(
            '[[sources]]\ntype = "rss"\npath = "feed.xml"\n', encoding="utf-8")

        build = subprocess.run(
            [corpusatlas_bin, "build", "--config", str(root / "corpusatlas.toml"),
            "--out", str(root / "graph.json")],
            capture_output=True, text=True, cwd=str(root))
        assert build.returncode == 0, f"corpusatlas build failed:\n{build.stdout}\n{build.stderr}"
        assert "rss" in build.stdout  # the source line names its own type

        import json
        graph = json.loads((root / "graph.json").read_text(encoding="utf-8"))
        # A lone RSS item with no links/tags produces no graph nodes (same as
        # a lone unlinked obsidian note) — the point here is that the source
        # loaded through the real plugin mechanism at all, which the printed
        # "rss  1 documents" line and a clean exit code already establish.
        assert "1 documents" in build.stdout
        assert graph["sources"] == ["rss (1)"]
