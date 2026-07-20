# corpusgraph

Turn a corpus of markdown and structured data into a knowledge graph you can
ship as a static file.

Built for the case described in
[Build-Time Knowledge Graphs](https://shirokoff.ca/blog/build-time-knowledge-graph):
a few hundred to a few thousand documents, where the whole graph fits in a
browser tab and a graph database would be an operational cost with no payoff.

## The contract

Two rules keep this a module rather than a framework:

1. **Sources are adapters.** Every adapter yields the same `Document` shape.
   The core never learns the name of your blog, your book, or your CMS.
2. **Output is files.** `corpusgraph` writes `graph.json` and exits. It owns no
   process, serves no requests, and has no opinion about what reads the output.

```
adapters → extract (deterministic) → resolve → merge → graph.json
```

## Install and run

No third-party dependencies. Python 3.11+.

```bash
python3 -m corpusgraph build --config corpusgraph.toml --out ../../knowledge-base/graph.json
python3 -m corpusgraph stats --graph ../../knowledge-base/graph.json
python3 -m corpusgraph validate --graph ../../knowledge-base/graph.json
```

## Configuration

```toml
[[sources]]
type    = "html_blog"        # adapter name
path    = "../../blog"
url_base = "/blog/"

[[sources]]
type = "radar_scorecards"
path = "../../architecture-radar/scorecards.json"

[ontology]
aliases = "aliases.yaml"
```

## Extraction tiers

**Tier 1 — deterministic.** Internal links, tags, headings, frontmatter, and
any structured data you already publish. Exact, free, and instant. This is what
ships today.

**Tier 2 — extraction.** NER or an LLM over prose, for relationships that are
genuinely latent in the text. Not implemented; the seam is `extract/base.py`
and the tier is recorded on every edge so the two never get confused.

Do tier 1 first and look at where the graph is thin. That gap is the spec for
tier 2 — not the other way round.

## Provenance

Every edge carries where it came from:

```json
{
  "src": "clickhouse", "rel": "COMPARES_TO", "dst": "starrocks",
  "prov": { "doc": "starrocks-vs-clickhouse-vs-doris", "tier": "deterministic",
            "extractor": "links@1", "at": "2026-07-20" }
}
```

An edge is a claim made *by* a document. When the document goes, the claim goes
with it — `merge.py` handles retraction, not just append.

## Extracting this into its own repository

It is deliberately self-contained: no imports from the site, all paths from
config, its own tests. When it earns a life of its own:

```bash
git subtree split --prefix=tools/corpusgraph -b corpusgraph
# then push that branch to a new repo — full history preserved
```

Until there is a second consumer, keeping it here means one commit changes the
pipeline and the page that renders its output together, and CI needs no
cross-repo credentials.

## Licence

MIT.
