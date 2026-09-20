"""Automated LLM Entity & Triple Extraction Pipeline.

Extracts structured entities and typed semantic relationships from unannotated text corpora
using Ollama or OpenAI-compatible local/remote endpoints with strict ontology schema conformity.
Zero external runtime dependencies.
"""
from __future__ import annotations

import json
import re
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from corpusatlas.ontology import Ontology, DEFAULT


def parse_llm_json_response(raw_text: str) -> dict[str, list[dict[str, Any]]]:
    """Extracts and parses JSON object from LLM response containing markdown codeblocks or raw text."""
    # Attempt to extract from ```json ... ``` code fence
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, re.DOTALL)
    if fence_match:
        json_str = fence_match.group(1)
    else:
        # Match outermost curly braces
        brace_match = re.search(r"(\{.*\})", raw_text, re.DOTALL)
        json_str = brace_match.group(1) if brace_match else raw_text

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return {"entities": [], "relations": []}

    entities = data.get("entities") or []
    relations = data.get("relations") or []
    return {
        "entities": [e for e in entities if isinstance(e, dict)],
        "relations": [r for r in relations if isinstance(r, dict)],
    }


def generate_extraction_prompt(text: str, ontology: Ontology | None = None) -> str:
    """Constructs a strict JSON extraction prompt adhering to the ontology schema."""
    ont = ontology or DEFAULT
    allowed_types = sorted(ont.entity_types)
    allowed_rels = sorted(ont.relations.keys())

    return f"""You are a knowledge graph extractor.
Analyze the following input text and extract all named entities and relationships.
Strictly conform to the provided ontology schema.

Allowed Entity Types:
{", ".join(allowed_types)}

Allowed Relationships:
{", ".join(allowed_rels)}

Format your response as a single valid JSON object:
```json
{{
  "entities": [
    {{"id": "kebab-case-id", "label": "Full Name", "type": "AllowedType"}}
  ],
  "relations": [
    {{"src": "kebab-case-source-id", "rel": "ALLOWED_REL", "dst": "kebab-case-target-id", "explanation": "Brief context"}}
  ]
}}
```

Input Text:
\"\"\"
{text}
\"\"\"
"""


def extract_entities_and_triples_from_text(
    text: str,
    endpoint: str = "http://localhost:11434/api/generate",
    model: str = "llama3",
    ontology: Ontology | None = None,
    mock_response: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Sends extraction prompt to LLM endpoint and returns schema-validated entities & triples."""
    ont = ontology or DEFAULT

    if mock_response is not None:
        raw_output = mock_response
    else:
        prompt = generate_extraction_prompt(text, ont)
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }).encode("utf-8")

        req = urllib.request.Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                raw_output = result.get("response") or result.get("content") or ""
        except (urllib.error.URLError, TimeoutError) as err:
            return {"entities": [], "relations": []}

    parsed = parse_llm_json_response(raw_output)
    return ont.filter_conforming_triples(parsed["entities"], parsed["relations"])


def convert_extracted_to_pack_toml(
    extracted: dict[str, list[dict[str, Any]]],
    pack_name: str = "extracted-pack",
) -> str:
    """Serializes schema-conforming entities and relations into standard CorpusAtlas TOML pack."""
    lines = [
        f'# CorpusAtlas Semantic Pack: {pack_name}',
        '# Generated via Automated LLM Extraction Pipeline',
        '',
    ]

    for ent in extracted.get("entities", []):
        eid = ent.get("id", "")
        label = ent.get("label", eid)
        etype = ent.get("type", "Technology")
        lines.append('[[entity]]')
        lines.append(f'id = "{eid}"')
        lines.append(f'label = "{label}"')
        lines.append(f'type = "{etype}"')
        lines.append('')

    for rel in extracted.get("relations", []):
        src = rel.get("src", "")
        dst = rel.get("dst", "")
        rname = rel.get("rel", "")
        expl = rel.get("explanation", "")
        lines.append('[[claim]]')
        lines.append(f'subject = "{src}"')
        lines.append(f'relation = "{rname}"')
        lines.append(f'object = "{dst}"')
        if expl:
            lines.append(f'explanation = "{expl}"')
        lines.append('')

    return "\n".join(lines)
