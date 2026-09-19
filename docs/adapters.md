# Adapters

Every adapter is a class with one `documents()` method yielding `Document`s
(`model.py`) — the core never learns anything about a source beyond that
shape. This is the seven that ship, side by side; each one's own module
docstring has the full story, including what it honestly doesn't handle.

| `type` | Class | Reads | Config keys |
| --- | --- | --- | --- |
| `html_blog` | `HtmlBlogAdapter` | A directory of rendered HTML articles | `path`, `url_base` (default `/blog/`), `index` (optional; defaults to `path/index.html`, where tags are read from) |
| `obsidian` | `ObsidianAdapter` | A directory of markdown notes — an Obsidian vault, or just plain markdown | `path`, `url_base` (default `/vault/`), `recursive` (default `true`) |
| `logseq` | `LogseqAdapter` | A Logseq graph — outline markdown, `key:: value` page properties | `path`, `url_base` (default `/notes/`), `recursive` (default `true`) |
| `web` | `WebAdapter` | A plain list of URLs, fetched at build time | `urls` (a list) and/or `url_list_file` (one URL per line); `timeout` (default `10.0`); `user_agent` |
| `entity_packs` | `EntityPacksAdapter` | A directory of curated entity-pack JSON files | `path`, `url_base` (default `""`) |
| `radar_scorecards` | `RadarScorecardsAdapter` | One JSON file: scored comparisons | `path` |
| `radar_entries` | `RadarEntriesAdapter` | One JSON file: dated ring calls | `path`, `doc_prefixes` (optional; overrides the id-prefix mapping) |

## Which one for what

- **Your own rendered site or docs?** `html_blog`, if the pages carry the
  markers it looks for (an `<h1>`, an `article:published_time` meta tag,
  `data-tags` on an index page). It reads what a reader sees, on the theory
  that the published page is the thing that's actually true.
- **A notes vault, or just a folder of markdown with no particular
  structure?** `obsidian`. Wikilinks are optional — a directory of plain
  `.md` files with no `[[links]]` at all still works, it just won't produce
  any `REFERENCES` edges from that adapter. This is also `corpusatlas init`'s
  default, because it's the one that runs against literally anything.
- **A Logseq graph specifically?** `logseq` — same `[[wikilink]]` syntax as
  Obsidian, but properties are `key:: value` lines rather than YAML
  frontmatter, and every line is conventionally a bullet. Not "a Roam
  adapter too": Roam's shape is similar, but its actual export formats
  haven't been tested against this.
- **A source you don't control, or that isn't a local checkout?** `web` — a
  list of URLs. The only adapter here that touches the network, which is a
  real tradeoff (see `adapters/web.py`): a build using it is only as
  reproducible as the pages it fetches.
- **Hand-curated structured claims about entities?** `entity_packs` — the
  curated tier's own format, described in `README.md`'s "Extraction tiers".
- **Scored comparisons or a dated call log, in this project's own
  Architecture-Radar-shaped JSON?** `radar_scorecards` / `radar_entries` —
  the two most site-specific adapters here; useful as a reference for
  writing your own structured-data adapter more than as something you'd
  reuse verbatim.

## Writing a new one

Copy whichever of the seven is closest in shape. The contract is exactly:
accept whatever config keys you need in `__init__`, and yield `Document`s
from `documents()` — `id`, `title`, `url`, `kind` (almost always `"article"`
unless you're doing something `radar_entries`-shaped), and whatever of
`date`, `text`, `tags`, `links` you can populate. `links` should be other
documents' ids that exist in the same batch — a link to something outside it
should be dropped, not left dangling (every adapter here does this; see how
`html_blog` checks the target file exists, or how `obsidian` resolves
against its own vault's filenames only).

## Shipping one as its own package

You don't have to fork this repo to add an adapter. `build()` falls back to
the `corpusatlas.adapters` entry-point group for any `type` it doesn't
recognise, so a separate package can register one:

```toml
# in your plugin package's own pyproject.toml
[project.entry-points."corpusatlas.adapters"]
notion = "corpusatlas_notion.adapter:NotionAdapter"
```

Once that package is installed alongside corpusatlas, `[[sources]] type =
"notion"` in a config resolves it exactly like `html_blog` resolves — no
change to corpusatlas itself. The seven built-in names can never be shadowed
this way: `REGISTRY` is checked before any entry point, so a plugin claiming
`type = "html_blog"` is simply ignored in favour of the real one. An unknown
`type` reports every name it looked for, built-in and external, in the same
error.
