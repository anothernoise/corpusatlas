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
adapters → resolve → extract (deterministic, then curated) → merge → graph.json
```

## Install and run

No third-party dependencies. Python 3.11+.

```bash
pip install -e .          # installs the `corpusgraph` console script
python tests/run.py       # invariant tests, stdlib only

corpusgraph build --config corpusgraph.toml --out graph.json
corpusgraph stats    --graph graph.json
corpusgraph validate --graph graph.json
```

`python3 -m corpusgraph …` works too, without installing — the console script
and the module entry point are the same `main()`.

## Configuration

```toml
[[sources]]
type    = "html_blog"        # adapter name
path    = "../../blog"
url_base = "/blog/"

[[sources]]
type = "radar_scorecards"
path = "../../architecture-radar/scorecards.json"

[[sources]]
type = "radar_entries"
path = "../../architecture-radar/radar.json"

[ontology]
aliases = "../../knowledge-base/aliases.toml"
```

Every path resolves relative to the config file, the alias table included.

The alias table maps written forms to canonical node ids. It is deliberately
small: slugging already handles the ordinary cases, so an entry in it is an
admission that a name is genuinely ambiguous and a human had to decide.

```toml
[[entity]]
canonical = "tech:apache-spark"
label     = "Apache Spark"
tags      = ["spark"]      # this tag names a technology, not a subject
radar     = []             # radar entry ids that name this technology
aliases   = []             # spellings that do not slug to the canonical id
```

## Extraction tiers

**Tier 1 — deterministic.** Internal links, tags, headings, frontmatter, and
any structured data you already publish. Exact, free, and instant. This is what
ships today.

**Curated — entity packs.** One reviewed JSON file per technology: concepts,
components, capabilities, dependencies, alternatives (always with a `scope`),
and the pages that discuss it. Drafted offline, with a model if you like,
then signed by a person. Nothing in the build calls a model. A pack is yielded
as a `Document`, so every curated edge names the pack that made the claim, and
deleting the file retracts all of it. Unsigned packs are skipped. Use
`--include-drafts` to preview one. The curated tier runs after the
deterministic one, and merge keeps the first writer. A pack can add links and
aliases to an existing node, but it can never change what was hand-written.

```toml
[[sources]]
type     = "entity_packs"
path     = "../../knowledge-base/entities"
url_base = "/knowledge-base/entities/"
```

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

Everything needed to stand on its own already ships here: `pyproject.toml`,
`LICENSE`, `.gitignore`, tests, and `.github/workflows/ci.yml` (inert in the
site repo, since GitHub only reads workflows from the repository root — it runs
the moment the package becomes a repository of its own). The site installs this
as a package and drives it through the `corpusgraph` console script, so the
split changes the install source and nothing else.

Until there is a second consumer, keeping it here means one commit changes the
pipeline and the page that renders its output together, and CI needs no
cross-repo credentials.

## Licence

MIT.
