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
(see `model.py`). Register it in `adapters/__init__.py`'s `REGISTRY`. The
existing six (`html_blog`, `obsidian`, `radar_scorecards`, `radar_entries`,
`entity_packs`, `web`) are the reference for the shape — pick whichever is
closest to your source and start from there.

## Adding an output format

A converter (see `graphml.py`, `csv_export.py`) reads the artifact
(`graph.json`, already parsed) and writes another format — it never touches
extraction. Wire it into `corpusatlas convert`'s `--format` choices in
`__main__.py`.

## Reporting a bug

Open an issue with the command you ran, what you expected, and what you
got. If it's about a specific corpus's output, a minimal `graph.json` (or
the config + a couple of source files) that reproduces it is worth more
than a description.
