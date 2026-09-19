"""Source adapters. Each yields Documents and knows nothing about the graph."""
from .entity_packs import EntityPacksAdapter
from .html_blog import HtmlBlogAdapter
from .obsidian import ObsidianAdapter
from .radar_entries import RadarEntriesAdapter
from .radar_scorecards import RadarScorecardsAdapter
from .web import WebAdapter

REGISTRY = {
    "entity_packs": EntityPacksAdapter,
    "html_blog": HtmlBlogAdapter,
    "obsidian": ObsidianAdapter,
    "radar_entries": RadarEntriesAdapter,
    "radar_scorecards": RadarScorecardsAdapter,
    "web": WebAdapter,
}


def build(spec: dict):
    kind = spec.get("type")
    if kind not in REGISTRY:
        raise ValueError(f"unknown adapter {kind!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[kind](**{k: v for k, v in spec.items() if k != "type"})
