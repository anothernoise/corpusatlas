"""Tests for the html_blog adapter against real files on disk — this is the
adapter shirokoff.ca's own build actually uses, and it had no dedicated test
at all before this: only exercised indirectly, through hand-built Document
objects in test_pipeline.py that bypass the adapter's own HTML parsing
entirely. Found via a coverage run (42%), not assumed."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.adapters.html_blog import HtmlBlogAdapter


def write_site(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, content in files.items():
        (d / name).write_text(content, encoding="utf-8")
    return d


def article(title: str, body: str, date: str = "2026-01-15") -> str:
    return (
        f'<html><head><meta property="article:published_time" content="{date}"></head>'
        f'<body><h1>{title}</h1>'
        f'<div class="article-content">{body}</div></body></html>'
    )


SITE = {
    "apache-spark.html": article(
        "Apache Spark",
        'Spark relates to <a href="lazy-evaluation">lazy evaluation</a> '
        'and <a href="https://external.example/x">an external link</a> and '
        '<a href="ghost-page">a page that does not exist</a>.',
    ),
    "lazy-evaluation.html": article("Lazy Evaluation", "Deferred execution, used by Spark."),
    "index.html": (
        '<html><body>'
        '<div data-tags="technology, big-data"><a href="apache-spark">Apache Spark</a></div>'
        '<div data-tags="concept"><a href="lazy-evaluation">Lazy Evaluation</a></div>'
        '</body></html>'
    ),
    "topics.html": "<html><body>should be skipped</body></html>",
}


def test_reads_every_article_and_skips_index_and_topics():
    site = write_site(SITE)
    docs = {d.id: d for d in HtmlBlogAdapter(path=str(site)).documents()}
    assert set(docs) == {"apache-spark", "lazy-evaluation"}


def test_title_date_and_body_are_parsed_and_tags_stripped():
    site = write_site(SITE)
    docs = {d.id: d for d in HtmlBlogAdapter(path=str(site)).documents()}
    spark = docs["apache-spark"]
    assert spark.title == "Apache Spark"
    assert spark.date == "2026-01-15"
    assert "<" not in spark.text and ">" not in spark.text  # HTML tags stripped from body


def test_links_to_a_missing_page_or_an_external_url_are_dropped():
    site = write_site(SITE)
    docs = {d.id: d for d in HtmlBlogAdapter(path=str(site)).documents()}
    spark = docs["apache-spark"]
    assert spark.links == ("lazy-evaluation",)  # external + ghost-page both dropped


def test_tags_come_from_the_index_page_not_the_article_itself():
    site = write_site(SITE)
    docs = {d.id: d for d in HtmlBlogAdapter(path=str(site)).documents()}
    assert set(docs["apache-spark"].tags) == {"technology", "big-data"}
    assert set(docs["lazy-evaluation"].tags) == {"concept"}


def test_an_article_with_no_h1_falls_back_to_its_slug_as_title():
    site = write_site({
        "no-title.html": '<html><body><div class="article-content">No heading here.</div></body></html>',
    })
    docs = list(HtmlBlogAdapter(path=str(site)).documents())
    assert docs[0].title == "no-title"
    assert docs[0].date is None


def test_url_base_and_a_custom_index_path_are_both_honoured():
    site = write_site(SITE)
    custom_index = site / "cards.html"
    custom_index.write_text(SITE["index.html"], encoding="utf-8")
    (site / "index.html").unlink()  # force it to use the custom index, not the default

    docs = {d.id: d for d in HtmlBlogAdapter(path=str(site), url_base="/writing/",
                                             index=str(custom_index)).documents()}
    assert docs["apache-spark"].url == "/writing/apache-spark"
    assert set(docs["apache-spark"].tags) == {"technology", "big-data"}


def test_no_index_file_at_all_means_no_tags_but_still_works():
    site = write_site({"solo.html": article("Solo", "No index page in this directory at all.")})
    docs = list(HtmlBlogAdapter(path=str(site)).documents())
    assert docs[0].tags == ()
