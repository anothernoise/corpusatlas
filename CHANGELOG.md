# Changelog

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
versioning follows [SemVer](https://semver.org/) as closely as a package
with no `1.0` yet reasonably can.

## [Unreleased]

### Added
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
