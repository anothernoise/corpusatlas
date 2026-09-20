# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/) as closely as a package
with no `1.0` yet reasonably can.

## [0.8.0] — 2026-09-19

### Added
- **`corpusatlas diff --old OLD.json --new NEW.json`** — nodes and edges
  added, removed or changed between two built graphs, plus
  `--fail-on-change` for a CI gate asserting a rebuild is a no-op. `stats`,
  `validate` and `diff` all take `--json` now for machine-readable output.
- **`ontology-check --dot`** — renders a schema's own type/relation graph as
  Graphviz DOT (`Ontology.to_dot()`), for seeing the shape of a vocabulary
  while designing it, not just confirming it's internally consistent.
- **A real worked example of the entry-point plugin mechanism**:
  `examples/plugin-rss-adapter/`, a genuine installable package (a local
  RSS/Atom feed adapter) proven end to end — a fresh venv, two editable
  installs, a real `corpusatlas build` subprocess — not just the lookup
  logic in isolation.
- **`.github/workflows/release.yml`** — a `vX.Y.Z` tag push now cuts the
  GitHub Release automatically, extracting that version's own section from
  `CHANGELOG.md`. `CONTRIBUTING.md` documents the (now shorter) process.
- **`tests/test_adapter_conformance.py`** — a shared contract across
  html_blog, obsidian, logseq and web (non-empty id/title/url, kind is
  always "article", no self-links, no duplicate ids), so a future adapter
  drifting from what the other four already agree on gets caught here.

### Changed
- **Web adapter: connection reuse, retries, robots.txt, url dedup.**
  Persistent HTTP(S) connections per (worker thread, host) instead of a
  fresh TLS handshake per request — a 100-page Wikipedia benchmark went
  from 7.81s to 5.97s. Bounded retry with backoff on a transient failure.
  `respect_robots=True` by default: robots.txt fetched and cached once per
  host, a disallowed url skipped, a `Crawl-delay` honoured across every
  worker thread. Two urls that a browser would treat as the same page
  (trailing slash, fragment, case) collapse to one document.
- **`cmd_build` loads multiple sources concurrently** (one thread per
  source, same principle as the web adapter's own internal concurrency),
  instead of one after another. `BuildCache` gained a lock, since a shared
  `--cache` is now genuinely touched from more than one thread at once.
- **Viewer:** fixed a performance cliff at exactly 2,000 nodes — Barnes-Hut
  layout optimisation was gated on `g.order > 2000`, so a graph just under
  that threshold paid full brute-force O(n²) cost while one well over it
  didn't (measured: 2,000 nodes took longer to lay out than 5,000). Lowered
  to 200.

### Investigated, not changed
- **Memory and parallel-extraction at scale**
  (`scripts/profile_scale.py`, written up in `docs/DESIGN.md`): both scale
  roughly linearly, not quadratically, up to 20,000 synthetic documents
  (295MB peak, 27s). Adapter parsing dominates build time at every size
  tested (~50-59%) — exactly what `--cache` already addresses for a
  rebuild — so parallelizing extraction itself isn't worth the added
  complexity against a corpus that doesn't exist yet.
- **The viewer's node-count ceiling**
  (`scripts/synth_large_graph.py`, written up in the README): tested to
  10,000 entities in a real browser. Search and click-to-focus stay
  responsive at every size; only the one-time layout computation slows
  down (~29s at 10,000).

## [0.7.0] — 2026-09-19

### Added
- **`build --cache PATH`** — an opt-in on-disk cache that skips re-parsing
  an unchanged file in the `html_blog`, `obsidian` or `logseq` adapters.
  Scoped to file-parsing only, never extraction: a source's whole file-set
  fingerprint has to match exactly, or every file in it reparses, not just
  the ones that look different — coarse on purpose, so a stale cache can
  never silently miss a case where one file's change should affect another
  (a new note a dangling wikilink now resolves to, a re-tagged index page).
  See `corpusatlas/cache.py` and `docs/DESIGN.md`.
- **Plugin adapters.** `adapters.build()` now falls back to the
  `corpusatlas.adapters` entry-point group for a source `type` it doesn't
  recognise, so a third-party package (a Notion export, an RSS feed,
  Confluence) can register an adapter without forking this repo. The seven
  built-in names can never be shadowed by one. See `docs/adapters.md`.
- **`corpusatlas convert --format turtle`** — Turtle/RDF export, previously
  set aside as a modelling decision rather than a reformat. Nodes become
  resources under a configurable `--base`; an edge's relation is the
  predicate directly; confidence/explanation/scope/provenance ride on a
  standard `rdf:Statement` reification alongside the plain triple. See
  `corpusatlas/rdf_export.py` for the full reasoning.
- **`corpusatlas registry-check --entities entities.toml`** — validates an
  entity registry alone (duplicate ids, types not in the ontology), no
  corpus needed, the registry-side counterpart to `ontology-check`.
- **Concurrent fetching in the `web` adapter** (`max_workers`, default 8,
  stdlib `ThreadPoolExecutor`) — the only adapter that touches the network
  was also the only one paying for it serially. Output still yields in
  `urls`' own configured order regardless of fetch completion order.
- **`schema_version`** in `graph.json` (currently `1`) — lets a consumer
  detect an artifact-shape change independent of the package version that
  wrote it. `corpusatlas validate` warns, rather than fails, on a graph
  newer than the build understands.
- **`docs/quickstart.md`** — install through a rendered graph in about five
  minutes, verified end to end rather than hand-typed.
- **Viewer:** a label search box and click-to-focus — dims everything
  outside the selected node's neighbourhood, pans the camera there, and
  makes the card's own neighbour list clickable to refocus.
- **mypy in CI**, one matrix combination (like the coverage gate) — the
  `py.typed` marker and `"Typing :: Typed"` classifier had nothing actually
  enforcing them until now.
- Performance regression tests (`tests/test_perf.py`): a synthetic
  400-document build stays inside a generous time ceiling, and a `--cache`
  warm rebuild is meaningfully faster than a cold one.

### Fixed
- `README.md`'s install command was still pinned to `@v0.5.0` after the
  0.6.0 release.
- A handful of real type-annotation gaps mypy's first run surfaced (a wrong
  tuple element type in the mentions extractor's compiled-pattern cache, an
  unannotated dict in `model.py`); everything else is a documented
  `type: ignore` on two dynamic-dict-splat patterns mypy's stubs can't
  express statically.

## [0.6.0] — 2026-09-19

### Added
- **Logseq adapter** (`logseq`) — the seventh source. Same `[[wikilink]]`
  syntax as `obsidian`, but page properties are `key:: value` lines rather
  than YAML frontmatter, and every line is conventionally a bullet.
  Deliberately not a Roam adapter too — Roam's shape is similar, but its
  real export formats haven't been tested against this.
- `Ontology.extend()` — layer new entity types and relations onto an
  existing ontology (`DEFAULT` or a loaded one) instead of redeclaring the
  whole vocabulary to add a few things to it. Raises `OntologyError` on any
  name that collides with what's already there.
- `extends = "default"` in a schema file: the TOML-only equivalent of
  `DEFAULT.extend(...)` — everything else in the file layers onto the
  built-in ontology rather than replacing it.
- `corpusatlas ontology-check --schema X` — validates a schema file alone,
  no corpus or `[[sources]]` required.
- `corpusatlas init --dir X` — scaffolds a starter `corpusatlas.toml` (an
  `obsidian` source by default, since that adapter runs against any folder
  of markdown with no other setup) and an empty `entities.toml`.
- `corpusatlas build --dry-run` — reports node/edge counts without writing
  the artifact; `--out` is no longer required when `--dry-run` is set.
- `corpusatlas/py.typed` — the PEP 561 marker the `"Typing :: Typed"`
  classifier had claimed since 0.4.0 with nothing behind it.
- `corpusatlas --version`.
- `corpusatlas convert --format neo4j` — the same fields as the plain CSV
  pair, under Neo4j's own `:ID`/`:LABEL`/`:START_ID`/`:END_ID`/`:TYPE`
  header convention, so the output loads directly with `neo4j-admin
  database import` rather than needing a column-mapping step first.
- `CONTRIBUTING.md`, `CHANGELOG.md`, issue templates, `docs/adapters.md`.
- CI now runs on Windows too, not just Ubuntu, across all three supported
  Python versions.
- A coverage gate in CI (measured once, not per matrix combination;
  `--fail-under=85`).
- Dedicated tests for `html_blog`, `radar_scorecards` and `radar_entries` —
  previously exercised only indirectly, through hand-built `Document`
  objects that bypassed each adapter's own parsing. Found via a coverage
  run showing all three well under 60%, `html_blog` (the adapter
  shirokoff.ca's own build actually uses) at 42%.

### Fixed
- `html_blog`: every article's extracted text started with a stray `>` —
  splitting on the literal string `class="article-content"` left the rest
  of that div's opening tag (`>` and any later attributes) in the body,
  which the tag-stripping regex couldn't remove because it wasn't a
  complete `<...>` tag. Harmless to mention-matching in practice (confirmed:
  the real site's graph node/edge counts are unchanged), but a real defect,
  live in every build since this adapter existed — found while writing the
  test above, not looked for.

## [0.5.0] — 2026-09-19

### Added
- **Configurable ontology.** `Ontology` is a frozen dataclass now, not a set
  of module constants — every extractor, the resolver, and `write_graph`
  take `ontology=` and default to `DEFAULT`. A corpus in a different domain
  supplies its own vocabulary via `[ontology] schema` and
  `Ontology.from_toml()`, checked against the same closed-world rules
  `DEFAULT` has always had to satisfy. See `docs/ontology-schema.md`.
- **Obsidian vault adapter** (`obsidian`) — the sixth source. `[[wikilinks]]`
  become `REFERENCES` edges and `#tags`/frontmatter `tags:` become `ABOUT`
  edges, with no adapter-specific code on the extraction side.
- **Web adapter** (`web`) — a plain list of URLs, fetched at build time, for
  a corpus that isn't a local checkout.
- **`corpusatlas convert`** — reformats a built `graph.json` as GraphML
  (`--format graphml`) or a `nodes.csv`/`edges.csv` pair (`--format csv`),
  without re-running extraction.
- **`viewer/index.html`** — a ~150-line reference renderer for any
  `graph.json` this module builds.
- `docs/DESIGN.md` and `docs/ontology-schema.md`.
- `cmd_validate` now reads its vocabulary from the artifact's own
  `entity_types`/`context_types`/`relation_groups` rather than a static
  import, so a graph built from a custom ontology validates against its own
  vocabulary.

### Changed
- The `generator` field in `graph.json` is derived from `__version__`
  instead of being a separately hardcoded string (they had drifted before).
- `extract/packs.py`'s pack-URL prefixes (`blog_prefix`, `assessment_prefix`,
  ...) moved from hardcoded `shirokoff.ca` regexes to `[packs]` config keys.

## [0.4.0] — 2026-09-18

### Changed
- Extracted from the shirokoff.ca blog repo (`git subtree split`, history
  preserved) and renamed from `corpusgraph` — that name collides with an
  established information-retrieval term and an unrelated academic tool.
