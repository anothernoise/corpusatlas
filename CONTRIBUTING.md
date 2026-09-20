# Contributing

## Setup

```bash
git clone https://github.com/anothernoise/corpusatlas.git
cd corpusatlas
pip install -e .      # installs the `corpusatlas` console script
python tests/run.py   # stdlib only — nothing else to install
```

No dependencies to lock, no virtualenv tooling required beyond what you
already have. That's deliberate — see `README.md`'s "The contract" for why,
and don't add a runtime dependency to fix a rough edge; find the stdlib way.

## Before you open a PR

- `python tests/run.py` passes. It auto-discovers every `tests/test_*.py` —
  a new file is picked up with no wiring.
- If you touched an adapter, test it against something real, not just a
  fixture shaped to be easy. `tests/test_obsidian_adapter.py` and
  `tests/test_web_adapter.py` are the pattern: real files on disk, a real
  local HTTP server — not everything mocked.
- If you touched the ontology, run the real site build too if you can
  (`corpusatlas build --config <a real corpusatlas.toml> --out /tmp/g.json`)
  and diff against a known-good `graph.json`. The test suite's own fixtures
  are small on purpose; a real corpus catches what a 6-node fixture won't.
- `corpusatlas --help` still lists every subcommand and each one's `--help`
  still makes sense — argparse won't tell you if a change made a flag's
  description stale.

## Style, such as it is

- Comments explain *why*, never *what* — a comment restating the line above
  it gets deleted, not merged. If you're explaining a non-obvious constraint,
  a past bug, or a tradeoff, that's exactly what a comment is for.
- Docstrings are honest about limitations, not just capabilities. See
  `adapters/web.py` and `adapters/obsidian.py` for the tone: "here's what
  this does, and here's specifically what it doesn't, on purpose."
- No third-party runtime dependencies. Dev-only tooling (a linter, a
  coverage tool) is a different question — ask in an issue first if you
  want to add one to CI.

## Adding a source adapter

An adapter is a class with one `documents()` method yielding `Document`s
(see `model.py`). The existing seven (`html_blog`, `obsidian`, `logseq`,
`radar_scorecards`, `radar_entries`, `entity_packs`, `web`) are the
reference for the shape — pick whichever is closest to your source and
start from there; `docs/adapters.md` has all seven side by side.

Belongs in this repo (register it in `adapters/__init__.py`'s `REGISTRY`)
if it's broadly useful and has no third-party dependency of its own. Belongs
in your own separately installed package instead (registered under the
`corpusatlas.adapters` entry-point group, see `docs/adapters.md`'s "Shipping
one as its own package") if it needs a dependency this project won't take
on, or if it's specific enough — a particular wiki platform, a particular
CMS's export format — that it's not this repo's to maintain.

Whichever adapter you write, run `tests/test_adapter_conformance.py`'s
checks against it too (or add it there) — id/title/url non-empty, `kind`
is `"article"`, `tags`/`links` are tuples, no self-links, no duplicate ids
in one batch. Every adapter already shipped here holds that contract; a new
one should too.

## Adding an output format

A converter (see `graphml.py`, `csv_export.py`) reads the artifact
(`graph.json`, already parsed) and writes another format — it never touches
extraction. Wire it into `corpusatlas convert`'s `--format` choices in
`__main__.py`.

## Releasing

1. Bump the version in both `corpusatlas/__init__.py` and `pyproject.toml`
   (they have to agree — nothing checks that automatically, so check it by
   eye).
2. Flip `CHANGELOG.md`'s `## [Unreleased]` section (or add a new one, dated
   today) to `## [X.Y.Z] — YYYY-MM-DD`.
3. Commit, then `git tag -a vX.Y.Z -m "corpusatlas X.Y.Z" && git push --tags`.
4. That's it — pushing the tag triggers `.github/workflows/release.yml`,
   which extracts that exact CHANGELOG section and cuts the GitHub Release
   from it. Check the Actions tab if a release doesn't appear; the most
   likely cause is the CHANGELOG heading not matching `## [X.Y.Z]` exactly
   (extra text after the version, or a version that doesn't match the tag).
5. If a consuming repo (shirokoff.ca's own CI, or anyone else's) pins a
   specific tag, bump it and verify locally before pushing — diff a fresh
   build's `graph.json` against the committed one with
   `corpusatlas diff --old committed.json --new fresh.json`; anything
   beyond the `generator`/`schema_version` fields means something changed
   that shouldn't have.

## Reporting a bug

Open an issue with the command you ran, what you expected, and what you
got. If it's about a specific corpus's output, a minimal `graph.json` (or
the config + a couple of source files) that reproduces it is worth more
than a description.
