"""Unit tests for Pagefind static search page generator."""
import json
import tempfile
from pathlib import Path
from corpusatlas.pagefind import generate_pagefind_pages


def test_generate_pagefind_pages_structure():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "search_pages"

        graph = {
            "schema_version": 1,
            "nodes": [
                {
                    "id": "tech:spark",
                    "label": "Apache Spark",
                    "type": "Technology",
                    "meta": {"description": "Unified engine for large-scale data processing."},
                    "aliases": ["Spark"],
                    "urls": {"wikipedia": "https://en.wikipedia.org/wiki/Apache_Spark"}
                },
                {
                    "id": "tech:kafka",
                    "label": "Apache Kafka",
                    "type": "Technology",
                    "meta": {"description": "Distributed event store and stream-processing platform."},
                }
            ],
            "edges": [
                {
                    "src": "tech:spark",
                    "rel": "consumes",
                    "dst": "tech:kafka",
                    "explanation": "Spark Streaming reads topics from Kafka."
                }
            ]
        }

        count = generate_pagefind_pages(graph, out_dir, clean=True)
        assert count == 2
        assert (out_dir / "tech_spark.html").exists()
        assert (out_dir / "tech_kafka.html").exists()

        spark_html = (out_dir / "tech_spark.html").read_text(encoding="utf-8")
        assert "data-pagefind-body" in spark_html
        assert "data-pagefind-meta=\"title\">Apache Spark" in spark_html
        assert "data-pagefind-filter=\"type:Technology\"" in spark_html
        assert "Unified engine for large-scale data processing." in spark_html
        assert "Spark Streaming reads topics from Kafka." in spark_html
        assert "https://en.wikipedia.org/wiki/Apache_Spark" in spark_html
