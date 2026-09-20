"""GitHub issues, pull requests, and discussions ingestion adapter."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from ..model import Document


class GitHubAdapter:
    """Ingests GitHub issues and pull requests from JSON export files or directories."""

    def __init__(self, path: str | Path, repo: Optional[str] = None, **kwargs: Any) -> None:
        self.path = Path(path)
        self.repo = repo or "github/repo"

    def _parse_item(self, item: Dict[str, Any], default_repo: str) -> Optional[Document]:
        if not isinstance(item, dict):
            return None
        num = item.get("number")
        if num is None:
            return None

        repo = self.repo or default_repo
        if "repository_url" in item and not self.repo:
            parts = item["repository_url"].split("/repos/")
            if len(parts) == 2:
                repo = parts[1]

        is_pr = "pull_request" in item
        kind = "pull-request" if is_pr else "issue"
        doc_id = f"github:{repo}#{num}"
        title = item.get("title", f"Issue #{num}")
        url = item.get("html_url", f"https://github.com/{repo}/issues/{num}")
        created_at = item.get("created_at")
        date_str = str(created_at)[:10] if created_at else None
        body = item.get("body") or ""
        full_text = f"{title}\n\n{body}"

        labels = item.get("labels") or []
        tags: List[str] = []
        for l in labels:
            if isinstance(l, dict) and "name" in l:
                tags.append(str(l["name"]))
            elif isinstance(l, str):
                tags.append(l)

        meta: Dict[str, Any] = {
            "author": (item.get("user") or {}).get("login") if isinstance(item.get("user"), dict) else None,
            "state": item.get("state"),
            "comments": item.get("comments", 0),
            "number": num,
            "repo": repo,
        }

        return Document(
            id=doc_id,
            title=title,
            url=url,
            kind=kind,
            date=date_str,
            text=full_text,
            tags=tuple(tags),
            meta={k: v for k, v in meta.items() if v is not None},
        )

    def documents(self) -> Iterator[Document]:
        if not self.path.exists():
            return

        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return

            items = data.get("items", data) if isinstance(data, dict) else data
            if isinstance(items, list):
                for it in items:
                    doc = self._parse_item(it, self.repo)
                    if doc:
                        yield doc
        elif self.path.is_dir():
            for p in sorted(self.path.glob("**/*.json")):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except Exception:
                    continue
                items = data.get("items", data) if isinstance(data, dict) else data
                if isinstance(items, list):
                    for it in items:
                        doc = self._parse_item(it, self.repo)
                        if doc:
                            yield doc
                elif isinstance(items, dict):
                    doc = self._parse_item(items, self.repo)
                    if doc:
                        yield doc
