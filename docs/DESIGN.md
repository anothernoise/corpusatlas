# Design notes

The README covers the contract and how to use this module. This is the
reasoning behind it — condensed from
[Build-Time Knowledge Graphs](https://shirokoff.ca/blog/build-time-knowledge-graph),
which has the full argument, the FAQ, and the search/library comparisons this
doc leaves out. Read that first if you want the narrative; read this if you
want the decision points without the story.

## The question that decides the architecture

Corpus size is the variable most knowledge-graph guides never state, because
most of them assume a corpus large enough that no human could hold it —
GraphRAG's regime, where expensive machinery pays for itself.

| Corpus | What actually works | Why |
| --- | --- | --- |
| Under ~1,000 docs | Build-time graph, static artifact, client-side query | Whole graph fits in memory. No server earns its keep. |
| ~1k–100k docs | Build-time graph + a real vector index | Retrieval starts to need help; traversal still cheap. |
| Over ~100k docs | Genuine GraphRAG: incremental indexing, graph DB, community summarisation | Enough structure that hierarchical summarisation adds real information. |

Treat those as heuristics, not thresholds — query concurrency, mutation rate,
query shape, latency budget and per-document extraction cost all move the
boundary as much as raw count does. This module is built for the top row and
works into the second; past that, the tradeoffs this repo makes (one writer,
no auth, ship the whole file) start working against you rather than for you.

## Mine the structure you already wrote

A well-maintained corpus already contains a hand-authored knowledge graph,
and it's more accurate than anything extraction will produce:

| Existing signal | Graph it yields | Accuracy |
| --- | --- | --- |
| Internal links | `Article -REFERENCES-> Article` | Exact — a human chose it |
| Tags, categories | `Article -ABOUT-> Topic` | Exact, if the vocabulary is controlled |
| Frontmatter, dates | Temporal and provenance edges | Exact |
| Structured data you publish | Typed entities and scored relations | Exact |
| Prose | Everything else | Whatever your extractor manages |

Only the last row needs a model — which is why `deterministic.py` runs
first and `mentions.py` (the only tier that reads unstructured prose) runs
last, over the vocabulary the first two tiers already produced. Build the
deterministic layer, look at what's thin, and let that gap be your curated
packs' scope — not a blanket LLM pass over everything you already typed by
hand.

## The ontology has to be closed before extraction, not after

Open-vocabulary extraction over a technical corpus produces a swamp. This is
why `ontology.py` declares a fixed set of entity types and, for every
relation, an explicit type signature — which entity types are valid on each
end. A pack proposing `HAS_COMPONENT` from a `Concept` fails the build before
it reaches the graph, mechanically, without anyone reviewing it by eye.

The honest tradeoff: that ontology is fixed, not pluggable. It's generic
across *sites* — nothing in it names any particular corpus — but specific to
*this domain*, a data-and-infrastructure-architecture vocabulary (`Technology`,
`ArchitecturePattern`, `CloudService`, and eleven more). A corpus about
biology or law would need to fork `ontology.py` rather than write a config
block. See "Flexibility" below.

## Entity resolution is the actual work

Extraction gives you mentions; a graph needs entities. "ClickHouse",
"Clickhouse", "CH" and "the ClickHouse engine" arrive as four strings that
have to become one node, and that decision is a domain judgement, not a
string-distance threshold. Get it wrong and the graph *looks* fine while
being useless — your most important node silently split into weakly-connected
fragments.

`entities.toml`'s job is exactly this: a hand-curated table an entity
resolves against, `options` for the exact strings that name it, `aliases`
for the rest. Never auto-merge past a threshold — a wrong merge is close to
undetectable afterwards, because the evidence two things were ever distinct
is gone. That's a review problem, not an automation problem.

## Provenance is not bookkeeping

Every edge in the artifact carries `prov.doc` (who claimed this), `prov.tier`
and `prov.extractor` (how sure the pipeline should be), and on a curated
edge, a confidence and a plain-language explanation. This is what lets
`merge.py` retract exactly the edges a deleted document made — not
"everything that happens to connect the same two entities" — and it's what
turns a wrong edge into something traceable to a document and an extractor
version, fixable as a class of error rather than a one-off patch.

## When this design is wrong

Three cases where the argument inverts:

- **The corpus is large or churns fast.** Past roughly a hundred thousand
  documents, community summarisation adds real information you can't get
  otherwise, and you need incremental indexing infrastructure — the regime
  GraphRAG was designed for.
- **Many writers, concurrent updates.** This module assumes one writer and a
  git history. Dozens of contributors editing continuously want a database
  with transactions, not a CI job.
- **Access control per node.** Shipping `graph.json` to the browser means
  shipping all of it. Per-user authorisation has to move server-side, which
  means you're deliberately building a service — not discovering you have
  one.

If none of those apply, the static build isn't a compromise. Nothing to
operate, nothing to page you, and the artifact is checkable by anyone who
reads it.

## Flexibility: what's configurable and what isn't

Three different things get asked about under "flexibility," and they have
different answers:

- **Sources.** Fully pluggable — this is the actual extension point. An
  adapter is a class with one `documents()` method; five ship as the
  reference (`html_blog`, `radar_scorecards`, `radar_entries`, `entity_packs`,
  `web`). Adding a sixth never touches the core.
- **Config.** Already flexible: everything in a `[[sources]]` block is
  adapter-specific keyword arguments, and paths resolve relative to the
  config file, not the install location.
- **Ontology.** The rigid one, on purpose for now: 14 entity types and 25
  typed relations, fixed as Python constants in `ontology.py`, imported as
  such from extraction through validation. Making this genuinely
  config-driven — an `ontology.toml` a reader could edit without forking —
  is a real, undone project, not a quick patch: every module that currently
  does `from .ontology import ENTITY_TYPES` would need to take an ontology
  as a parameter instead. Worth doing for a second real consumer outside
  data/infrastructure writing; not worth doing speculatively.
