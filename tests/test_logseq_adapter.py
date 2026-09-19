"""Tests for the Logseq adapter against real files on disk — same discipline
as the Obsidian adapter's tests: real files, not fixtures pre-shaped to be
easy."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.adapters.logseq import LogseqAdapter, plain_text, split_properties, wikilink_targets
from corpusatlas.extract import DeterministicExtractor


def write_vault(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    for rel, content in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return d


VAULT = {
    "Apache Spark.md": (
        "type:: technology\n"
        "tags:: big-data, performance\n"
        "- Spark is a distributed engine.\n"
        "- See [[Lazy Evaluation]] and [[Structured Streaming|the streaming API]].\n"
        "- It also relates to #performance work in [[Projects/My Pipeline]].\n"
    ),
    "Lazy Evaluation.md": (
        "- Lazy evaluation means transformations are deferred until an action triggers execution.\n"
        "- Used heavily by [[Apache Spark]].\n"
    ),
    "Structured Streaming.md": (
        "title:: Structured Streaming (Spark)\n"
        "- Structured Streaming is Spark's streaming engine.\n"
    ),
    "Projects/My Pipeline.md": (
        "- A real pipeline using [[Apache Spark]] and [[Nonexistent Page]].\n\n"
        "```python\nspark = SparkSession.builder.getOrCreate()\n```\n"
    ),
}


# --- small parsing helpers, in isolation -------------------------------------

def test_split_properties_reads_key_value_lines_at_the_top_only():
    props, body = split_properties("type:: technology\ntags:: a, b\n- First real bullet.\n- Second.")
    assert props == {"type": "technology", "tags": "a, b"}
    assert body == "- First real bullet.\n- Second."


def test_a_page_with_no_properties_is_just_the_whole_file_as_body():
    props, body = split_properties("- Just a bullet, no properties block.")
    assert props == {}
    assert body.startswith("- Just a bullet")


def test_wikilink_targets_handles_plain_alias_and_heading_forms():
    body = "See [[Page A]], [[Page B|display text]], and [[Page C#Some Heading]]."
    assert wikilink_targets(body) == [
        ("Page A", "Page A"),
        ("Page B", "display text"),
        ("Page C", "Page C"),
    ]


def test_plain_text_strips_bullet_markers_code_and_resolves_links():
    body = "- Uses [[Apache Spark|Spark]] daily.\n- ```python\n  secret_entity_name\n  ```"
    text = plain_text(body)
    assert "Spark" in text
    assert "secret_entity_name" not in text
    assert not text.startswith("-")
    assert "```" not in text


# --- the adapter against a real small vault -----------------------------------

def test_adapter_reads_every_page_recursively():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in LogseqAdapter(path=str(vault)).documents()}
    assert set(docs) == {"Apache Spark", "Lazy Evaluation", "Structured Streaming", "My Pipeline"}


def test_title_property_overrides_the_filename():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in LogseqAdapter(path=str(vault)).documents()}
    assert docs["Structured Streaming"].title == "Structured Streaming (Spark)"
    assert docs["Apache Spark"].title == "Apache Spark"  # no title:: property, falls back


def test_tags_combine_the_tags_property_and_inline_hashtags():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in LogseqAdapter(path=str(vault)).documents()}
    assert set(docs["Apache Spark"].tags) == {"big-data", "performance"}


def test_properties_do_not_leak_into_the_extracted_text():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in LogseqAdapter(path=str(vault)).documents()}
    assert "type::" not in docs["Apache Spark"].text
    assert "tags::" not in docs["Apache Spark"].text


def test_wikilinks_resolve_by_title_including_aliased_and_folder_qualified_ones():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in LogseqAdapter(path=str(vault)).documents()}
    assert set(docs["Apache Spark"].links) == {"Lazy Evaluation", "Structured Streaming", "My Pipeline"}


def test_a_link_to_a_page_that_does_not_exist_is_silently_dropped():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in LogseqAdapter(path=str(vault)).documents()}
    assert "Nonexistent Page" not in docs["My Pipeline"].links
    assert len(docs["My Pipeline"].links) == 1


def test_code_fence_contents_never_leak_into_extracted_text():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in LogseqAdapter(path=str(vault)).documents()}
    assert "SparkSession" not in docs["My Pipeline"].text


def test_non_recursive_mode_ignores_subfolders():
    vault = write_vault(VAULT)
    docs = {d.id for d in LogseqAdapter(path=str(vault), recursive=False).documents()}
    assert "My Pipeline" not in docs
    assert "Apache Spark" in docs


def test_url_is_a_slug_of_the_title_under_url_base():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in LogseqAdapter(path=str(vault), url_base="/notes/").documents()}
    assert docs["Apache Spark"].url == "/notes/apache-spark"


# --- through the deterministic tier -----------------------------------------

def test_wikilinks_become_references_edges_and_tags_become_about_edges():
    vault = write_vault(VAULT)
    docs = list(LogseqAdapter(path=str(vault)).documents())
    _, edges = DeterministicExtractor().run(docs)
    rels = {(e.src, e.rel, e.dst) for e in edges}
    assert ("Apache Spark", "REFERENCES", "Lazy Evaluation") in rels
    assert ("Apache Spark", "REFERENCES", "My Pipeline") in rels
    assert ("Apache Spark", "ABOUT", "topic:big-data") in rels
    assert ("Lazy Evaluation", "REFERENCES", "Apache Spark") in rels
