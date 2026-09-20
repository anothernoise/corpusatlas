"""Confluence space and HTML export ingestion adapter."""
from __future__ import annotations

import re
from html import unescape
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from ..model import Document


def _strip_html(html: str) -> str:
    # Remove script and style elements
    clean = re.sub(r"<(script|style).*?>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Convert breaks and paragraphs to newlines
    clean = re.sub(r"<(p|br|div|tr|li)[^>]*>", "\n", clean, flags=re.IGNORECASE)
    # Remove all remaining HTML tags
    clean = re.sub(r"<[^>]+>", " ", clean)
    clean = unescape(clean)
    # Normalize multiple whitespace and newlines
    lines = [line.strip() for line in clean.splitlines()]
    return "\n".join(l for l in lines if l)


class ConfluenceAdapter:
    """Ingests Confluence space exports (HTML/Markdown) into Document models."""

    def __init__(self, path: str | Path, space_key: Optional[str] = None, **kwargs: Any) -> None:
        self.path = Path(path)
        self.space_key = space_key or "GLOBAL"

    def documents(self) -> Iterator[Document]:
        if not self.path.exists():
            return

        files: List[Path] = []
        if self.path.is_file():
            files = [self.path]
        else:
            files.extend(sorted(self.path.glob("**/*.html")))
            files.extend(sorted(self.path.glob("**/*.htm")))
            files.extend(sorted(self.path.glob("**/*.md")))

        for f in files:
            try:
                raw = f.read_text(encoding="utf-8")
            except Exception:
                continue

            title = f.stem
            is_html = f.suffix.lower() in (".html", ".htm")
            if is_html:
                # Try finding <title>
                title_match = re.search(r"<title>(.*?)</title>", raw, re.IGNORECASE | re.DOTALL)
                if title_match:
                    title = title_match.group(1).split(" - Confluence")[0].split(" : ")[-1].strip()
                text = _strip_html(raw)
            else:
                # Markdown
                first_heading = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
                if first_heading:
                    title = first_heading.group(1).strip()
                text = raw

            doc_id = f"confluence:{self.space_key}/{f.stem}"
            url = f"https://confluence.atlassian.net/wiki/spaces/{self.space_key}/pages/{f.stem}"

            meta: Dict[str, Any] = {
                "space_key": self.space_key,
                "file_path": str(f),
            }

            yield Document(
                id=doc_id,
                title=title,
                url=url,
                kind="confluence-page",
                text=text,
                meta=meta,
            )
