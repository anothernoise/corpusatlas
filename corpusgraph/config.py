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
    # Every path in the config is relative to the config file, so the module
    # stays portable — the alias table is no exception.
    onto = cfg.get("ontology")
    if onto and "aliases" in onto:
        onto["aliases"] = str((base / onto["aliases"]).resolve())
    return cfg
