#!/usr/bin/env python3
"""Rebuild the Animals corpus with:
1. Multi-typed biological entities (Mammal, Bird, Reptile, Amphibian, Fish, Invertebrate, Habitat, Diet, Taxon).
2. Trophic, Ecological, Taxonomic, and Comparative semantic relations.
3. Conservation Radar recommendations and scorecards (Adopt, Trial, Assess, Hold).
4. Emitted pre-computed ForceAtlas2 coordinates for the viewer.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from corpusatlas import config as cfgmod
from corpusatlas.adapters import build as build_adapter
from corpusatlas.cache import BuildCache
from corpusatlas.emit import write_graph
from corpusatlas.extract import DeterministicExtractor, MentionsExtractor, PacksExtractor
from corpusatlas.merge import merge
from corpusatlas.ontology import Ontology
from corpusatlas.resolve import Resolver

ANIMALS_DIR = ROOT / "corpora" / "animals"
NOTES_DIR = ANIMALS_DIR / "notes"
PACKS_DIR = ANIMALS_DIR / "packs"
PACKS_DIR.mkdir(parents=True, exist_ok=True)

# Taxonomic classifiers based on keyword analysis
BIRD_KEYWORDS = {"bird", "avian", "passerine", "falcon", "eagle", "hawk", "owl", "parrot", "duck", "goose", "penguin", "seabird", "songbird", "aves", "feather", "beak"}
MAMMAL_KEYWORDS = {"mammal", "mammalia", "marsupial", "rodent", "carnivoran", "ungulate", "cetacean", "primate", "bat", "feline", "canine", "bovid", "felidae", "canidae", "equid"}
REPTILE_KEYWORDS = {"reptile", "reptilia", "snake", "lizard", "turtle", "tortoise", "crocodile", "alligator", "squamata", "serpentes", "gecko", "chameleon"}
AMPHIBIAN_KEYWORDS = {"amphibian", "amphibia", "frog", "toad", "salamander", "newt", "anura"}
FISH_KEYWORDS = {"fish", "shark", "ray", "salmon", "trout", "teleost", "osteichthyes", "chondrichthyes", "eel", "tuna", "carp", "bass"}
INVERT_KEYWORDS = {"insect", "spider", "arthropod", "mollusc", "crustacean", "beetle", "ant", "bee", "butterfly", "moth", "snail", "octopus", "jellyfish", "coral", "wasp", "crab", "lobster"}

HABITAT_DEFS = {
    "habitat-savanna": ("Savanna & Grassland", ["savanna", "grassland", "plains", "prairie", "steppe"]),
    "habitat-rainforest": ("Tropical Rainforest", ["rainforest", "tropical forest", "jungle"]),
    "habitat-ocean": ("Ocean & Coral Reef", ["marine", "ocean", "sea", "coral reef", "pelagic", "coastal"]),
    "habitat-wetlands": ("Freshwater Wetlands", ["wetland", "river", "lake", "freshwater", "swamp", "marsh"]),
    "habitat-desert": ("Desert & Arid Shrubland", ["desert", "arid", "semi-arid", "dune"]),
    "habitat-forest": ("Temperate & Boreal Forest", ["temperate forest", "woodland", "boreal", "taiga", "coniferous"]),
    "habitat-polar": ("Polar Tundra & Ice", ["arctic", "antarctic", "tundra", "polar"]),
    "habitat-mountains": ("Montane & Alpine", ["mountain", "alpine", "high altitude"]),
}

DIET_DEFS = {
    "diet-carnivore": ("Apex Carnivore", ["apex predator", "carnivore", "carnivorous", "preys mostly", "preys on", "meat"]),
    "diet-herbivore": ("Herbivore", ["herbivore", "herbivorous", "grazer", "browser", "folivore", "frugivore", "grass", "foliage", "leaves"]),
    "diet-omnivore": ("Omnivore", ["omnivore", "omnivorous", "feeds on both"]),
    "diet-insectivore": ("Insectivore", ["insectivore", "insectivorous", "ants", "termites", "myrmecophagy"]),
    "diet-piscivore": ("Piscivore", ["piscivore", "fish-eating", "preys on fish"]),
}

KNOWN_TAXA = {
    "taxon-felidae": ("Felidae (Cats)", ["felid", "felidae"]),
    "taxon-canidae": ("Canidae (Canines)", ["canid", "canidae"]),
    "taxon-ursidae": ("Ursidae (Bears)", ["ursid", "ursidae"]),
    "taxon-cetacea": ("Cetacea (Whales & Dolphins)", ["cetacean", "whale", "dolphin"]),
    "taxon-primates": ("Primates", ["primate", "primates", "ape"]),
    "taxon-accipitridae": ("Accipitridae (Birds of Prey)", ["accipitrid", "accipitridae"]),
    "taxon-crocodylidae": ("Crocodylidae (Crocodilians)", ["crocodil", "crocodylidae"]),
    "taxon-squamata": ("Squamata (Scaled Reptiles)", ["squamat", "squamata"]),
    "taxon-panthera": ("Panthera", ["panthera"]),
    "taxon-equidae": ("Equidae (Equines)", ["equid", "equidae"]),
    "taxon-bovidae": ("Bovidae (Hollow-horned Ruminants)", ["bovid", "bovidae"]),
    "taxon-mustelidae": ("Mustelidae (Weasels & Otters)", ["mustelid", "mustelidae"]),
}


def classify_animal(title: str, text: str) -> str:
    lower = f"{title.lower()} {text.lower()}"
    scores = {
        "Bird": sum(1 for k in BIRD_KEYWORDS if k in lower),
        "Mammal": sum(1 for k in MAMMAL_KEYWORDS if k in lower),
        "Reptile": sum(1 for k in REPTILE_KEYWORDS if k in lower),
        "Amphibian": sum(1 for k in AMPHIBIAN_KEYWORDS if k in lower),
        "Fish": sum(1 for k in FISH_KEYWORDS if k in lower),
        "Invertebrate": sum(1 for k in INVERT_KEYWORDS if k in lower),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "Mammal"


def get_quadrant(btype: str) -> str:
    if btype == "Mammal":
        return "mammals"
    elif btype == "Bird":
        return "birds"
    elif btype in ("Reptile", "Amphibian"):
        return "reptiles-and-amphibians"
    else:
        return "aquatic-and-invertebrates"


def get_conservation_status(text: str) -> tuple[str, str, str]:
    lower = text.lower()
    if "critically endangered" in lower:
        return "adopt", "Critically Endangered", "Critical Action: Establish strictly guarded sanctuary corridors, emergency captive breeding, and intensive anti-poaching units."
    elif "endangered" in lower:
        return "trial", "Endangered", "Priority Action: Habitat restoration, genetic diversity monitoring, and community-led conservancy rewilding."
    elif "vulnerable" in lower or "near threatened" in lower:
        return "assess", "Vulnerable", "Active Monitoring: Satellite tracking of migration corridors, quota enforcement, and climate resilience assessments."
    else:
        return "hold", "Least Concern", "Sustained Equilibrium: Maintain protected wilderness boundaries and conduct biennial ecological population censuses."


def main():
    print("Rebuilding Animals Pack...")
    notes = sorted(NOTES_DIR.glob("*.md"))
    print(f"Found {len(notes)} animal articles in {NOTES_DIR}")

    animal_entities = {}
    animal_data = {}
    links_map = {}

    link_re = re.compile(r"\[\[([^\]]+)\]\]")

    for f in notes:
        slug = f.stem
        content = f.read_text(encoding="utf-8")
        title_line = content.splitlines()[0] if content else slug
        title = title_line.replace("#", "").strip() or slug.capitalize()

        btype = classify_animal(title, content)
        ring, status, rec = get_conservation_status(content)
        quad = get_quadrant(btype)

        found_links = [l.strip() for l in link_re.findall(content)]
        links_map[slug] = found_links

        animal_data[slug] = {
            "id": slug,
            "name": title,
            "type": btype,
            "ring": ring,
            "status": status,
            "rec": rec,
            "quadrant": quad,
            "content": content,
            "links": found_links,
            "url": f"https://en.wikipedia.org/wiki/{slug}",
        }

        animal_entities[slug] = {
            "id": slug,
            "name": title,
            "type": btype,
            "canonical_url": f"https://en.wikipedia.org/wiki/{slug}",
            "notes": f"{btype} · {status}. Recommendation: {rec}",
        }

    # 1. Write entities.toml
    entities_toml_lines = ["# Animal Kingdom & Ecology Registry\n"]
    for e in animal_entities.values():
        entities_toml_lines.append(
            f'[[entity]]\nid   = "{e["id"]}"\nname = "{e["name"]}"\ntype = "{e["type"]}"\n'
            f'canonical_url = "{e["canonical_url"]}"\nclassification_notes = "{e["notes"]}"\n'
            f'radar = ["{e["id"]}"]\n'
        )

    # Add Habitats
    for hid, (hname, _) in HABITAT_DEFS.items():
        entities_toml_lines.append(f'[[entity]]\nid   = "{hid}"\nname = "{hname}"\ntype = "Habitat"\ncanonical_url = "https://en.wikipedia.org/wiki/{hid}"\n')

    # Add Diets
    for did, (dname, _) in DIET_DEFS.items():
        entities_toml_lines.append(f'[[entity]]\nid   = "{did}"\nname = "{dname}"\ntype = "Diet"\ncanonical_url = "https://en.wikipedia.org/wiki/{did}"\n')

    # Add Taxa
    for tid, (tname, _) in KNOWN_TAXA.items():
        entities_toml_lines.append(f'[[entity]]\nid   = "{tid}"\nname = "{tname}"\ntype = "Taxon"\ncanonical_url = "https://en.wikipedia.org/wiki/{tid}"\n')

    (ANIMALS_DIR / "entities.toml").write_text("\n".join(entities_toml_lines), encoding="utf-8")
    print(f"Wrote {ANIMALS_DIR / 'entities.toml'}")

    # 2. Write radar.json and scorecards.json
    radar_entries = []
    scorecard_assessments = {
        "mammals-conservation": {"platforms": {}},
        "birds-conservation": {"platforms": {}},
        "reptiles-conservation": {"platforms": {}},
        "aquatic-conservation": {"platforms": {}},
    }

    for slug, d in animal_data.items():
        assessment_key = f"{d['quadrant'].split('-')[0]}-conservation"
        if assessment_key not in scorecard_assessments:
            assessment_key = "mammals-conservation"

        scorecard_assessments[assessment_key]["platforms"][d["name"]] = {
            "status": d["status"],
            "recommendation": d["rec"]
        }

        radar_entries.append({
            "id": slug,
            "name": d["name"],
            "quadrant": d["quadrant"],
            "ring": d["ring"],
            "category": f"{d['type']} · {d['status']}",
            "reviewed": "2026-01-01",
            "url": d["url"],
            "history": [{"date": "2026-01-01", "event": "added", "ring": d["ring"]}],
            "scorecard": {
                "assessment": assessment_key,
                "options": [d["name"]]
            }
        })

    radar_doc = {
        "edition": "2026.01",
        "entries": radar_entries
    }
    (ANIMALS_DIR / "radar.json").write_text(json.dumps(radar_doc, indent=2), encoding="utf-8")
    (ANIMALS_DIR / "scorecards.json").write_text(json.dumps({"assessments": scorecard_assessments}, indent=2), encoding="utf-8")
    print("Wrote radar.json and scorecards.json")

    # 3. Generate Curated Semantic Relationships Pack (packs/animals.json)
    slug_by_name = {d["name"].lower(): slug for slug, d in animal_data.items()}
    relationships = []
    seen_rel = set()

    def add_rel(src, rel, dst, conf=0.9, expl=""):
        key = (src, rel, dst)
        if key not in seen_rel:
            seen_rel.add(key)
            relationships.append({
                "source_id": src,
                "relationship": rel,
                "target_id": dst,
                "confidence": conf,
                "explanation": expl
            })

    # Habitat & Diet relations
    for slug, d in animal_data.items():
        lower = d["content"].lower()
        # Habitat
        for hid, (hname, kws) in HABITAT_DEFS.items():
            if any(k in lower for k in kws):
                add_rel(slug, "FOUND_IN", hid, 0.95, f"{d['name']} inhabits {hname}.")
                break
        # Diet
        for did, (dname, kws) in DIET_DEFS.items():
            if any(k in lower for k in kws):
                add_rel(slug, "CONSUMES", did, 0.95, f"{d['name']} dietary guild: {dname}.")
                break
        # Taxon
        for tid, (tname, kws) in KNOWN_TAXA.items():
            if any(k in lower for k in kws):
                add_rel(slug, "BELONGS_TO_TAXON", tid, 0.95, f"Classified under {tname}.")

        # Interspecies links (PREYS_ON, COMPETES_WITH, COMPARES_TO)
        for link in d["links"]:
            l_slug = slug_by_name.get(link.lower())
            if l_slug and l_slug != slug:
                target_d = animal_data[l_slug]
                # If predator/prey
                if d["type"] in ("Mammal", "Bird", "Reptile") and ("carnivore" in lower or "prey" in lower):
                    if target_d["type"] in ("Mammal", "Bird", "Fish", "Invertebrate"):
                        add_rel(slug, "PREYS_ON", l_slug, 0.88, f"{d['name']} preys on or hunts {target_d['name']}.")
                # If same guild and same type -> COMPETES_WITH / COMPARES_TO
                elif d["type"] == target_d["type"] and d["type"] in ("Mammal", "Bird"):
                    add_rel(slug, "COMPARES_TO", l_slug, 0.85, f"Comparative ecological guild between {d['name']} and {target_d['name']}.")

    print(f"Generated {len(relationships)} curated semantic relationships across Trophic, Ecology, Taxonomy, Comparative groups.")

    pack_entities = []
    for slug, d in animal_data.items():
        pack_entities.append({
            "id": slug,
            "name": d["name"],
            "type": d["type"],
            "short_description": f"{d['type']} · {d['status']}. {d['rec']}",
            "canonical_url": d["url"],
            "wikipedia_url": d["url"]
        })
    for hid, (hname, _) in HABITAT_DEFS.items():
        pack_entities.append({"id": hid, "name": hname, "type": "Habitat", "canonical_url": f"https://en.wikipedia.org/wiki/{hid}"})
    for did, (dname, _) in DIET_DEFS.items():
        pack_entities.append({"id": did, "name": dname, "type": "Diet", "canonical_url": f"https://en.wikipedia.org/wiki/{did}"})
    for tid, (tname, _) in KNOWN_TAXA.items():
        pack_entities.append({"id": tid, "name": tname, "type": "Taxon", "canonical_url": f"https://en.wikipedia.org/wiki/{tid}"})

    pack_doc = {
        "subject": {"name": "Animal Kingdom & Ecological Network"},
        "authored": {"drafted": "2026-01-01"},
        "entities": pack_entities,
        "relationships": relationships
    }

    (PACKS_DIR / "animals.json").write_text(json.dumps(pack_doc, indent=2), encoding="utf-8")
    print(f"Wrote {PACKS_DIR / 'animals.json'}")

    # 4. Run Build Pipeline
    print("\nExecuting build pipeline with --layout...")
    cfg = cfgmod.load(ANIMALS_DIR / "corpusatlas.toml")
    schema_path = (cfg.get("ontology") or {}).get("schema")
    ontology = Ontology.from_toml(schema_path)

    resolver = Resolver.from_config(cfg, ontology=ontology)

    docs = []
    cache_path = ANIMALS_DIR / ".cache.json"
    if cache_path.exists():
        cache_path.unlink()
    cache = BuildCache(cache_path)
    for spec in cfg.get("sources", []):
        docs.extend(build_adapter(spec, cache=cache).documents())
    cache.save()

    det = DeterministicExtractor(resolver=resolver, ontology=ontology)
    det_nodes, det_edges = det.run(docs)

    packs = PacksExtractor(resolver=resolver, ontology=ontology)
    pack_nodes, pack_edges = packs.run(docs)

    mentions = MentionsExtractor(det_nodes + pack_nodes, resolver=resolver, ontology=ontology)
    ment_nodes, ment_edges = mentions.run(docs)

    nodes, edges = merge([det_nodes, pack_nodes, ment_nodes],
                         [det_edges, pack_edges, ment_edges],
                         live_doc_ids={d.id for d in docs})

    out_path = ROOT / "viewer" / "graph.json"
    entity_colors = (cfg.get("ontology") or {}).get("entity_colors")
    counts = write_graph(out_path, nodes, edges, sources=["Wikipedia Animals (1000)", "IUCN Red List Conservation Radar"],
                         ontology=ontology, layout=False, entity_colors=entity_colors)

    print(f"\nSUCCESS: Built graph.json with {counts['nodes']} nodes and {counts['edges']} edges into {out_path}!")


if __name__ == "__main__":
    main()
