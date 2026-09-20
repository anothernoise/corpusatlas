"""Datalog-Lite forward-chaining deductive inference engine.

Applies declarative ontological rules (transitive closure, inverse, symmetry, composition)
to materialize implied semantic knowledge graph relationships with confidence dampening.
Zero external dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from .model import Edge


@dataclass(frozen=True)
class DatalogRule:
    """Declarative inference rule."""

    name: str
    rule_type: str  # "transitive", "inverse", "symmetric", "composition"
    rel: str
    target_rel: str | None = None
    rel2: str | None = None  # for composition: (A, rel, B) & (B, rel2, C) => (A, target_rel, C)
    dampening: float = 0.9


class DatalogEngine:
    """Fixpoint forward-chaining rule engine."""

    def __init__(self, rules: Iterable[DatalogRule]):
        self.rules = list(rules)

    def infer(self, edges: Iterable[Edge], max_rounds: int = 10) -> list[Edge]:
        """Materialize inferred edges until fixpoint or max_rounds is reached."""
        known: dict[tuple[str, str, str], Edge] = {
            (e.src, e.rel, e.dst): e for e in edges
        }
        all_inferred: list[Edge] = []

        for _ in range(max_rounds):
            new_in_round: list[Edge] = []

            # Group edges by relation for efficient pattern matching
            by_rel: dict[str, list[Edge]] = {}
            for e in known.values():
                by_rel.setdefault(e.rel, []).append(e)

            # Map src -> list[Edge] and dst -> list[Edge] for join queries
            by_src: dict[str, list[Edge]] = {}
            by_dst: dict[str, list[Edge]] = {}
            for e in known.values():
                by_src.setdefault(e.src, []).append(e)
                by_dst.setdefault(e.dst, []).append(e)

            for rule in self.rules:
                rel_edges = by_rel.get(rule.rel, [])

                if rule.rule_type == "transitive":
                    target_rel = rule.target_rel or rule.rel
                    for e1 in rel_edges:
                        # Find e2 where e2.src == e1.dst and e2.rel == rule.rel
                        for e2 in by_src.get(e1.dst, []):
                            if e2.rel != rule.rel:
                                continue
                            if e1.src == e2.dst:
                                continue  # Avoid self-cycles
                            key = (e1.src, target_rel, e2.dst)
                            if key not in known:
                                conf1 = e1.confidence if e1.confidence is not None else 1.0
                                conf2 = e2.confidence if e2.confidence is not None else 1.0
                                new_conf = round(conf1 * conf2 * rule.dampening, 4)
                                derived = Edge(
                                    src=e1.src,
                                    rel=target_rel,
                                    dst=e2.dst,
                                    confidence=new_conf,
                                    explanation=f"Inferred by {rule.name} from ({e1.src} -> {e1.dst}) and ({e2.src} -> {e2.dst})",
                                    prov={"rule": rule.name, "inferred": True},
                                )
                                known[key] = derived
                                new_in_round.append(derived)

                elif rule.rule_type == "inverse":
                    target_rel = rule.target_rel or f"inv_{rule.rel}"
                    for e1 in rel_edges:
                        key = (e1.dst, target_rel, e1.src)
                        if key not in known:
                            conf1 = e1.confidence if e1.confidence is not None else 1.0
                            new_conf = round(conf1 * rule.dampening, 4)
                            derived = Edge(
                                src=e1.dst,
                                rel=target_rel,
                                dst=e1.src,
                                confidence=new_conf,
                                explanation=f"Inferred inverse by {rule.name} from ({e1.src} -> {e1.dst})",
                                prov={"rule": rule.name, "inferred": True},
                            )
                            known[key] = derived
                            new_in_round.append(derived)

                elif rule.rule_type == "symmetric":
                    for e1 in rel_edges:
                        key = (e1.dst, rule.rel, e1.src)
                        if key not in known:
                            conf1 = e1.confidence if e1.confidence is not None else 1.0
                            new_conf = round(conf1 * rule.dampening, 4)
                            derived = Edge(
                                src=e1.dst,
                                rel=rule.rel,
                                dst=e1.src,
                                confidence=new_conf,
                                explanation=f"Inferred symmetric by {rule.name} from ({e1.src} -> {e1.dst})",
                                prov={"rule": rule.name, "inferred": True},
                            )
                            known[key] = derived
                            new_in_round.append(derived)

                elif rule.rule_type == "composition" and rule.rel2 and rule.target_rel:
                    for e1 in rel_edges:
                        for e2 in by_src.get(e1.dst, []):
                            if e2.rel != rule.rel2:
                                continue
                            if e1.src == e2.dst:
                                continue
                            key = (e1.src, rule.target_rel, e2.dst)
                            if key not in known:
                                conf1 = e1.confidence if e1.confidence is not None else 1.0
                                conf2 = e2.confidence if e2.confidence is not None else 1.0
                                new_conf = round(conf1 * conf2 * rule.dampening, 4)
                                derived = Edge(
                                    src=e1.src,
                                    rel=rule.target_rel,
                                    dst=e2.dst,
                                    confidence=new_conf,
                                    explanation=f"Inferred composition by {rule.name}",
                                    prov={"rule": rule.name, "inferred": True},
                                )
                                known[key] = derived
                                new_in_round.append(derived)

            if not new_in_round:
                break
            all_inferred.extend(new_in_round)

        return all_inferred


def run_inference(
    graph_data: dict[str, Any], rules: list[DatalogRule]
) -> dict[str, Any]:
    """Execute inference rules against a graph dictionary artifact."""
    edges_raw = graph_data.get("edges", [])
    model_edges = [
        Edge(
            src=e["src"],
            rel=e["rel"],
            dst=e["dst"],
            confidence=float(e.get("confidence", 1.0)),
            explanation=e.get("explanation"),
            prov=e.get("prov", {}),
        )
        for e in edges_raw
    ]

    engine = DatalogEngine(rules)
    new_edges = engine.infer(model_edges)

    updated = dict(graph_data)
    combined = list(edges_raw) + [e.to_json() for e in new_edges]
    updated["edges"] = combined
    updated["counts"] = {
        "nodes": len(updated.get("nodes", [])),
        "edges": len(combined),
    }
    updated["inferred_edge_count"] = len(new_edges)
    return updated
