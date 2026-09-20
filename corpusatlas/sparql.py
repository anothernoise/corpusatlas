"""In-memory SPARQL query engine for CorpusAtlas knowledge graphs."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple


def _build_triples(graph_data: Dict[str, Any]) -> Set[Tuple[str, str, str]]:
    triples: Set[Tuple[str, str, str]] = set()

    # Node triples
    for node in graph_data.get("nodes", []):
        nid = node["id"]
        ntype = node.get("type", "Entity")
        lbl = node.get("label", nid)
        triples.add((nid, "a", ntype))
        triples.add((nid, "rdf:type", ntype))
        triples.add((nid, "rdfs:label", lbl))

    # Edge triples
    for edge in graph_data.get("edges", []):
        src = edge["source"]
        tgt = edge["target"]
        rel = edge.get("rel", "related_to")
        triples.add((src, rel, tgt))
        triples.add((src, f":{rel}", tgt))

    return triples


def _normalize_term(term: str) -> str:
    term = term.strip()
    if term.startswith(":") and len(term) > 1:
        return term[1:]
    return term


def parse_sparql_query(query: str) -> Tuple[List[str], List[Tuple[str, str, str]]]:
    # Match SELECT ... WHERE { ... }
    clean = " ".join(query.strip().split())
    sel_match = re.search(r"SELECT\s+(.+?)\s+WHERE\s*\{(.*?)\}", clean, re.IGNORECASE)
    if not sel_match:
        # Fallback to finding variables and triples
        vars_selected = [v.lstrip("?") for v in re.findall(r"\?[a-zA-Z0-9_]+", clean)]
        where_part = clean
    else:
        vars_selected = [v.lstrip("?") for v in sel_match.group(1).split() if v.startswith("?")]
        where_part = sel_match.group(2)

    # Split where clauses by period
    pattern_strs = [p.strip() for p in where_part.split(".") if p.strip()]
    patterns: List[Tuple[str, str, str]] = []
    for pat in pattern_strs:
        tokens = pat.split()
        if len(tokens) >= 3:
            s, p, o = tokens[0], tokens[1], tokens[2]
            patterns.append((s, p, o))

    return vars_selected, patterns


def execute_sparql(graph_data: Dict[str, Any], query: str) -> List[Dict[str, str]]:
    triples = _build_triples(graph_data)
    variables, patterns = parse_sparql_query(query)

    solutions: List[Dict[str, str]] = [{}]

    for s_pat, p_pat, o_pat in patterns:
        norm_p = _normalize_term(p_pat)
        norm_o = _normalize_term(o_pat)
        norm_s = _normalize_term(s_pat)

        new_solutions: List[Dict[str, str]] = []
        for sol in solutions:
            for t_s, t_p, t_o in triples:
                # Check predicate
                if p_pat.startswith("?"):
                    pass
                elif norm_p != t_p and p_pat != t_p:
                    continue

                # Check subject
                if s_pat.startswith("?"):
                    var = s_pat.lstrip("?")
                    if var in sol and sol[var] != t_s:
                        continue
                elif norm_s != t_s and s_pat != t_s:
                    continue

                # Check object
                if o_pat.startswith("?"):
                    var = o_pat.lstrip("?")
                    if var in sol and sol[var] != t_o:
                        continue
                elif norm_o != t_o and o_pat != t_o:
                    continue

                # Valid match, bind variables
                match_sol = dict(sol)
                if s_pat.startswith("?"):
                    match_sol[s_pat.lstrip("?")] = t_s
                if p_pat.startswith("?"):
                    match_sol[p_pat.lstrip("?")] = t_p
                if o_pat.startswith("?"):
                    match_sol[o_pat.lstrip("?")] = t_o

                if match_sol not in new_solutions:
                    new_solutions.append(match_sol)

        solutions = new_solutions

    # Project requested variables
    if variables:
        final_solutions = []
        for s in solutions:
            row = {v: s.get(v, "") for v in variables if v in s}
            if row not in final_solutions:
                final_solutions.append(row)
        return final_solutions

    return solutions
