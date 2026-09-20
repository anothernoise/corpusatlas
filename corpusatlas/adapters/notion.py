"""Notion workspace export ingestion adapter."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ..model import Document


def _parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    meta: Dict[str, Any] = {}
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            raw_meta = parts[1]
            body = parts[2].strip()
            for line in raw_meta.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    k = k.strip()
                    v = v.strip()
                    if v.startswith("[") and v.endswith("]"):
                        # List of items
                        items = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
                        meta[k] = items
                    else:
                        meta[k] = v.strip("'\"")
    return meta, body


class NotionAdapter:
    """Ingests Notion workspace markdown and block export trees."""

    def __init__(self, path: str | Path, workspace: Optional[str] = None, **kwargs: Any) -> None:
        self.path = Path(path)
        self.workspace = workspace or "notion"

    def documents(self) -> Iterator[Document]:
        if not self.path.exists():
            return

        files = [self.path] if self.path.is_file() else sorted(self.path.glob("**/*.md"))
        for f in files:
            try:
                raw = f.read_text(encoding="utf-8")
            except Exception:
                continue

            meta, body = _parse_frontmatter(raw)

            # Determine title: frontmatter title, or first # Heading, or filename
            title = meta.get("title")
            if not title:
                match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
                if match:
                    title = match.group(1).strip()
                else:
                    # Clean notion export hex suffix like "My Page 1a2b3c4d"
                    stem = f.stem
                    title = re.sub(r"\s+[0-9a-f]{32}$", "", stem)

            doc_id = f"notion:{f.stem}"
            url = meta.get("url", f"https://notion.so/{f.stem}")
            date = str(meta.get("date")) if "date" in meta else None

            tags_val = meta.get("tags", [])
            tags: List[str] = tags_val if isinstance(tags_val, list) else [str(tags_val)]

            yield Document(
                id=doc_id,
                title=title,
                url=url,
                kind="notion-page",
                date=date,
                text=body,
                tags=tuple(tags),
                meta=meta,
            )
