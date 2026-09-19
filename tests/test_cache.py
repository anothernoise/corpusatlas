"""Tests for the --cache file-parse cache (corpusatlas/cache.py) — the
correctness bar is stricter than "faster": a cache hit must reproduce
exactly what a fresh parse would have produced, and anything that could
change what an *unchanged* file resolves to (a new sibling note, a re-tagged
index page) must be detected and invalidate rather than serve stale data.

Real files on disk, real adapters — the same style as the rest of this
suite — rather than exercising cache.py's classes in isolation, since the
fingerprinting is half adapter-side, half cache-side, and only meaningful
together.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.adapters.html_blog import HtmlBlogAdapter
from corpusatlas.adapters.obsidian import ObsidianAdapter
from corpusatlas.cache import BuildCache

ARTICLE = """<html><head><h1>{title}</h1>
<meta property="article:published_time" content="2026-01-01"></head>
<body><div class="article-content"><p>{body}</p></div></body></html>"""


def _write_blog(dir_: Path, slug: str, title: str, body: str = "hello") -> None:
    (dir_ / f"{slug}.html").write_text(ARTICLE.format(title=title, body=body), encoding="utf-8")


def test_html_blog_cache_hit_reproduces_the_uncached_document():
    with tempfile.TemporaryDirectory() as d:
        blog = Path(d)
        _write_blog(blog, "a", "A")
        _write_blog(blog, "b", "B")

        uncached = {doc.id: doc for doc in HtmlBlogAdapter(str(blog)).documents()}

        cache = BuildCache(None)  # in-memory only, never persisted
        bucket = cache.bucket("html_blog:x")
        cached_docs = {doc.id: doc for doc in HtmlBlogAdapter(str(blog), cache=bucket).documents()}
        assert cache.hits == 0 and cache.misses == 2  # nothing cached yet

        bucket2 = cache.bucket("html_blog:x")
        warm_docs = {doc.id: doc for doc in HtmlBlogAdapter(str(blog), cache=bucket2).documents()}
        assert cache.hits == 2 and cache.misses == 2

        assert warm_docs == uncached == cached_docs


def test_cache_persists_across_save_and_reload():
    with tempfile.TemporaryDirectory() as d:
        blog = Path(d) / "blog"
        blog.mkdir()
        _write_blog(blog, "a", "A")
        cache_path = Path(d) / "cache.json"

        cache1 = BuildCache(cache_path)
        list(HtmlBlogAdapter(str(blog), cache=cache1.bucket("html_blog:x")).documents())
        cache1.save()
        assert cache_path.exists()

        cache2 = BuildCache(cache_path)
        docs = list(HtmlBlogAdapter(str(blog), cache=cache2.bucket("html_blog:x")).documents())
        assert cache2.hits == 1 and cache2.misses == 0
        assert docs[0].id == "a"


def test_editing_one_file_invalidates_only_that_file():
    with tempfile.TemporaryDirectory() as d:
        blog = Path(d)
        _write_blog(blog, "a", "A")
        _write_blog(blog, "b", "B")

        cache = BuildCache(None)
        list(HtmlBlogAdapter(str(blog), cache=cache.bucket("k")).documents())
        hits_before, misses_before = cache.hits, cache.misses

        _write_blog(blog, "a", "A (revised)")
        docs = {doc.id: doc for doc in HtmlBlogAdapter(str(blog), cache=cache.bucket("k")).documents()}
        # b reused (a hit), a reparsed (a miss) — counted as this run's delta,
        # since hits/misses accumulate over the BuildCache's whole lifetime.
        assert cache.hits - hits_before == 1
        assert cache.misses - misses_before == 1
        assert docs["a"].title == "A (revised)"
        assert docs["b"].title == "B"


def test_adding_a_file_invalidates_the_whole_source_not_just_the_new_one():
    """A coarse but safe rule: any change to the file set reparses
    everything in that source, since an unrelated file's [[wikilink]] or
    index-page tag could now resolve differently."""
    with tempfile.TemporaryDirectory() as d:
        blog = Path(d)
        _write_blog(blog, "a", "A")

        cache = BuildCache(None)
        list(HtmlBlogAdapter(str(blog), cache=cache.bucket("k")).documents())
        hits_before, misses_before = cache.hits, cache.misses

        _write_blog(blog, "b", "B")  # a new file, "a" itself untouched
        list(HtmlBlogAdapter(str(blog), cache=cache.bucket("k")).documents())
        assert cache.hits - hits_before == 0  # a is not reused either
        assert cache.misses - misses_before == 2


def test_retagging_the_index_page_invalidates_cached_articles_tags():
    with tempfile.TemporaryDirectory() as d:
        blog = Path(d)
        _write_blog(blog, "a", "A")
        index = blog / "index.html"
        index.write_text('<div data-tags="one"><a href="a">A</a></div>', encoding="utf-8")

        cache = BuildCache(None)
        first = list(HtmlBlogAdapter(str(blog), cache=cache.bucket("k")).documents())
        assert first[0].tags == ("one",)

        index.write_text('<div data-tags="two"><a href="a">A</a></div>', encoding="utf-8")
        second = list(HtmlBlogAdapter(str(blog), cache=cache.bucket("k")).documents())
        assert cache.misses == 2  # the article file itself never changed, but its tags did
        assert second[0].tags == ("two",)


def test_obsidian_cache_hit_reproduces_wikilink_resolution():
    with tempfile.TemporaryDirectory() as d:
        vault = Path(d)
        (vault / "A.md").write_text("Links to [[B]].", encoding="utf-8")
        (vault / "B.md").write_text("No links here.", encoding="utf-8")

        cache = BuildCache(None)
        first = {doc.id: doc for doc in ObsidianAdapter(str(vault), cache=cache.bucket("k")).documents()}
        second = {doc.id: doc for doc in ObsidianAdapter(str(vault), cache=cache.bucket("k")).documents()}
        assert cache.hits == 2
        assert first["A"].links == second["A"].links == ("B",)


def test_a_new_note_making_a_dangling_wikilink_resolve_is_not_served_stale():
    """A regression guard for exactly the bug this cache design exists to
    avoid: [[C]] in A.md can't resolve until C.md exists, and once it does,
    A.md — itself unchanged — must be reparsed to pick up the new link."""
    with tempfile.TemporaryDirectory() as d:
        vault = Path(d)
        (vault / "A.md").write_text("Links to [[C]].", encoding="utf-8")

        cache = BuildCache(None)
        first = {doc.id: doc for doc in ObsidianAdapter(str(vault), cache=cache.bucket("k")).documents()}
        assert first["A"].links == ()  # C doesn't exist yet

        (vault / "C.md").write_text("Here.", encoding="utf-8")
        second = {doc.id: doc for doc in ObsidianAdapter(str(vault), cache=cache.bucket("k")).documents()}
        assert second["A"].links == ("C",)


def test_no_cache_argument_behaves_exactly_as_before():
    """cache=None (the default) must be a complete no-op — the whole point
    of --cache being opt-in."""
    with tempfile.TemporaryDirectory() as d:
        blog = Path(d)
        _write_blog(blog, "a", "A")
        docs = list(HtmlBlogAdapter(str(blog)).documents())
        assert docs[0].id == "a"


def test_a_corrupt_cache_file_is_treated_as_empty_not_fatal():
    with tempfile.TemporaryDirectory() as d:
        cache_path = Path(d) / "cache.json"
        cache_path.write_text("not json{{{", encoding="utf-8")
        cache = BuildCache(cache_path)  # must not raise
        assert cache._data == {}


def test_cache_survives_concurrent_sources_without_losing_hits_or_corrupting_state():
    """cmd_build loads more than one source concurrently (one thread per
    source) — the shared BuildCache's hit/miss counters and its on-disk
    _data dict have to survive that without a lost update or a torn write.
    Two obsidian sources, two separate vaults, built with --cache twice."""
    from corpusatlas.__main__ import main

    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        for name in ("vault1", "vault2"):
            v = root / name
            v.mkdir()
            for i in range(15):
                (v / f"Note {i}.md").write_text(f"# Note {i}\n\nSome text.", encoding="utf-8")

        config = root / "corpusatlas.toml"
        config.write_text('''
[[sources]]
type = "obsidian"
path = "vault1"
url_base = "/v1/"

[[sources]]
type = "obsidian"
path = "vault2"
url_base = "/v2/"
''', encoding="utf-8")
        out = root / "graph.json"
        cache_path = root / "cache.json"

        assert main(["build", "--config", str(config), "--out", str(out),
                    "--cache", str(cache_path)]) == 0
        cold_bytes = out.read_bytes()
        cache_data = json.loads(cache_path.read_text())
        assert len(cache_data) == 2  # one bucket per source, neither clobbered the other
        assert all(len(bucket["files"]) == 15 for bucket in cache_data.values())

        assert main(["build", "--config", str(config), "--out", str(out),
                    "--cache", str(cache_path)]) == 0
        assert out.read_bytes() == cold_bytes  # warm rebuild, same output
