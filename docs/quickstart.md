# Quickstart

Five minutes, no real corpus needed yet — a handful of throwaway notes is
enough to see a graph come out the other end. Everything here runs from an
empty directory.

## 1. Install

```bash
pip install git+https://github.com/anothernoise/corpusatlas@v0.8.0
```

No third-party dependencies, so this is the whole install.

## 2. Scaffold a config

```bash
mkdir my-corpus && cd my-corpus
corpusatlas init
```

This writes `corpusatlas.toml` (pointing at a `notes/` directory, the
`obsidian` adapter) and an empty `entities.toml`. `init` picks the
`obsidian` adapter specifically because it runs against any folder of
markdown, wikilinks or not — nothing to configure before it produces
something.

## 3. Write a few notes

```bash
mkdir notes
cat > notes/spark.md <<'EOF'
# Apache Spark

A distributed processing engine. Often compared to [[flink]] for streaming
workloads. #data-engineering
EOF

cat > notes/flink.md <<'EOF'
# Apache Flink

Another distributed stream processor, an alternative to [[spark]].
#data-engineering
EOF
```

The `[[wikilink]]`s will become `REFERENCES` edges and the `#tag` will
become an `ABOUT` edge — no code, no config, the deterministic tier already
knows what to do with both.

## 4. See what it would build, then build it

```bash
corpusatlas build --config corpusatlas.toml --out graph.json --dry-run
```

```
  obsidian                2 documents
  deterministic@2         3 nodes, 4 edges
  packs@2                 0 nodes, 0 edges
  mentions@2               0 nodes, 0 edges

(dry run) would write 3 nodes, 4 edges — nothing written
```

(3 nodes because `#data-engineering` becomes its own `Topic` node, shared by
both articles — 2 notes plus the tag they have in common; 4 edges because
each note both references the other and is `ABOUT` the shared tag.)

Drop `--dry-run` once that looks right:

```bash
corpusatlas build --config corpusatlas.toml --out graph.json
corpusatlas stats --graph graph.json
corpusatlas validate --graph graph.json
```

## 5. Look at it

```bash
curl -o viewer.html https://raw.githubusercontent.com/anothernoise/corpusatlas/master/viewer/index.html
python3 -m http.server 8000
# open http://localhost:8000/viewer.html?graph=./graph.json
```

Or point the same viewer at any `graph.json` this module has ever built,
including [shirokoff.ca's own](https://shirokoff.ca/knowledge-base/graph.json):
`viewer.html?graph=https://shirokoff.ca/knowledge-base/graph.json`.

## Where to go from here

- **A real corpus.** Point `corpusatlas.toml` at an actual vault, or add an
  `html_blog` / `logseq` / `web` source alongside `obsidian` — see
  [docs/adapters.md](adapters.md) for what each one reads.
- **Named entities, not just wikilink-derived ones.** Add entries to
  `entities.toml` so "Apache Spark" is a typed `Technology` with a stable
  id, not just a slug node — `corpusatlas registry-check --entities
  entities.toml` validates the registry on its own as you write it, no
  corpus needed.
- **A vocabulary that isn't data/infrastructure architecture.** See
  [docs/ontology-schema.md](ontology-schema.md) — `corpusatlas ontology-check
  --schema ontology.toml` validates a custom schema the same standalone way.
- **A faster rebuild loop on a large corpus.** Add `--cache
  .corpusatlas_cache.json` to the build command once re-parsing an unchanged
  corpus starts taking long enough to notice.
- **The full design reasoning** — why entity resolution is the real work,
  what's fixed on purpose versus configurable, the three extraction tiers —
  is in [docs/DESIGN.md](DESIGN.md) and the main
  [README](../README.md).
