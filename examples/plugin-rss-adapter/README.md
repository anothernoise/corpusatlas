# corpusatlas-rss (example plugin adapter)

A worked example of corpusatlas's plugin mechanism — a real, installable
package that adds a source adapter (`type = "rss"`) without any change to
corpusatlas itself. **Copy this directory to start your own**; it isn't
meant to be depended on as-is, and isn't published anywhere.

## What it proves

`adapters.build()` in corpusatlas falls back to the `corpusatlas.adapters`
entry-point group for a source `type` it doesn't recognise. This package
registers one:

```toml
# pyproject.toml
[project.entry-points."corpusatlas.adapters"]
rss = "corpusatlas_rss.adapter:RssAdapter"
```

Install it alongside corpusatlas, and `[[sources]] type = "rss"` in any
`corpusatlas.toml` resolves to `RssAdapter` — the same way `type =
"html_blog"` resolves to a built-in adapter, just from a different package.

## Try it

```bash
cd examples/plugin-rss-adapter
pip install -e .        # also installs corpusatlas itself, as a dependency
```

```toml
# corpusatlas.toml
[[sources]]
type = "rss"
path = "feed.xml"       # a local RSS 2.0 or Atom file — see adapter.py for why local
```

```bash
corpusatlas build --config corpusatlas.toml --out graph.json
```

## What `RssAdapter` actually does

Reads a local RSS 2.0 or Atom XML file (not a URL — fetching one properly,
with retries and robots.txt, is corpusatlas's own `web` adapter's job, and
duplicating that here would make this example about HTTP instead of about
the plugin mechanism) and yields one `Document` per item/entry: title,
link, a description/summary as `text`, and a parsed date where the feed has
one. See `corpusatlas_rss/adapter.py` — under 90 lines, the same rough size
as any of corpusatlas's own seven built-in adapters.

## Adapting this for your own source

1. Rename the package and the entry-point's `type` name.
2. Replace `documents()`'s body with however your real source is shaped.
3. Keep yielding the same `Document` fields every adapter yields — `id`,
   `title`, `url`, `kind`, and whatever of `date`, `text`, `tags`, `links`
   your source has. `links` should be other documents' ids *within this
   same batch*; a link outside it should be dropped, not left dangling (see
   how corpusatlas's own adapters do this).
4. If you're publishing it for others, register it in `docs/adapters.md`'s
   style — what it reads, what config keys it takes, what it honestly
   doesn't handle.
