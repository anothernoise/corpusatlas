"""Entity resolution: many written forms, one typed entity.

Without this every producer invents its own spelling and the graph quietly
grows two nodes for one thing. The registry is the single place that says
what an entity is called, what type it is, and which scorecard options, radar
entries and tags name it.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from .ontology import DEFAULT, ENTITY_PREFIX, Ontology


def slug(s: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in s)
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def entity_id(s: str) -> str:
    """"apache-spark" or "entity:apache-spark" -> "entity:apache-spark"."""
    return s if s.startswith(ENTITY_PREFIX) else ENTITY_PREFIX + s


class RegistryError(ValueError):
    pass


class Resolver:
    """Maps a written form to canonical entity ids.

    Resolution returns a LIST, because one scorecard option can name two
    entities ("Druid / Pinot"). Four lookup kinds, because the same string
    means different things depending on where it was read:

    ``option``  A scorecard option string. Table first; falls back to slugging
                so an unregistered option still lands somewhere predictable
                (validate_entities.py is what refuses to ship that).
    ``name``    A name or alias, as written in prose or a pack. Falls back to
                slugging.
    ``radar``   A radar entry id. Table-only: an entry names an entity only
                when the registry says which one.
    ``tag``     A blog tag. Table-only: "olap" names a concept only because a
                human said so; most tags are subjects, not entities.
    """

    def __init__(self, entities=(), ontology: Ontology = DEFAULT):
        self._entities: dict[str, dict] = {}
        self._by_name: dict[str, str] = {}
        self._by_option: dict[str, list[str]] = {}
        self._by_radar: dict[str, list[str]] = {}
        self._by_tag: dict[str, list[str]] = {}
        for raw in entities:
            e = dict(raw)
            eid = entity_id(e["id"])
            if eid in self._entities:
                raise RegistryError(f"duplicate entity id {e['id']}")
            if e.get("type") not in ontology.entity_types:
                raise RegistryError(f"{e['id']}: type {e.get('type')!r} is not an entity type")
            self._entities[eid] = e
            for form in (e["id"], e["name"], *e.get("aliases", ())):
                self._by_name.setdefault(slug(form), eid)
            for o in e.get("options", ()):
                self._by_option.setdefault(o, []).append(eid)
            for r in e.get("radar", ()):
                self._by_radar.setdefault(r, []).append(eid)
            for t in e.get("tags", ()):
                self._by_tag.setdefault(t, []).append(eid)

    @classmethod
    def from_config(cls, cfg: dict, ontology: Ontology = DEFAULT) -> "Resolver":
        path = (cfg.get("ontology") or {}).get("entities")
        if not path:
            return cls(ontology=ontology)
        doc = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        return cls(doc.get("entity", []), ontology=ontology)

    def resolve(self, raw: str, kind: str = "name") -> list[str]:
        if kind == "option":
            if raw in self._by_option:
                return list(self._by_option[raw])
            return self.resolve(raw, "name")
        if kind == "name":
            s = slug(raw)
            if not s:
                return []
            return [self._by_name.get(s, ENTITY_PREFIX + s)]
        if kind == "radar":
            return list(self._by_radar.get(raw, ()))
        if kind == "tag":
            return list(self._by_tag.get(raw, ()))
        raise ValueError(f"unknown resolution kind {kind!r}")

    def known(self, eid: str) -> bool:
        return eid in self._entities

    def entity(self, eid: str) -> dict | None:
        return self._entities.get(eid)

    def type(self, eid: str) -> str | None:
        e = self._entities.get(eid)
        return e["type"] if e else None

    def entities(self):
        return self._entities.items()

    def options_registered(self) -> set[str]:
        return set(self._by_option)
