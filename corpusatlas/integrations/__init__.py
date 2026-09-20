"""External platform and framework integrations for CorpusAtlas.

Provides native adapters and plugins for Obsidian, MkDocs Material, and web embed runtimes.
Zero external runtime dependencies.
"""
from corpusatlas.integrations.obsidian import export_obsidian_canvas, export_obsidian_vault
from corpusatlas.integrations.mkdocs_plugin import CorpusAtlasPlugin, transform_markdown_fences

__all__ = [
    "export_obsidian_canvas",
    "export_obsidian_vault",
    "CorpusAtlasPlugin",
    "transform_markdown_fences",
]
