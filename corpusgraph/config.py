from __future__ import annotations

import tomllib
from pathlib import Path


def load(path: str | Path) -> dict:
    p = Path(path)
    cfg = tomllib.loads(p.read_text(encoding="utf-8"))
    base = p.parent
    for src in cfg.get("sources", []):
        for key in ("path", "index"):
            if key in src:
                src[key] = str((base / src[key]).resolve())
    return cfg
