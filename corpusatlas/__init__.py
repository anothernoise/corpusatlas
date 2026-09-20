"""CorpusAtlas knowledge graph engine."""
from .dataframe import (
    GraphData,
    load_graph,
    to_arrow,
    to_dict_records,
    to_pandas,
    to_polars,
)
from .model import Document, Edge, Node
from .notebook import show, to_html

__version__ = "0.12.0"

__all__ = [
    "__version__",
    "Document",
    "Node",
    "Edge",
    "GraphData",
    "load_graph",
    "to_arrow",
    "to_polars",
    "to_pandas",
    "to_dict_records",
    "show",
    "to_html",
]
