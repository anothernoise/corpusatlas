"""Source adapters. Each yields Documents and knows nothing about the graph.

Ships seven, registered by name in REGISTRY below. A source type not found
there falls back to the "corpusatlas.adapters" entry-point group, so a
third-party package can add another one without forking this repo: a
Notion export, an RSS feed, a Confluence space, whatever your corpus is
shaped like. Register it in the plugin's own pyproject.toml —

    [project.entry-points."corpusatlas.adapters"]
    notion = "corpusatlas_notion.adapter:NotionAdapter"

— and `[[sources]] type = "notion"` in a config finds it exactly like it
finds html_blog. The built-in seven are never shadowed: REGISTRY is checked
first, so an external package can't silently override one of this module's
own adapter names. See docs/adapters.md for the contract a class has to meet.
"""
from importlib.metadata import entry_points as _entry_points

from ..cache import BuildCache
from .entity_packs import EntityPacksAdapter
from .html_blog import HtmlBlogAdapter
from .logseq import LogseqAdapter
from .obsidian import ObsidianAdapter
from .radar_entries import RadarEntriesAdapter
from .radar_scorecards import RadarScorecardsAdapter
from .web import WebAdapter

REGISTRY = {
    "entity_packs": EntityPacksAdapter,
    "html_blog": HtmlBlogAdapter,
    "logseq": LogseqAdapter,
    "obsidian": ObsidianAdapter,
    "radar_entries": RadarEntriesAdapter,
    "radar_scorecards": RadarScorecardsAdapter,
    "web": WebAdapter,
}

ENTRY_POINT_GROUP = "corpusatlas.adapters"

# The three that read a directory of files and do real parsing per file —
# the only ones an on-disk build cache pays off for. Not offered to an
# external plugin's adapter: this module has no way to know whether a
# third-party class's __init__ even accepts a `cache` kwarg, let alone that
# it would use it correctly.
CACHEABLE = {"html_blog", "obsidian", "logseq"}


def _discover_external() -> dict[str, str]:
    """Name -> the dotted path it would load, for external adapters only —
    used to report what's available without importing every one of them."""
    return {ep.name: ep.value for ep in _entry_points(group=ENTRY_POINT_GROUP)
            if ep.name not in REGISTRY}


def _external(kind: str):
    for ep in _entry_points(group=ENTRY_POINT_GROUP):
        if ep.name == kind:
            return ep.load()
    return None


def build(spec: dict, cache: BuildCache | None = None):
    kind = spec.get("type")
    cls = REGISTRY.get(kind) if kind else None
    if cls is None and kind:
        cls = _external(kind)
    if cls is None:
        known = sorted(REGISTRY) + sorted(_discover_external())
        raise ValueError(f"unknown adapter {kind!r}; known: {known}")
    kwargs = {k: v for k, v in spec.items() if k != "type"}
    if cache is not None and kind in CACHEABLE:
        kwargs["cache"] = cache.bucket(f"{kind}:{spec.get('path', '')}")
    return cls(**kwargs)
