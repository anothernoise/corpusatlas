"""Source adapters. Each yields Documents and knows nothing about the graph."""
from .html_blog import HtmlBlogAdapter
from .radar_entries import RadarEntriesAdapter
from .radar_scorecards import RadarScorecardsAdapter

REGISTRY = {
    "html_blog": HtmlBlogAdapter,
    "radar_entries": RadarEntriesAdapter,
    "radar_scorecards": RadarScorecardsAdapter,
}


def build(spec: dict):
    kind = spec.get("type")
    if kind not in REGISTRY:
        raise ValueError(f"unknown adapter {kind!r}; known: {sorted(REGISTRY)}")
    return REGISTRY[kind](**{k: v for k, v in spec.items() if k != "type"})
