"""MkDocs Material Plugin and Markdown Fence Transformer for CorpusAtlas.

Enables documentation authors to embed interactive knowledge graphs in MkDocs with simple Markdown code blocks:
```corpusatlas
src: assets/graph.json
focus: apache-spark
height: 500px
theme: dark
```
Zero external runtime dependencies.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any


CORPUSATLAS_FENCE_RE = re.compile(
    r"```corpusatlas\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def transform_markdown_fences(markdown_text: str) -> str:
    """Transforms ```corpusatlas fence blocks into <corpusatlas-graph> custom elements."""

    def replacer(match: re.Match) -> str:
        body = match.group(1).strip()
        params: dict[str, str] = {}
        for line in body.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                k, v = line.split(":", 1)
                params[k.strip().lower()] = v.strip().strip('"\'')

        src = params.get("src", "graph.json")
        focus = params.get("focus", "")
        height = params.get("height", "500px")
        theme = params.get("theme", "auto")
        layout = params.get("layout", "force")

        attrs = [f'src="{src}"', f'height="{height}"']
        if focus:
            attrs.append(f'focus="{focus}"')
        if theme != "auto":
            attrs.append(f'theme="{theme}"')
        if layout != "force":
            attrs.append(f'layout="{layout}"')

        attr_str = " ".join(attrs)
        return f'<corpusatlas-graph {attr_str}></corpusatlas-graph>'

    return CORPUSATLAS_FENCE_RE.sub(replacer, markdown_text)


try:
    from mkdocs.plugins import BasePlugin
except ImportError:
    # Graceful fallback when mkdocs is not installed in the current environment
    class BasePlugin:  # type: ignore[no-redef]
        pass


class CorpusAtlasPlugin(BasePlugin):
    """MkDocs plugin for integrating CorpusAtlas interactive graph components."""

    def on_config(self, config: dict[str, Any]) -> dict[str, Any]:
        extra_js = config.setdefault("extra_javascript", [])
        embed_js_url = "https://cdn.jsdelivr.net/npm/@corpusatlas/graph@0.11.0/dist/corpusatlas-graph.js"
        if embed_js_url not in extra_js:
            extra_js.append(embed_js_url)
        return config

    def on_page_markdown(
        self,
        markdown: str,
        page: Any = None,
        config: Any = None,
        files: Any = None,
    ) -> str:
        return transform_markdown_fences(markdown)
