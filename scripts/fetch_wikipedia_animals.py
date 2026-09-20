#!/usr/bin/env python3
"""Fetch 1,000 animal Wikipedia pages and materialize as an Obsidian-compatible corpus.
Uses batch requests (50 titles per call) with polite User-Agent and retry logic.

Usage:
    python3 scripts/fetch_wikipedia_animals.py [target_count]
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = ROOT / "corpora" / "animals"
NOTES_DIR = CORPUS_DIR / "notes"
NOTES_DIR.mkdir(parents=True, exist_ok=True)

USER_AGENT = "CorpusAtlasAnimalBenchmark/1.0 (contact: dmansh@gmail.com) Python-urllib"
TARGET_COUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 1000


def api_get(params: dict) -> dict:
    url = f"https://en.wikipedia.org/w/api.php?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1.0 * (attempt + 1))
    return {}


def collect_animal_titles(target_count: int = 1000) -> list[str]:
    print(f"Collecting {target_count} animal titles from Wikipedia lists...")
    lists = [
        "List_of_animal_names",
        "List_of_birds",
        "List_of_mammals",
        "List_of_reptiles",
        "List_of_amphibians",
    ]
    titles = set()
    stop_words = [
        "identifier", "wayback", "doi", "bibcode", "issn", "pmid",
        "disambiguation", "category:", "portal:", "wikipedia:", "list of",
        "template:", "family", "genus", "order", "class", "species", "subspecies"
    ]
    for page in lists:
        data = api_get({"action": "parse", "page": page, "prop": "links", "format": "json"})
        links = [x["*"] for x in data.get("parse", {}).get("links", []) if x.get("ns") == 0]
        for l in links:
            l_clean = l.strip()
            if not l_clean or len(l_clean) < 3 or "(" in l_clean or "/" in l_clean:
                continue
            if any(s in l_clean.lower() for s in stop_words):
                continue
            titles.add(l_clean)
            if len(titles) >= target_count:
                break
        if len(titles) >= target_count:
            break
        time.sleep(0.5)

    ordered = sorted(list(titles))[:target_count]
    print(f"Collected {len(ordered)} animal titles.")
    return ordered


def fetch_and_materialize(titles: list[str]) -> None:
    title_set = set(titles)
    batch_size = 50
    total = len(titles)
    print(f"Fetching {total} pages in batches of {batch_size}...")

    entities_toml = ["# Animal Registry\n"]

    for i in range(0, total, batch_size):
        batch = titles[i : i + batch_size]
        titles_str = "|".join(batch)
        params = {
            "action": "query",
            "prop": "extracts|links",
            "pllimit": 500,
            "exintro": 1,
            "explaintext": 1,
            "titles": titles_str,
            "format": "json",
        }
        data = api_get(params)
        pages = data.get("query", {}).get("pages", {})

        for pid, page in pages.items():
            t = page.get("title", "")
            if not t:
                continue
            extract = page.get("extract", "")
            raw_links = [l.get("title", "") for l in page.get("links", []) if l.get("ns") == 0]
            animal_links = [l for l in raw_links if l in title_set and l != t]

            content_lines = [f"# {t}\n", f"Wikipedia article for {t}.\n"]
            if extract:
                content_lines.append(extract + "\n")
            if animal_links:
                content_lines.append("## Related Animals\n")
                content_lines.append(" ".join(f"[[{al}]]" for al in animal_links[:15]) + "\n")

            slug = re.sub(r"[^\w]+", "-", t.lower()).strip("-")
            filename = f"{slug}.md"
            (NOTES_DIR / filename).write_text("\n".join(content_lines), encoding="utf-8")

            entities_toml.append(
                f'[[entity]]\n'
                f'id   = "{slug}"\n'
                f'name = "{t}"\n'
                f'type = "Animal"\n'
                f'canonical_url = "https://en.wikipedia.org/wiki/{urllib.parse.quote(t.replace(" ", "_"))}"\n'
            )

        print(f"  Fetched {min(i + batch_size, total)}/{total} pages...")
        time.sleep(0.4)

    (CORPUS_DIR / "entities.toml").write_text("\n".join(entities_toml), encoding="utf-8")
    print(f"Wrote {CORPUS_DIR / 'entities.toml'}")

    ontology_content = """# Animals Domain Ontology
entity_types  = ["Animal", "Taxon", "Habitat", "Diet"]
context_types = ["Document"]

[[relation]]
name   = "PREYS_ON"
source = ["Animal"]
target = ["Animal"]
group  = "Ecology"

[[relation]]
name   = "FOUND_IN"
source = ["Animal"]
target = ["Habitat"]
group  = "Ecology"

[[relation]]
name   = "CONSUMES"
source = ["Animal"]
target = ["Diet"]
group  = "Ecology"

[[relation]]
name   = "BELONGS_TO_TAXON"
source = ["Animal"]
target = ["Taxon"]
group  = "Taxonomy"

[[relation]]
name      = "COMPARES_TO"
source    = ["Animal"]
target    = ["Animal"]
group     = "Ecology"
symmetric = true

[[relation]]
name      = "ALTERNATIVE_TO"
source    = ["Animal"]
target    = ["Animal"]
group     = "Ecology"
symmetric = true

[[relation]]
name    = "REFERENCES"
source  = ["Document"]
target  = ["Document"]
context = true

[[relation]]
name    = "COVERS"
source  = ["Document"]
target  = ["Animal", "Taxon", "Habitat", "Diet"]
context = true

[[relation]]
name    = "ABOUT"
source  = ["Document"]
target  = ["Taxon", "Habitat", "Diet"]
context = true
"""
    (CORPUS_DIR / "ontology.toml").write_text(ontology_content, encoding="utf-8")
    print(f"Wrote {CORPUS_DIR / 'ontology.toml'}")

    config_content = """# Configuration for 1000 Animal Wikipedia pages
[[sources]]
type     = "obsidian"
path     = "notes"
url_base = "https://en.wikipedia.org/wiki/"

[ontology]
entities = "entities.toml"
schema   = "ontology.toml"
"""
    (CORPUS_DIR / "corpusatlas.toml").write_text(config_content, encoding="utf-8")
    print(f"Wrote {CORPUS_DIR / 'corpusatlas.toml'}")


if __name__ == "__main__":
    titles = collect_animal_titles(TARGET_COUNT)
    fetch_and_materialize(titles)
    print("Done! Corpus ready in corpora/animals/")
