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

---

## 7. Columnar DataFrame Interoperability & Ingestion

Load graphs into Polars, Apache Arrow, or Pandas without intermediate file conversions:

```python
import corpusatlas as ca

# Load from disk
graph_data = ca.load_graph("viewer/graph.json")

# Zero required dependencies - dict records:
nodes_dict, edges_dict = ca.dataframe.to_dict_records(graph_data.nodes, graph_data.edges)

# High-performance columnar dataframes (requires pip install "corpusatlas[all]")
nodes_pl, edges_pl = graph_data.to_polars()
nodes_pa, edges_pa = graph_data.to_arrow()
nodes_df, edges_df = graph_data.to_pandas()

# Filter or aggregate relationships with Polars
tech_implementations = edges_pl.filter(edges_pl["rel"] == "IMPLEMENTS")
print(tech_implementations.head())
```

Ingest tabular data directly into the pipeline via `DataFrameAdapter`:

```python
from corpusatlas.adapters.dataframe import DataFrameAdapter

adapter = DataFrameAdapter(
    nodes_data=[{"id": "doc:1", "type": "Document", "label": "Pipeline Guide"}],
    edges_data=[{"src": "doc:1", "rel": "ABOUT", "dst": "topic:etl"}],
)
docs = list(adapter.documents())
```

---

## 8. Model Context Protocol (MCP) Server for AI Assistants

Expose your knowledge graph to AI coding assistants (Claude Desktop, Cursor, Gemini Antigravity) over standard I/O:

```bash
corpusatlas serve-mcp --graph viewer/graph.json
```

Add to Claude Desktop config (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "corpusatlas": {
      "command": "corpusatlas",
      "args": ["serve-mcp", "--graph", "/path/to/graph.json"]
    }
  }
}
```

Exposes tools:
- `search_nodes`: Search nodes by text query and type filter.
- `extract_context_ppr`: Ego-network extraction with Personalized PageRank.
- `traverse_subgraph`: Breadth-first graph expansion up to depth $N$.
- `audit_graph`: Graph topology health and bridge edge detection.
- `get_provenance`: Claim provenance and confidence audit trail.

---

## 9. Hybrid BM25 + PPR Search with Reciprocal Rank Fusion

Combine Okapi BM25 keyword relevance with Personalized PageRank topological centrality:

```bash
corpusatlas context --graph viewer/graph.json --entity "Apache Spark" --algorithm hybrid --top-k 15
```

Ranks candidate nodes using Reciprocal Rank Fusion ($k=60$):
$$\text{RRF}(d) = \frac{1}{60 + r_{\text{BM25}}(d)} + \frac{1}{60 + r_{\text{PPR}}(d)}$$

---

## 10. Hierarchical Community Detection (Louvain Modularity)

Group entities into topical communities by maximizing modularity ($Q$):

```bash
corpusatlas cluster --graph viewer/graph.json --resolution 1.0 --out viewer/clustered.json
```

Outputs clusters with dominant entity types and Louvain modularity score.

---

## 11. Bi-Temporal Historical Snapshots (`corpusatlas as-of`)

Filter knowledge graph to point-in-time states using temporal valid-time intervals:

```bash
corpusatlas as-of --graph viewer/graph.json --date "2024-01-01" --out snapshot_2024.json
```

The web viewer (`viewer/index.html`) includes an interactive timeline slider allowing visual inspection of graph state at any historical moment.

---

## 12. Datalog-Lite Rule Inference Engine

Deduce implicit transitive, symmetric, or composed relationships using pure Python forward-chaining fixpoint evaluation:

```python
from corpusatlas.datalog import DatalogEngine, Rule
from corpusatlas.model import Edge

edges = [
    Edge(src="entity:a", rel="PART_OF", dst="entity:b"),
    Edge(src="entity:b", rel="PART_OF", dst="entity:c"),
]

engine = DatalogEngine(rules=[
    Rule(head_rel="PART_OF", body_rels=("PART_OF", "PART_OF"), confidence_factor=0.9)
])

inferred_edges = engine.evaluate(edges)
# Inferred: entity:a -PART_OF-> entity:c (confidence: 0.9)
```

