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
from .cache import BuildCache, MerkleDAGCache, run_extractor_cached
from .csv_export import write_csv
from .emit import SCHEMA_VERSION, write_graph
from .export import export_duckdb
from .extract import DeterministicExtractor, Extractor, MentionsExtractor, PacksExtractor
from .graphml import write_graphml
from .merge import merge
from .neo4j_export import write_neo4j_csv
from .ontology import DEFAULT, Ontology, OntologyError, TIERS
from .pipeline_store import SQLitePipelineStore
from .rdf_export import DEFAULT_BASE, write_turtle
from .resolve import RegistryError, Resolver


def cmd_build(args) -> int:
    if not args.dry_run and not args.out:
        print("build needs --out (or --dry-run)", file=sys.stderr)
        return 1
    cfg = cfgmod.load(args.config)
    schema = (cfg.get("ontology") or {}).get("schema")
    ontology = Ontology.from_toml(schema) if schema else DEFAULT
    cache = BuildCache(Path(args.cache) if args.cache else None, fine_grained=getattr(args, "fine_cache", False))
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
    det: Extractor = DeterministicExtractor(resolver=resolver, ontology=ontology)
    packs: Extractor = PacksExtractor.from_config(cfg, resolver=resolver, ontology=ontology)

    merkle_path = getattr(args, "merkle_cache", None)
    merkle = MerkleDAGCache(Path(merkle_path)) if merkle_path else None

    if merkle is not None:
        det_nodes, det_edges, det_hits, det_misses = run_extractor_cached(det, docs, merkle)
        pack_nodes, pack_edges, pack_hits, pack_misses = run_extractor_cached(packs, docs, merkle)
        merkle.save()
        total_claims = det_hits + det_misses + pack_hits + pack_misses
        if total_claims > 0 and (det_hits + pack_hits) > 0:
            print(f"  merkle-dag cache    {det_hits + pack_hits:>4}/{total_claims} claims reused")
    else:
        det_out_nodes, det_out_edges = det.run(docs)
        det_nodes, det_edges = list(det_out_nodes), list(det_out_edges)
        packs_out_nodes, packs_out_edges = packs.run(docs)
        pack_nodes, pack_edges = list(packs_out_nodes), list(packs_out_edges)

    mentions: Extractor = MentionsExtractor(det_nodes + pack_nodes, resolver=resolver, ontology=ontology)
    ment_out_nodes, ment_out_edges = mentions.run(docs)
    ment_nodes, ment_edges = list(ment_out_nodes), list(ment_out_edges)

    for ex_name, n, e in ((det.name, det_nodes, det_edges),
                          (packs.name, pack_nodes, pack_edges),
                          (mentions.name, ment_nodes, ment_edges)):
        print(f"  {ex_name:<20} {len(n):>4} nodes, {len(e)} edges")

    store_mode = getattr(args, "store", "memory")
    if store_mode in ("sqlite", "duckdb"):
        db_path = getattr(args, "db_path", None)
        if not db_path:
            db_path = str(Path(args.out).with_suffix(".db")) if args.out else ":memory:"
        store = SQLitePipelineStore(db_path)
        store.add_tier_nodes(det_nodes, tier_order=0)
        store.add_tier_edges(det_edges, tier_order=0)
        store.add_tier_nodes(pack_nodes, tier_order=1)
        store.add_tier_edges(pack_edges, tier_order=1)
        store.add_tier_nodes(ment_nodes, tier_order=2)
        store.add_tier_edges(ment_edges, tier_order=2)
        node_cnt, edge_cnt = store.compact(live_doc_ids={d.id for d in docs})
        nodes = {n.id: n for n in store.stream_nodes()}
        edges = list(store.stream_edges())
        store.close()
        print(f"  pipeline_store ({store_mode}) {node_cnt} nodes, {edge_cnt} edges staged in {db_path}")
        if store_mode == "duckdb" and args.out:
            duckdb_target = Path(args.out).parent / (Path(args.out).stem + ".duckdb")
            export_duckdb(nodes.values(), edges, out_dir=Path(args.out).parent, db_name=duckdb_target.name)
            print(f"  duckdb_store        exported native duckdb to {duckdb_target}")
    else:
        node_sets = [det_nodes, pack_nodes, ment_nodes]
        edge_sets = [det_edges, pack_edges, ment_edges]
        nodes, edges = merge(node_sets, edge_sets, live_doc_ids={d.id for d in docs})
    if args.dry_run:
        print(f"\n(dry run) would write {len(nodes)} nodes, {len(edges)} edges — nothing written")
        return 0
    entity_colors = (cfg.get("ontology") or {}).get("entity_colors")
    counts = write_graph(Path(args.out), nodes, edges, sources=sources, ontology=ontology,
                         layout=getattr(args, "layout", False), entity_colors=entity_colors)
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

    if getattr(args, "gui", False) and getattr(args, "out", None):
        diff_nodes = []
        for nid, n in new_nodes.items():
            nd = dict(n)
            if nid in nodes_added:
                nd["diff"] = "added"
            elif nid in nodes_changed:
                nd["diff"] = "changed"
            else:
                nd["diff"] = "same"
            diff_nodes.append(nd)
        for nid in nodes_removed:
            nd = dict(old_nodes[nid])
            nd["diff"] = "removed"
            diff_nodes.append(nd)

        diff_edges = []
        for ek, e in new_edges.items():
            ed = dict(e)
            if ek in edges_added:
                ed["diff"] = "added"
            else:
                ed["diff"] = "same"
            diff_edges.append(ed)
        for ek in edges_removed:
            ed = dict(old_edges[ek])
            ed["diff"] = "removed"
            diff_edges.append(ed)

        diff_graph = {
            "schema_version": new.get("schema_version", 1),
            "generated": new.get("generated", ""),
            "generator": "corpusatlas diff --gui",
            "diff_summary": {
                "nodes_added": len(nodes_added),
                "nodes_removed": len(nodes_removed),
                "nodes_changed": len(nodes_changed),
                "edges_added": len(edges_added),
                "edges_removed": len(edges_removed),
            },
            "nodes": diff_nodes,
            "edges": diff_edges,
        }
        for k in ("entity_types", "context_types", "inverse_labels", "relation_groups"):
            if k in new:
                diff_graph[k] = new[k]
        Path(args.out).write_text(json.dumps(diff_graph, indent=1) + "\n", encoding="utf-8")
        print(f"wrote GUI diff graph to {args.out}")
        return 0

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
    if getattr(args, "dot", False):
        print(o.to_dot())
        return 0
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


def cmd_context(args) -> int:
    """Extracts an entity's ego-network formatted for LLM Graph RAG prompts."""
    from .context import extract_rag_subgraph, format_rag_markdown
    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    algo = getattr(args, "algorithm", "ppr")
    top_k = int(getattr(args, "top_k", 20))
    depth = int(getattr(args, "depth", 1))
    alpha = float(getattr(args, "alpha", 0.15))

    if algo == "hybrid":
        from .hybrid_search import hybrid_graph_search
        res = hybrid_graph_search(g, query=args.entity, top_k=top_k)
    else:
        res = extract_rag_subgraph(
            g,
            args.entity,
            algorithm=algo,
            top_k=top_k,
            depth=depth,
            alpha=alpha,
        )

    if "error" in res:
        print(res["error"], file=sys.stderr)
        return 1

    fmt = getattr(args, "format", "markdown")
    if fmt == "json":
        print(json.dumps(res, indent=2))
    else:
        print(format_rag_markdown(res))
    return 0


def cmd_export(args) -> int:
    """Exports a built graph to Cypher, RDF Turtle, or DuckDB/Parquet."""
    from .export import export_cypher, export_duckdb, export_turtle
    from .model import Edge, Node

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    nodes = [
        Node(
            id=n["id"],
            label=n["label"],
            type=n["type"],
            aliases=tuple(n.get("aliases") or ()),
            meta=n.get("meta") or {},
        )
        for n in g.get("nodes", [])
    ]
    edges = [
        Edge(
            src=e["src"],
            rel=e["rel"],
            dst=e["dst"],
            confidence=float(e.get("confidence", 1.0)),
            explanation=e.get("explanation"),
            prov=e.get("prov") or {},
        )
        for e in g.get("edges", [])
    ]

    fmt = args.format.lower()
    if fmt == "cypher":
        if not args.out:
            print("export --format cypher needs --out", file=sys.stderr)
            return 1
        export_cypher(nodes, edges, args.out)
        print(f"exported {len(nodes)} nodes and {len(edges)} edges to Cypher: {args.out}")
    elif fmt == "turtle":
        if not args.out:
            print("export --format turtle needs --out", file=sys.stderr)
            return 1
        export_turtle(nodes, edges, args.out)
        print(f"exported {len(nodes)} nodes and {len(edges)} edges to RDF Turtle: {args.out}")
    elif fmt == "duckdb":
        out_dir = args.out_dir or "duckdb_export"
        res = export_duckdb(nodes, edges, out_dir)
        print(f"exported DuckDB tables to {out_dir}:")
        for k, v in res.items():
            print(f"  {k}: {v}")
    else:
        print(f"unknown export format: {fmt}", file=sys.stderr)
        return 1
    return 0


def cmd_tile(args) -> int:
    """Partitions graph layout into quadtree LOD tiles for client-side streaming."""
    from .emit_tiles import generate_spatial_tiles
    from .model import Edge, Node

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    nodes = [
        Node(
            id=n["id"],
            label=n["label"],
            type=n["type"],
            aliases=tuple(n.get("aliases") or ()),
            meta=n.get("meta") or {},
        )
        for n in g.get("nodes", [])
    ]
    edges = [
        Edge(
            src=e["src"],
            rel=e["rel"],
            dst=e["dst"],
            confidence=float(e.get("confidence", 1.0)),
            explanation=e.get("explanation"),
            prov=e.get("prov") or {},
        )
        for e in g.get("edges", [])
    ]

    out_dir = args.out_dir or "tiles"
    max_zoom = int(getattr(args, "max_zoom", 3))
    manifest = generate_spatial_tiles(nodes, edges, out_dir, max_zoom=max_zoom)
    print(f"generated {manifest['tile_count']} tiles across zoom 0..{max_zoom} in {out_dir}/")
    return 0


def cmd_as_of(args) -> int:
    """Filters graph to a historical point-in-time snapshot."""
    from .temporal import filter_as_of

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    filtered = filter_as_of(g, args.date)

    if getattr(args, "out", None):
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(filtered, indent=2) + "\n", encoding="utf-8")
        print(f"wrote as-of {args.date} snapshot to {out_path}: {filtered['counts']['nodes']} nodes, {filtered['counts']['edges']} edges")
    else:
        print(json.dumps(filtered, indent=2))
    return 0


def cmd_audit(args) -> int:
    """Audits graph quality, connectivity, cycle anomalies, and structural integrity."""
    from .audit import audit_graph

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    report = audit_graph(g)

    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
        return 0

    print(f"Knowledge Graph Audit Report (Health Score: {report['health_score']}/100)")
    print(f"  Nodes: {report['node_count']} | Edges: {report['edge_count']}")
    print(f"  Connected components: {report['connected_components_count']} (largest: {report['largest_component_size']} nodes)")
    print(f"  Degree Gini coefficient: {report['degree_gini_coefficient']} (hub inequality)")
    print(f"  Average confidence: {report['average_confidence']} (low-confidence edges: {report['low_confidence_count']})")
    print(f"  Bridge edges: {report['bridge_edges_count']}")
    print(f"  Hierarchical cycles: {len(report['hierarchical_cycles'])}")
    print(f"  Contradictory relationship pairs: {report['contradictory_pairs_count']}")

    if report["hierarchical_cycles"]:
        print("\n  Warning: Detected hierarchical cycles:")
        for cycle in report["hierarchical_cycles"][:3]:
            print(f"    {' -> '.join(cycle)}")

    if report["contradictory_pairs_count"] > 0:
        print("\n  Warning: Conflicting reciprocal relations:")
        for contra in report["contradictions_sample"]:
            print(f"    {contra['source']} <-> {contra['target']}: {contra['conflicting_relations']}")

    return 0


def cmd_migrate(args) -> int:
    """Applies declarative schema migration rules to a graph artifact."""
    from .migrate import apply_migration, load_migration_spec

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    migrations = load_migration_spec(args.migration)
    migrated = apply_migration(g, migrations)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(migrated, indent=2) + "\n", encoding="utf-8")
    print(f"migrated graph written to {out_path}: {migrated['counts']['nodes']} nodes, {migrated['counts']['edges']} edges")
    return 0


def cmd_infer(args) -> int:
    """Infers co-occurrence relationships from document overlap."""
    from .infer import infer_cooccurrence
    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    nodes = g.get("nodes", [])
    edges = g.get("edges", [])
    inferred = infer_cooccurrence(
        nodes, edges,
        threshold=float(getattr(args, "threshold", 0.5)),
        min_docs=int(getattr(args, "min_docs", 2))
    )
    result = {
        "graph": args.graph,
        "inferred_count": len(inferred),
        "inferred_edges": inferred,
    }
    if getattr(args, "out", None):
        Path(args.out).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(inferred)} inferred edges to {args.out}")
    else:
        print(json.dumps(result, indent=2))
    return 0


def cmd_cluster(args) -> int:
    """Detects community clusters in the graph using modularity optimization."""
    from .community import detect_communities, evaluate_modularity

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    nodes = g.get("nodes", [])
    edges = g.get("edges", [])
    assignment, clusters = detect_communities(nodes, edges, resolution=float(getattr(args, "resolution", 1.0)))
    modularity = evaluate_modularity(nodes, edges, assignment)

    for n in nodes:
        n["community_id"] = assignment.get(n["id"], 0)

    g["communities"] = clusters
    g["modularity"] = round(modularity, 4)

    if getattr(args, "out", None):
        out_path = Path(args.out)
        out_path.write_text(json.dumps(g, indent=2) + "\n", encoding="utf-8")
        print(f"wrote clustered graph to {out_path} ({len(clusters)} communities, modularity {modularity:.3f})")
    else:
        print(f"Detected {len(clusters)} communities (modularity Q = {modularity:.3f}):\n")
        for c in clusters:
            types_str = ", ".join(f"{k}: {v}" for k, v in c["dominant_types"].items())
            print(f"  [{c['community_id']}] {c['label']:<30} {c['size']:>4} nodes ({types_str})")
    return 0


def cmd_serve_mcp(args) -> int:
    """Runs standard I/O Model Context Protocol (MCP) server."""
    from .mcp_server import MCPServer
    server = MCPServer(graph_path=args.graph)
    server.serve_stdio()
    return 0


def cmd_serve_api(args) -> int:
    """Runs zero-dependency REST API server daemon."""
    from .rest_server import run_api_server
    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 8080)
    run_api_server(graph_path=args.graph, host=host, port=port)
    return 0


def cmd_rag(args) -> int:
    """Extracts k-hop subgraph context around query entities for LLM prompting."""
    from .rag import extract_rag_context

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    res = extract_rag_context(
        g,
        query=args.query,
        k_hops=int(getattr(args, "k_hops", 2)),
        token_budget=int(getattr(args, "token_budget", 2000)),
        format=getattr(args, "format", "markdown"),
    )
    if getattr(args, "format", "markdown") == "json":
        print(json.dumps(res, indent=2))
    else:
        print(res["prompt_text"])
    return 0


def cmd_query(args) -> int:
    """Answers natural language graph queries."""
    from .nl_query import execute_nl_query

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    ask_query = getattr(args, "ask", None)
    if not ask_query:
        print("query needs --ask \"question\"", file=sys.stderr)
        return 1
    res = execute_nl_query(g, ask_query)
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        print(f"Intent: {res['matched_intent']}")
        print(f"Summary: {res['summary']}\n")
        if "path" in res:
            print("Path: " + " -> ".join(n["label"] for n in res["path"]))
        elif res.get("results"):
            for r in res["results"][:15]:
                if "label" in r:
                    print(f"  - {r.get('label')} ({r.get('type', 'Unknown')})")
                elif "rel" in r:
                    print(f"  - {r.get('source')} --[{r.get('rel')}]--> {r.get('target')}")
    return 0


def cmd_sparql(args) -> int:
    """Executes in-memory SPARQL 1.1 pattern queries over graph."""
    from .sparql import execute_sparql

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    res = execute_sparql(g, args.query)
    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        if not res:
            print("No matching solutions found.")
            return 0
        vars_list = list(res[0].keys())
        print(" | ".join(vars_list))
        print("-" * (len(vars_list) * 20))
        for row in res:
            print(" | ".join(str(row.get(v, "")) for v in vars_list))
    return 0


def cmd_analyze(args) -> int:
    """Computes topological metrics, single points of failure, and health score."""
    from .analyze import analyze_graph_topology

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    metrics = analyze_graph_topology(g)
    if getattr(args, "json", False):
        print(json.dumps(metrics, indent=2))
    else:
        print("CorpusAtlas Graph Topology & Health Report")
        print("=" * 45)
        print(f"Nodes: {metrics['num_nodes']}, Edges: {metrics['num_edges']}")
        print(f"Orphan Nodes: {metrics['num_orphans']}")
        print(f"Density: {metrics['density']}, Avg Degree: {metrics['average_degree']}")
        print(f"Connected Components: {metrics['connected_components_count']}")
        print(f"Articulation Points (SPOF): {len(metrics['articulation_points'])}")
        if metrics['articulation_points']:
            print("  " + ", ".join(metrics['articulation_points'][:10]))
        print(f"Overall Health Score: {metrics['health_score']}/100")
    return 0


def cmd_lint(args) -> int:
    """Lints architecture and relational graph against declarative rules."""
    from .lint import lint_graph

    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    rules = {}
    if getattr(args, "rules", None):
        rpath = Path(args.rules)
        if rpath.suffix == ".json":
            rules = json.loads(rpath.read_text(encoding="utf-8"))
        else:
            rules = tomllib.loads(rpath.read_text(encoding="utf-8"))
    else:
        # Default lint rules: warn on god nodes > 50 degree
        rules = {"max_degree": 50}

    violations = lint_graph(g, rules)
    errors = [v for v in violations if v.get("severity") == "error"]
    warnings = [v for v in violations if v.get("severity") == "warning"]

    if getattr(args, "json", False):
        print(json.dumps(violations, indent=2))
    else:
        for v in violations:
            lvl = v.get("severity", "error").upper()
            msg = v.get("message", "")
            print(f"[{lvl}] {msg}")
        print(f"\nLint complete: {len(errors)} errors, {len(warnings)} warnings.")

    return 1 if errors else 0


def cmd_benchmark(args) -> int:
    """Runs micro-benchmarks across core graph algorithms and reports performance telemetry."""
    from .benchmark import run_all_benchmarks
    quick = getattr(args, "quick", False)
    print("Running CorpusAtlas performance benchmarks...")
    report = run_all_benchmarks(quick=quick)
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
        return 0

    bm = report["benchmarks"]
    print("\n[Barnes-Hut Layout]")
    print(f"  Nodes: {bm['barnes_hut']['num_nodes']}, Edges: {bm['barnes_hut']['num_edges']}")
    print(f"  Throughput: {bm['barnes_hut']['iterations_per_sec']} iterations/sec ({bm['barnes_hut']['duration_ms']} ms)")

    print("\n[Aho-Corasick Keyword Scanner]")
    print(f"  Patterns: {bm['aho_corasick']['num_patterns']}, Scanned: {bm['aho_corasick']['chars_scanned']} chars")
    print(f"  Throughput: {bm['aho_corasick']['chars_per_sec']:,.0f} chars/sec ({bm['aho_corasick']['scan_duration_ms']} ms)")

    print("\n[Datalog-Lite Fixpoint Inference]")
    print(f"  Input: {bm['datalog']['initial_edges']} edges -> Inferred: {bm['datalog']['inferred_edges']} edges in {bm['datalog']['duration_ms']} ms")
    return 0


def cmd_publish(args) -> int:
    """Bundles viewer and graph into a standalone static site distribution."""
    import shutil
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    viewer_dir = Path(__file__).resolve().parents[1] / "viewer"
    for fname in ("index.html", "style.css", "app.js"):
        src = viewer_dir / fname
        if src.exists():
            shutil.copy2(src, out_dir / fname)

    gsrc = Path(args.graph)
    if not gsrc.exists():
        print(f"graph file not found: {args.graph}", file=sys.stderr)
        return 1
    shutil.copy2(gsrc, out_dir / "graph.json")

    js_dir = viewer_dir / "js"
    if js_dir.exists():
        shutil.copytree(js_dir, out_dir / "js", dirs_exist_ok=True)

    print(f"Published static knowledge graph site to {out_dir}/")
    print(f"Serve locally with:\n  python3 -m http.server --directory {out_dir}")
    return 0


def cmd_export_obsidian(args) -> int:
    """Exports graph data as Obsidian Canvas (.canvas) and/or Markdown vault."""
    import json
    from corpusatlas.integrations.obsidian import export_obsidian_canvas, export_obsidian_vault

    gpath = Path(args.graph)
    if not gpath.exists():
        print(f"graph file not found: {args.graph}", file=sys.stderr)
        return 1

    graph_data = json.loads(gpath.read_text(encoding="utf-8"))
    count = 0
    if args.canvas:
        export_obsidian_canvas(graph_data, args.canvas)
        print(f"Exported Obsidian Canvas to {args.canvas}")
        count += 1
    if args.vault:
        n = export_obsidian_vault(graph_data, args.vault)
        print(f"Exported {n} Obsidian notes to vault at {args.vault}/")
        count += 1
    if count == 0:
        cpath = gpath.with_suffix(".canvas")
        export_obsidian_canvas(graph_data, cpath)
        print(f"Exported Obsidian Canvas to {cpath}")
    return 0


def cmd_project_embeddings(args) -> int:
    """Projects dense embedding vectors to 2D/3D semantic space coordinates."""
    import json
    from corpusatlas.projection import compute_graph_semantic_projection

    gpath = Path(args.graph)
    if not gpath.exists():
        print(f"graph file not found: {args.graph}", file=sys.stderr)
        return 1

    graph_data = json.loads(gpath.read_text(encoding="utf-8"))
    projected = compute_graph_semantic_projection(graph_data, n_components=args.dims)
    out_path = Path(args.out or args.graph)
    out_path.write_text(json.dumps(projected, indent=2), encoding="utf-8")
    print(f"Computed semantic {args.dims}D vector projection for {len(projected.get('nodes', []))} nodes -> {out_path}")
    return 0


def cmd_extract_llm(args) -> int:
    """Extracts ontology-conforming entities and triples from text using LLM."""
    from corpusatlas.extract_llm import extract_entities_and_triples_from_text, convert_extracted_to_pack_toml
    from corpusatlas.ontology import Ontology

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"input path not found: {args.input}", file=sys.stderr)
        return 1

    ont = Ontology.from_toml(args.schema) if args.schema else None

    text_parts = []
    if in_path.is_file():
        text_parts.append(in_path.read_text(encoding="utf-8"))
    else:
        for f in in_path.glob("**/*"):
            if f.is_file() and f.suffix.lower() in (".md", ".txt", ".html"):
                text_parts.append(f.read_text(encoding="utf-8"))

    combined_text = "\n\n".join(text_parts)[:15000]
    extracted = extract_entities_and_triples_from_text(
        combined_text,
        endpoint=args.endpoint,
        model=args.model,
        ontology=ont,
    )

    toml_content = convert_extracted_to_pack_toml(extracted, pack_name=in_path.stem)
    out_file = Path(args.out)
    out_file.write_text(toml_content, encoding="utf-8")
    print(f"Extracted {len(extracted.get('entities', []))} entities and {len(extracted.get('relations', []))} relations -> {out_file}")
    return 0


def cmd_redact(args) -> int:
    """Redacts graph based on role clearance policy."""
    import json
    from corpusatlas.rbac import redact_graph_by_role, RBACPolicy

    gpath = Path(args.graph)
    if not gpath.exists():
        print(f"graph file not found: {args.graph}", file=sys.stderr)
        return 1

    policy = RBACPolicy.from_toml(args.policy) if args.policy else None
    graph_data = json.loads(gpath.read_text(encoding="utf-8"))
    redacted, audit = redact_graph_by_role(graph_data, role=args.role, policy=policy)

    out_file = Path(args.out)
    out_file.write_text(json.dumps(redacted, indent=2), encoding="utf-8")
    print(f"Redacted graph for role '{args.role}': {audit['retained_nodes_count']} nodes retained ({audit['redacted_nodes_count']} redacted), {audit['retained_edges_count']} edges retained -> {out_file}")
    return 0


def cmd_export_wc(args) -> int:
    """Exports autonomous <corpusatlas-graph> standalone web component bundle."""
    import shutil
    out_file = Path(args.out)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    src_wc = Path(__file__).resolve().parents[1] / "viewer" / "js" / "embed.js"
    if src_wc.exists():
        shutil.copy2(src_wc, out_file)
        print(f"Exported standalone Web Component to {out_file}")
        return 0
    print("embed.js not found", file=sys.stderr)
    return 1


def cmd_scaffold(args) -> int:
    """Generates a schema-compliant starter TOML pack."""
    topic = args.topic
    slug = "-".join(topic.lower().split())
    content = f'''# Semantic Pack: {topic}
# Schema-conforming relations and entities for corpusatlas

[[entity]]
id = "entity:{slug}"
label = "{topic}"
type = "Technology"
description = "Overview and core capabilities of {topic}."

[[relation]]
src = "entity:{slug}"
rel = "CATEGORIZED_AS"
dst = "entity:distributed-systems"
confidence = 0.95
explanation = "{topic} is categorized under distributed systems architecture."
'''
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    print(f"scaffolded pack to {target}")
    return 0


def cmd_watch(args) -> int:
    """Watches source directories for changes and auto-rebuilds the graph."""
    import time
    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"config file not found: {args.config}", file=sys.stderr)
        return 1

    cfg = cfgmod.load(str(cfg_path))
    sources = cfg.get("sources", [])
    watch_dirs = [Path(s["path"]) for s in sources if "path" in s and Path(s["path"]).exists()]
    watch_dirs.append(cfg_path)

    def max_mtime() -> float:
        m = 0.0
        for p in watch_dirs:
            if p.is_file():
                m = max(m, p.stat().st_mtime)
            elif p.is_dir():
                for f in p.rglob("*"):
                    if f.is_file():
                        try:
                            m = max(m, f.stat().st_mtime)
                        except OSError:
                            pass
        return m

    print(f"watching {len(watch_dirs)} source location(s)... (Press Ctrl+C to stop)")
    last_m = max_mtime()
    cmd_build(args)

    if getattr(args, "once", False):
        return 0

    try:
        while True:
            time.sleep(float(getattr(args, "poll_interval", 0.5)))
            cur_m = max_mtime()
            if cur_m > last_m:
                last_m = cur_m
                print(f"[{time.strftime('%H:%M:%S')}] Changes detected, rebuilding...")
                cmd_build(args)
    except KeyboardInterrupt:
        print("\nstopped watch")
        return 0


def cmd_layout(args) -> int:
    """Computes force-directed 2D, 3D, or Multi-Scale LOD coordinates."""
    from .layout import compute_layout, compute_multiscale_layout
    in_path = Path(args.graph)
    if not in_path.exists():
        print(f"graph file not found: {args.graph}", file=sys.stderr)
        return 1
    graph = json.loads(in_path.read_text(encoding="utf-8"))
    nodes = graph.get("nodes", [])
    edges = graph.get("edges", [])
    if getattr(args, "multiscale", False):
        compute_multiscale_layout(nodes, edges, iterations=getattr(args, "iterations", 60), dimensions=3 if args.three_d else 2)
    else:
        compute_layout(nodes, edges, iterations=getattr(args, "iterations", 60), three_d=args.three_d)

    out_path = Path(args.out) if args.out else in_path
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(graph, indent=2), encoding="utf-8")
    print(f"computed layout for {len(nodes)} nodes (3D={args.three_d}, multiscale={getattr(args, 'multiscale', False)}) -> {out_path}")
    return 0


def cmd_index_pagefind(args) -> int:
    """Generates Pagefind static search HTML pages from graph.json."""
    from .pagefind import generate_pagefind_pages
    graph_path = Path(args.graph)
    if not graph_path.exists():
        print(f"graph file not found: {args.graph}", file=sys.stderr)
        return 1
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    out_dir = Path(args.out_dir)
    count = generate_pagefind_pages(graph, out_dir, clean=args.clean)
    print(f"wrote {count} Pagefind search document(s) to {out_dir}")
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
    b.add_argument("--layout", action="store_true",
                   help="pre-calculate 2D coordinates (x, y) for nodes using force layout")
    b.add_argument("--cache",
                   help="path to a file-parse cache (html_blog/obsidian/logseq only); "
                        "created if missing, reused and updated if present")
    b.add_argument("--fine-cache", action="store_true",
                   help="enable fine-grained per-file cache invalidation across directory changes")
    b.add_argument("--merkle-cache", metavar="PATH",
                   help="path to Merkle-DAG extractor cache (defaults to <cache>.merkle.json when --cache is used)")
    b.add_argument("--store", choices=["memory", "sqlite", "duckdb"], default="memory",
                   help="pipeline deduplication & staging engine: memory (default), sqlite (disk out-of-core), or duckdb")
    b.add_argument("--db-path",
                   help="path to disk database file for --store sqlite or --store duckdb")
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
    d.add_argument("--gui", action="store_true", help="export diff-annotated graph for visual inspection")
    d.add_argument("--out", help="output file, when used with --gui")
    d.add_argument("--fail-on-change", action="store_true",
                   help="exit 1 if OLD and NEW differ at all — for a CI step asserting a no-op rebuild")
    d.set_defaults(fn=cmd_diff)

    ctx = sub.add_parser("context", help="format ego-network context for LLM Graph RAG")
    ctx.add_argument("--graph", required=True, help="path to graph.json")
    ctx.add_argument("--entity", required=True, help="entity id or label to focus on")
    ctx.add_argument("--algorithm", choices=["ppr", "bfs", "hybrid"], default="ppr", help="extraction algorithm (ppr, bfs, or hybrid)")
    ctx.add_argument("--depth", type=int, default=1, choices=[1, 2], help="ego network hop depth (for bfs)")
    ctx.add_argument("--top-k", type=int, default=20, help="max nodes to extract (for ppr)")
    ctx.add_argument("--alpha", type=float, default=0.15, help="restart probability for PPR")
    ctx.add_argument("--format", choices=["markdown", "json"], default="markdown")
    ctx.set_defaults(fn=cmd_context)

    exp = sub.add_parser("export", help="export graph to Cypher, RDF Turtle, or DuckDB/Parquet")
    exp.add_argument("--graph", required=True, help="path to graph.json")
    exp.add_argument("--format", choices=["cypher", "turtle", "duckdb"], required=True)
    exp.add_argument("--out", help="output file for cypher or turtle")
    exp.add_argument("--out-dir", help="output directory for duckdb")
    exp.set_defaults(fn=cmd_export)

    til = sub.add_parser("tile", help="partition layout into quadtree LOD tiles for streaming")
    til.add_argument("--graph", required=True, help="path to graph.json")
    til.add_argument("--out-dir", default="tiles", help="output directory for tiles")
    til.add_argument("--max-zoom", type=int, default=3, help="max zoom level (0..N)")
    til.set_defaults(fn=cmd_tile)

    asof = sub.add_parser("as-of", help="filter graph to a historical point-in-time snapshot")
    asof.add_argument("--graph", required=True, help="path to graph.json")
    asof.add_argument("--date", required=True, help="ISO date string (YYYY-MM-DD) for point-in-time snapshot")
    asof.add_argument("--out", help="output path for snapshot json")
    asof.set_defaults(fn=cmd_as_of)

    aud = sub.add_parser("audit", help="audit graph quality, connectivity, cycle anomalies, and structural integrity")
    aud.add_argument("--graph", required=True, help="path to graph.json")
    aud.add_argument("--json", action="store_true", help="output audit results as JSON")
    aud.set_defaults(fn=cmd_audit)

    mig = sub.add_parser("migrate", help="apply schema migration rules to an existing graph")
    mig.add_argument("--graph", required=True, help="path to input graph.json")
    mig.add_argument("--migration", required=True, help="path to migration spec (.toml or .json)")
    mig.add_argument("--out", required=True, help="path to output migrated graph.json")
    mig.set_defaults(fn=cmd_migrate)

    inf = sub.add_parser("infer", help="infer latent co-occurrence relationships")
    inf.add_argument("--graph", required=True, help="path to graph.json")
    inf.add_argument("--out", help="output json path")
    inf.add_argument("--threshold", type=float, default=0.5, help="Jaccard overlap threshold (0.0 to 1.0)")
    inf.add_argument("--min-docs", type=int, default=2, help="minimum shared documents")
    inf.set_defaults(fn=cmd_infer)

    pub = sub.add_parser("publish", help="bundle viewer and graph into a static site distribution")
    pub.add_argument("--graph", required=True, help="path to built graph.json")
    pub.add_argument("--out-dir", required=True, help="output directory for static bundle")
    pub.set_defaults(fn=cmd_publish)

    scf = sub.add_parser("scaffold", help="generate schema-compliant starter TOML pack")
    scf.add_argument("--topic", required=True, help="topic or domain name")
    scf.add_argument("--out", required=True, help="output toml file path")
    scf.set_defaults(fn=cmd_scaffold)

    wtc = sub.add_parser("watch", help="watch source directories and auto-rebuild on change")
    wtc.add_argument("--config", default="corpusatlas.toml")
    wtc.add_argument("--out", required=True)
    wtc.add_argument("--poll-interval", type=float, default=0.5)
    wtc.add_argument("--once", action="store_true", help="run single scan and exit")
    wtc.add_argument("--layout", action="store_true")
    wtc.add_argument("--cache")
    wtc.set_defaults(fn=cmd_watch)

    c = sub.add_parser("convert", help="reformat a built graph as GraphML or CSV")
    c.add_argument("--graph", required=True)
    c.add_argument("--format", choices=["graphml", "csv", "neo4j", "turtle"], required=True)
    c.add_argument("--out", help="output file, for --format graphml or turtle")
    c.add_argument("--out-dir", help="output directory, for --format csv or neo4j")
    c.add_argument("--base", help=f"resource IRI base, for --format turtle (default: {DEFAULT_BASE})")
    c.set_defaults(fn=cmd_convert)

    mcp = sub.add_parser("serve-mcp", help="start Model Context Protocol (MCP) server over stdio")
    mcp.add_argument("--graph", required=True, help="path to graph.json artifact")
    mcp.set_defaults(fn=cmd_serve_mcp)

    api = sub.add_parser("serve-api", help="start zero-dependency local REST API daemon")
    api.add_argument("--graph", required=True, help="path to graph.json artifact")
    api.add_argument("--host", default="127.0.0.1", help="host interface to bind (default: 127.0.0.1)")
    api.add_argument("--port", type=int, default=8080, help="port to listen on (default: 8080)")
    api.set_defaults(fn=cmd_serve_api)

    cl = sub.add_parser("cluster", help="detect community clusters in graph via modularity optimization")
    cl.add_argument("--graph", required=True, help="path to graph.json")
    cl.add_argument("--resolution", type=float, default=1.0, help="modularity resolution parameter (default: 1.0)")
    cl.add_argument("--out", help="output path to write graph with community annotations")
    cl.set_defaults(fn=cmd_cluster)

    rag_parser = sub.add_parser("rag", help="extract k-hop subgraph context for LLM prompt injection")
    rag_parser.add_argument("--graph", required=True, help="path to graph.json")
    rag_parser.add_argument("--query", required=True, help="query keywords or entity terms")
    rag_parser.add_argument("--k-hops", type=int, default=2, help="k-hop expansion radius (default: 2)")
    rag_parser.add_argument("--token-budget", type=int, default=2000, help="max token budget (default: 2000)")
    rag_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="output format (default: markdown)")
    rag_parser.set_defaults(fn=cmd_rag)

    query_parser = sub.add_parser("query", help="natural language query engine for knowledge graph")
    query_parser.add_argument("--graph", required=True, help="path to graph.json")
    query_parser.add_argument("--ask", required=True, help="natural language question")
    query_parser.add_argument("--json", action="store_true", help="output structured JSON response")
    query_parser.set_defaults(fn=cmd_query)

    sparql_parser = sub.add_parser("sparql", help="query graph with W3C SPARQL pattern matching")
    sparql_parser.add_argument("--graph", required=True, help="path to graph.json")
    sparql_parser.add_argument("--query", required=True, help="SPARQL SELECT query string")
    sparql_parser.add_argument("--json", action="store_true", help="output results as JSON")
    sparql_parser.set_defaults(fn=cmd_sparql)

    analyze_parser = sub.add_parser("analyze", help="compute graph topology, articulation points, and health metrics")
    analyze_parser.add_argument("--graph", required=True, help="path to graph.json")
    analyze_parser.add_argument("--json", action="store_true", help="output metrics as JSON")
    analyze_parser.set_defaults(fn=cmd_analyze)

    lint_parser = sub.add_parser("lint", help="lint graph architecture against declarative rules (exits 1 on error)")
    lint_parser.add_argument("--graph", required=True, help="path to graph.json")
    lint_parser.add_argument("--rules", help="path to rules.toml or rules.json configuration")
    lint_parser.add_argument("--json", action="store_true", help="output violations as JSON")
    lint_parser.set_defaults(fn=cmd_lint)

    bm = sub.add_parser("benchmark", help="run performance micro-benchmarks and report telemetry")
    bm.add_argument("--quick", action="store_true", help="run faster benchmark with smaller graph")
    bm.add_argument("--json", action="store_true", help="output report as JSON")
    bm.set_defaults(fn=cmd_benchmark)

    oc = sub.add_parser("ontology-check", help="validate a schema file on its own, no corpus needed")
    oc.add_argument("--schema", required=True)
    oc.add_argument("--dot", action="store_true",
                    help="print the schema's own type/relation graph as Graphviz DOT instead")
    oc.set_defaults(fn=cmd_ontology_check)

    rc = sub.add_parser("registry-check",
                        help="validate an entity registry on its own, no corpus needed")
    rc.add_argument("--entities", required=True)
    rc.add_argument("--schema", help="a custom ontology schema, if entities aren't typed against DEFAULT")
    rc.set_defaults(fn=cmd_registry_check)

    i = sub.add_parser("init", help="scaffold a starter config and entity registry")
    i.add_argument("--dir", default=".", help="directory to write into (default: current directory)")
    i.set_defaults(fn=cmd_init)

    lay = sub.add_parser("layout", help="compute force-directed 2D, 3D, or Multi-Scale LOD coordinates")
    lay.add_argument("--graph", required=True, help="path to graph.json")
    lay.add_argument("--out", help="output path (defaults to overwriting input graph)")
    lay.add_argument("--3d", dest="three_d", action="store_true", help="compute 3D coordinates (x, y, z)")
    lay.add_argument("--multiscale", action="store_true", help="assign multi-scale Level of Detail (LOD) tiers")
    lay.add_argument("--iterations", type=int, default=60, help="force simulation iterations (default: 60)")
    lay.set_defaults(fn=cmd_layout)

    pf = sub.add_parser("index-pagefind", help="generate Pagefind static search HTML documents")
    pf.add_argument("--graph", required=True, help="path to graph.json")
    pf.add_argument("--out-dir", default="dist/search_pages", help="output directory for search pages")
    pf.add_argument("--clean", action="store_true", help="clean output directory before writing")
    pf.set_defaults(fn=cmd_index_pagefind)

    obs = sub.add_parser("export-obsidian", help="export graph as Obsidian Canvas or Markdown vault")
    obs.add_argument("graph", nargs="?", default="graph.json", help="path to graph.json")
    obs.add_argument("--canvas", help="output path for Obsidian Canvas .canvas file")
    obs.add_argument("--vault", help="output directory for Obsidian Markdown vault notes")
    obs.set_defaults(fn=cmd_export_obsidian)

    pe = sub.add_parser("project-embeddings", help="project dense embedding vectors to 2D/3D semantic space coordinates")
    pe.add_argument("graph", nargs="?", default="graph.json", help="path to graph.json")
    pe.add_argument("--dims", type=int, default=3, choices=[2, 3], help="projection dimensions (2 or 3)")
    pe.add_argument("--out", help="output path (defaults to overwriting input graph)")
    pe.set_defaults(fn=cmd_project_embeddings)

    ellm = sub.add_parser("extract-llm", help="extract ontology-conforming entities and triples from text using LLM")
    ellm.add_argument("input", help="input file or directory containing raw text")
    ellm.add_argument("--schema", help="optional path to ontology schema TOML")
    ellm.add_argument("--endpoint", default="http://localhost:11434/api/generate", help="LLM inference HTTP endpoint")
    ellm.add_argument("--model", default="llama3", help="model identifier")
    ellm.add_argument("--out", default="extracted-pack.toml", help="output TOML pack path")
    ellm.set_defaults(fn=cmd_extract_llm)

    rd = sub.add_parser("redact", help="redact graph based on role clearance policy")
    rd.add_argument("graph", nargs="?", default="graph.json", help="path to graph.json")
    rd.add_argument("--role", default="public", help="role clearance level (e.g. public, internal, admin)")
    rd.add_argument("--policy", help="path to custom rbac.toml policy file")
    rd.add_argument("--out", default="redacted_graph.json", help="output redacted graph path")
    rd.set_defaults(fn=cmd_redact)

    wc = sub.add_parser("export-wc", help="export autonomous <corpusatlas-graph> standalone web component bundle")
    wc.add_argument("--out", default="corpusatlas-graph.js", help="output JavaScript bundle path")
    wc.set_defaults(fn=cmd_export_wc)

    args = p.parse_args(argv)
    return args.fn(args)



if __name__ == "__main__":
    raise SystemExit(main())
