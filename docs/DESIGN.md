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

**What "fits in memory" actually measures like.** `scripts/profile_scale.py`
builds a synthetic, cross-linked corpus and times every pipeline stage —
real numbers, not the claim restated. At 5,000 documents (shirokoff.ca
itself is ~350): 8.2s total, 74MB peak Python-level allocation
(`tracemalloc`), a 12.9MB `graph.json`. At 20,000 (4x): 27.1s, 295MB, 52MB
— scaling roughly linearly, not quadratically, in every stage. Where the
time actually goes, at either size: **adapter parsing dominates** (~50-59%
— this is exactly what `--cache` exists to skip on a rebuild), the
**mentions tier** is the one extraction stage worth naming (~19-23%, word-
boundary scanning over every document's full text), and **JSON
serialisation** is a comparable, easy-to-forget cost (~19-23%) since it's
outside "extraction" entirely. The deterministic tier, packs and merge are
all near-zero regardless of size.

This is also the answer to "should extraction run in parallel processes":
investigated, not implemented. At 20,000 documents the only genuinely
parallel-shaped extraction cost (mentions, embarrassingly parallel per
document) is a fifth of total time, and it's dwarfed by adapter parsing —
which `--cache` already addresses on every build after the first, for free,
with no new failure modes. Multiprocessing would add real complexity
(process pool lifecycle, pickling Documents/Nodes/Edges across a process
boundary) to shave a minority slice of a build nobody has actually reported
as slow — corpusatlas's one real consumer today is 70x smaller than the
size tested here. Worth revisiting if a corpus this large and this
mention-heavy actually shows up; not worth building against a corpus that
doesn't exist yet.

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
why an `Ontology` declares a closed set of entity types and, for every
relation, an explicit type signature — which entity types are valid on each
end. A pack proposing `HAS_COMPONENT` from a `Concept` fails the build before
it reaches the graph, mechanically, without anyone reviewing it by eye.

This package's own `DEFAULT` ontology is generic across *sites* — nothing in
it names any particular corpus — but specific to *this domain*, a
data-and-infrastructure-architecture vocabulary (`Technology`,
`ArchitecturePattern`, `CloudService`, and eleven more). A corpus about
biology or law wants its own types and relations, not `DEFAULT`'s — and can
have them from a schema file, without forking anything. See "Flexibility"
below.

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
- **Ontology.** Configurable now, as of `Ontology` becoming a value rather
  than a set of module constants — every extractor, the resolver and
  `write_graph` take `ontology=` and default to `DEFAULT` (this package's own
  14 types, 25 relations), never reaching for a module global directly. A
  corpus in a different domain gets its own types and relations from a
  `[ontology] schema` TOML file, checked at load with the same closed-world
  rules `DEFAULT` has always had to satisfy — see
  [docs/ontology-schema.md](ontology-schema.md). What's still fixed
  regardless: the `entity:`/`assessment:`/`radar:`/`topic:` id-prefix scheme,
  and the three extraction tiers themselves. Those are structural — shared by
  every ontology — not vocabulary a schema file would sensibly vary.
