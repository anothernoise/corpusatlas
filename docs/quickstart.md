# Quickstart

Five minutes, no real corpus needed yet — a handful of throwaway notes is
enough to see a graph come out the other end. Everything here runs from an
empty directory.

## 1. Install

```bash
pip install git+https://github.com/anothernoise/corpusatlas@v0.10.0
# Or with optional high-performance tabular engines:
pip install "corpusatlas[all]"
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

## 6. Advanced Discovery, Graph RAG, Analytics & Export
 
- **Model Context Protocol (MCP) Server**: Expose the knowledge graph directly to AI coding assistants (Claude Desktop, Cursor, Gemini Antigravity) via JSON-RPC 2.0 over standard I/O:
  ```bash
  corpusatlas serve-mcp --graph graph.json
  ```
- **Hybrid BM25 + PPR Context Retrieval**: Combine lexical keyword relevance (Okapi BM25) and topological centrality (Personalized PageRank) via Reciprocal Rank Fusion:
  ```bash
  corpusatlas context --graph graph.json --entity spark --algorithm hybrid --top-k 20 --format markdown
  ```
- **Hierarchical Community Clustering**: Group nodes into topical clusters maximizing Louvain modularity ($Q$):
  ```bash
  corpusatlas cluster --graph graph.json --out clustered.json
  ```
- **Bi-Temporal Historical Snapshots**: Query point-in-time graph states or scrub timeline intervals:
  ```bash
  corpusatlas as-of --graph graph.json --date "2024-01-01" --out snapshot_2024.json
  ```
- **Out-of-Core Staging Engines**: Stage and deduplicate large corpora in SQLite or DuckDB:
  ```bash
  corpusatlas build --config corpusatlas.toml --out graph.json --store sqlite --db-path staging.db
  ```
- **Performance Telemetry Micro-Benchmarks**: Measure engine throughput across layout, scanning, and Datalog fixpoints:
  ```bash
  corpusatlas benchmark --quick
  ```
- **Knowledge Graph Quality & Topological Audit**: Inspect graph health, Gini network concentration, bridge bottlenecks, cycle anomalies, and contradictory claims:
  ```bash
  corpusatlas audit --graph graph.json
  ```
- **Multi-Format Export (DuckDB, Parquet, Cypher, RDF Turtle)**: Export graph data for SQL analytics, columnar storage, or graph databases:
  ```bash
  corpusatlas export --graph graph.json --format duckdb --out-dir duckdb_export/
  corpusatlas export --graph graph.json --format cypher --out graph.cql
  corpusatlas export --graph graph.json --format turtle --out graph.ttl
  ```
- **Spatial Quadtree LOD Tiling**: Partition 2D layout into multi-resolution tiles (`tiles/{z}/{x}_{y}.json`) for streaming large graphs without loading them all at once:
  ```bash
  corpusatlas tile --graph graph.json --out-dir tiles/ --max-zoom 3
  ```
- **Declarative Schema Refactoring & Migration**: Evolve node and edge types without re-running full builds:
  ```bash
  corpusatlas migrate --graph graph.json --migration migration.toml --out migrated.json
  ```
- **Pre-computed 2D Layout (Barnes-Hut Quadtree)**: Calculate $O(N \log N)$ force-directed node coordinates during build for instantaneous first-frame browser rendering:
  ```bash
  corpusatlas build --config corpusatlas.toml --out graph.json --layout
  ```
- **Zero-Config Static Publishing**: Bundle viewer HTML, CSS, JS and `graph.json` into a deployable distribution directory:
  ```bash
  corpusatlas publish --graph graph.json --out-dir dist/
  ```
- **Live File Watcher**: Auto-rebuild on any document or configuration edit:
  ```bash
  corpusatlas watch --config corpusatlas.toml --out graph.json
  ```

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
- **Try a 1,000-page real-world benchmark.** Fetch and compile 1,000 Wikipedia
  animal articles with `python3 scripts/fetch_wikipedia_animals.py` and benchmark
  cold/warm performance with `python3 scripts/benchmark_animals.py`.
- **The full design reasoning** — why entity resolution is the real work,
  what's fixed on purpose versus configurable, the three extraction tiers —
  is in [docs/DESIGN.md](DESIGN.md) and the main
  [README](../README.md).

