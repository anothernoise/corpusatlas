# Writing a custom ontology

`ontology.py`'s `DEFAULT` — 14 entity types, 25 relations — is a
data-and-infrastructure-architecture vocabulary. A corpus about something
else needs its own. This is the file format for that, and it's the same
shape `Ontology` itself uses internally, so nothing about validation is
different for a custom schema versus the built-in one.

## The two things a schema declares

**Types**, split the same way `DEFAULT` splits them:

```toml
entity_types  = ["Dish", "Ingredient"]   # what the graph is about — drawn as nodes
context_types = ["Document"]              # where a claim was published — linked from a card
```

A type can't be in both lists. `context_types` can be empty if every source
in your corpus is itself an entity (no separate "this came from an article"
concept) — omit it or leave it `[]`.

**Relations**, one `[[relation]]` table per relation:

```toml
[[relation]]
name   = "USES_INGREDIENT"
source = ["Dish"]           # allowed types on the source end
target = ["Ingredient"]      # allowed types on the target end
group  = "Composition"       # which canvas filter group this belongs to
```

Every relation is *either* semantic (assigned to a `group`, drawn on the
canvas, filterable) *or* a context relation (`context = true`, shown as a
link on a card, never drawn) — never both, never neither. This mirrors
`DEFAULT`'s own split: `IMPLEMENTS` is semantic; `COVERS` (an article names an
entity) is context.

Two optional per-relation flags:

```toml
symmetric = true              # stored as one direction only, read as either
inverse   = "USED_BY"         # a pack may author this name; it gets flipped
                               # into the relation above and stored that way
```

## A complete worked example

```toml
entity_types  = ["Dish", "Ingredient"]
context_types = ["Document"]

[[relation]]
name  = "USES_INGREDIENT"
source = ["Dish"]
target = ["Ingredient"]
group  = "Composition"

[[relation]]
name      = "PAIRS_WITH"
source    = ["Dish"]
target    = ["Dish"]
group     = "Composition"
symmetric = true

[[relation]]
name    = "COVERS"
source  = ["Document"]
target  = ["Dish", "Ingredient"]
context = true
```

Wire it into a build with `[ontology] schema` in the corpus config, alongside
the entity registry it's already got a key for:

```toml
[ontology]
entities = "entities.toml"   # the registry: named instances of these types
schema   = "ontology.toml"   # the file above: the types and relations themselves
```

`schema` is optional — omit it and a build uses `DEFAULT`, exactly as it did
before this existed.

## What gets checked, and when

`Ontology.from_toml()` runs the same closed-world checks `DEFAULT` itself has
always had to pass, now raised as `OntologyError` with a specific message
instead of a bare `assert` at import time:

- every relation is in exactly one of a `group` or `context = true`
- no relation references a type that isn't in `entity_types` or `context_types`
- `entity_types` and `context_types` don't overlap
- an `inverse` names a relation that actually exists

A malformed schema fails here, at load — before a single document is read —
not partway through a build with a confusing type error on an edge that has
nothing to do with the actual mistake.

## What stays fixed regardless

The id scheme (`entity:<slug>` for entities; `assessment:`, `radar:`,
`topic:` prefixes for context) isn't part of the schema — it's structural,
shared by every ontology, and not something a corpus would want to vary.
Same for the three extraction tiers themselves (`deterministic`, `curated`,
`extracted`) — a schema changes what a relation *means*, not how the pipeline
that produces one is organised.
