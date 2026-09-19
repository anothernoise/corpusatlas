"""corpusatlas CLI — build, stats, validate, convert."""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import __version__
from . import config as cfgmod
from .adapters import build as build_adapter
from .cache import BuildCache
from .csv_export import write_csv
from .emit import SCHEMA_VERSION, write_graph
from .extract import DeterministicExtractor, MentionsExtractor, PacksExtractor
from .graphml import write_graphml
from .merge import merge
from .neo4j_export import write_neo4j_csv
from .ontology import DEFAULT, Ontology, OntologyError, TIERS
from .rdf_export import DEFAULT_BASE, write_turtle
from .resolve import RegistryError, Resolver


def cmd_build(args) -> int:
    if not args.dry_run and not args.out:
        print("build needs --out (or --dry-run)", file=sys.stderr)
        return 1
    cfg = cfgmod.load(args.config)
    schema = (cfg.get("ontology") or {}).get("schema")
    ontology = Ontology.from_toml(schema) if schema else DEFAULT
    cache = BuildCache(Path(args.cache) if args.cache else None)
    specs = cfg.get("sources", [])
    docs, sources = [], []

    def load(spec: dict) -> list:
        return list(build_adapter(spec, cache=cache).documents())

    # Each source's own I/O (a web fetch, a directory walk) is independent
    # of every other source's, so with more than one they load concurrently
    # — same principle as WebAdapter's own internal concurrency. Below two
    # sources the thread pool would be pure overhead for no benefit, so it's
    # skipped entirely rather than spun up to run one thing. Either way,
    # results are collected back in the config's own order: which source
    # loads first is not something a build's output may depend on.
    if len(specs) <= 1:
        results = [load(spec) for spec in specs]
    else:
        with ThreadPoolExecutor(max_workers=min(8, len(specs))) as pool:
            results = list(pool.map(load, specs))

    for spec, got in zip(specs, results):
        docs.extend(got)
        sources.append(f"{spec['type']} ({len(got)})")
        print(f"  {spec['type']:<20} {len(got):>4} documents")

    if args.cache:
        cache.save()
        total = cache.hits + cache.misses
        if total:
            print(f"  cache               {cache.hits:>4}/{total} files reused from {args.cache}")

    if not docs:
        print("no documents found — check the paths in your config", file=sys.stderr)
        return 1

    resolver = Resolver.from_config(cfg, ontology=ontology)
    # Order is precedence: merge keeps the first writer of any node or edge.
    # Deterministic runs first, packs second (a curated claim beats an
    # independent re-derivation of the same fact), and the mentions scanner
    # runs last, over the vocabulary the first two tiers just produced — so
    # it can only ADD reach, never relabel or override a hand-written or
    # reviewed claim. Sequential, not a uniform loop, because mentions needs
    # to see what the earlier tiers named before it can search for it.
    det = DeterministicExtractor(resolver=resolver, ontology=ontology)
    det_nodes, det_edges = (list(x) for x in det.run(docs))
    packs = PacksExtractor.from_config(cfg, resolver=resolver, ontology=ontology)
    pack_nodes, pack_edges = (list(x) for x in packs.run(docs))
    mentions = MentionsExtractor(det_nodes + pack_nodes, resolver=resolver, ontology=ontology)
    ment_nodes, ment_edges = (list(x) for x in mentions.run(docs))

    for ex_name, n, e in ((det.name, det_nodes, det_edges),
                          (packs.name, pack_nodes, pack_edges),
                          (mentions.name, ment_nodes, ment_edges)):
        print(f"  {ex_name:<20} {len(n):>4} nodes, {len(e)} edges")

    node_sets = [det_nodes, pack_nodes, ment_nodes]
    edge_sets = [det_edges, pack_edges, ment_edges]
    nodes, edges = merge(node_sets, edge_sets, live_doc_ids={d.id for d in docs})
    if args.dry_run:
        print(f"\n(dry run) would write {len(nodes)} nodes, {len(edges)} edges — nothing written")
        return 0
    counts = write_graph(Path(args.out), nodes, edges, sources=sources, ontology=ontology)
    print(f"\nwrote {args.out}: {counts['nodes']} nodes, {counts['edges']} edges")
    return 0


def cmd_stats(args) -> int:
    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    by_type: dict[str, int] = {}
    for n in g["nodes"]:
        by_type[n["type"]] = by_type.get(n["type"], 0) + 1
    by_rel: dict[str, int] = {}
    for e in g["edges"]:
        by_rel[e["rel"]] = by_rel.get(e["rel"], 0) + 1
    top = sorted(g["nodes"], key=lambda n: -n.get("degree", 0))[:10]

    if getattr(args, "json", False):
        print(json.dumps({
            "generated": g["generated"], "generator": g["generator"],
            "schema_version": g.get("schema_version", 0),
            "counts": g["counts"],
            "by_type": by_type, "by_relation": by_rel,
            "most_connected": [{"id": n["id"], "label": n["label"], "degree": n.get("degree", 0)}
                               for n in top],
        }, indent=1))
        return 0

    print(f"generated {g['generated']} by {g['generator']} "
          f"(schema {g.get('schema_version', '<1')})")
    print(f"{g['counts']['nodes']} nodes, {g['counts']['edges']} edges\n")
    print("nodes by type:")
    for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<12} {v:>5}")
    print("\nedges by relation:")
    for k, v in sorted(by_rel.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<12} {v:>5}")
    print("\nmost connected:")
    for n in top:
        print(f"  {n.get('degree',0):>4}  {n['label'][:60]}")
    return 0


def cmd_validate(args) -> int:
    """Invariants the artifact must satisfy before it is allowed to ship.

    Reads its vocabulary from the artifact itself (`entity_types`,
    `context_types`, `relation_groups`) rather than this package's own
    ontology — a graph built from a custom schema validates against its own
    vocabulary, not corpusatlas's default. `context_types` is only present
    from this version on; an older artifact falls back to the default so it
    still validates.
    """
    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    # A newer schema_version means a future corpusatlas changed the artifact's
    # shape in a way this build doesn't know about — not necessarily invalid
    # (the checks below are still meaningful over the fields they know), but
    # worth a heads-up rather than a silent pass on fields this code can't see.
    seen_version = g.get("schema_version", 0)
    if seen_version > SCHEMA_VERSION:
        print(f"  warning: graph is schema_version {seen_version}, this corpusatlas "
              f"knows up to {SCHEMA_VERSION} — some checks may not see newer fields",
              file=sys.stderr)
    entity_types = set(g.get("entity_types") or ())
    context_types = set(g.get("context_types") or DEFAULT.context_types)
    node_types = entity_types | context_types
    semantic_relations = {r for rs in (g.get("relation_groups") or {}).values() for r in rs}
    ids = {n["id"] for n in g["nodes"]}
    errs: list[str] = []

    if len(ids) != len(g["nodes"]):
        errs.append("duplicate node ids")
    # The ontology is only closed if something checks it on the way out. A node
    # type nothing recognises means a producer invented one, and the renderer
    # would draw it in the fallback grey rather than fail.
    for n in g["nodes"]:
        if n["type"] not in node_types:
            errs.append(f"unknown node type {n['type']!r} on {n['id']}")
    for e in g["edges"]:
        if e["src"] not in ids:
            errs.append(f"dangling src {e['src']}")
        if e["dst"] not in ids:
            errs.append(f"dangling dst {e['dst']}")
        if not e.get("prov", {}).get("doc"):
            errs.append(f"edge without provenance: {e['src']}-{e['rel']}->{e['dst']}")
        # The tier is what keeps a hand-written edge from ever being mistaken
        # for an inferred one, so an edge without it is not shippable.
        if e.get("prov", {}).get("tier") not in TIERS:
            errs.append(f"edge without a known tier: {e['src']}-{e['rel']}->{e['dst']}")
    # The renderer draws semantic edges and links context from cards. An edge
    # that is both — a semantic relation touching an article or a radar call —
    # would be invisible in one and wrong in the other.
    types = {n["id"]: n["type"] for n in g["nodes"]}
    for e in g["edges"]:
        if e["rel"] in semantic_relations and (types.get(e["src"]) in context_types
                                              or types.get(e["dst"]) in context_types):
            errs.append(f"semantic edge touches a context node: {e['src']}-{e['rel']}->{e['dst']}")
    if g["counts"]["nodes"] != len(g["nodes"]) or g["counts"]["edges"] != len(g["edges"]):
        errs.append("counts header disagrees with the payload")
    isolated = ids - ({e["src"] for e in g["edges"]} | {e["dst"] for e in g["edges"]})
    if isolated:
        errs.append(f"{len(isolated)} isolated nodes")

    if getattr(args, "json", False):
        print(json.dumps({"valid": not errs, "problems": errs}, indent=1))
        return 1 if errs else 0

    for e in errs[:20]:
        print(f"  FAIL {e}", file=sys.stderr)
    print(f"{len(errs)} problems" if errs else "graph valid")
    return 1 if errs else 0


def cmd_diff(args) -> int:
    """Compares two built graphs — what a verification-before-shipping step
    (this project's own release process, and any consuming site's CI) has
    always had to reconstruct by hand: does a rebuild actually match what's
    committed, and if not, exactly what changed. `--fail-on-change` turns
    that into a gate: exit 1 if OLD and NEW differ at all, for a CI step
    that's meant to assert a rebuild is a no-op.

    Node degree is intentionally not itself a tracked field — it is derived
    from edges, so a node whose degree changed shows up via the edge diff
    that caused it, not as a second, redundant "node changed" report.
    """
    old = json.loads(Path(args.old).read_text(encoding="utf-8"))
    new = json.loads(Path(args.new).read_text(encoding="utf-8"))

    def node_content(n: dict) -> dict:
        return {k: v for k, v in n.items() if k != "degree"}

    old_nodes = {n["id"]: n for n in old["nodes"]}
    new_nodes = {n["id"]: n for n in new["nodes"]}
    nodes_added = sorted(set(new_nodes) - set(old_nodes))
    nodes_removed = sorted(set(old_nodes) - set(new_nodes))
    nodes_changed = sorted(nid for nid in (set(old_nodes) & set(new_nodes))
                           if node_content(old_nodes[nid]) != node_content(new_nodes[nid]))

    def edge_key(e: dict) -> tuple:
        return (e["src"], e["rel"], e["dst"], e.get("scope") or "")

    old_edges = {edge_key(e): e for e in old["edges"]}
    new_edges = {edge_key(e): e for e in new["edges"]}
    edges_added = sorted(set(new_edges) - set(old_edges))
    edges_removed = sorted(set(old_edges) - set(new_edges))

    changed = bool(nodes_added or nodes_removed or nodes_changed or edges_added or edges_removed)

    if getattr(args, "json", False):
        print(json.dumps({
            "changed": changed,
            "nodes_added": nodes_added, "nodes_removed": nodes_removed,
            "nodes_changed": nodes_changed,
            "edges_added": [{"src": s, "rel": r, "dst": d, "scope": sc or None}
                            for s, r, d, sc in edges_added],
            "edges_removed": [{"src": s, "rel": r, "dst": d, "scope": sc or None}
                              for s, r, d, sc in edges_removed],
        }, indent=1))
    else:
        if not changed:
            print("no differences")
        else:
            for nid in nodes_added:
                print(f"  + node {nid} ({new_nodes[nid]['type']})")
            for nid in nodes_removed:
                print(f"  - node {nid} ({old_nodes[nid]['type']})")
            for nid in nodes_changed:
                print(f"  ~ node {nid}")
            for s, r, d, sc in edges_added:
                print(f"  + edge {s} -{r}-> {d}" + (f" [{sc}]" if sc else ""))
            for s, r, d, sc in edges_removed:
                print(f"  - edge {s} -{r}-> {d}" + (f" [{sc}]" if sc else ""))
            print(f"\n{len(nodes_added)} nodes added, {len(nodes_removed)} removed, "
                  f"{len(nodes_changed)} changed; "
                  f"{len(edges_added)} edges added, {len(edges_removed)} removed")

    if args.fail_on_change and changed:
        return 1
    return 0


def cmd_convert(args) -> int:
    """Reformats a built graph.json — it never re-runs extraction, so it
    works on any graph.json this module ever produced, not just a fresh
    build."""
    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    if args.format == "graphml":
        if not args.out:
            print("convert --format graphml needs --out", file=sys.stderr)
            return 1
        write_graphml(Path(args.out), g)
        print(f"wrote {args.out}")
    elif args.format == "csv":
        if not args.out_dir:
            print("convert --format csv needs --out-dir", file=sys.stderr)
            return 1
        nodes_path, edges_path = write_csv(Path(args.out_dir), g)
        print(f"wrote {nodes_path}\nwrote {edges_path}")
    elif args.format == "neo4j":
        if not args.out_dir:
            print("convert --format neo4j needs --out-dir", file=sys.stderr)
            return 1
        nodes_path, rels_path = write_neo4j_csv(Path(args.out_dir), g)
        print(f"wrote {nodes_path}\nwrote {rels_path}\n\n"
              f"Load with, e.g.:\n"
              f"  neo4j-admin database import full --nodes={nodes_path} "
              f"--relationships={rels_path} neo4j")
    elif args.format == "turtle":
        if not args.out:
            print("convert --format turtle needs --out", file=sys.stderr)
            return 1
        write_turtle(Path(args.out), g, base=args.base or DEFAULT_BASE)
        print(f"wrote {args.out}")
    return 0


def cmd_ontology_check(args) -> int:
    """Loads and validates a schema file alone — no corpus, no [[sources]],
    just Ontology.from_toml()'s own checks. For iterating on a schema before
    there's a real corpus configured to build it against."""
    try:
        o = Ontology.from_toml(args.schema)
    except OntologyError as e:
        print(f"  FAIL {e}", file=sys.stderr)
        return 1
    print(f"schema valid: {len(o.entity_types)} entity types, {len(o.context_types)} context types")
    print(f"{len(o.relations)} relations: {len(o.semantic_relations)} semantic, "
          f"{len(o.context_relations)} context")
    return 0


def cmd_registry_check(args) -> int:
    """Loads and validates an entity registry (entities.toml) alone — no
    corpus, no [[sources]], just Resolver's own checks: every id unique,
    every type a real entity type in the ontology in play. The counterpart
    to ontology-check for the other half of a config that can go wrong
    before there's a real corpus to build against.
    """
    ontology = Ontology.from_toml(args.schema) if args.schema else DEFAULT
    try:
        doc = tomllib.loads(Path(args.entities).read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(f"  FAIL {e}", file=sys.stderr)
        return 1
    entities = doc.get("entity", [])
    try:
        resolver = Resolver(entities, ontology=ontology)
    except RegistryError as e:
        print(f"  FAIL {e}", file=sys.stderr)
        return 1

    by_type: dict[str, int] = {}
    for _, entity in resolver.entities():
        by_type[entity["type"]] = by_type.get(entity["type"], 0) + 1
    print(f"registry valid: {len(entities)} entities")
    for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"  {t:<20} {n:>4}")
    return 0


_INIT_CONFIG = '''\
# Generated by `corpusatlas init`. Edit the path below to point at your own
# corpus, then:
#   corpusatlas build --config corpusatlas.toml --out graph.json

[[sources]]
type     = "obsidian"   # a directory of markdown notes — an Obsidian vault
path     = "notes"      # or just plain markdown; wikilinks are optional
url_base = "/notes/"

[ontology]
entities = "entities.toml"
# schema = "ontology.toml"   # optional — see docs/ontology-schema.md
'''

_INIT_ENTITIES = '''\
# The entity registry: named instances of your ontology's types. Empty is a
# valid starting point — corpusatlas still builds a graph from whatever
# structure your corpus already has (wikilinks, tags); the registry adds
# identity and precise typing on top of that.

# [[entity]]
# id   = "example"
# name = "Example"
# type = "Concept"
'''


def cmd_init(args) -> int:
    """Scaffolds a starter config and an empty entity registry — a place to
    start editing rather than copying example.toml, which points at a real
    corpus's own directories and doesn't run as-is."""
    target = Path(args.dir)
    target.mkdir(parents=True, exist_ok=True)
    config_path = target / "corpusatlas.toml"
    entities_path = target / "entities.toml"
    existing = [p for p in (config_path, entities_path) if p.exists()]
    if existing:
        print(f"  refusing to overwrite: {', '.join(str(p) for p in existing)}", file=sys.stderr)
        return 1
    config_path.write_text(_INIT_CONFIG, encoding="utf-8")
    entities_path.write_text(_INIT_ENTITIES, encoding="utf-8")
    print(f"wrote {config_path}\nwrote {entities_path}\n\n"
          f"Edit the path in {config_path.name} to point at your corpus, then:\n"
          f"  corpusatlas build --config {config_path} --out graph.json")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="corpusatlas")
    p.add_argument("--version", action="version", version=f"corpusatlas {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the graph from a config")
    b.add_argument("--config", default="corpusatlas.toml")
    b.add_argument("--out", help="required unless --dry-run")
    b.add_argument("--dry-run", action="store_true",
                   help="report node/edge counts without writing the artifact")
    b.add_argument("--cache",
                   help="path to a file-parse cache (html_blog/obsidian/logseq only); "
                        "created if missing, reused and updated if present")
    b.set_defaults(fn=cmd_build)

    s = sub.add_parser("stats", help="summarise a built graph")
    s.add_argument("--graph", required=True)
    s.add_argument("--json", action="store_true", help="machine-readable output")
    s.set_defaults(fn=cmd_stats)

    v = sub.add_parser("validate", help="check the graph's invariants")
    v.add_argument("--graph", required=True)
    v.add_argument("--json", action="store_true", help="machine-readable output")
    v.set_defaults(fn=cmd_validate)

    d = sub.add_parser("diff", help="compare two built graphs")
    d.add_argument("--old", required=True)
    d.add_argument("--new", required=True)
    d.add_argument("--json", action="store_true", help="machine-readable output")
    d.add_argument("--fail-on-change", action="store_true",
                   help="exit 1 if OLD and NEW differ at all — for a CI step asserting a no-op rebuild")
    d.set_defaults(fn=cmd_diff)

    c = sub.add_parser("convert", help="reformat a built graph as GraphML or CSV")
    c.add_argument("--graph", required=True)
    c.add_argument("--format", choices=["graphml", "csv", "neo4j", "turtle"], required=True)
    c.add_argument("--out", help="output file, for --format graphml or turtle")
    c.add_argument("--out-dir", help="output directory, for --format csv or neo4j")
    c.add_argument("--base", help=f"resource IRI base, for --format turtle (default: {DEFAULT_BASE})")
    c.set_defaults(fn=cmd_convert)

    oc = sub.add_parser("ontology-check", help="validate a schema file on its own, no corpus needed")
    oc.add_argument("--schema", required=True)
    oc.set_defaults(fn=cmd_ontology_check)

    rc = sub.add_parser("registry-check",
                        help="validate an entity registry on its own, no corpus needed")
    rc.add_argument("--entities", required=True)
    rc.add_argument("--schema", help="a custom ontology schema, if entities aren't typed against DEFAULT")
    rc.set_defaults(fn=cmd_registry_check)

    i = sub.add_parser("init", help="scaffold a starter config and entity registry")
    i.add_argument("--dir", default=".", help="directory to write into (default: current directory)")
    i.set_defaults(fn=cmd_init)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
