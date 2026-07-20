"""corpusgraph CLI — build, stats, validate."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config as cfgmod
from .adapters import build as build_adapter
from .emit import write_graph
from .extract import DeterministicExtractor
from .merge import merge


def cmd_build(args) -> int:
    cfg = cfgmod.load(args.config)
    docs, sources = [], []
    for spec in cfg.get("sources", []):
        adapter = build_adapter(spec)
        got = list(adapter.documents())
        docs.extend(got)
        sources.append(f"{spec['type']} ({len(got)})")
        print(f"  {spec['type']:<20} {len(got):>4} documents")

    if not docs:
        print("no documents found — check the paths in your config", file=sys.stderr)
        return 1

    extractors = [DeterministicExtractor()]
    node_sets, edge_sets = [], []
    for ex in extractors:
        n, e = ex.run(docs)
        n, e = list(n), list(e)
        node_sets.append(n)
        edge_sets.append(e)
        print(f"  {ex.name:<20} {len(n):>4} nodes, {len(e)} edges")

    nodes, edges = merge(node_sets, edge_sets, live_doc_ids={d.id for d in docs})
    counts = write_graph(Path(args.out), nodes, edges, sources=sources)
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

    print(f"generated {g['generated']} by {g['generator']}")
    print(f"{g['counts']['nodes']} nodes, {g['counts']['edges']} edges\n")
    print("nodes by type:")
    for k, v in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<12} {v:>5}")
    print("\nedges by relation:")
    for k, v in sorted(by_rel.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<12} {v:>5}")
    top = sorted(g["nodes"], key=lambda n: -n.get("degree", 0))[:10]
    print("\nmost connected:")
    for n in top:
        print(f"  {n.get('degree',0):>4}  {n['label'][:60]}")
    return 0


def cmd_validate(args) -> int:
    """Invariants the artifact must satisfy before it is allowed to ship."""
    g = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    ids = {n["id"] for n in g["nodes"]}
    errs: list[str] = []

    if len(ids) != len(g["nodes"]):
        errs.append("duplicate node ids")
    for e in g["edges"]:
        if e["src"] not in ids:
            errs.append(f"dangling src {e['src']}")
        if e["dst"] not in ids:
            errs.append(f"dangling dst {e['dst']}")
        if not e.get("prov", {}).get("doc"):
            errs.append(f"edge without provenance: {e['src']}-{e['rel']}->{e['dst']}")
    if g["counts"]["nodes"] != len(g["nodes"]) or g["counts"]["edges"] != len(g["edges"]):
        errs.append("counts header disagrees with the payload")
    isolated = ids - ({e["src"] for e in g["edges"]} | {e["dst"] for e in g["edges"]})
    if isolated:
        errs.append(f"{len(isolated)} isolated nodes")

    for e in errs[:20]:
        print(f"  FAIL {e}", file=sys.stderr)
    print(f"{len(errs)} problems" if errs else "graph valid")
    return 1 if errs else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="corpusgraph")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build the graph from a config")
    b.add_argument("--config", default="corpusgraph.toml")
    b.add_argument("--out", required=True)
    b.set_defaults(fn=cmd_build)

    s = sub.add_parser("stats", help="summarise a built graph")
    s.add_argument("--graph", required=True)
    s.set_defaults(fn=cmd_stats)

    v = sub.add_parser("validate", help="check the graph's invariants")
    v.add_argument("--graph", required=True)
    v.set_defaults(fn=cmd_validate)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
