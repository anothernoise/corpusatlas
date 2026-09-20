# corpusatlas

[![CI](https://github.com/anothernoise/corpusatlas/actions/workflows/ci.yml/badge.svg)](https://github.com/anothernoise/corpusatlas/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-%E2%89%A585%25-brightgreen.svg)](.github/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/anothernoise/corpusatlas?color=blue&logo=github)](https://github.com/anothernoise/corpusatlas/releases)
[![Dependencies](https://img.shields.io/badge/dependencies-0%20runtime-success.svg)](#)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

Turn a corpus of markdown and structured data into a knowledge graph you can
ship as a static file.

Built for the case described in
[Build-Time Knowledge Graphs](https://shirokoff.ca/blog/build-time-knowledge-graph):
a few hundred to a few thousand documents, where the whole graph fits in a
browser tab and a graph database would be an operational cost with no payoff.
[docs/DESIGN.md](docs/DESIGN.md) has the reasoning condensed for this repo —
the size table, why entity resolution is the real work, and what's actually
flexible here versus fixed on purpose. New here? [docs/quickstart.md](docs/quickstart.md)
gets a graph out of a handful of throwaway notes in about five minutes.

## The contract

Two rules keep this a module rather than a framework:

1. **Sources are adapters.** Every adapter yields the same `Document` shape.
   The core never learns the name of your blog, your book, or your CMS. Ships
   with eleven built-in adapters: markdown notes (`obsidian`, `logseq`), rendered
   HTML (`html_blog`), Notion workspaces (`notion`), Confluence spaces
   (`confluence`), GitHub issues & PRs (`github`), tabular DataFrames / Arrow /
   dicts (`dataframe`), curated entity packs (`entity_packs`), Architecture Radar
   scorecards and entries (`radar_scorecards`, `radar_entries`), and a list of
   URLs (`web`). See `corpusatlas/adapters/` and [docs/adapters.md](docs/adapters.md)
   for what each one handles. A new source is a class with one `documents()`
   method; you can copy one or ship yours as an external package via the
   `corpusatlas.adapters` entry-point group without forking this repo.
2. **Output is files.** `corpusatlas` writes `graph.json` and exits. It owns no
   process, serves no requests, and has no opinion about what reads the output.

```
adapters → resolve → extract (deterministic, then curated) → merge → graph.json
```

## Install and run

No third-party dependencies. Python 3.11+.

```bash
pip install git+https://github.com/anothernoise/corpusatlas@v0.11.0
# Or with optional high-performance columnar extras:
pip install "corpusatlas[all]"

corpusatlas init --dir my-corpus    # a starter config + entity registry
# edit my-corpus/corpusatlas.toml to point `path` at your notes, then:
corpusatlas build --config my-corpus/corpusatlas.toml --out graph.json --dry-run   # counts, nothing written
corpusatlas build --config my-corpus/corpusatlas.toml --out graph.json
corpusatlas stats    --graph graph.json
corpusatlas validate --graph graph.json
```

`init` scaffolds an `obsidian` source by default — point it at any directory
of markdown and it runs immediately, wikilinks or not. `example.toml` (below)
shows every adapter's shape but points at a real corpus's own directories, so
it isn't runnable as-is the way `init`'s output is.

Iterating on a custom ontology or a registry doesn't need a corpus at all:

```bash
corpusatlas ontology-check --schema ontology.toml
corpusatlas ontology-check --schema ontology.toml --dot | dot -Tsvg -o ontology.svg
corpusatlas registry-check --entities entities.toml
```

`--dot` renders the schema's own type/relation graph as Graphviz DOT — the
vocabulary itself, not any data built against it, useful while actually
designing one rather than only checking it's internally consistent.

On a large corpus, `build --cache .corpusatlas_cache.json` skips re-parsing
any `html_blog`/`obsidian`/`logseq` file whose content hasn't changed since
the last build at that cache path — opt-in, and never changes what gets
built, only how long it takes.

`corpusatlas diff --old OLD.json --new NEW.json` compares two built graphs —
nodes and edges added, removed or changed — and `--fail-on-change` turns
that into a gate: exit 1 if they differ at all, for a CI step asserting a
rebuild is a no-op (exactly the check this project's own release process
runs by hand before every release). `stats`, `validate` and `diff` all take
`--json` for machine-readable output instead of the default text.

Working on the module itself:

```bash
pip install -e .          # installs the `corpusatlas` console script
python tests/run.py       # invariant tests, stdlib only
```

`python3 -m corpusatlas …` works too, without installing — the console script
and the module entry point are the same `main()`.

## Configuration

```toml
[[sources]]
type     = "html_blog"          # adapter name
path     = "../blog"
url_base = "/blog/"

[[sources]]
type = "radar_scorecards"
path = "../architecture-radar/scorecards.json"

[[sources]]
type = "radar_entries"
path = "../architecture-radar/radar.json"

[[sources]]
type     = "entity_packs"
path     = "entities"
url_base = "/knowledge-base/entities/"

[ontology]
entities = "entities.toml"

# Packs cite their sources by URL; the graph joins on document id. This says
# how to get from one to the other, and defaults to the values below minus
# site_url — a corpus published under /blog/ can leave the section out.
[packs]
site_url             = "https://example.org"
blog_prefix          = "/blog/"
assessment_prefix    = "/architecture-radar/"
assessment_id_prefix = "assessment:"
```

Every path resolves relative to the config file, so the config lives with the
corpus and this module stays portable. See `example.toml`.

## Ontology

Two kinds of node, and the split is the design:

- **Entities** are what the graph is about. `DEFAULT` (this package's own,
  used unless a build says otherwise) has 14 types: `Concept`,
  `ArchitecturePattern`, `Technology`, `Component`, `Language`, `API`,
  `Protocol`, `Standard`, `FileFormat`, `TableFormat`, `Product`,
  `CloudService`, `Company` and `UseCase`. Ids are type-neutral
  (`entity:<slug>`), so reclassifying something never changes its id.
- **Context** is where claims were published: `Document` (an article),
  `Assessment`, `RadarEntry` and `Topic`.

Semantic relations (`IMPLEMENTS`, `HAS_COMPONENT`, `READS`, `RUNS_ON`,
`MANAGED_BY`, `ALTERNATIVE_TO`, ...) join entities. Context relations
(`COVERS`, `HAS_RADAR_ENTRY`, `ASSESSES`, ...) join entities to their
evidence. `corpusatlas validate` refuses a semantic edge that touches a
context node. The artifact carries `entity_types` and `inverse_labels`, so a
renderer never hard-codes the split.

**The vocabulary itself is an `Ontology` value, not a fixed set of
constants.** `DEFAULT` is a data-and-infrastructure-architecture ontology,
built for this package's own use, and every extractor, the resolver and
`write_graph` take an `ontology=` parameter and use it instead of reaching
for a module global — which is what lets a build actually swap it out. A
corpus about something else entirely — cooking, case law, whatever — gets its
own types and relations from a schema file:

```toml
# in your corpus's config
[ontology]
entities = "entities.toml"   # unchanged: named instances of the types below
schema   = "ontology.toml"   # new: the types and relations themselves
```

See [docs/ontology-schema.md](docs/ontology-schema.md) for the file format
and a complete worked example, and [docs/DESIGN.md](docs/DESIGN.md) for why
the id scheme and the three extraction tiers stay fixed regardless — those
are structural, not vocabulary.

The **entity registry** (`entities.toml`) is the vocabulary. It gives each
entity a name, type, aliases and links. It also lists the scorecard options,
radar entries and blog tags that name the entity, so one option can name two
entities ("Druid / Pinot"):

```toml
[[entity]]
id      = "apache-druid"
name    = "Apache Druid"
type    = "Technology"
options = ["Apache Druid", "Druid / Pinot"]
case_sensitive = true      # text matching respects case
```

## Extraction tiers

Three tiers run in order, and merge keeps the first writer. A later tier can
add links, aliases and descriptions to an entity, but never change its label
or type.

**Deterministic.** Links, tags, scorecards and radar entries, resolved
through the registry. Exact, free and instant.

**Curated: entity packs.** One JSON file per subject: typed entities, and
typed relationships, each with a confidence and an explanation. Packs are
drafted offline and machine-checked. Nothing in the build calls a model. A
pack is yielded as a `Document`, so every curated edge names its pack, and
deleting the file retracts all of it. An ill-typed relationship, or one that
contradicts the registry, fails the build.

**Extracted: mentions.** Word-boundary matching of every entity's name and
aliases over article text, with a minimum-occurrence bar. Companies are not
matched. It produces `COVERS` edges tagged `extracted`. No model; the output
is byte-identical on every run.

## Provenance

Every edge carries where it came from:

```json
{
  "src": "entity:clickhouse", "rel": "COMPARES_TO", "dst": "entity:starrocks",
  "prov": { "doc": "starrocks-vs-clickhouse-vs-doris", "tier": "deterministic",
            "extractor": "deterministic@2", "via": "scorecard" }
}
```

An edge is a claim made *by* a document. When the document goes, the claim goes
with it — `merge.py` handles retraction, not just append.

## Interactive Web Viewer

`viewer/index.html` provides a zero-build, dependency-free interactive WebGL knowledge graph viewer designed for exploratory analysis and documentation embeds:

- **Full-Text Fuzzy Search & Typeahead**: Subsequence fuzzy matching with typo tolerance, prefix boosts, and word-boundary ranking across entities, descriptions, and aliases.
- **3D Force-Directed Graph Mode**: Seamlessly switch between 2D canvas and 3D WebGL force-directed space for complex topology exploration.
- **Vector & Subgraph Export**: One-click export to scalable vector graphics (**SVG**), high-res **PNG**, **Gephi GEXF 1.2 XML**, **GraphML XML**, and filtered JSON subgraphs.
- **Temporal Graph Evolution Player**: Time-travel scrubber animating graph growth and entity arrivals across historical dates and snapshots.
- **Topological Clusters & Centrality Insights**: Community overlays (Louvain modularity) and on-demand hub rankings (Degree, PageRank, Betweenness).
- **Smooth Navigation & Minimap**: Camera history (back/forward), calibrated minimap with pan tracking, and directional particle flow animations.

![The reference viewer showing shirokoff.ca's 214-entity graph, type-coloured, with Apache Spark focused and its neighbours listed on the right](docs/images/viewer-screenshot.jpg)

```bash
corpusatlas build --config your-corpus.toml --out viewer/graph.json
python3 -m http.server 8000 --directory viewer
# open http://localhost:8000/
```

(`example.toml`'s paths point at a real corpus's directories, so it won't
build on its own inside a clone of this repo — swap in your own config, or
pass `?graph=<url>` to point the viewer at any already-built `graph.json`,
shirokoff.ca's included.)

**How far this scales.** Measured against synthetic graphs (dense,
uniformly random edges — worse than a real corpus's natural clustering):
1,000 entities loads in ~2s, 2,000 in ~4s, 5,000 in ~12s, 10,000 in ~29s.
Search and click-to-focus stay responsive at every size tested — it's only
the one-time ForceAtlas2 layout that gets slower, not runtime interaction
afterward. Shirokoff.ca's own graph (214 entities) is nowhere near where
this starts to matter. A real fix for a much larger graph would be
precomputing layout coordinates at build time instead of laying out in the
browser on every load; not done here since nothing this module's own
consumer has needs it yet.

## Storage Engines & Out-of-Core Build

For corpora with hundreds of thousands of claims, `corpusatlas build` supports out-of-core deduplication and staging engines:

```bash
# In-memory deduplication (default):
corpusatlas build --config corpusatlas.toml --out graph.json --store memory

# Disk-backed SQLite staging (bounded memory footprint):
corpusatlas build --config corpusatlas.toml --out graph.json --store sqlite --db-path staging.db

# DuckDB-backed analytical staging:
corpusatlas build --config corpusatlas.toml --out graph.json --store duckdb --db-path staging.duckdb
```

## DataFrame Interoperability & Ingestion

CorpusAtlas provides first-class, zero-copy interoperability with Polars, Apache Arrow, and Pandas (`pip install corpusatlas[all]`):

```python
import corpusatlas as ca

# Load graph into tabular dataframes
graph_data = ca.load_graph("graph.json")

# Zero required dependencies — standard dict records
records = graph_data.to_dict_records()

# Optional high-performance columnar formats:
nodes_pl, edges_pl = graph_data.to_polars()
nodes_pa, edges_pa = graph_data.to_arrow()
nodes_df, edges_df = graph_data.to_pandas()
```

Tabular sources can also be ingested directly via `DataFrameAdapter`:
```python
from corpusatlas.adapters.dataframe import DataFrameAdapter

adapter = DataFrameAdapter({"nodes": my_nodes_df, "edges": my_edges_df})
docs = list(adapter.documents())
```

## Graph RAG, Analytics & Advanced Tooling

Beyond building static graphs, CorpusAtlas provides a comprehensive zero-dependency backend toolkit:

### 1. GraphRAG Subgraph Context Extractor (`rag`)
Extract $k$-hop subgraphs around query keywords or entities, bounded by a target LLM token budget, formatted for immediate prompt injection:
```bash
# Markdown prompt context for LLMs (default):
corpusatlas rag --graph graph.json --query "Apache Spark" --k-hops 2 --token-budget 2000

# JSON structured context:
corpusatlas rag --graph graph.json --query "Spark" --format json
```

### 2. Natural Language Graph Query (`query --ask`)
Translate plain-English questions into graph traversals, shortest paths, comparisons, dependencies, and hub rankings:
```bash
corpusatlas query --graph graph.json --ask "What technologies connect to Apache Spark?"
corpusatlas query --graph graph.json --ask "How is Airflow connected to Kafka?"
corpusatlas query --graph graph.json --ask "Compare PostgreSQL and Spark"
```

### 3. In-Memory W3C SPARQL 1.1 Engine (`sparql`)
Query entities, types, and relationships using standard SPARQL pattern matching directly over the graph:
```bash
corpusatlas sparql --graph graph.json --query "SELECT ?tech ?db WHERE { ?tech a :Technology . ?tech :writes_to ?db }"
```

### 4. Graph Topology & Health Analytics (`analyze`)
Compute network topology metrics, component sizes, articulation points (single points of failure / SPOF via Hopcroft-Tarjan), and an overall health score (0–100):
```bash
corpusatlas analyze --graph graph.json
corpusatlas analyze --graph graph.json --json
```

### 5. Declarative Architecture Linter (`lint`)
Enforce architectural boundaries, forbidden cross-tier edges (e.g. Presentation $\to$ Database), required metadata attributes, and acyclic dependencies in CI/CD (exits with code 1 on violations):
```bash
corpusatlas lint --graph graph.json --rules architecture_rules.toml
```

### 6. Model Context Protocol (MCP) Server (`serve-mcp`)
Expose your knowledge graph to AI coding assistants (Claude Desktop, Cursor, Gemini Antigravity) over standard I/O:
```bash
corpusatlas serve-mcp --graph graph.json
```
Available tools:
- `search_nodes(query, type_filter)`: Substring and alias search.
- `extract_context_ppr(entity, top_k, alpha)`: Personalized PageRank ego-network retrieval.
- `traverse_subgraph(start_node_id, depth, allowed_rels)`: Bounded BFS expansion.
- `audit_graph()`: Topological health, bridge detection, and cycle metrics.
- `get_provenance(edge_id)`: Source document audit trail and confidence.

### 2. Hybrid BM25 + PPR Search with Reciprocal Rank Fusion
Combines lexical keyword relevance (Okapi BM25) with topological graph centrality (Personalized PageRank) using Reciprocal Rank Fusion:
```bash
corpusatlas context --graph graph.json --entity "Apache Spark" --algorithm hybrid --top-k 20
```

### 3. Hierarchical Community Detection (Louvain Modularity)
Clusters the knowledge graph into thematic communities by maximizing modularity ($Q$):
```bash
corpusatlas cluster --graph graph.json --resolution 1.0 --out clustered_graph.json
```

### 4. Bi-Temporal Historical Snapshots (`as-of`)
Filter graphs to point-in-time states using valid-time (`valid_from`, `valid_to`) intervals and transaction time:
```bash
corpusatlas as-of --graph graph.json --date "2024-01-01" --out snapshot_2024.json
```
In the interactive viewer, a timeline scrubber slider provides real-time playback of graph evolution over time.

### 5. Performance Telemetry & Automated Micro-Benchmarks
Measure core engine throughput across Barnes-Hut layout, Aho-Corasick scanning, and Datalog fixpoint evaluation:
```bash
corpusatlas benchmark --quick
corpusatlas benchmark --json
```

### 6. Knowledge Graph Auditing & Quality Metrics
Run topological graph health checks to identify cycle anomalies, bridge bottlenecks, hub concentration, and contradictory relations:
```bash
corpusatlas audit --graph graph.json
```
Computes:
- **Degree Gini Coefficient**: Measure network centralization and power-law distribution.
- **Bridge Edge Detection**: Single points of topological failure using Tarjan's bridge algorithm.
- **Hierarchical Cycle Detection**: Detects invalid circular taxonomic/hierarchical relations.
- **Contradiction Detection**: Flags conflicting reciprocal relationships between identical entities.

### 7. Declarative Schema Migration
Refactor entity types and relationship names on an existing `graph.json` without re-running long corpus builds:
```bash
corpusatlas migrate --graph graph.json --migration migration.toml --out migrated.json
```

### 8. Spatial Quadtree LOD Tiling & Streaming Viewer
For massive graphs, partition 2D layout coordinates into a multi-resolution quadtree pyramid for client-side streaming:
```bash
corpusatlas tile --graph graph.json --out-dir tiles/ --max-zoom 3
```
Emits `tiles/{z}/{x}_{y}.json` and `manifest.json`. The web viewer automatically streams visible bounding-box tiles on zoom and pan.

### 9. Multi-Format Export (DuckDB, Parquet, Cypher, RDF Turtle)

Export `graph.json` for analytical SQL engines, columnar storage, and graph databases:

```bash
# Export to DuckDB database, Apache Parquet, CSV, and SQL import script:
corpusatlas export --graph graph.json --format duckdb --out-dir duckdb_export/

# Export to Cypher statements for Neo4j / AWS Neptune:
corpusatlas export --graph graph.json --format cypher --out graph.cql

# Export to W3C RDF Turtle for SPARQL triple-stores:
corpusatlas export --graph graph.json --format turtle --out graph.ttl
```

When DuckDB CLI is installed on the host system, `export --format duckdb` automatically invokes DuckDB to build native `.duckdb` and `.parquet` files directly without requiring any third-party Python pip dependencies!

### 10. Datalog-Lite Fixpoint Rule Inference
Deduce implicit transitive, symmetric, or custom relational rules using forward-chaining fixpoint evaluation:
```python
from corpusatlas.datalog import DatalogEngine, Rule
engine = DatalogEngine(rules=[
    Rule(head_rel="PART_OF", body_rels=("PART_OF", "PART_OF"), confidence_factor=0.9)
])
inferred_edges = engine.evaluate(edges)
```

### 11. Sub-Quadratic MinHash / LSH Deduplication
Cluster and deduplicate near-identical entities using character $k$-shingles, 64 universal hash permutations, and Locality-Sensitive Hashing (LSH) without $O(N^2)$ all-pairs comparisons:
```python
from corpusatlas.minhash import MinHashLSH
lsh = MinHashLSH(threshold=0.8)
clusters = lsh.cluster_entities(nodes)
```

### 12. Declarative SHACL Shape Validation
Enforce domain/range constraints, required properties, regex patterns, and cardinality bounds on knowledge graphs:
```python
from corpusatlas.shacl import SHACLValidator
validator = SHACLValidator.from_toml("shapes.toml")
results = validator.validate(nodes, edges)
```

### 13. Remote Wikidata Taxonomy Linker
Resolve local entity nodes to Wikidata QIDs, concept descriptions, and Wikipedia links with offline fallback caching:
```python
from corpusatlas.link import link_entity_to_wikidata
link_info = link_entity_to_wikidata("Apache Spark")
# {'qid': 'Q3011409', 'label': 'Apache Spark', 'url': 'https://www.wikidata.org/wiki/Q3011409', ...}
```

### 14. Vector Embedding & Cosine Similarity Index
Pure Python embedding vector store with nearest neighbor search and semantic similarity edge materialization (`SIMILAR_TO`):
```python
from corpusatlas.vector import VectorIndex
vindex = VectorIndex()
vindex.add("entity:spark", [0.12, 0.85, ...])
similar = vindex.nearest_neighbors("entity:spark", top_k=5)
```

### 15. Zero-Dependency Local REST API Daemon (`serve-api`)
Serve your knowledge graph over standard HTTP with multi-threaded request processing, CORS preflight headers, and ETag caching (`304 Not Modified`):
```bash
corpusatlas serve-api --graph graph.json --port 8080
```
Endpoints:
- `GET /`: Health check, API version, and graph metadata.
- `GET /stats`: Breakdown of node and edge types.
- `GET /nodes?query=...&type=...&limit=...`: Filter and paginate entities.
- `GET /nodes/<node_id>`: Node details with inbound and outbound relationships.
- `GET /edges?src=...&dst=...&rel=...`: Filter relationships.
- `GET /context?entity=...&algorithm=ppr|bfs|hybrid&format=json|markdown`: Graph RAG ego-network context extraction.
- `GET /audit`: Topological health checks (Gini coefficient, bridges, cycles).

## Other formats

`graph.json` stays the artifact `build` writes — it's what the browser reads
with zero transformation, and every other format here is a converter over
it, not a second thing the pipeline produces. `convert` never re-runs
extraction, so it works on any `graph.json` this module ever wrote:

```bash
corpusatlas convert --graph graph.json --format graphml --out graph.graphml
corpusatlas convert --graph graph.json --format csv --out-dir csv/
corpusatlas convert --graph graph.json --format neo4j --out-dir neo4j/
corpusatlas convert --graph graph.json --format turtle --out graph.ttl
```

GraphML opens directly in Gephi, yEd, NetworkX (`nx.read_graphml`) or igraph
— real graph analysis tools, not a browser view. The CSV pair
(`nodes.csv`/`edges.csv`) is for reach rather than fidelity: pandas, a
spreadsheet, anything with a CSV reader. `neo4j` writes the same fields under
Neo4j's own `:ID`/`:LABEL`/`:START_ID`/`:END_ID`/`:TYPE` header convention —
loads directly with `neo4j-admin database import full`, no column-mapping
step first; a node's `type` becomes its Neo4j label, an edge's `rel` becomes
its relationship type. All three keep the same lean column set — a node's
label, type, degree and url; an edge's relation, confidence, explanation and
scope — rather than trying to be the complete record; `graph.json` still is
that, provenance and all.

`turtle` is the odd one out: unlike the three above, it isn't a reformat of
the same fields — RDF has no single obvious mapping for a typed, provenanced
graph like this one, so it's a real modelling decision, not a converter.
Every node becomes a resource under `--base` (a placeholder by default —
pick your own for anything meant to be dereferenced); a node's ontology type
becomes its `rdf:type`, and an edge's relation becomes the predicate
directly (`ca:IMPLEMENTS`, not a generic "relatedTo"). Confidence,
explanation, scope and provenance can't ride on a plain triple, so an edge
carrying any of them is written twice — once as the bare triple a simple
SPARQL query expects, once as a standard `rdf:Statement` reification
carrying the metadata — chosen over RDF-star or singleton properties for
being the more broadly compatible option. See `corpusatlas/rdf_export.py`
for the full reasoning. Worth doing because something now needs to `SPARQL`
this graph; wasn't worth doing speculatively before that was true.

## Performance & Architecture

- **Barnes-Hut $O(N \log N)$ Quadtree Layout**: Precalculates 2D force-directed node coordinates using adaptive quadtree spatial decomposition (`--layout`), scaling to tens of thousands of nodes in seconds.
- **Aho-Corasick Linear-Time Mention Scanner**: Deterministic string automaton matching across vocabulary keywords with word-boundary checks in $O(L + M)$ time.
- **SQLite Out-of-Core Pipeline Store**: Provides memory-bounded relational ingestion, deduplication, document retraction, and JSON streaming via `SQLitePipelineStore`.
- **Merkle-DAG Incremental Cache**: Content-addressable SHA-256 tree over extractor tier claims, invalidating only touched documents on rebuilds.

## Used by

[shirokoff.ca/knowledge-base](https://shirokoff.ca/knowledge-base/) builds its
graph with this module in CI on every push: ~290 articles, 16 scored
assessments and a set of curated entity packs become one `graph.json`, rendered
as an interactive canvas and as a
[plain-HTML list](https://shirokoff.ca/knowledge-base/entities). The site holds
the corpus, the config and the entity registry; this repo holds the engine.

It grew inside that site's repository and was split out with
`git subtree split`, so the history below predates this repository.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). [CHANGELOG.md](CHANGELOG.md) has the
version history; [docs/adapters.md](docs/adapters.md) lists all eight sources
side by side.

## Licence

MIT.
