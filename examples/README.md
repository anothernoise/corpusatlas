# CorpusAtlas Examples & Integrations

This directory contains real-world extensions, integrations, and usage recipes for CorpusAtlas.

---

## 1. Custom Adapters: `plugin-rss-adapter`

A standalone, installable Python package demonstrating how to extend CorpusAtlas with custom document sources via Python entry-points without modifying core code.

- **Location**: [`examples/plugin-rss-adapter/`](plugin-rss-adapter/)
- **Registration**: Registered under the `corpusatlas.adapters` entry-point group in `pyproject.toml`.
- **Usage**:
  ```toml
  [[sources]]
  type = "rss"
  path = "feeds.txt"
  ```

---

## 2. DuckDB & Parquet Analytical Queries

CorpusAtlas graphs can be exported directly to high-performance columnar DuckDB databases and Apache Parquet files:

```bash
corpusatlas export --graph viewer/graph.json --format duckdb --out-dir duckdb_export/
```

This generates:
- `duckdb_export/corpusatlas.duckdb` (native DuckDB database)
- `duckdb_export/nodes.parquet` & `duckdb_export/edges.parquet`
- `duckdb_export/nodes.csv` & `duckdb_export/edges.csv`
- `duckdb_export/import_duckdb.sql`

### Example SQL Queries in DuckDB:

Query the database directly using the DuckDB CLI or Python/R/Node:

```bash
duckdb duckdb_export/corpusatlas.duckdb
```

```sql
-- Top entity types by frequency
SELECT type, COUNT(*) AS count
FROM nodes
GROUP BY type
ORDER BY count DESC;

-- Find strongest multi-hop relationships
SELECT
    s.label AS source,
    e.rel AS relationship,
    d.label AS target,
    e.confidence
FROM edges e
JOIN nodes s ON e.src = s.id
JOIN nodes d ON e.dst = d.id
WHERE e.confidence >= 0.9
ORDER BY e.confidence DESC
LIMIT 10;

-- Degree distribution & hub connectivity
SELECT
    n.label,
    n.type,
    COUNT(e.dst) AS degree
FROM nodes n
JOIN edges e ON n.id = e.src OR n.id = e.dst
GROUP BY n.label, n.type
ORDER BY degree DESC
LIMIT 15;
```

---

## 3. Cypher & Neo4j / AWS Neptune Export

Export your knowledge graph to Cypher statements (`.cql`):

```bash
corpusatlas export --graph viewer/graph.json --format cypher --out graph.cql
```

Statements include unique constraints, node property sets, and typed relationships with edge confidence. You can run them against Neo4j, Memgraph, or AWS Neptune:

```cypher
MATCH (t:Technology)-[r:IMPLEMENTS]->(c:Concept)
RETURN t.label, type(r), c.label
LIMIT 25;
```

---

## 4. RDF Turtle (.ttl) & W3C SPARQL

Export to standard RDF Turtle syntax:

```bash
corpusatlas export --graph viewer/graph.json --format turtle --out graph.ttl
```

Query with SPARQL:

```sparql
PREFIX ca: <https://corpusatlas.org/schema/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?subject ?label ?target
WHERE {
    ?subject a ca:Mammal ;
             rdfs:label ?label ;
             ca:PREYS_ON ?target .
}
```

---

## 5. Graph RAG Subgraph Extraction (Personalized PageRank)

Extract an entity's ego-network powered by random-walks with restart (PPR) for LLM prompts:

```bash
corpusatlas context --graph viewer/graph.json --entity "Tiger" --algorithm ppr --top-k 15
```

Produces focused Markdown context containing direct and tightly bound multi-hop relationships for immediate LLM ingestion.

---

## 6. Declarative Schema Refactoring (`corpusatlas migrate`)

Transform entity and relationship types in an existing `graph.json` without re-parsing your entire corpus:

Create `migration.toml`:
```toml
[[migrate]]
action = "rename_type"
from = "Technology"
to = "SoftwareModule"

[[migrate]]
action = "rename_relation"
from = "COMPARES_TO"
to = "BENCHMARKED_AGAINST"
```

Run migration:
```bash
corpusatlas migrate --graph graph.json --migration migration.toml --out migrated.json
```
