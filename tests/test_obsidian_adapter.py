"""Tests for the Obsidian vault adapter, against real files on disk — same
discipline as the web adapter's real local HTTP server: the parsing has to
survive actual Obsidian output, not a fixture already shaped to be easy."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from corpusatlas.adapters.obsidian import ObsidianAdapter, plain_text, split_frontmatter, wikilink_targets
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
        "---\n"
        "tags: [technology, big-data]\n"
        "date: 2026-01-15\n"
        "---\n"
        "# Apache Spark\n\n"
        "Spark is a distributed engine. See [[Lazy Evaluation]] and "
        "[[Structured Streaming|the streaming API]].\n\n"
        "It also relates to #performance work in [[Projects/My Pipeline]].\n"
    ),
    "Lazy Evaluation.md": (
        "Lazy evaluation means transformations are deferred until an action "
        "triggers execution.\n\nUsed heavily by [[Apache Spark]].\n"
    ),
    "Structured Streaming.md": (
        "---\n"
        "title: Structured Streaming (Spark)\n"
        "tags:\n"
        "  - streaming\n"
        "  - technology\n"
        "---\n"
        "Structured Streaming is Spark's streaming engine.\n"
    ),
    "Projects/My Pipeline.md": (
        "A real pipeline using [[Apache Spark]] and [[Nonexistent Note]].\n\n"
        "```python\nspark = SparkSession.builder.getOrCreate()\n```\n"
    ),
}


# --- small parsing helpers, in isolation -------------------------------------

def test_frontmatter_splits_flow_list_and_scalar_forms():
    fm, body = split_frontmatter("---\ntags: [a, b]\ndate: 2026-01-01\n---\nBody text.")
    assert fm == {"tags": ["a", "b"], "date": "2026-01-01"}
    assert body == "Body text."


def test_frontmatter_splits_block_list_form():
    fm, body = split_frontmatter("---\ntags:\n  - a\n  - b\n---\nBody.")
    assert fm == {"tags": ["a", "b"]}


def test_a_note_with_no_frontmatter_is_just_the_whole_file_as_body():
    fm, body = split_frontmatter("# Just a note\n\nNo frontmatter here.")
    assert fm == {}
    assert body.startswith("# Just a note")


def test_wikilink_targets_handles_plain_alias_and_heading_forms():
    body = "See [[Note A]], [[Note B|display text]], and [[Note C#Some Heading]]."
    targets = wikilink_targets(body)
    assert targets == [
        ("Note A", "Note A"),
        ("Note B", "display text"),
        ("Note C", "Note C"),
    ]


def test_plain_text_strips_code_and_resolves_links_to_display_text():
    body = "Uses [[Apache Spark|Spark]] daily.\n\n```python\nsecret_entity_name\n```\n\n`inline` too."
    text = plain_text(body)
    assert "Spark" in text
    assert "secret_entity_name" not in text
    assert "```" not in text and "`inline`" not in text


# --- the adapter against a real small vault -----------------------------------

def test_adapter_reads_every_note_recursively():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in ObsidianAdapter(path=str(vault)).documents()}
    assert set(docs) == {"Apache Spark", "Lazy Evaluation", "Structured Streaming", "My Pipeline"}


def test_title_prefers_frontmatter_over_the_filename():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in ObsidianAdapter(path=str(vault)).documents()}
    assert docs["Structured Streaming"].title == "Structured Streaming (Spark)"
    assert docs["Apache Spark"].title == "Apache Spark"  # no title: field, falls back to filename


def test_tags_combine_frontmatter_and_inline_hashtags():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in ObsidianAdapter(path=str(vault)).documents()}
    assert set(docs["Apache Spark"].tags) == {"technology", "big-data", "performance"}


def test_wikilinks_resolve_by_title_including_aliased_and_folder_qualified_ones():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in ObsidianAdapter(path=str(vault)).documents()}
    spark = docs["Apache Spark"]
    # Lazy Evaluation (plain), Structured Streaming (aliased display text),
    # My Pipeline (folder-qualified as [[Projects/My Pipeline]]).
    assert set(spark.links) == {"Lazy Evaluation", "Structured Streaming", "My Pipeline"}


def test_a_link_to_a_note_that_does_not_exist_is_silently_dropped():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in ObsidianAdapter(path=str(vault)).documents()}
    assert "Nonexistent Note" not in docs["My Pipeline"].links
    assert len(docs["My Pipeline"].links) == 1  # only Apache Spark


def test_code_fence_contents_never_leak_into_extracted_text():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in ObsidianAdapter(path=str(vault)).documents()}
    assert "SparkSession" not in docs["My Pipeline"].text


def test_date_comes_only_from_frontmatter_never_from_the_filesystem():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in ObsidianAdapter(path=str(vault)).documents()}
    assert docs["Apache Spark"].date == "2026-01-15"
    assert docs["Lazy Evaluation"].date is None  # no frontmatter at all


def test_non_recursive_mode_ignores_subfolders():
    vault = write_vault(VAULT)
    docs = {d.id for d in ObsidianAdapter(path=str(vault), recursive=False).documents()}
    assert "My Pipeline" not in docs
    assert "Apache Spark" in docs


def test_url_is_a_slug_of_the_title_under_url_base():
    vault = write_vault(VAULT)
    docs = {d.id: d for d in ObsidianAdapter(path=str(vault), url_base="/notes/").documents()}
    assert docs["Apache Spark"].url == "/notes/apache-spark"


# --- through the deterministic tier: wikilinks and tags become real edges ---

def test_wikilinks_become_references_edges_and_tags_become_about_edges():
    vault = write_vault(VAULT)
    docs = list(ObsidianAdapter(path=str(vault)).documents())
    _, edges = DeterministicExtractor().run(docs)
    rels = {(e.src, e.rel, e.dst) for e in edges}
    assert ("Apache Spark", "REFERENCES", "Lazy Evaluation") in rels
    assert ("Apache Spark", "REFERENCES", "My Pipeline") in rels
    assert ("Apache Spark", "ABOUT", "topic:technology") in rels
    # A wikilink is symmetric in the sense that each side records its own
    # REFERENCES — Obsidian doesn't distinguish forward/back links either.
    assert ("Lazy Evaluation", "REFERENCES", "Apache Spark") in rels
