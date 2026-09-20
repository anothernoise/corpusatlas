// Knowledge-graph explorer for /knowledge-base/.
//
// The whole entity graph on one persistent canvas, laid out by a live
// ForceAtlas2 simulation — the Obsidian graph-view model. Navigation never
// rebuilds the graph or re-runs the layout from scratch: selecting a node
// only changes what is lit, faded and framed, so the map a reader has built
// in their head stays where they left it while they walk node → edge → node.
//
// This is readable because the canvas holds entities only (~600 nodes, ~4000
// edges as entity packs have grown). Articles, radar calls and assessments
// are evidence, shown as links on an entity's card; with them as nodes the
// same view was a hairball.
//
// Data comes from knowledge-base/graph.json, built in CI by corpusatlas.
// graphology/sigma load as plain globals; ForceAtlas2 ships no browser build,
// so it comes in as jsDelivr's +esm bundle (this file is type="module").
import forceAtlas2 from 'https://cdn.jsdelivr.net/npm/graphology-layout-forceatlas2@0.10.1/+esm';
import pagerank from 'https://cdn.jsdelivr.net/npm/graphology-metrics@2.4.0/centrality/pagerank/+esm';
import { createEdgeCurveProgram } from 'https://cdn.jsdelivr.net/npm/@sigma/edge-curve@3.1.0/+esm';

const urlParams = new URLSearchParams(window.location.search);
const GRAPH_URL = urlParams.get('data') || 'graph.json';
const CDN = {
  graphology: 'https://cdn.jsdelivr.net/npm/graphology@0.25.4/dist/graphology.umd.min.js',
  sigma: 'https://cdn.jsdelivr.net/npm/sigma@3.0.1/dist/sigma.min.js',
};

// Colours come in families, so the kind of thing is readable before the
// label is: teal for ideas, amber/orange for things you run, pink/indigo for
// things you buy and who sells them, cyan for use cases.
const TYPE_COLOR = {
  Concept:             '#14b8a6',
  ArchitecturePattern: '#0d9488',
  Technology:          '#f59e0b',
  Component:           '#f97316',
  Language:            '#fbbf24',
  API:                 '#d97706',
  Protocol:            '#eab308',
  Standard:            '#ca8a04',
  FileFormat:          '#fb923c',
  TableFormat:         '#ea580c',
  Product:             '#ec4899',
  CloudService:        '#db2777',
  Company:             '#6366f1',
  UseCase:             '#06b6d4',
  // Biological & Ecological types
  Mammal:              '#f59e0b',
  Bird:                '#06b6d4',
  Reptile:             '#10b981',
  Amphibian:           '#84cc16',
  Fish:                '#3b82f6',
  Invertebrate:        '#8b5cf6',
  Habitat:             '#14b8a6',
  Diet:                '#ec4899',
  Taxon:               '#a855f7',
  Animal:              '#f97316',
};
const DYNAMIC_PALETTE = [
  '#f59e0b', '#14b8a6', '#ec4899', '#3b82f6', '#8b5cf6',
  '#10b981', '#f97316', '#06b6d4', '#eab308', '#6366f1',
  '#84cc16', '#a855f7', '#0ea5e9', '#f43f5e', '#d946ef'
];
function getTypeColor(type) {
  if (TYPE_COLOR[type]) return TYPE_COLOR[type];
  let hash = 0;
  for (let i = 0; i < (type || "").length; i++) hash = (hash * 31 + type.charCodeAt(i)) | 0;
  return DYNAMIC_PALETTE[Math.abs(hash) % DYNAMIC_PALETTE.length];
}
const TYPE_LABEL = {
  Concept: 'Concept', ArchitecturePattern: 'Architecture pattern', Technology: 'Technology',
  Component: 'Component', Language: 'Language', API: 'API', Protocol: 'Protocol', Standard: 'Standard',
  FileFormat: 'File format', TableFormat: 'Table format', Product: 'Product', CloudService: 'Cloud service',
  Company: 'Company', UseCase: 'Use case',
  Document: 'Article', Assessment: 'Radar assessment', RadarEntry: 'Radar entry', Topic: 'Topic',
  Mammal: 'Mammal', Bird: 'Bird', Reptile: 'Reptile', Amphibian: 'Amphibian', Fish: 'Fish',
  Invertebrate: 'Invertebrate', Habitat: 'Habitat', Diet: 'Diet', Taxon: 'Taxon', Animal: 'Animal',
};
// Only to disambiguate two on-screen labels that collide.
const TYPE_SHORT = {
  Concept: 'Concept', ArchitecturePattern: 'Pattern', Technology: 'Tech', Component: 'Component',
  Language: 'Language', API: 'API', Protocol: 'Protocol', Standard: 'Standard', FileFormat: 'Format',
  TableFormat: 'Table format', Product: 'Product', CloudService: 'Service', Company: 'Company', UseCase: 'Use case',
  Mammal: 'Mammal', Bird: 'Bird', Reptile: 'Reptile', Amphibian: 'Amphibian', Fish: 'Fish',
  Invertebrate: 'Invert', Habitat: 'Habitat', Diet: 'Diet', Taxon: 'Taxon', Animal: 'Animal',
};
const ENTITY_ORDER = ['Technology', 'Component', 'Product', 'CloudService', 'Concept', 'ArchitecturePattern',
  'Language', 'API', 'Protocol', 'Standard', 'FileFormat', 'TableFormat', 'Company', 'UseCase',
  'Mammal', 'Bird', 'Reptile', 'Amphibian', 'Fish', 'Invertebrate', 'Habitat', 'Diet', 'Taxon', 'Animal'];

// Panel settings. Forces map onto ForceAtlas2: centre → gravity, repel →
// scalingRatio, link → a multiplier on every edge's weight.
const DEFAULTS = {
  depth: 1, orphans: true, comparisons: true,
  textFade: 7, nodeSize: 1, linkWidth: 1, arrows: false,
  center: 0.4, repel: 25, link: 1,
  hiddenTypes: [],
};
const STORE_KEY = 'kb-graph-settings-v2';
// Scorecard comparisons are 110 of ~200 edges and say only "scored on the same
// axes". At full weight they pull every assessed tool into one ball.
const COMPARES_WEIGHT = 0.25;
// Camera ratio bounds. A non-finite or extreme ratio renders the whole graph
// collapsed to a point — the production bug this guard exists for.
const RATIO_MIN = 0.08;
const RATIO_MAX = 1.6;
const CITE_CAP = 10;
const MINIMAP_SIZE = 116;
// One colour per relation group, so the graph's shape reads before a click:
// structure in blue, concepts in violet, data flow in green, and so on.
const REL_GROUP_COLOR = {
  Structure: '#38bdf8', Concepts: '#a78bfa', 'Data flow': '#34d399',
  Commercial: '#fb7185', Alternatives: '#fbbf24',
  Trophic: '#ef4444', Ecology: '#10b981', Taxonomy: '#3b82f6', Comparative: '#8b5cf6',
  Other: '#94a3b8',
};

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
const relText = (rel) => rel.replace(/_/g, ' ').toLowerCase();
const fmtDate = (d) => new Date(`${d}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const capitalise = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

function alpha(hex, a) {
  const h = hex.replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// Deterministic seed positions, so the same graph always settles the same way.
function hashSeed(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
  return () => {
    h += 0x6d2b79f5;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error(`failed to load ${src}`));
    document.head.appendChild(s);
  });
}
const resolveGraph = () => (window.graphology && (window.graphology.Graph || window.graphology));
const resolveSigma = () => (window.Sigma && (window.Sigma.Sigma || window.Sigma));

// Every entity's evidence — articles, radar calls, assessments — for its card.
function buildContext(data, byId, entityTypes) {
  const context = new Map();
  const slot = (id) => {
    if (!context.has(id)) context.set(id, { articles: new Map(), radar: new Map(), assessments: new Map() });
    return context.get(id);
  };
  const rank = { deterministic: 0, curated: 1, extracted: 2 };
  for (const e of data.edges) {
    const src = byId.get(e.src), dst = byId.get(e.dst);
    if (!src || !dst) continue;
    const srcEnt = entityTypes.has(src.type), dstEnt = entityTypes.has(dst.type);
    if (srcEnt === dstEnt) continue;
    const [entity, page] = srcEnt ? [src, dst] : [dst, src];
    const bucket = page.type === 'Document' ? 'articles' : page.type === 'RadarEntry' ? 'radar'
      : page.type === 'Assessment' ? 'assessments' : null;
    if (!bucket) continue;
    const list = slot(entity.id)[bucket];
    const prev = list.get(page.id);
    // One entry per page; keep the strongest tier when several edges link it.
    const tier = e.prov && e.prov.tier;
    if (!prev || (rank[tier] ?? 3) < (rank[prev.tier] ?? 3)) {
      list.set(page.id, {
        id: page.id, label: page.label, url: page.url, date: page.meta && page.meta.date,
        ring: page.meta && page.meta.ring, edition: page.meta && (page.meta.reviewed || page.meta.edition),
        quadrant: page.meta && page.meta.quadrant,
        category: page.meta && page.meta.category,
        rel: e.rel, tier
      });
    }
  }
  // Articles a person tagged or a pack cites come before text matches; newest first.
  const TIER_RANK = { deterministic: 0, curated: 0, extracted: 1 };
  const newest = (a, b) => (TIER_RANK[a.tier] ?? 2) - (TIER_RANK[b.tier] ?? 2)
    || (b.date || '').localeCompare(a.date || '') || a.label.localeCompare(b.label);
  for (const [id, c] of context) {
    context.set(id, {
      articles: [...c.articles.values()].sort(newest),
      radar: [...c.radar.values()].sort((a, b) => a.label.localeCompare(b.label)),
      assessments: [...c.assessments.values()].sort((a, b) => a.label.localeCompare(b.label)),
    });
  }
  return context;
}

const TIER_TITLE = {
  extracted: 'A word-boundary match of this entity\'s name in the article text, not a tag a person set',
  curated: 'From an entity pack: model-drafted, every link machine-checked',
};
function tierChip(tier) {
  return tier && tier !== 'deterministic'
    ? `<b class="kb-tier kb-tier-${esc(tier)}" title="${esc(TIER_TITLE[tier] || tier)}">${esc(tier)}</b>` : '';
}

function contextHtml(ctx, { articleCap = CITE_CAP, compact = false } = {}) {
  if (!ctx) return '';
  const sections = [];
  if (ctx.radar.length || ctx.assessments.length) {
    const items = [
      ...ctx.radar.map((r) =>
        `<li><a href="${esc(r.url || '#')}">${esc(r.label)}</a> ` +
        `<span class="kb-ring kb-ring-${esc(r.ring || '')}">${esc(capitalise(r.ring || ''))}</span>` +
        (r.edition ? ` <span class="kb-cite-date">${esc(r.edition)}</span>` : '') +
        (r.category ? `<div style="font-size:0.75rem; color:var(--text-muted); margin-top:2px;">${esc(r.category)}</div>` : '') +
        `</li>`),
      ...(compact ? [] : ctx.assessments.map((a) =>
        `<li><a href="${esc(a.url || '#')}">${esc(a.label)}</a> <span class="kb-cite-date">assessment</span></li>`)),
    ];
    sections.push(`<div class="kb-cites"><span class="kb-cites-label">Radar &amp; Recommendations</span><ul>${items.join('')}</ul></div>`);
  }
  if (ctx.articles.length) {
    const cap = compact ? 3 : articleCap;
    const items = ctx.articles.slice(0, cap).map((c) =>
      `<li><a href="${esc(c.url || '#')}">${esc(c.label)}</a>` +
      (c.date ? ` <span class="kb-cite-date">${fmtDate(c.date)}</span>` : '') + tierChip(c.tier) + `</li>`);
    if (ctx.articles.length > cap) items.push(`<li class="kb-cite-more">+${ctx.articles.length - cap} more</li>`);
    sections.push(`<div class="kb-cites"><span class="kb-cites-label">Related articles</span><ul>${items.join('')}</ul></div>`);
  }
  return sections.join('');
}

function shortLabel(label) {
  let s = label;
  if (s.length > 34) {
    const cut = s.search(/[:—–]/);
    if (cut > 10) s = s.slice(0, cut).trim();
  }
  return s.length > 34 ? `${s.slice(0, 32).trimEnd()}…` : s;
}

// Suffix the type only on names that actually collide, so labels stay short.
function dedupeLabels(nodes) {
  const short = new Map(nodes.map((n) => [n.id, shortLabel(n.label)]));
  const counts = new Map();
  for (const n of nodes) {
    const key = short.get(n.id).toLowerCase();
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return new Map(nodes.map((n) => {
    const s = short.get(n.id);
    return [n.id, counts.get(s.toLowerCase()) > 1 ? `${s} · ${TYPE_SHORT[n.type] || n.type}` : s];
  }));
}

function loadSettings() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
    if (raw && typeof raw === 'object') return { ...DEFAULTS, ...raw };
  } catch (err) { /* private mode or blocked storage: defaults */ }
  return { ...DEFAULTS };
}

export async function initKbGraph(root) {
  if (!root) return;
  const $ = (sel) => root.querySelector(sel);
  const status = $('[data-kb-status]');
  const canvas = $('[data-kb-canvas]');
  const stage = $('[data-kb-stage]');
  const card = $('[data-kb-card]');
  const pinBox = $('[data-kb-pin]');
  const navBack = $('[data-kb-nav-back]');
  const navForward = $('[data-kb-nav-forward]');
  const breadcrumbEl = $('[data-kb-breadcrumb]');
  const expandBtn = $('[data-kb-expand]');
  const centre = $('[data-kb-centre]');
  const loading = $('[data-kb-loading]');
  const zoomBox = $('[data-kb-zoom]');
  const relsEl = $('[data-kb-rels]');
  const groupsEl = $('[data-kb-groups]');
  const panel = $('[data-kb-panel]');
  const bottomPanel = $('[data-kb-bottom-panel]');
  const bottomSummary = $('[data-kb-bottom-summary]');
  const meta = $('[data-kb-meta]');
  const searchInput = $('[data-kb-search]');
  const suggestEl = $('[data-kb-suggest]');

  let data;
  try {
    const res = await fetch(GRAPH_URL);
    if (!res.ok) throw new Error(`graph.json ${res.status}`);
    data = await res.json();
  } catch (err) {
    if (loading) loading.hidden = true;
    status.textContent =
      'The graph could not be loaded. It is built in CI — if this persists the last build may have failed.';
    status.classList.add('is-error');
    return;
  }

  status.textContent = `${data.counts.nodes} nodes · ${data.counts.edges} edges in the artifact · built ${data.generated}`;
  const counts = {
    articles: data.nodes.filter((n) => n.type === 'Document').length,
    assessments: data.nodes.filter((n) => n.type === 'Assessment').length,
    nodes: data.counts.nodes,
    edges: data.counts.edges,
    built: data.generated,
  };
  document.querySelectorAll('[data-kb-n]').forEach((el) => {
    if (counts[el.dataset.kbN] != null) el.textContent = counts[el.dataset.kbN];
  });

  const byId = new Map(data.nodes.map((n) => [n.id, n]));
  const entityTypes = new Set(data.entity_types || ENTITY_ORDER);
  const inverseLabel = data.inverse_labels || {};
  const semanticRels = new Set(Object.values(data.relation_groups || {}).flat());
  let entities = data.nodes.filter((n) => entityTypes.has(n.type));
  let semEdges = data.edges.filter((e) => semanticRels.has(e.rel)
    && entityTypes.has(byId.get(e.src)?.type) && entityTypes.has(byId.get(e.dst)?.type));
  if (semEdges.length === 0 && entities.length > 0) {
    // Project document-level wikilinks to entity-level relations, keeping canvas clean with entities only
    const docToEnt = new Map();
    for (const e of data.edges) {
      if (e.rel === "COVERS") {
        const src = byId.get(e.src), dst = byId.get(e.dst);
        if (src && dst) {
          if (src.type === "Document" && entityTypes.has(dst.type)) docToEnt.set(src.id, dst.id);
          else if (dst.type === "Document" && entityTypes.has(src.type)) docToEnt.set(dst.id, src.id);
        }
      }
    }
    const projected = [];
    const seen = new Set();
    for (const e of data.edges) {
      if (e.rel === "REFERENCES") {
        const s = docToEnt.get(e.src) || (entityTypes.has(byId.get(e.src)?.type) ? e.src : null);
        const t = docToEnt.get(e.dst) || (entityTypes.has(byId.get(e.dst)?.type) ? e.dst : null);
        if (s && t && s !== t) {
          const key = `${s}->${t}`;
          if (!seen.has(key)) {
            seen.add(key);
            projected.push({
              src: s, dst: t, rel: "REFERENCES",
              prov: e.prov || { tier: "extracted" },
              explanation: "Wikilink reference between documents",
            });
          }
        }
      }
    }
    if (projected.length > 0) {
      semEdges = projected;
    } else {
      // Pure document corpus fallback
      entities = data.nodes;
      semEdges = data.edges;
      for (const n of entities) entityTypes.add(n.type);
    }
  }
  const context = buildContext(data, byId, entityTypes);
  const labelFor = dedupeLabels(entities);

  const S = loadSettings();
  let saveTimer = 0;
  function saveSettings() {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      try { localStorage.setItem(STORE_KEY, JSON.stringify(S)); } catch (err) { /* storage unavailable */ }
    }, 250);
  }

  // ---- Relations filter (Filters section) --------------------------------
  // Grouped checkboxes with a master per group. Everything starts checked:
  // hiding a relation by default would hide data without the reader knowing.
  const rels = [...new Set(semEdges.map((e) => e.rel))].sort();
  const relBox = (r) =>
    `<label class="kb-rel"><input type="checkbox" value="${r}" checked> <span>${relText(r)}</span></label>`;
  let groups = Object.entries(data.relation_groups || {})
    .map(([name, rs]) => [name, rs.filter((r) => rels.includes(r))]).filter(([, rs]) => rs.length);
  if (groups.length === 0 && rels.length > 0) {
    groups = [['Relations', rels]];
  }
  const relGroupOf = new Map(groups.flatMap(([name, rs]) => rs.map((r) => [r, name])));
  const relColor = (rel) => REL_GROUP_COLOR[relGroupOf.get(rel)] || REL_GROUP_COLOR.Other;
  relsEl.innerHTML = groups
    .map(([name, rs], gi) =>
      `<div class="kb-relgroup">` +
        `<label class="kb-rel kb-relgroup-all"><input type="checkbox" data-kb-group="${gi}" checked> <span>${esc(name)}</span></label>` +
        `<button type="button" class="kb-relgroup-toggle" aria-expanded="false" aria-controls="kb-relgroup-${gi}" aria-label="Show ${esc(name)} relations">${rs.length} &#9662;</button>` +
        `<div class="kb-relgroup-items" id="kb-relgroup-${gi}" data-kb-group-items="${gi}" hidden>${rs.map(relBox).join('')}</div>` +
      `</div>`)
    .join('');
  // Registered before the filter listener below, so a master checkbox has
  // already updated its children by the time the graph reads them.
  relsEl.addEventListener('change', (ev) => {
    const t = ev.target;
    if (t.dataset.kbGroup != null) {
      relsEl.querySelectorAll(`[data-kb-group-items="${t.dataset.kbGroup}"] input`).forEach((i) => { i.checked = t.checked; });
      t.indeterminate = false;
      return;
    }
    syncGroupMaster(t.closest('[data-kb-group-items]'));
  });
  function syncGroupMaster(items) {
    if (!items) return;
    const boxes = [...items.querySelectorAll('input')];
    const on = boxes.filter((i) => i.checked).length;
    const master = relsEl.querySelector(`[data-kb-group="${items.dataset.kbGroupItems}"]`);
    master.checked = on === boxes.length;
    master.indeterminate = on > 0 && on < boxes.length;
  }
  relsEl.addEventListener('click', (ev) => {
    const btn = ev.target.closest('.kb-relgroup-toggle');
    if (!btn) return;
    const open = btn.getAttribute('aria-expanded') !== 'true';
    btn.setAttribute('aria-expanded', String(open));
    relsEl.querySelector(`#${btn.getAttribute('aria-controls')}`).hidden = !open;
  });
  function setRel(rel, checked) {
    const box = relsEl.querySelector(`input[value="${rel}"]`);
    if (!box || box.checked === checked) return;
    box.checked = checked;
    syncGroupMaster(box.closest('[data-kb-group-items]'));
  }
  function setAllRels(checked) {
    relsEl.querySelectorAll('input[type="checkbox"]').forEach((i) => { i.checked = checked; i.indeterminate = false; });
  }
  root.querySelectorAll('[data-kb-rels-all], [data-kb-rels-none]').forEach((btn) => {
    btn.addEventListener('click', () => {
      setAllRels(btn.hasAttribute('data-kb-rels-all'));
      applyFilters();
    });
  });

  // ---- Groups section: one row per entity type ---------------------------
  const typeCounts = new Map();
  for (const n of entities) typeCounts.set(n.type, (typeCounts.get(n.type) || 0) + 1);
  const hiddenTypes = new Set(S.hiddenTypes);
  groupsEl.innerHTML = [...new Set([...ENTITY_ORDER, ...typeCounts.keys()])].filter((t) => typeCounts.has(t)).map((t) =>
    `<label class="kb-group"><input type="checkbox" data-kb-type="${t}"${hiddenTypes.has(t) ? '' : ' checked'}>` +
    `<span class="kb-dot" style="background:${getTypeColor(t)}"></span><span class="kb-group-name">${esc(TYPE_LABEL[t] || t)}</span>` +
    `<span class="kb-group-n">${typeCounts.get(t)}</span></label>`).join('');

  const edgeLegendEl = root.querySelector('[data-kb-edge-legend]');
  if (edgeLegendEl) {
    edgeLegendEl.innerHTML = groups.map(([name]) =>
      `<span class="kb-edge-legend-item"><span class="kb-swatch" style="background:${REL_GROUP_COLOR[name] || REL_GROUP_COLOR.Other}"></span>${esc(name)}</span>`)
      .join('');
  }

  // ---- Renderer -----------------------------------------------------------
  try {
    await loadScript(CDN.graphology);
    await loadScript(CDN.sigma);
  } catch (err) {
    status.textContent =
      'The graph renderer could not load — a script blocker may be preventing it. The data itself is at /knowledge-base/graph.json.';
    status.classList.add('is-error');
    return;
  }
  const Graph = resolveGraph();
  const Sigma = resolveSigma();
  if (!Graph || !Sigma) {
    status.textContent = 'The graph renderer loaded but did not initialise.';
    status.classList.add('is-error');
    return;
  }
  // Sigma renders on WebGL; a browser with it disabled (some locked-down
  // corporate images, some GPU-blocklisted setups) would otherwise fail
  // deep inside the constructor with no clue what actually went wrong.
  const hasWebGL = (() => {
    try {
      const c = document.createElement('canvas');
      return !!(c.getContext('webgl2') || c.getContext('webgl') || c.getContext('experimental-webgl'));
    } catch (err) { return false; }
  })();
  if (!hasWebGL) {
    status.textContent =
      'This browser has WebGL disabled or unavailable, and the graph needs it to render. ' +
      'The data itself is still readable at /knowledge-base/graph.json.';
    status.classList.add('is-error');
    return;
  }

  // Directed so arrows point the stored way; every walk below treats it as undirected.
  const g = new Graph({ multi: true, type: 'directed' });
  const degree = new Map();
  for (const e of semEdges) {
    degree.set(e.src, (degree.get(e.src) || 0) + 1);
    degree.set(e.dst, (degree.get(e.dst) || 0) + 1);
  }
  // Deterministic curvature for COMPARES_TO: a small clique of mutually-scored
  // tools (Druid/Pinot/StarRocks/ClickHouse…) draws as N overlapping straight
  // chords through the middle otherwise — a fixed per-edge bend fans them out.
  function edgeCurvature(key) {
    let h = 0;
    for (let i = 0; i < key.length; i++) h = (h * 31 + key.charCodeAt(i)) | 0;
    return ((h % 2 === 0) ? 1 : -1) * (0.16 + (Math.abs(h) % 100) / 100 * 0.22);
  }
  for (const n of entities) {
    const rnd = hashSeed(n.id);
    const angle = rnd() * Math.PI * 2, r = 20 + rnd() * 80;
    g.addNode(n.id, {
      label: labelFor.get(n.id),
      kind: n.type, // "type" is reserved by Sigma for the node program
      x: Math.cos(angle) * r,
      y: Math.sin(angle) * r,
      color: (n.meta && n.meta.color) || (data.entity_colors && data.entity_colors[n.type]) || getTypeColor(n.type),
    });
  }
  // Group edges by unordered pair {src, dst} to disambiguate multi-edges with progressive curvature
  const pairGroups = new Map();
  semEdges.forEach((e, i) => {
    const pairKey = [e.src, e.dst].sort().join(':::');
    if (!pairGroups.has(pairKey)) pairGroups.set(pairKey, []);
    pairGroups.get(pairKey).push({ edge: e, index: i });
  });

  const edgeCurvatures = new Map();
  for (const [pairKey, list] of pairGroups.entries()) {
    if (list.length === 1) {
      const { edge, index } = list[0];
      const key = `e${index}`;
      edgeCurvatures.set(key, edge.rel === 'COMPARES_TO' ? edgeCurvature(key) : 0);
    } else {
      list.forEach(({ edge, index }, k) => {
        const key = `e${index}`;
        if (edge.rel === 'COMPARES_TO') {
          edgeCurvatures.set(key, edgeCurvature(key));
        } else {
          const sign = (k % 2 === 0) ? 1 : -1;
          const mag = 0.16 + Math.floor(k / 2) * 0.14;
          const forward = edge.src < edge.dst;
          edgeCurvatures.set(key, (forward ? sign : -sign) * mag);
        }
      });
    }
  }

  semEdges.forEach((e, i) => {
    const baseWeight = e.rel === 'COMPARES_TO' ? COMPARES_WEIGHT : 1;
    const key = `e${i}`;
    const curv = edgeCurvatures.get(key) || 0;
    g.addEdgeWithKey(key, e.src, e.dst, {
      rel: e.rel, tier: e.prov && e.prov.tier, doc: e.prov && e.prov.doc, via: e.prov && e.prov.via,
      confidence: e.confidence, scope: e.scope, sources: e.sources || [], explanation: e.explanation,
      baseWeight, weight: baseWeight * S.link,
      size: e.rel === 'COMPARES_TO' ? 0.6 : 1,
      curvature: curv,
    });
  });
  // Node size blends raw degree (so a leaf with one edge is still visible)
  // with PageRank (so a concept many technologies implement outranks a
  // technology with a handful of shallow scorecard comparisons).
  let pr = new Map();
  try {
    const scores = pagerank(g, { getEdgeWeight: 'baseWeight' });
    for (const [id, v] of Object.entries(scores)) pr.set(id, v);
  } catch (err) { /* degree-only sizing below still works */ }
  const maxPr = Math.max(...pr.values(), 1e-9);
  g.forEachNode((n) => {
    const base = 3 + 1.4 * Math.sqrt(degree.get(n) || 0);
    const boost = maxPr > 0 ? 1 + 1.6 * Math.sqrt((pr.get(n) || 0) / maxPr) : 1;
    g.setNodeAttribute(n, 'size', Math.min(base * boost, 20));
  });

  const fa2Settings = () => ({
    gravity: S.center,
    scalingRatio: S.repel,
    // Strong gravity keeps disconnected islands and orphans in orbit instead
    // of drifting off; plain (not LinLog, not hub-dissuading) attraction is
    // what separated this graph's scorecard cliques into distinct clusters.
    strongGravityMode: true,
    barnesHutOptimize: false,
    slowDown: 1 + Math.log(g.order),
    edgeWeightInfluence: 1,
  });
  const hasPrecomputed = entities.some((n) => typeof n.x === 'number' && typeof n.y === 'number');
  if (!hasPrecomputed) {
    try {
      forceAtlas2.assign(g, { iterations: 400, getEdgeWeight: 'weight', settings: fa2Settings() });
    } catch (err) { /* seed positions are still a usable, if scattered, layout */ }
  } else {
    entities.forEach((n) => {
      if (typeof n.x === 'number' && typeof n.y === 'number' && g.hasNode(n.id)) {
        g.setNodeAttribute(n.id, 'x', n.x);
        g.setNodeAttribute(n.id, 'y', n.y);
      }
    });
  }



  // ForceAtlas2 on the main thread costs several milliseconds per tick on a
  // graph this size — enough to compete with Sigma's own frame budget during
  // Animate or a Forces slider drag. graphology-layout-forceatlas2 ships its
  // own worker-backed supervisor (FA2Layout) that owns graph sync internally,
  // so this is a thin, verified-before-use wrapper around it, not a second
  // implementation of the algorithm to keep correct.
  //
  // Verified, not assumed: constructed, started, and checked for a real tick
  // before anything relies on it. If that fails for any reason — blocked,
  // unsupported, a module worker Safari doesn't like — fa2WorkerAvailable
  // stays false and every call below runs the exact main-thread rAF loop
  // that existed before this did. Never active during a drag regardless: a
  // dragged node needs same-frame position coupling only the main thread
  // gives, so downNode always stops it first.
  let fa2WorkerAvailable = false, FA2LayoutCtor = null, activeFa2Worker = null;
  (async () => {
    try {
      const mod = await import('https://cdn.jsdelivr.net/npm/graphology-layout-forceatlas2@0.10.1/worker/+esm');
      const probe = new mod.default(g, { settings: fa2Settings() });
      probe.start();
      await new Promise((resolve) => setTimeout(resolve, 120));
      const ok = probe.isRunning();
      try { probe.stop(); probe.kill(); } catch (err) { /* already gone */ }
      if (ok) { FA2LayoutCtor = mod.default; fa2WorkerAvailable = true; }
    } catch (err) { /* fa2WorkerAvailable stays false */ }
  })();

  let dark = document.documentElement.getAttribute('data-theme') !== 'light';
  const palette = () => ({
    dim: dark ? 'rgba(71,85,105,0.28)' : 'rgba(203,213,225,0.75)',
    edge: dark ? 'rgba(148,163,184,0.28)' : 'rgba(100,116,139,0.3)',
    edgeFaint: dark ? 'rgba(148,163,184,0.12)' : 'rgba(100,116,139,0.14)',
    edgeGhost: dark ? 'rgba(148,163,184,0.05)' : 'rgba(100,116,139,0.06)',
    edgeLit: dark ? 'rgba(226,232,240,0.85)' : 'rgba(30,41,59,0.75)',
    label: dark ? '#cbd5e1' : '#334155',
  });
  let P = palette();

  // ---- Interaction state --------------------------------------------------
  let allowedRels = new Set(rels);
  let visDeg = new Map();
  let hovered = null, hoverSet = new Set();
  let hoveredEdge = null;
  let selected = null;       // node id in focus
  let multiSelected = new Set(); // shift-drag lasso result — no single focus, several highlighted
  let pathMode = false;        // Ctrl/Cmd-click path mode is open (even if no path was found)
  let pathNodes = null;        // ordered [id, id, ...] along the found path, or null
  let pathEdgeSet = new Set(); // edge keys along the current path, for the reducers
  let selectedEdge = null;   // edge key pinned, if the card shows an edge
  let focusDist = new Map(); // node id -> hops from `selected`, within S.depth
  let dragged = null, dragMoved = false, suppressClick = false;
  let maximized = false;
  let trail = [], trailIndex = -1;

  // Extract date metadata for temporal evolution
  const nodeDates = new Map();
  for (const n of data.nodes) {
    let dt = n.meta && (n.meta.date || n.meta.reviewed || n.meta.edition);
    if (!dt && context.has(n.id)) {
      const arts = context.get(n.id).articles;
      if (arts && arts.length > 0) {
        const sorted = arts.map((a) => a.date).filter(Boolean).sort();
        if (sorted.length > 0) dt = sorted[0];
      }
    }
    if (dt) nodeDates.set(n.id, String(dt).slice(0, 10));
  }
  const allDates = [...new Set(nodeDates.values())].sort();
  let timelineCutoff = null; // null = all time

  const nodeVisible = (n) => {
    if (hiddenTypes.has(g.getNodeAttribute(n, "kind"))) return false;
    if (timelineCutoff && nodeDates.has(n) && nodeDates.get(n) > timelineCutoff) return false;
    return S.orphans || (visDeg.get(n) || 0) > 0;
  };
  const edgeVisible = (e) => {
    if (!allowedRels.has(g.getEdgeAttribute(e, 'rel'))) return false;
    const [s, t] = g.extremities(e);
    return !hiddenTypes.has(g.getNodeAttribute(s, 'kind')) && !hiddenTypes.has(g.getNodeAttribute(t, 'kind'));
  };

  function computeVisDeg() {
    visDeg = new Map();
    g.forEachEdge((e, a, s, t) => {
      if (!edgeVisible(e)) return;
      visDeg.set(s, (visDeg.get(s) || 0) + 1);
      visDeg.set(t, (visDeg.get(t) || 0) + 1);
    });
  }

  function computeFocus() {
    focusDist = new Map();
    if (!selected) return;
    focusDist.set(selected, 0);
    let frontier = [selected];
    for (let d = 1; d <= S.depth; d++) {
      const next = [];
      for (const id of frontier) {
        g.forEachEdge(id, (e, a, s, t) => {
          if (!edgeVisible(e)) return;
          const other = s === id ? t : s;
          if (focusDist.has(other) || !nodeVisible(other)) return;
          focusDist.set(other, d);
          next.push(other);
        });
      }
      frontier = next;
    }
  }

  // Shortest path between two entities over the currently-visible graph —
  // unweighted BFS, since a relation being one hop or ten carries no
  // meaningful distance beyond hop count. Returns null when the two aren't
  // connected under the current filters (a real, reportable answer, not a
  // failure) rather than the whole unfiltered graph.
  // Distances from one root, over the currently-visible graph, treating
  // every edge as undirected for the walk (same convention as computeFocus).
  function bfsDist(root) {
    const dist = new Map([[root, 0]]);
    let frontier = [root];
    while (frontier.length) {
      const next = [];
      for (const id of frontier) {
        g.forEachEdge(id, (e, a, s, t) => {
          if (!edgeVisible(e)) return;
          const other = s === id ? t : s;
          if (dist.has(other) || !nodeVisible(other)) return;
          dist.set(other, dist.get(id) + 1);
          next.push(other);
        });
      }
      frontier = next;
    }
    return dist;
  }

  // Every shortest path, not an arbitrary one BFS happened to find first:
  // an edge (u,v) lies on SOME shortest from -> to route exactly when
  // distFrom[u] + 1 + distTo[v] equals the overall shortest distance (or
  // the reverse orientation). Two equally-short routes between the same
  // pair are common in a graph this interconnected, and picking just one
  // silently hides the other.
  function shortestPath(from, to) {
    if (from === to) return { nodes: [from], edges: [], hopCount: 0, chain: [from] };
    const distFrom = bfsDist(from);
    if (!distFrom.has(to)) return null;
    const distTo = bfsDist(to);
    const hopCount = distFrom.get(to);
    const nodes = new Set(), edges = new Set();
    const chainPrev = new Map([[from, null]]); // one readable example route
    let frontier = [from];
    while (frontier.length) {
      const next = [];
      for (const id of frontier) {
        g.forEachEdge(id, (e, a, s, t) => {
          if (!edgeVisible(e)) return;
          const other = s === id ? t : s;
          if (!nodeVisible(other) || !distFrom.has(other) || !distTo.has(other)) return;
          const onShortest = distFrom.get(id) + 1 + distTo.get(other) === hopCount;
          if (!onShortest) return;
          if (distFrom.get(other) === distFrom.get(id) + 1) {
            edges.add(e);
            nodes.add(id); nodes.add(other);
            if (!chainPrev.has(other)) { chainPrev.set(other, { from: id, edge: e }); next.push(other); }
          }
        });
      }
      frontier = next;
    }
    const chain = [to];
    let cur = to;
    while (chainPrev.get(cur)) { cur = chainPrev.get(cur).from; chain.unshift(cur); }
    return { nodes: [...nodes], edges: [...edges], hopCount, chain };
  }

  function computeMultiPath(waypoints) {
    if (!waypoints || waypoints.length < 2) return null;
    const allNodes = new Set();
    const allEdges = new Set();
    let totalHops = 0;
    const fullChain = [];

    for (let i = 0; i < waypoints.length - 1; i++) {
      const leg = shortestPath(waypoints[i], waypoints[i + 1]);
      if (!leg) return null;
      leg.nodes.forEach(n => allNodes.add(n));
      leg.edges.forEach(e => allEdges.add(e));
      totalHops += leg.hopCount;
      if (i === 0) fullChain.push(...leg.chain);
      else fullChain.push(...leg.chain.slice(1));
    }
    return { nodes: [...allNodes], edges: [...allEdges], hopCount: totalHops, chain: fullChain, waypoints };
  }

  const COMMUNITY_COLORS = [
    '#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6',
    '#06b6d4', '#f97316', '#14b8a6', '#6366f1', '#84cc16',
    '#e11d48', '#0284c7', '#a855f7', '#d97706', '#059669',
    '#4f46e5', '#ca8a04', '#db2777', '#2563eb', '#16a34a'
  ];
  let communityMode = false;
  let communityMap = new Map();

  function computeCommunitiesFallback(graph) {
    const communities = new Map();
    let cid = 0;
    graph.forEachNode(node => { communities.set(node, cid++); });
    for (let iter = 0; iter < 4; iter++) {
      graph.forEachNode(u => {
        const counts = new Map();
        graph.forEachNeighbor(u, v => {
          const c = communities.get(v);
          counts.set(c, (counts.get(c) || 0) + 1);
        });
        let bestC = communities.get(u), maxCount = 0;
        for (const [c, cnt] of counts.entries()) {
          if (cnt > maxCount) { maxCount = cnt; bestC = c; }
        }
        communities.set(u, bestC);
      });
    }
    const map = new Map();
    let nextId = 0;
    const result = {};
    for (const [node, c] of communities.entries()) {
      if (!map.has(c)) map.set(c, nextId++);
      result[node] = map.get(c);
    }
    return result;
  }

  function computeBetweennessFallback(graph) {
    const cb = new Map();
    graph.forEachNode(n => cb.set(n, 0));
    const nodes = graph.nodes();
    for (const s of nodes) {
      const S = [];
      const P = new Map();
      const sigma = new Map();
      const d = new Map();
      for (const v of nodes) {
        P.set(v, []);
        sigma.set(v, 0);
        d.set(v, -1);
      }
      sigma.set(s, 1);
      d.set(s, 0);
      const Q = [s];
      while (Q.length) {
        const v = Q.shift();
        S.push(v);
        graph.forEachNeighbor(v, w => {
          if (d.get(w) < 0) {
            Q.push(w);
            d.set(w, d.get(v) + 1);
          }
          if (d.get(w) === d.get(v) + 1) {
            sigma.set(w, sigma.get(w) + sigma.get(v));
            P.get(w).push(v);
          }
        });
      }
      const delta = new Map();
      for (const v of nodes) delta.set(v, 0);
      while (S.length) {
        const w = S.pop();
        for (const v of P.get(w)) {
          delta.set(v, delta.get(v) + (sigma.get(v) / sigma.get(w)) * (1 + delta.get(w)));
        }
        if (w !== s) cb.set(w, cb.get(w) + delta.get(w));
      }
    }
    return cb;
  }

  function computeCentrality() {
    const degreeList = [];
    g.forEachNode(n => {
      degreeList.push({ id: n, label: (byId.get(n) || {}).label || n, score: g.degree(n) });
    });
    degreeList.sort((a, b) => b.score - a.score);

    const prList = [];
    g.forEachNode(n => {
      prList.push({ id: n, label: (byId.get(n) || {}).label || n, score: (pr.get(n) || 0) });
    });
    prList.sort((a, b) => b.score - a.score);

    const cb = computeBetweennessFallback(g);
    const bwList = [];
    for (const [n, val] of cb.entries()) {
      bwList.push({ id: n, label: (byId.get(n) || {}).label || n, score: Math.round(val * 10) / 10 });
    }
    bwList.sort((a, b) => b.score - a.score);

    return { degree: degreeList.slice(0, 7), pagerank: prList.slice(0, 7), betweenness: bwList.slice(0, 7) };
  }

  const layoutPositions = { force: new Map(), dag: new Map(), radar: new Map() };
  let currentLayout = 'force';

  function initLayouts() {
    // 1. Force positions
    g.forEachNode((n, a) => {
      layoutPositions.force.set(n, { x: a.x, y: a.y });
    });

    // 2. DAG (Hierarchical) Layout
    const depths = new Map();
    g.forEachNode(n => {
      if (g.inDegree(n) === 0) depths.set(n, 0);
    });
    // Fallback if graph is circular or has no sources
    if (depths.size === 0) {
      g.forEachNode((n, i) => { if (i % 5 === 0) depths.set(n, 0); });
    }
    const queue = [...depths.keys()];
    let head = 0;
    while (head < queue.length) {
      const u = queue[head++];
      const d = depths.get(u);
      if (d >= 8) continue;
      g.forEachEdge(u, (e, a, s, t) => {
        if (s !== u) return; // directed DAG walk
        if (!depths.has(t)) {
          depths.set(t, d + 1);
          queue.push(t);
        }
      });
    }
    g.forEachNode(n => { if (!depths.has(n)) depths.set(n, 0); });

    const byDepth = new Map();
    depths.forEach((d, n) => {
      if (!byDepth.has(d)) byDepth.set(d, []);
      byDepth.get(d).push(n);
    });

    const maxDepth = Math.max(...depths.values(), 1);
    byDepth.forEach((nodes, d) => {
      const y = (d - maxDepth / 2) * 180;
      const count = nodes.length;
      nodes.forEach((n, i) => {
        const x = (i - count / 2) * 140;
        layoutPositions.dag.set(n, { x, y });
      });
    });

    // 3. Radar Layout
    const R_MAX = 700;
    const quadrantAngles = {
      'techniques': Math.PI / 4,
      'tools': 3 * Math.PI / 4,
      'platforms': 5 * Math.PI / 4,
      'languages-and-frameworks': 7 * Math.PI / 4,
      // Animal quadrants
      'mammals': Math.PI / 4,
      'birds': 3 * Math.PI / 4,
      'reptiles-and-amphibians': 5 * Math.PI / 4,
      'aquatic-and-invertebrates': 7 * Math.PI / 4,
    };
    const ringRadii = {
      'adopt': 0.22 * R_MAX,
      'trial': 0.45 * R_MAX,
      'assess': 0.68 * R_MAX,
      'hold': 0.90 * R_MAX,
    };

    g.forEachNode((n, idx) => {
      const meta = (byId.get(n) || {}).meta || {};
      const ctxRadar = (context.get(n)?.radar || [])[0] || {};
      const q = (meta.quadrant || ctxRadar.quadrant || '').toLowerCase();
      const r = (meta.ring || ctxRadar.ring || '').toLowerCase();
      const baseAngle = quadrantAngles[q] !== undefined ? quadrantAngles[q] : ((idx % 4) * Math.PI / 2 + Math.PI / 4);
      const baseRadius = ringRadii[r] !== undefined ? ringRadii[r] : (0.5 * R_MAX);

      // deterministic hash jitter
      let hash = 0;
      for (let c = 0; c < n.length; c++) hash = (hash * 31 + n.charCodeAt(c)) & 0xffffffff;
      const jitterAngle = ((hash % 100) / 100 - 0.5) * (Math.PI / 3);
      const jitterR = (((hash >> 4) % 100) / 100 - 0.5) * 80;

      const angle = baseAngle + jitterAngle;
      const radius = Math.max(40, baseRadius + jitterR);
      layoutPositions.radar.set(n, {
        x: Math.round(radius * Math.cos(angle)),
        y: Math.round(radius * Math.sin(angle))
      });
    });
  }
  try {
    initLayouts();
  } catch (err) {
    console.warn('initLayouts failed:', err);
  }

  function switchLayout(targetMode) {


    if (!layoutPositions[targetMode] || layoutPositions[targetMode].size === 0) return;
    currentLayout = targetMode;
    const targetMap = layoutPositions[targetMode];
    const startPos = new Map();
    g.forEachNode((n, a) => { startPos.set(n, { x: a.x, y: a.y }); });

    const startTime = performance.now();
    const duration = 480;

    function step(now) {
      const p = Math.min(1, (now - startTime) / duration);
      const ease = 1 - Math.pow(1 - p, 3); // cubic ease out
      g.forEachNode((n) => {
        const s = startPos.get(n);
        const t = targetMap.get(n) || s;
        g.setNodeAttribute(n, 'x', s.x + (t.x - s.x) * ease);
        g.setNodeAttribute(n, 'y', s.y + (t.y - s.y) * ease);
      });
      renderer.refresh();
      if (p < 1) {
        requestAnimationFrame(step);
      } else {
        try { renderer.setCustomBBox(renderer.getBBox()); } catch (e) {}
        fit();
      }
    }
    requestAnimationFrame(step);
  }

  function drawNodeHover(context, data, settings) {
    const size = settings.labelSize || 12;
    const font = settings.labelFont || "Inter, system-ui, sans-serif";
    const weight = settings.labelWeight || "600";
    context.font = `${weight} ${size}px ${font}`;

    const isDark = document.documentElement.getAttribute("data-theme") !== "light";
    const bgColor = isDark ? "#1e293b" : "#ffffff";
    const textColor = isDark ? "#f8fafc" : "#0f172a";
    const borderColor = isDark ? "rgba(255, 255, 255, 0.28)" : "rgba(0, 0, 0, 0.18)";
    const shadowColor = isDark ? "rgba(0, 0, 0, 0.7)" : "rgba(0, 0, 0, 0.22)";

    const pad = 3;
    if (typeof data.label === "string" && data.label.length > 0) {
      const textWidth = context.measureText(data.label).width;
      const boxWidth = Math.round(textWidth + 10);
      const boxHeight = Math.round(size + 2 * pad + 2);
      const radius = Math.max(data.size, size / 2) + pad;
      const angle = Math.asin((boxHeight / 2) / radius);
      const h = Math.sqrt(Math.abs(Math.pow(radius, 2) - Math.pow(boxHeight / 2, 2)));

      context.save();
      context.shadowOffsetX = 0;
      context.shadowOffsetY = 2;
      context.shadowBlur = 8;
      context.shadowColor = shadowColor;

      context.fillStyle = bgColor;
      context.beginPath();
      context.moveTo(data.x + h, data.y + boxHeight / 2);
      context.lineTo(data.x + radius + boxWidth, data.y + boxHeight / 2);
      context.lineTo(data.x + radius + boxWidth, data.y - boxHeight / 2);
      context.lineTo(data.x + h, data.y - boxHeight / 2);
      context.arc(data.x, data.y, radius, angle, -angle);
      context.closePath();
      context.fill();

      context.shadowBlur = 0;
      context.strokeStyle = borderColor;
      context.lineWidth = 1;
      context.stroke();
      context.restore();

      context.fillStyle = textColor;
      context.font = `${weight} ${size}px ${font}`;
      context.fillText(data.label, data.x + data.size + 5, data.y + size / 3);
    } else {
      context.save();
      context.fillStyle = bgColor;
      context.beginPath();
      context.arc(data.x, data.y, data.size + pad, 0, Math.PI * 2);
      context.closePath();
      context.fill();
      context.restore();
    }
  }

  const renderer = new Sigma(g, canvas, {
    labelColor: { color: P.label },
    edgeLabelColor: { color: P.label },
    labelSize: 12,
    labelWeight: '500',
    labelFont: 'Inter, system-ui, sans-serif',
    edgeLabelSize: 10,
    edgeLabelFont: 'Inter, system-ui, sans-serif',
    labelDensity: 0.12,
    labelGridCellSize: 90,
    labelRenderedSizeThreshold: S.textFade,
    renderEdgeLabels: true,
    enableEdgeEvents: true,
    minCameraRatio: RATIO_MIN,
    maxCameraRatio: RATIO_MAX,
    stagePadding: 30,
    zIndex: true,
    edgeProgramClasses: { curved: createEdgeCurveProgram() },
    defaultDrawNodeHover: drawNodeHover,
    nodeReducer: (node, a) => {
      let r = { ...a, size: a.size * S.nodeSize };
      if (!nodeVisible(node)) return { ...r, hidden: true };
      if (node === dragged) return { ...r, highlighted: true, forceLabel: true, zIndex: 5 };

      // Community / Cluster coloring
      if (communityMode && communityMap.has(node)) {
        const cId = communityMap.get(node);
        r.color = COMMUNITY_COLORS[cId % COMMUNITY_COLORS.length];
      }

      // Visual Delta Diff coloring
      const nMeta = byId.get(node) || {};
      const diffState = a.diff || nMeta.diff;
      if (diffState === 'added') {
        r.color = '#10b981';
      } else if (diffState === 'removed') {
        r.color = '#ef4444';
      } else if (diffState === 'changed') {
        r.color = '#3b82f6';
      }

      if (hoveredEdge) {
        const [s, t] = g.extremities(hoveredEdge);
        if (node === s || node === t) return { ...r, forceLabel: true, highlighted: true, zIndex: 4 };
      }
      if (hovered && hovered !== selected) {
        if (node === hovered) return { ...r, forceLabel: true, zIndex: 4 };
        if (hoverSet.has(node)) return { ...r, forceLabel: true, zIndex: 3 };
        return { ...r, color: P.dim, label: '', zIndex: 0 };
      }
      if (multiSelected.size && !selected) {
        return multiSelected.has(node)
          ? { ...r, forceLabel: true, highlighted: true, zIndex: 4 }
          : { ...r, color: P.dim, label: '', zIndex: 0 };
      }
      if (pathMode) {
        return pathNodes && pathNodes.includes(node)
          ? { ...r, forceLabel: true, highlighted: true, zIndex: 4 }
          : { ...r, color: P.dim, label: '', zIndex: 0 };
      }
      if (!selected) {
        // In unselected overview, only prominent/hub nodes show labels to avoid overlapping clutter
        if (a.size < 6) return { ...r, label: "" };
      }
      if (selected) {
        const d = focusDist.get(node);
        if (d === 0) return { ...r, forceLabel: true, highlighted: true, zIndex: 4 };
        if (d === 1) return { ...r, forceLabel: focusDist.size <= 26, zIndex: 3 };
        if (d === 2) return { ...r, color: alpha(r.color, 0.6), zIndex: 2 };
        if (d === 3) return { ...r, color: alpha(r.color, 0.35), zIndex: 1 };
        return { ...r, color: P.dim, label: '', zIndex: 0 };
      }
      return r;
    },
    edgeReducer: (edge, a) => {
      if (!edgeVisible(edge)) return { ...a, hidden: true };
      const [s, t] = g.extremities(edge);
      if (!nodeVisible(s) || !nodeVisible(t)) return { ...a, hidden: true };
      const size = a.size * S.linkWidth;
      const curved = Math.abs(a.curvature || 0) > 0.001;
      let restColor = alpha(relColor(a.rel), curved ? (dark ? 0.2 : 0.24) : (dark ? 0.42 : 0.38));
      if (a.diff === 'added') restColor = '#10b981';
      else if (a.diff === 'removed') restColor = '#ef4444';
      const base = { ...a, size, type: curved ? 'curved' : (S.arrows ? 'arrow' : 'line'), label: '', color: restColor, curvature: a.curvature || 0 };

      if (edge === hoveredEdge || edge === selectedEdge) {
        return { ...base, color: P.edgeLit, size: size * 2.6, label: relText(a.rel), forceLabel: true, zIndex: 5 };
      }
      if (hovered && hovered !== selected) {
        return s === hovered || t === hovered
          ? { ...base, color: P.edgeLit, size: size * 1.5, zIndex: 3 }
          : { ...base, color: P.edgeGhost, zIndex: 0 };
      }
      if (multiSelected.size && !selected) {
        return multiSelected.has(s) || multiSelected.has(t)
          ? { ...base, color: P.edgeLit, size: size * 1.4, zIndex: 3 }
          : { ...base, color: P.edgeGhost, zIndex: 0 };
      }
      if (pathMode) {
        return pathEdgeSet.has(edge)
          ? { ...base, color: P.edgeLit, size: size * 2, label: relText(a.rel), forceLabel: true, zIndex: 5 }
          : { ...base, color: P.edgeGhost, zIndex: 0 };
      }
      if (selected) {
        const ds = focusDist.get(s), dt = focusDist.get(t);
        if (ds == null || dt == null) return { ...base, color: P.edgeGhost, zIndex: 0 };
        if (ds === 0 || dt === 0) {
          const few = focusDist.size <= 13;
          return { ...base, color: P.edgeLit, size: size * 1.5, label: few ? relText(a.rel) : '', forceLabel: few, zIndex: 3 };
        }
        return { ...base, color: Math.max(ds, dt) <= 2 ? P.edge : P.edgeFaint, zIndex: 2 };
      }
      return base;
    },
  });
  const camera = renderer.getCamera();
  // Freeze the coordinate normalisation after the initial settle. Without it
  // Sigma re-fits to the node extent on every layout tick, so a running
  // simulation or a dragged node would make the whole view breathe.
  try { renderer.setCustomBBox(renderer.getBBox()); } catch (err) { /* older sigma: tolerate drift */ }
  if (loading) loading.hidden = true;

  // ---- Camera -------------------------------------------------------------
  // Where a reader left the view, so a plain reload without a focus in the
  // URL comes back to that rather than always snapping to the full fit.
  const CAMERA_STORE_KEY = `${STORE_KEY}:camera`;
  let cameraSaveTimer = 0;
  camera.on('updated', () => {
    clearTimeout(cameraSaveTimer);
    cameraSaveTimer = setTimeout(() => {
      try { localStorage.setItem(CAMERA_STORE_KEY, JSON.stringify(camera.getState())); } catch (err) { /* ignore */ }
    }, 400);
  });
  let flyTimer = 0;
  function moveCamera(state, duration = 450) {
    const target = { ...camera.getState(), ...state };
    target.ratio = clamp(target.ratio, RATIO_MIN, RATIO_MAX);
    if (![target.x, target.y, target.ratio].every(Number.isFinite)) return;
    try { camera.animate(target, { duration }); } catch (err) { camera.setState(target); }
    // animate() rides requestAnimationFrame, which a background tab or an
    // embedded pane can throttle to nothing; land on the target regardless.
    clearTimeout(flyTimer);
    flyTimer = setTimeout(() => {
      const cur = camera.getState();
      if (Math.abs(cur.ratio - target.ratio) > 1e-3 || Math.abs(cur.x - target.x) > 1e-3 || Math.abs(cur.y - target.y) > 1e-3) {
        camera.setState(target);
      }
    }, duration + 120);
  }
  function frame(ids, pad = 1.35) {
    const pts = ids.map((id) => renderer.getNodeDisplayData(id)).filter((p) => p && Number.isFinite(p.x));
    if (!pts.length) return;
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    for (const p of pts) { x0 = Math.min(x0, p.x); x1 = Math.max(x1, p.x); y0 = Math.min(y0, p.y); y1 = Math.max(y1, p.y); }
    const w = stage.clientWidth, h = stage.clientHeight;
    const shape = w > 0 && h > 0 ? w / h : 1;
    // Sigma frames the unit square to the shorter side, so a wide span on a
    // tall stage (or the reverse) needs proportionally more room.
    const span = Math.max((x1 - x0) / Math.max(shape, 1), (y1 - y0) * Math.min(shape, 1), 0.06);
    const ratio = clamp(span * pad, RATIO_MIN, RATIO_MAX);
    // With the focus card docked on the right, centre the frame in the space
    // left of it rather than behind it. One framed unit spans the stage's
    // shorter side at ratio 1.
    // On a phone the card is a bottom sheet, so the same shift is vertical.
    let dx = 0, dy = 0;
    if (!pinBox.hidden && w >= 640) dx = ((pinBox.offsetWidth + 16) / 2) / Math.min(w, h) * ratio;
    else if (!pinBox.hidden) dy = -((pinBox.offsetHeight + 16) / 2) / Math.min(w, h) * ratio;
    moveCamera({ x: (x0 + x1) / 2 + dx, y: (y0 + y1) / 2 + dy, ratio });
  }
  function fitAll() {
    frame(g.filterNodes((n) => nodeVisible(n)), 1.12);
  }

  // ---- Live simulation ----------------------------------------------------
  let simRAF = 0, simUntil = 0, simMinimapRAF = 0, workerStopTimer = 0;
  function stopWorkerSim() {
    clearTimeout(workerStopTimer);
    workerStopTimer = 0;
    if (activeFa2Worker) {
      try { activeFa2Worker.stop(); activeFa2Worker.kill(); } catch (err) { /* already gone */ }
      activeFa2Worker = null;
    }
    simMinimapRAF = 0;
  }
  // Cosmetic only — redraws the minimap while the worker runs. It must NOT be
  // what stops the worker: requestAnimationFrame is throttled to near-zero on
  // a backgrounded tab, but the Worker itself keeps computing regardless of
  // tab visibility (unlike the main-thread step() loop below, which
  // naturally goes idle when its own rAF stops firing). A stop condition that
  // only checks on an rAF tick found that the hard way in testing: the worker
  // kept running for as long as the tab stayed backgrounded, well past the
  // requested duration. setTimeout is the actual stop signal — throttled in
  // a background tab too, but never frozen to zero the way rAF is.
  function minimapTick() {
    if (!activeFa2Worker) { simMinimapRAF = 0; return; }
    drawMinimap();
    if (dragged) { stopWorkerSim(); return; }
    simMinimapRAF = requestAnimationFrame(minimapTick);
  }
  function simulate(ms = 3000) {
    simUntil = Math.max(simUntil, performance.now() + ms);
    if (fa2WorkerAvailable && !dragged) {
      if (activeFa2Worker) { try { activeFa2Worker.kill(); } catch (err) { /* already gone */ } }
      try {
        activeFa2Worker = new FA2LayoutCtor(g, { settings: fa2Settings() });
        activeFa2Worker.start();
      } catch (err) {
        activeFa2Worker = null;
        fa2WorkerAvailable = false; // don't keep retrying a path that just failed live
      }
      if (activeFa2Worker) {
        clearTimeout(workerStopTimer);
        workerStopTimer = setTimeout(stopWorkerSim, Math.max(0, simUntil - performance.now()) + 50);
        if (!simMinimapRAF) simMinimapRAF = requestAnimationFrame(minimapTick);
        return;
      }
    }
    if (!simRAF) simRAF = requestAnimationFrame(step);
  }
  function step() {
    simRAF = 0;
    const before = new Map();
    g.forEachNode((n, a) => before.set(n, [a.x, a.y]));
    try {
      forceAtlas2.assign(g, { iterations: 3, getEdgeWeight: 'weight', settings: fa2Settings() });
    } catch (err) { return; }
    let moved = 0, x0 = Infinity, x1 = -Infinity;
    g.forEachNode((n, a) => {
      const [bx, by] = before.get(n);
      moved += Math.hypot(a.x - bx, a.y - by);
      x0 = Math.min(x0, a.x); x1 = Math.max(x1, a.x);
    });
    const settled = moved / g.order < (x1 - x0) * 0.0004;
    drawMinimap();
    if (dragged || (performance.now() < simUntil && !settled)) simRAF = requestAnimationFrame(step);
  }

  // ---- Minimap --------------------------------------------------------------
  // A plain 2D canvas, not a second Sigma instance: it only ever needs dots
  // and one rectangle, and reusing WebGL for that is not worth a second
  // renderer to keep in sync. Dots come straight from getNodeDisplayData()'s
  // own normalised space. The viewport rectangle is trickier: Sigma exposes
  // no display-space <-> viewport-pixel conversion, so it is calibrated live
  // from two real, maximally-separated nodes each redraw (see drawMinimap).
  const minimapCanvas = root.querySelector('[data-kb-minimap]');
  const minimapCtx = minimapCanvas && minimapCanvas.getContext('2d');
  // Sized from its own CSS box (which shrinks on a phone) rather than a fixed
  // constant, so the backing store always matches what is actually on screen.
  let mmSize = MINIMAP_SIZE;
  if (minimapCanvas) {
    const dpr = window.devicePixelRatio || 1;
    mmSize = minimapCanvas.getBoundingClientRect().width || MINIMAP_SIZE;
    minimapCanvas.width = mmSize * dpr;
    minimapCanvas.height = mmSize * dpr;
    minimapCtx.scale(dpr, dpr);
  }
  function drawMinimap() {
    if (!minimapCtx) return;
    // Sigma only recomputes the transform graphToViewport()/getNodeDisplayData()
    // read from on its own render pass, which camera.animate() schedules for
    // the next frame rather than applying synchronously — so a minimap redraw
    // triggered from the SAME tick as a camera move (the common case) would
    // read one frame stale without forcing that render first.
    renderer.refresh({ skipIndexation: true });
    minimapCtx.clearRect(0, 0, mmSize, mmSize);
    // Track the nodes at each display-space extreme while drawing dots, to
    // calibrate the viewport-pixel <-> display-space mapping below — Sigma
    // exposes no direct conversion between the two, and hand-deriving one
    // from camera ratio/shape once produced a rectangle 80% too large.
    let xLo = null, xHi = null, yLo = null, yHi = null;
    g.forEachNode((n) => {
      if (!nodeVisible(n)) return;
      const d = renderer.getNodeDisplayData(n);
      if (!d || !Number.isFinite(d.x)) return;
      minimapCtx.fillStyle = d.color || '#94a3b8';
      minimapCtx.beginPath();
      minimapCtx.arc(d.x * mmSize, d.y * mmSize, 1.4, 0, Math.PI * 2);
      minimapCtx.fill();
      if (!xLo || d.x < xLo.x) xLo = { id: n, x: d.x };
      if (!xHi || d.x > xHi.x) xHi = { id: n, x: d.x };
      if (!yLo || d.y < yLo.y) yLo = { id: n, y: d.y };
      if (!yHi || d.y > yHi.y) yHi = { id: n, y: d.y };
    });
    if (!xLo || xLo.id === xHi.id || yLo.id === yHi.id) return; // not enough spread to calibrate
    const vp = (id) => renderer.graphToViewport(g.getNodeAttributes(id));
    const xLoVp = vp(xLo.id).x, xHiVp = vp(xHi.id).x, yLoVp = vp(yLo.id).y, yHiVp = vp(yHi.id).y;
    const A = (xHiVp - xLoVp) / (xHi.x - xLo.x), B = xLoVp - A * xLo.x;
    const C = (yHiVp - yLoVp) / (yHi.y - yLo.y), D = yLoVp - C * yLo.y;
    if (![A, B, C, D].every(Number.isFinite)) return;
    const w = stage.clientWidth, h = stage.clientHeight;
    // Invert the fit: which display-space x/y do the current screen edges show.
    const x0 = clamp((0 - B) / A, -0.5, 1.5) * mmSize, x1 = clamp((w - B) / A, -0.5, 1.5) * mmSize;
    const y0 = clamp((0 - D) / C, -0.5, 1.5) * mmSize, y1 = clamp((h - D) / C, -0.5, 1.5) * mmSize;
    minimapCtx.strokeStyle = dark ? 'rgba(226,232,240,0.85)' : 'rgba(30,41,59,0.75)';
    minimapCtx.lineWidth = 1;
    minimapCtx.strokeRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
  }
  if (minimapCanvas) {
    camera.on('updated', drawMinimap);
    const jump = (ev) => {
      const rect = minimapCanvas.getBoundingClientRect();
      moveCamera({
        x: clamp((ev.clientX - rect.left) / rect.width, 0, 1),
        y: clamp((ev.clientY - rect.top) / rect.height, 0, 1),
      }, 200);
    };
    let mmDragging = false;
    minimapCanvas.addEventListener('mousedown', (ev) => { mmDragging = true; jump(ev); });
    window.addEventListener('mousemove', (ev) => { if (mmDragging) jump(ev); });
    window.addEventListener('mouseup', () => { mmDragging = false; });
  }

  // ---- Cards --------------------------------------------------------------
  function linksHtml(n) {
    const refs = n.urls || {};
    const links = [];
    if (refs.wikipedia) links.push(`<a href="${esc(refs.wikipedia)}" target="_blank" rel="noopener">Wikipedia &nearr;</a>`);
    if (refs.canonical) links.push(`<a href="${esc(refs.canonical)}" target="_blank" rel="noopener">Website &nearr;</a>`);
    return links.join(' ');
  }

  // A node's visible relationships, each read from this node's end: Spark
  // "implements" lazy evaluation; lazy evaluation is "implemented by" Spark.
  function neighbours(node) {
    const out = [];
    g.forEachEdge(node, (e, a, s, t) => {
      if (!edgeVisible(e)) return;
      const other = s === node ? t : s;
      if (!nodeVisible(other)) return;
      out.push({ edge: e, id: other, rel: s === node ? a.rel : (inverseLabel[a.rel] || a.rel), tier: a.tier, scope: a.scope });
    });
    return out;
  }

  function walkRow(r) {
    const n = byId.get(r.id);
    return `<button type="button" class="kb-walk" data-kb-walk="${esc(r.id)}">` +
      `<span class="kb-dot" style="background:${getTypeColor(n.type)}"></span>` +
      `<span class="kb-walk-name">${esc(n.label)}</span>` +
      (r.scope ? `<i class="kb-walk-scope">${esc(r.scope)}</i>` : '') + tierChip(r.tier) + `</button>`;
  }

  function nodePinHtml(node) {
    const n = byId.get(node);
    const rows = neighbours(node);
    const byRel = new Map();
    for (const r of rows) {
      if (!byRel.has(r.rel)) byRel.set(r.rel, []);
      byRel.get(r.rel).push(r);
    }
    const relSections = [...byRel.entries()]
      .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
      .map(([rel, rs]) =>
        `<div class="kb-walk-group"><span class="kb-cites-label">${esc(relText(rel))} <span class="kb-walk-n">${rs.length}</span></span>` +
        rs.sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0)).map(walkRow).join('') + `</div>`)
      .join('');
    const links = linksHtml(n);
    return (
      `<button type="button" class="kb-pin-close" data-kb-pin-close aria-label="Close and clear the focus">&times;</button>` +
      `<span class="kb-card-type" style="--c:${getTypeColor(n.type)}">${esc(TYPE_LABEL[n.type] || n.type)}</span>` +
      `<strong>${esc(n.label)}</strong>` +
      (n.meta && n.meta.description ? `<p class="kb-pin-desc">${esc(n.meta.description)}</p>` : '') +
      (links ? `<div class="kb-pin-links">${links}</div>` : '') +
      (rows.length
        ? `<div class="kb-walks" role="group" aria-label="Connected entities — choose one to move along that edge">${relSections}</div>`
        : `<p class="kb-pin-empty">No relationships under the current filters.</p>`) +
      contextHtml(context.get(node), { articleCap: 5 })
    );
  }

  function sourceHtml(a) {
    const parts = [];
    const doc = a.doc && byId.get(a.doc);
    if (a.doc && a.doc.startsWith('pack:')) {
      const slug = a.doc.slice(5);
      parts.push(`<a href="/knowledge-base/entities/${esc(slug)}.json">${esc(slug)} entity pack</a>`);
    } else if (doc) {
      parts.push(`<a href="${esc(doc.url || '#')}">${esc(doc.label)}</a>${a.via ? ` <span class="kb-cite-date">${esc(a.via)}</span>` : ''}`);
    }
    for (const url of a.sources || []) {
      let host = url;
      try { host = new URL(url).hostname.replace(/^www\./, ''); } catch (err) { /* keep raw */ }
      parts.push(`<a href="${esc(url)}" target="_blank" rel="noopener">${esc(host)} &nearr;</a>`);
    }
    return parts.length
      ? `<div class="kb-cites"><span class="kb-cites-label">Source</span><ul>${parts.map((p) => `<li>${p}</li>`).join('')}</ul></div>` : '';
  }

  function edgePinHtml(edge) {
    const a = g.getEdgeAttributes(edge);
    const [s, t] = g.extremities(edge);
    const end = (id) => walkRow({ id });
    return (
      `<button type="button" class="kb-pin-close" data-kb-pin-close aria-label="Close">&times;</button>` +
      `<span class="kb-card-type" style="--c:var(--accent-primary)">Relationship</span>` +
      `<div class="kb-edge-ends">${end(s)}<span class="kb-edge-rel">${esc(relText(a.rel))} &darr;</span>${end(t)}</div>` +
      (a.scope ? `<p class="kb-pin-desc"><b>Scope:</b> ${esc(a.scope)}</p>` : '') +
      (a.explanation ? `<p class="kb-pin-desc">${esc(a.explanation)}</p>` : '') +
      `<p class="kb-edge-meta">` +
        (a.confidence != null ? `Confidence ${Math.round(a.confidence * 100)}%` : '') +
        (a.tier ? `${a.confidence != null ? ' · ' : ''}${esc(a.tier)}` : '') +
        (a.rel === 'COMPARES_TO' ? ' · scored on the same scorecard axes' : '') +
      `</p>` +
      sourceHtml(a)
    );
  }

  function openPin(html) {
    pinBox.innerHTML = html;
    pinBox.hidden = false;
    pinBox.scrollTop = 0;
    stage.classList.add('has-pin');
    pinBox.style.maxHeight = `${Math.max(140, stage.clientHeight - 16)}px`;
    // A phone cannot show the settings panel and a card at once.
    if (panel && stage.clientWidth < 640) panel.open = false;
  }
  function closePin() {
    pinBox.hidden = true;
    stage.classList.remove('has-pin');
  }

  function positionFloating(el, pos) {
    el.hidden = false;
    const w = stage.clientWidth, h = stage.clientHeight;
    el.style.maxHeight = `${Math.max(120, h - 16)}px`;
    const ew = el.offsetWidth, eh = el.offsetHeight;
    let left = pos.x + 16, top = pos.y + 16;
    if (left + ew > w - 8) left = pos.x - ew - 16;
    if (top + eh > h - 8) top = pos.y - eh - 16;
    el.style.left = `${Math.max(8, left)}px`;
    el.style.top = `${Math.max(8, Math.min(top, h - 8))}px`;
  }

  function showNodeCard(node, pos) {
    const n = byId.get(node);
    const rows = neighbours(node);
    const shown = rows.slice(0, 4).map((r) =>
      `<span class="kb-rel-tag"><i>${esc(relText(r.rel))}</i> ${esc(byId.get(r.id).label)}</span>`).join('');
    card.innerHTML =
      `<span class="kb-card-type" style="--c:${getTypeColor(n.type)}">${esc(TYPE_LABEL[n.type] || n.type)}</span>` +
      `<strong>${esc(n.label)}</strong>` +
      (n.meta && n.meta.description ? `<span class="kb-card-meta">${esc(n.meta.description)}</span>` : '') +
      (rows.length ? `<span class="kb-card-rels">${shown}${rows.length > 4 ? `<span class="kb-rel-more">+${rows.length - 4} more</span>` : ''}</span>` : '') +
      contextHtml(context.get(node), { compact: true }) +
      `<span class="kb-card-hint">${node === selected ? 'In focus' : 'Click to focus · drag to move'}</span>`;
    positionFloating(card, pos);
  }
  function showEdgeCard(edge, pos) {
    const a = g.getEdgeAttributes(edge);
    const [s, t] = g.extremities(edge);
    card.innerHTML =
      `<span class="kb-card-type" style="--c:var(--accent-primary)">Relationship</span>` +
      `<strong>${esc(byId.get(s).label)} <i class="kb-edge-inline">${esc(relText(a.rel))}</i> ${esc(byId.get(t).label)}</strong>` +
      (a.explanation ? `<span class="kb-card-meta">${esc(a.explanation)}</span>` : '') +
      `<span class="kb-card-hint">Click for the source</span>`;
    positionFloating(card, pos);
  }
  const hideCard = () => { card.hidden = true; };

  function renderCentre() {
    if (!centre) return;
    if (!selected) {
      centre.innerHTML =
        `<span class="kb-centre-meta">${entities.length} entities · ${semEdges.length} relationships. ` +
        `Search, or click any node to focus it and walk its connections.</span>`;
      if (bottomSummary) bottomSummary.textContent = 'Details';
      return;
    }
    const n = byId.get(selected);
    const ctx = context.get(selected);
    const ctxCount = ctx ? ctx.articles.length : 0;
    centre.innerHTML =
      `<span class="kb-dot" style="background:${getTypeColor(n.type)}"></span>` +
      `<span class="kb-centre-type">${esc(TYPE_LABEL[n.type] || n.type)}</span> <strong>${esc(n.label)}</strong> ` +
      `<span class="kb-centre-meta">${ctxCount} related article${ctxCount === 1 ? '' : 's'}</span> ` +
      linksHtml(n) +
      (n.meta && n.meta.description ? `<p class="kb-centre-desc">${esc(n.meta.description)}</p>` : '') +
      (n.meta && n.meta.notes ? `<p class="kb-centre-note"><span>Classification:</span> ${esc(n.meta.notes)}</p>` : '') +
      contextHtml(ctx);
    // The panel is collapsed by default, so the summary row is the only
    // place a reader sees which entity's details are inside before opening.
    if (bottomSummary) bottomSummary.textContent = `${n.label} — ${ctxCount} related article${ctxCount === 1 ? '' : 's'}`;
  }

  function renderMeta() {
    if (!meta) return;
    const nodes = g.filterNodes((n) => nodeVisible(n)).length;
    const edges = g.filterEdges((e) => edgeVisible(e)).length;
    meta.textContent = `${nodes} of ${g.order} entities · ${edges} of ${g.size} relationships shown` +
      (selected ? ` · ${focusDist.size - 1} within ${S.depth} hop${S.depth === 1 ? '' : 's'} of ${byId.get(selected).label}` : '');
  }

  // ---- Selection, history, deep links ------------------------------------
  // The full view — focus, depth, and every filter that isn't the default —
  // lives in the URL, so a shared link reproduces what was actually on
  // screen, not just which entity was centred.
  function syncUrl() {
    const p = new URLSearchParams();
    if (S.depth !== DEFAULTS.depth) p.set('depth', S.depth);
    if (!S.orphans) p.set('orphans', '0');
    if (!S.comparisons) p.set('cmp', '0');
    const offRels = rels.filter((r) => !allowedRels.has(r) && r !== 'COMPARES_TO');
    if (offRels.length) p.set('hideRel', offRels.join(','));
    if (hiddenTypes.size) p.set('hideType', [...hiddenTypes].join(','));
    const qs = p.toString();
    const url = `${window.location.pathname}${qs ? `?${qs}` : ''}${selected ? `#${selected}` : ''}`;
    try { window.history.replaceState(null, '', url); } catch (err) { /* sandboxed frame */ }
  }

  function select(id, { push = true, fly = true } = {}) {
    if (!id || !g.hasNode(id)) { clearSelection(); return; }
    const kind = g.getNodeAttribute(id, 'kind');
    if (hiddenTypes.has(kind)) {
      // Asking for a hidden entity by name is asking to see it.
      hiddenTypes.delete(kind);
      const box = groupsEl.querySelector(`[data-kb-type="${kind}"]`);
      if (box) box.checked = true;
      S.hiddenTypes = [...hiddenTypes];
      saveSettings();
      computeVisDeg();
    }
    multiSelected = new Set();
    pathMode = false;
    pathNodes = null;
    pathEdgeSet = new Set();
    selected = id;
    selectedEdge = null;
    pushRecent(id);
    if (push && trail[trailIndex] !== id) {
      trail = trail.slice(0, trailIndex + 1);
      trail.push(id);
      trailIndex = trail.length - 1;
    }
    computeFocus();
    hideCard();
    openPin(nodePinHtml(id));
    renderCentre();
    renderNav();
    renderMeta();
    syncUrl();
    renderer.refresh({ skipIndexation: true });
    if (fly) frame([...focusDist.entries()].filter(([, d]) => d <= 1).map(([n]) => n));
  }

  function selectEdge(edge) {
    multiSelected = new Set();
    pathMode = false;
    pathNodes = null;
    pathEdgeSet = new Set();
    selectedEdge = edge;
    hideCard();
    openPin(edgePinHtml(edge));
    renderer.refresh({ skipIndexation: true });
  }

  // A shift-drag lasso result: no single focus, but several nodes lit at
  // once so their place relative to each other and the rest is visible.
  function showMultiSelect(ids) {
    selected = null;
    selectedEdge = null;
    focusDist = new Map();
    pathMode = false;
    pathNodes = null;
    pathEdgeSet = new Set();
    multiSelected = new Set(ids);
    hideCard();
    const rows = ids
      .map((id) => byId.get(id))
      .sort((a, b) => (degree.get(b.id) || 0) - (degree.get(a.id) || 0));
    openPin(
      `<button type="button" class="kb-pin-close" data-kb-pin-close aria-label="Close">&times;</button>` +
      `<span class="kb-card-type" style="--c:var(--accent-primary)">${ids.length} entities selected</span>` +
      `<div class="kb-walk-group">${rows.map((n) => walkRow({ id: n.id })).join('')}</div>`
    );
    renderCentre();
    renderMeta();
    renderer.refresh({ skipIndexation: true });
    frame(ids, 1.5);
  }

  function clearSelection() {
    selected = null;
    selectedEdge = null;
    multiSelected = new Set();
    pathMode = false;
    pathNodes = null;
    pathEdgeSet = new Set();
    focusDist = new Map();
    closePin();
    renderCentre();
    renderNav();
    renderMeta();
    syncUrl();
    renderer.refresh({ skipIndexation: true });
  }

  let pathWaypoints = [];

  function pathHtml(result) {
    const { nodes, edges, hopCount, chain, waypoints } = result;
    const waypointChips = (waypoints || pathWaypoints || []).map((w, idx) => {
      const label = esc((byId.get(w) || {}).label || w);
      return `<span class="kb-waypoint-chip">${label} <button type="button" class="kb-waypoint-del" data-kb-del-waypoint="${idx}" aria-label="Remove waypoint">&times;</button></span>`;
    }).join(' &rarr; ');

    const rows = chain.map((id, i) => {
      let rel = null;
      if (i > 0) {
        g.forEachEdge(chain[i - 1], (e, a, s, t) => {
          if (!rel && ((s === chain[i - 1] && t === id) || (s === id && t === chain[i - 1]))) rel = a.rel;
        });
      }
      const hop = rel ? `<div class="kb-edge-rel">${esc(relText(rel))} &darr;</div>` : '';
      return hop + walkRow({ id });
    }).join('');
    const otherRoutes = nodes.length > chain.length || edges.length > chain.length - 1;
    return (
      `<button type="button" class="kb-pin-close" data-kb-pin-close aria-label="Close">&times;</button>` +
      `<span class="kb-card-type" style="--c:var(--accent-primary)">Waypoint Route &middot; ${hopCount} hop${hopCount === 1 ? '' : 's'}</span>` +
      `<div class="kb-waypoint-list" style="margin: 0.4rem 0;">${waypointChips}</div>` +
      `<div class="kb-edge-ends" style="max-height:240px; overflow-y:auto;">${rows}</div>` +
      `<p class="kb-pin-desc" style="font-size:0.72rem; color:var(--text-muted); margin-top:0.4rem;">Shift-click another entity to add it as a waypoint.</p>` +
      (otherRoutes ? `<p class="kb-pin-desc">One example route &mdash; other equally-short paths are highlighted too.</p>` : '')
    );
  }

  function showPath(fromId, toId) {
    pathWaypoints = [fromId, toId];
    renderCurrentPath();
  }

  function addWaypoint(nodeId) {
    if (!pathWaypoints.includes(nodeId)) {
      pathWaypoints.push(nodeId);
      renderCurrentPath();
    }
  }

  function removeWaypoint(idx) {
    if (pathWaypoints.length > 2) {
      pathWaypoints.splice(idx, 1);
      renderCurrentPath();
    } else {
      clearPath();
    }
  }

  function renderCurrentPath() {
    const result = computeMultiPath(pathWaypoints);
    multiSelected = new Set();
    pathMode = true;
    hideCard();
    if (!result) {
      pathNodes = null;
      pathEdgeSet = new Set();
      openPin(
        `<button type="button" class="kb-pin-close" data-kb-pin-close aria-label="Close">&times;</button>` +
        `<span class="kb-card-type" style="--c:var(--accent-primary)">No path</span>` +
        `<p class="kb-pin-desc">The selected waypoints aren't connected under the current filters.</p>`
      );
      renderer.refresh({ skipIndexation: true });
      return;
    }
    pathNodes = result.nodes;
    pathEdgeSet = new Set(result.edges);
    openPin(pathHtml(result));
    renderer.refresh({ skipIndexation: true });
    frame(pathNodes, 1.5);
  }

  function clearPath() {
    pathMode = false;
    pathNodes = null;
    pathWaypoints = [];
    pathEdgeSet = new Set();
    if (selected) openPin(nodePinHtml(selected)); else closePin();
    renderer.refresh({ skipIndexation: true });
  }


  function goTo(index) {
    if (index < 0 || index >= trail.length) return;
    trailIndex = index;
    select(trail[index], { push: false });
  }
  const goBack = () => goTo(trailIndex - 1);
  const goForward = () => goTo(trailIndex + 1);

  function renderNav() {
    if (navBack) navBack.disabled = trailIndex <= 0;
    if (navForward) navForward.disabled = trailIndex >= trail.length - 1;
    if (!breadcrumbEl) return;
    const MAX_CRUMBS = 4;
    const path = trail.slice(0, trailIndex + 1);
    const shown = path.slice(-MAX_CRUMBS);
    const offset = path.length - shown.length;
    const parts = offset > 0 ? ['<span class="kb-breadcrumb-sep">&hellip;&nbsp;&rsaquo;</span>'] : [];
    shown.forEach((id, i) => {
      const label = esc((byId.get(id) || {}).label || id);
      const current = i === shown.length - 1 && id === selected;
      if (current) { parts.push(`<span class="kb-breadcrumb-current">${label}</span>`); return; }
      parts.push(`<button type="button" data-kb-jump="${offset + i}">${label}</button>` +
        (i < shown.length - 1 ? '<span class="kb-breadcrumb-sep">&rsaquo;</span>' : ''));
    });
    breadcrumbEl.innerHTML = parts.join(' ');
  }

  // ---- Filters ------------------------------------------------------------
  function applyFilters() {
    allowedRels = new Set([...relsEl.querySelectorAll('input:checked:not([data-kb-group])')].map((i) => i.value));
    const cmp = root.querySelector('[data-kb-set="comparisons"]');
    if (cmp) cmp.checked = S.comparisons = allowedRels.has('COMPARES_TO');
    computeVisDeg();
    if (selected && !nodeVisible(selected)) { clearSelection(); } else {
      computeFocus();
      if (selectedEdge && !edgeVisible(selectedEdge)) { selectedEdge = null; closePin(); }
      else if (selected && !selectedEdge) openPin(nodePinHtml(selected));
    }
    renderMeta();
    renderer.refresh({ skipIndexation: true });
    drawMinimap();
    saveSettings();
    syncUrl();
  }
  relsEl.addEventListener('change', applyFilters);
  groupsEl.addEventListener('change', (ev) => {
    const t = ev.target.dataset.kbType;
    if (!t) return;
    if (ev.target.checked) hiddenTypes.delete(t); else hiddenTypes.add(t);
    S.hiddenTypes = [...hiddenTypes];
    applyFilters();
  });

  // Curated shortcuts over the same checkboxes — "apply and reset", not a
  // persistent radio: tweaking a box afterwards should not fight a label
  // claiming to still describe the view.
  const PRESETS = {
    everything: () => { setAllRels(true); hiddenTypes.clear(); },
    no_comparisons: () => { setAllRels(true); setRel('COMPARES_TO', false); hiddenTypes.clear(); },
    structure: () => {
      relsEl.querySelectorAll('input[type="checkbox"]:not([data-kb-group])').forEach((i) => {
        i.checked = ['Structure', 'Data flow'].includes(relGroupOf.get(i.value));
      });
      relsEl.querySelectorAll('[data-kb-group-items]').forEach(syncGroupMaster);
      hiddenTypes.clear();
    },
    concepts: () => {
      setAllRels(true);
      hiddenTypes.clear();
      ENTITY_ORDER.forEach((t) => { if (!['Concept', 'ArchitecturePattern'].includes(t)) hiddenTypes.add(t); });
      groupsEl.querySelectorAll('input').forEach((i) => { i.checked = !hiddenTypes.has(i.dataset.kbType); });
    },
  };
  const presetSelect = root.querySelector('[data-kb-preset]');
  if (presetSelect) {
    presetSelect.addEventListener('change', () => {
      const fn = PRESETS[presetSelect.value];
      presetSelect.value = '';
      if (!fn) return;
      fn();
      S.hiddenTypes = [...hiddenTypes];
      applyFilters();
    });
  }

  // ---- Panel settings -----------------------------------------------------
  const FORMAT = { center: (v) => v.toFixed(1), repel: (v) => String(v), link: (v) => v.toFixed(1),
    nodeSize: (v) => `${v.toFixed(1)}×`, linkWidth: (v) => `${v.toFixed(1)}×`, textFade: (v) => String(v), depth: (v) => String(v) };
  function syncInputs() {
    root.querySelectorAll('[data-kb-set]').forEach((input) => {
      const key = input.dataset.kbSet;
      if (input.type === 'checkbox') input.checked = !!S[key];
      else input.value = S[key];
      const out = root.querySelector(`[data-kb-out="${key}"]`);
      if (out && FORMAT[key]) out.textContent = FORMAT[key](Number(S[key]));
    });
  }
  syncInputs();
  if (!S.comparisons) setRel('COMPARES_TO', false);

  root.querySelectorAll('[data-kb-set]').forEach((input) => {
    input.addEventListener(input.type === 'checkbox' ? 'change' : 'input', () => {
      const key = input.dataset.kbSet;
      S[key] = input.type === 'checkbox' ? input.checked : Number(input.value);
      const out = root.querySelector(`[data-kb-out="${key}"]`);
      if (out && FORMAT[key]) out.textContent = FORMAT[key](S[key]);
      if (key === 'comparisons') { setRel('COMPARES_TO', S.comparisons); applyFilters(); return; }
      if (key === 'orphans') { applyFilters(); return; }
      if (key === 'depth') { computeFocus(); renderMeta(); syncUrl(); }
      if (key === 'textFade') renderer.setSetting('labelRenderedSizeThreshold', S.textFade);
      if (key === 'link') g.forEachEdge((e, a) => g.setEdgeAttribute(e, 'weight', a.baseWeight * S.link));
      if (key === 'center' || key === 'repel' || key === 'link') simulate(3000);
      renderer.refresh({ skipIndexation: true });
      saveSettings();
    });
  });
  // One snapshot of positions + force settings, so scattering the layout or
  // resetting forces is never a one-way trip — a reader who was mid-way
  // through a tuned arrangement can always get back to it.
  let layoutSnapshot = null;
  const undoLayoutBtn = root.querySelector('[data-kb-undo-layout]');
  function snapshotLayout() {
    const positions = new Map();
    g.forEachNode((n, a) => positions.set(n, [a.x, a.y]));
    layoutSnapshot = { positions, forces: { center: S.center, repel: S.repel, link: S.link } };
    if (undoLayoutBtn) undoLayoutBtn.hidden = false;
  }
  if (undoLayoutBtn) {
    undoLayoutBtn.addEventListener('click', () => {
      if (!layoutSnapshot) return;
      for (const [n, [x, y]] of layoutSnapshot.positions) {
        if (g.hasNode(n)) g.mergeNodeAttributes(n, { x, y });
      }
      Object.assign(S, layoutSnapshot.forces);
      g.forEachEdge((e, a) => g.setEdgeAttribute(e, 'weight', a.baseWeight * S.link));
      syncInputs();
      saveSettings();
      layoutSnapshot = null;
      undoLayoutBtn.hidden = true;
      renderer.refresh({ skipIndexation: true });
      drawMinimap();
    });
  }
  const animateBtn = root.querySelector('[data-kb-animate]');
  if (animateBtn) {
    // Obsidian's Animate: scatter and watch it find its shape again.
    animateBtn.addEventListener('click', () => {
      snapshotLayout();
      g.forEachNode((n) => {
        const rnd = hashSeed(`${n}:${Date.now()}`);
        const angle = rnd() * Math.PI * 2, r = 5 + rnd() * 40;
        g.mergeNodeAttributes(n, { x: Math.cos(angle) * r, y: Math.sin(angle) * r });
      });
      simulate(6000);
    });
  }
  const resetForces = root.querySelector('[data-kb-forces-reset]');
  if (resetForces) {
    resetForces.addEventListener('click', () => {
      snapshotLayout();
      Object.assign(S, { center: DEFAULTS.center, repel: DEFAULTS.repel, link: DEFAULTS.link });
      g.forEachEdge((e, a) => g.setEdgeAttribute(e, 'weight', a.baseWeight));
      syncInputs();
      saveSettings();
      simulate(3000);
    });
  }


  // ---- Timeline Scrubber & Temporal Filter ----
  const timelineEl = root.querySelector("[data-kb-timeline]");
  const timelinePlay = root.querySelector("[data-kb-timeline-play]");
  const timelineSlider = root.querySelector("[data-kb-timeline-slider]");
  const timelineDate = root.querySelector("[data-kb-timeline-date]");
  const timelineTotal = root.querySelector("[data-kb-timeline-total]");
  let timelinePlaying = false, timelineTimer = 0;

  function setTimelineIndex(idx) {
    if (idx >= allDates.length) {
      timelineCutoff = null;
      if (timelineDate) timelineDate.textContent = "All time";
    } else {
      timelineCutoff = allDates[idx];
      if (timelineDate) timelineDate.textContent = timelineCutoff;
    }
    if (timelineSlider) timelineSlider.value = idx;
    computeVisDeg();
    renderer.refresh({ skipIndexation: true });
    drawMinimap();
  }

  if (allDates.length >= 2 && timelineEl) {
    timelineEl.hidden = false;
    timelineSlider.max = allDates.length;
    timelineSlider.value = allDates.length;
    timelineDate.textContent = "All time";
    timelineTotal.textContent = `${allDates[0]} – ${allDates[allDates.length - 1]}`;

    timelineSlider.addEventListener("input", (e) => {
      setTimelineIndex(parseInt(e.target.value, 10));
    });

    if (timelinePlay) {
      timelinePlay.addEventListener("click", () => {
        timelinePlaying = !timelinePlaying;
        timelinePlay.innerHTML = timelinePlaying ? "&#9646;&#9646;" : "&#9654;";
        if (timelinePlaying) {
          if (parseInt(timelineSlider.value, 10) >= allDates.length) {
            setTimelineIndex(0);
          }
          timelineTimer = setInterval(() => {
            let next = parseInt(timelineSlider.value, 10) + 1;
            if (next > allDates.length) {
              timelinePlaying = false;
              timelinePlay.innerHTML = "&#9654;";
              clearInterval(timelineTimer);
              return;
            }
            setTimelineIndex(next);
          }, 350);
        } else {
          clearInterval(timelineTimer);
        }
      });
    }
  }

  // ---- Shareable Permalink & Toast ----
  const shareBtn = root.querySelector("[data-kb-copy-link]");
  const toastEl = document.querySelector("[data-kb-toast]");
  function showToast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add("is-visible");
    setTimeout(() => toastEl.classList.remove("is-visible"), 2200);
  }
  if (shareBtn) {
    shareBtn.addEventListener("click", () => {
      const cam = camera.getState();
      const params = new URLSearchParams(window.location.search);
      params.set("depth", S.depth);
      params.set("x", (Math.round(cam.x * 1000) / 1000).toFixed(3));
      params.set("y", (Math.round(cam.y * 1000) / 1000).toFixed(3));
      params.set("r", (Math.round(cam.ratio * 1000) / 1000).toFixed(3));
      if (timelineCutoff) params.set("until", timelineCutoff);
      const permalink = `${window.location.origin}${window.location.pathname}?${params.toString()}${selected ? "#" + selected : ""}`;
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(permalink).then(() => showToast("Shareable link copied to clipboard!"));
      } else {
        showToast("Link created in address bar!");
      }
      history.replaceState(null, "", permalink);
    });
  }

  // ---- Export --------------------------------------------------------------
  function downloadBlob(blob, filename) {
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  }
  // toBlob() on a canvas just drawImage()'d from a WebGL source (Sigma's own
  // layers) can hand back null on its very first call in the same tick — a
  // GPU-readback timing quirk, not a real failure — and reliably succeeds a
  // frame later. One retry covers it without a user-visible delay.
  function toBlobRetry(canvasEl, cb, attemptsLeft = 2) {
    canvasEl.toBlob((blob) => {
      if (blob || attemptsLeft <= 1) { cb(blob); return; }
      requestAnimationFrame(() => toBlobRetry(canvasEl, cb, attemptsLeft - 1));
    });
  }
  const exportPngBtn = root.querySelector('[data-kb-export-png]');
  if (exportPngBtn) {
    exportPngBtn.addEventListener('click', () => {
      // Sigma layers several <canvas> elements (edges, nodes, labels, hover);
      // a single flat PNG needs them composited in DOM order onto one canvas.
      const layers = [...canvas.querySelectorAll('canvas')];
      if (!layers.length) return;
      const out = document.createElement('canvas');
      out.width = layers[0].width;
      out.height = layers[0].height;
      const ctx = out.getContext('2d');
      ctx.fillStyle = dark ? '#0b0f17' : '#fafaf9';
      ctx.fillRect(0, 0, out.width, out.height);
      for (const layer of layers) ctx.drawImage(layer, 0, 0, out.width, out.height);
      toBlobRetry(out, (blob) => {
        if (blob) downloadBlob(blob, `knowledge-graph-${selected ? byId.get(selected).id.slice(7) : 'overview'}.png`);
      });
    });
  }
  const exportJsonBtn = root.querySelector('[data-kb-export-json]');
  if (exportJsonBtn) {
    exportJsonBtn.addEventListener('click', () => {
      const nodes = g.filterNodes((n) => nodeVisible(n)).map((n) => {
        const a = g.getNodeAttributes(n);
        const meta = byId.get(n);
        return { id: n, label: meta.label, type: meta.type, x: a.x, y: a.y };
      });
      const edges = g.filterEdges((e) => edgeVisible(e)).map((e) => {
        const a = g.getEdgeAttributes(e);
        const [s, t] = g.extremities(e);
        return { source: s, target: t, relation: a.rel, confidence: a.confidence ?? null, tier: a.tier ?? null };
      });
      downloadBlob(new Blob([JSON.stringify({ nodes, edges }, null, 2)], { type: 'application/json' }),
        `knowledge-graph-${selected ? byId.get(selected).id.slice(7) : 'view'}.json`);
    });
  }

  if (panel) {
    // Open by default where there is room for it; a phone starts with the canvas.
    let openState = null;
    try { openState = localStorage.getItem(`${STORE_KEY}:panel`); } catch (err) { /* ignore */ }
    panel.open = openState != null ? openState === 'open' && stage.clientWidth >= 640 : stage.clientWidth >= 900;
    panel.addEventListener('toggle', () => {
      try { localStorage.setItem(`${STORE_KEY}:panel`, panel.open ? 'open' : 'closed'); } catch (err) { /* ignore */ }
    });
  }

  // Collapsed by default — a reader opens on the graph, not a wall of text
  // under it — but remembers an explicit choice to keep it open, the same
  // way the settings panel above does.
  if (bottomPanel) {
    let bottomOpen = null;
    try { bottomOpen = localStorage.getItem(`${STORE_KEY}:bottom`); } catch (err) { /* ignore */ }
    bottomPanel.open = bottomOpen === 'open';
    bottomPanel.addEventListener('toggle', () => {
      try { localStorage.setItem(`${STORE_KEY}:bottom`, bottomPanel.open ? 'open' : 'closed'); } catch (err) { /* ignore */ }
    });
  }

  const onboarding = root.querySelector('[data-kb-onboarding]');
  if (onboarding) {
    const ONBOARD_KEY = `${STORE_KEY}:onboarded`;
    let seen = false;
    try { seen = localStorage.getItem(ONBOARD_KEY) === '1'; } catch (err) { /* ignore */ }
    const dismissOnboarding = () => {
      onboarding.hidden = true;
      try { localStorage.setItem(ONBOARD_KEY, '1'); } catch (err) { /* ignore */ }
    };
    if (!seen) {
      onboarding.hidden = false;
      setTimeout(dismissOnboarding, 14000);
    }
    const dismissBtn = onboarding.querySelector('[data-kb-onboarding-dismiss]');
    if (dismissBtn) dismissBtn.addEventListener('click', dismissOnboarding);
  }

  // ---- Sigma events -------------------------------------------------------
  const eventPos = (event, node) => (event && Number.isFinite(event.x) ? { x: event.x, y: event.y }
    : node ? renderer.graphToViewport(g.getNodeAttributes(node)) : { x: 0, y: 0 });

  renderer.on('enterNode', ({ node, event }) => {
    if (dragged) return;
    hovered = node;
    hoverSet = new Set(neighbours(node).map((r) => r.id));
    canvas.style.cursor = 'pointer';
    renderer.refresh({ skipIndexation: true });
    showNodeCard(node, eventPos(event, node));
  });
  renderer.on('leaveNode', () => {
    hovered = null;
    hoverSet = new Set();
    canvas.style.cursor = '';
    hideCard();
    renderer.refresh({ skipIndexation: true });
  });
  renderer.on('enterEdge', ({ edge, event }) => {
    if (dragged || hovered) return;
    hoveredEdge = edge;
    canvas.style.cursor = 'pointer';
    renderer.refresh({ skipIndexation: true });
    showEdgeCard(edge, eventPos(event));
  });
  renderer.on('leaveEdge', () => {
    hoveredEdge = null;
    canvas.style.cursor = '';
    hideCard();
    renderer.refresh({ skipIndexation: true });
  });

  renderer.on('downNode', ({ node }) => {
    stopWorkerSim();
    dragged = node;
    dragMoved = false;
    g.setNodeAttribute(node, 'fixed', true);
  });
  renderer.on('moveBody', ({ event }) => {
    if (!dragged) return;
    if (!dragMoved) { dragMoved = true; hideCard(); simulate(600); }
    const p = renderer.viewportToGraph(event);
    g.mergeNodeAttributes(dragged, { x: p.x, y: p.y });
    event.preventSigmaDefault();
    if (event.original) { event.original.preventDefault(); event.original.stopPropagation(); }
  });
  const endDrag = () => {
    if (!dragged) return;
    g.removeNodeAttribute(dragged, 'fixed');
    if (dragMoved) { suppressClick = true; setTimeout(() => { suppressClick = false; }, 0); simulate(1500); }
    dragged = null;
    renderer.refresh({ skipIndexation: true });
  };
  renderer.on('upNode', endDrag);
  renderer.on('upStage', endDrag);

  // Shift-drag over empty canvas: a lasso, to pull a whole cluster into
  // focus at once instead of one entity at a time.
  let lassoing = false, lassoStart = null, lassoLast = null, lassoEl = null;
  function positionLasso() {
    if (!lassoEl) return;
    const left = Math.min(lassoStart.x, lassoLast.x), top = Math.min(lassoStart.y, lassoLast.y);
    lassoEl.style.left = `${left}px`;
    lassoEl.style.top = `${top}px`;
    lassoEl.style.width = `${Math.abs(lassoStart.x - lassoLast.x)}px`;
    lassoEl.style.height = `${Math.abs(lassoStart.y - lassoLast.y)}px`;
  }
  let lassoSticky = false; // touch has no shift key — a toggle button stands in for it
  const lassoToggleBtn = root.querySelector('[data-kb-lasso-toggle]');
  function setLassoSticky(on) {
    lassoSticky = on;
    if (lassoToggleBtn) lassoToggleBtn.setAttribute('aria-pressed', String(on));
  }
  if (lassoToggleBtn) lassoToggleBtn.addEventListener('click', () => setLassoSticky(!lassoSticky));
  renderer.on('downStage', ({ event }) => {
    if (!lassoSticky && !(event.original && event.original.shiftKey)) return;
    lassoing = true;
    lassoStart = { x: event.x, y: event.y };
    lassoLast = lassoStart;
    lassoEl = document.createElement('div');
    lassoEl.className = 'kb-lasso';
    stage.appendChild(lassoEl);
    positionLasso();
    event.preventSigmaDefault();
  });
  renderer.on('moveBody', ({ event }) => {
    if (!lassoing) return;
    lassoLast = { x: event.x, y: event.y };
    positionLasso();
    event.preventSigmaDefault();
    if (event.original) { event.original.preventDefault(); event.original.stopPropagation(); }
  });
  function endLasso() {
    if (!lassoing) return;
    lassoing = false;
    if (lassoSticky) setLassoSticky(false); // one shot, like a picked-up selection tool
    const left = Math.min(lassoStart.x, lassoLast.x), top = Math.min(lassoStart.y, lassoLast.y);
    const w = Math.abs(lassoStart.x - lassoLast.x), h = Math.abs(lassoStart.y - lassoLast.y);
    if (lassoEl) { lassoEl.remove(); lassoEl = null; }
    if (w < 6 || h < 6) return;
    // Same staleness as the minimap: force the transform current before
    // hit-testing, so a lasso drawn right after a camera move (rare, but
    // possible) matches where nodes actually sit on screen.
    renderer.refresh({ skipIndexation: true });
    const hit = [];
    g.forEachNode((n) => {
      if (!nodeVisible(n)) return;
      const p = renderer.graphToViewport(g.getNodeAttributes(n));
      if (p.x >= left && p.x <= left + w && p.y >= top && p.y <= top + h) hit.push(n);
    });
    if (hit.length < 2) return;
    suppressClick = true;
    setTimeout(() => { suppressClick = false; }, 0);
    showMultiSelect(hit);
  }
  renderer.on('upStage', endLasso);
  window.addEventListener('mouseup', endLasso);

  renderer.on('clickNode', ({ node, event }) => {
    if (suppressClick || dragMoved) { dragMoved = false; return; }
    const mod = event && event.original && (event.original.metaKey || event.original.ctrlKey);
    const shift = event && event.original && event.original.shiftKey;
    if (pathMode && (shift || mod)) { addWaypoint(node); return; }
    if (mod && selected && node !== selected) { showPath(selected, node); return; }
    if (node === selected && !selectedEdge) { frame([...focusDist.keys()]); return; }
    select(node);
  });
  renderer.on('doubleClickNode', ({ node, event }) => {
    event.preventSigmaDefault();
    const d = renderer.getNodeDisplayData(node);
    if (d) moveCamera({ x: d.x, y: d.y, ratio: Math.max(camera.getState().ratio / 2.2, RATIO_MIN) });
  });
  renderer.on('clickEdge', ({ edge }) => selectEdge(edge));
  renderer.on('clickStage', () => {
    if (suppressClick) return;
    if (selected || selectedEdge || multiSelected.size) clearSelection();
  });
  canvas.addEventListener('mousedown', () => stage.focus({ preventScroll: true }));

  // ---- Chrome: pin, nav, zoom, maximize, search, keys --------------------
  pinBox.addEventListener('click', (ev) => {
    if (ev.target.closest('[data-kb-pin-close]')) {
      if (pathMode) clearPath(); else clearSelection();
      stage.focus({ preventScroll: true });
      return;
    }
    const delWp = ev.target.closest('[data-kb-del-waypoint]');
    if (delWp) {
      const idx = parseInt(delWp.getAttribute('data-kb-del-waypoint'), 10);
      removeWaypoint(idx);
      return;
    }
    const walk = ev.target.closest('[data-kb-walk]');
    if (walk) {
      select(walk.dataset.kbWalk);
      const first = pinBox.querySelector('[data-kb-walk]');
      if (first) first.focus({ preventScroll: true });
    }
  });


  if (navBack) navBack.addEventListener('click', goBack);
  if (navForward) navForward.addEventListener('click', goForward);
  if (breadcrumbEl) {
    breadcrumbEl.addEventListener('click', (ev) => {
      const btn = ev.target.closest('[data-kb-jump]');
      if (btn) goTo(parseInt(btn.dataset.kbJump, 10));
    });
  }

  if (zoomBox) {
    zoomBox.addEventListener('click', (ev) => {
      const btn = ev.target.closest('[data-kb-zoom-action]');
      if (!btn) return;
      const cur = camera.getState();
      const action = btn.dataset.kbZoomAction;
      if (action === 'in') moveCamera({ ratio: cur.ratio * 0.65 }, 250);
      else if (action === 'out') moveCamera({ ratio: cur.ratio / 0.65 }, 250);
      else if (action === 'reset') fitAll();
    });
  }

  function toggleMaximize(force) {
    maximized = force != null ? force : !maximized;
    root.classList.toggle('is-maximized', maximized);
    if (expandBtn) {
      expandBtn.setAttribute('aria-pressed', String(maximized));
      const label = expandBtn.querySelector('span');
      if (label) label.textContent = maximized ? 'Exit' : 'Expand';
    }
    document.body.style.overflow = maximized ? 'hidden' : '';
    requestAnimationFrame(() => {
      try { renderer.resize(); } catch (err) { /* refresh below still resizes */ }
      renderer.refresh();
      if (!pinBox.hidden) pinBox.style.maxHeight = `${Math.max(140, stage.clientHeight - 16)}px`;
      if (selected) frame([...focusDist.entries()].filter(([, d]) => d <= 1).map(([n]) => n)); else fitAll();
    });
  }
  if (expandBtn) expandBtn.addEventListener('click', () => toggleMaximize());

  // ---- Enhanced Fuzzy Search with Match Highlighting ----
  function fuzzyMatch(text, query) {
    if (!text || !query) return { match: false, score: 99, highlight: esc(text || "") };
    const t = text.toLowerCase();
    const q = query.toLowerCase();
    if (t === q) return { match: true, score: 0, highlight: `<span class="kb-suggest-match">${esc(text)}</span>` };
    const exactIdx = t.indexOf(q);
    if (exactIdx !== -1) {
      const hl = esc(text.slice(0, exactIdx)) +
        `<span class="kb-suggest-match">${esc(text.slice(exactIdx, exactIdx + q.length))}</span>` +
        esc(text.slice(exactIdx + q.length));
      return { match: true, score: exactIdx === 0 ? 1 : 2, highlight: hl };
    }
    // Word boundary start match
    const words = t.split(/[\s/().-]+/);
    if (words.some((w) => w.startsWith(q))) {
      let hl = "";
      const wIdx = t.indexOf(q);
      if (wIdx !== -1) {
        hl = esc(text.slice(0, wIdx)) + `<span class="kb-suggest-match">${esc(text.slice(wIdx, wIdx + q.length))}</span>` + esc(text.slice(wIdx + q.length));
        return { match: true, score: 3, highlight: hl };
      }
    }
    // Subsequence match (e.g. spk -> Spark)
    let hl = "", tPos = 0;
    for (let i = 0; i < q.length; i++) {
      const ch = q[i];
      const found = t.indexOf(ch, tPos);
      if (found === -1) return { match: false, score: 99, highlight: esc(text) };
      hl += esc(text.slice(tPos, found)) + `<span class="kb-suggest-match">${esc(text[found])}</span>`;
      tPos = found + 1;
    }
    hl += esc(text.slice(tPos));
    const score = 4 + (tPos - q.length) * 0.1;
    return { match: true, score, highlight: hl };
  }

  // Search index over names, aliases, and descriptions
  const index = entities.map((n) => {
    const meta = byId.get(n.id);
    const desc = meta && meta.meta && meta.meta.description ? meta.meta.description : "";
    return {
      id: n.id, label: n.label, type: n.type, desc,
      terms: [n.label, ...(n.aliases || [])],
    };
  });
  let suggestions = [], active = -1, recentMode = false, currentQuery = "";
  const RECENT_KEY = `${STORE_KEY}:recent`;
  function loadRecent() {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY) || "[]").filter((id) => byId.has(id)); }
    catch (err) { return []; }
  }
  function pushRecent(id) {
    const recent = [id, ...loadRecent().filter((x) => x !== id)].slice(0, 8);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(recent)); } catch (err) { /* ignore */ }
  }
  function renderSuggest() {
    if (!suggestions.length) { suggestEl.hidden = true; searchInput.setAttribute("aria-expanded", "false"); return; }
    const heading = recentMode ? `<li class="kb-suggest-heading" aria-hidden="true">Recently viewed</li>` : "";
    suggestEl.innerHTML = heading + suggestions.map((s, i) =>
      `<li role="option" id="kb-sug-${i}" data-id="${esc(s.id)}" aria-selected="${i === active}">` +
      `<span class="kb-dot" style="background:${getTypeColor(s.type)}"></span>${s.highlight || esc(s.label)}` +
      `<small>${esc(TYPE_LABEL[s.type] || s.type)}</small></li>`).join("");
    suggestEl.hidden = false;
    searchInput.setAttribute("aria-expanded", "true");
    if (active >= 0) searchInput.setAttribute("aria-activedescendant", `kb-sug-${active}`);
    else searchInput.removeAttribute("aria-activedescendant");
  }
  function showRecent() {
    const recent = loadRecent().filter((id) => id !== selected);
    if (!recent.length) return;
    recentMode = true;
    currentQuery = "";
    suggestions = recent.map((id) => index.find((it) => it.id === id)).filter(Boolean)
      .map((it) => ({ ...it, highlight: esc(it.label) }));
    active = -1;
    renderSuggest();
  }
  function updateSuggest() {
    const q = searchInput.value.trim();
    active = -1;
    recentMode = false;
    currentQuery = q;
    if (!q) { showRecent(); return; }
    const results = [];
    for (const it of index) {
      let bestMatch = null;
      // Test main label and aliases
      for (const term of it.terms) {
        const m = fuzzyMatch(term, q);
        if (m.match && (!bestMatch || m.score < bestMatch.score)) {
          bestMatch = { ...m, highlight: m.highlight };
        }
      }
      // Test description as fallback
      if (!bestMatch && it.desc) {
        const m = fuzzyMatch(it.desc, q);
        if (m.match) bestMatch = { match: true, score: 8, highlight: `${esc(it.label)} <small style="opacity:0.7">(${m.highlight})</small>` };
      }
      if (bestMatch && bestMatch.score < 20) {
        results.push({ ...it, s: bestMatch.score, highlight: bestMatch.highlight });
      }
    }
    suggestions = results.sort((a, b) => a.s - b.s || (degree.get(b.id) || 0) - (degree.get(a.id) || 0)).slice(0, 8);
    active = suggestions.length ? 0 : -1;
    renderSuggest();
  }
  function pickSuggestion(i) {
    const s = suggestions[i];
    if (!s) return;
    searchInput.value = '';
    suggestions = [];
    renderSuggest();
    select(s.id);
  }
  if (searchInput && suggestEl) {
    searchInput.addEventListener('input', updateSuggest);
    searchInput.addEventListener('focus', () => { if (!searchInput.value.trim()) showRecent(); });
    searchInput.addEventListener('keydown', (ev) => {
      if (ev.key === 'ArrowDown' && suggestions.length) { active = (active + 1) % suggestions.length; renderSuggest(); ev.preventDefault(); }
      else if (ev.key === 'ArrowUp' && suggestions.length) { active = (active - 1 + suggestions.length) % suggestions.length; renderSuggest(); ev.preventDefault(); }
      else if (ev.key === 'Enter') { pickSuggestion(Math.max(active, 0)); ev.preventDefault(); }
      else if (ev.key === 'Escape') {
        if (suggestions.length) { suggestions = []; renderSuggest(); } else searchInput.blur();
        ev.preventDefault();
        ev.stopPropagation();
      }
    });
    // mousedown, not click: selecting must happen before the input's blur closes the list.
    suggestEl.addEventListener('mousedown', (ev) => {
      const li = ev.target.closest('[data-id]');
      if (!li) return;
      ev.preventDefault();
      pickSuggestion(suggestions.findIndex((s) => s.id === li.dataset.id));
    });
    searchInput.addEventListener('blur', () => setTimeout(() => { suggestions = []; renderSuggest(); }, 100));
  }

  document.addEventListener('keydown', (ev) => {
    const tag = document.activeElement && document.activeElement.tagName;
    const typing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(tag) && document.activeElement.type !== 'checkbox'
      && document.activeElement.type !== 'range';
    const inGraph = maximized || root.contains(document.activeElement);
    if (ev.key === 'Escape') {
      if (typing) return;
      if (pathMode) { clearPath(); return; }
      if (selected || selectedEdge) { clearSelection(); return; }
      if (maximized) toggleMaximize(false);
      return;
    }
    if (typing) return;
    if (ev.key === '/' && !ev.metaKey && !ev.ctrlKey && searchInput) {
      ev.preventDefault();
      searchInput.focus();
      return;
    }
    if (!inGraph) return;
    if (ev.altKey && ev.key === 'ArrowLeft') { ev.preventDefault(); goBack(); return; }
    if (ev.altKey && ev.key === 'ArrowRight') { ev.preventDefault(); goForward(); return; }
    if ((ev.key === 'f' || ev.key === 'F') && !ev.metaKey && !ev.ctrlKey && !ev.altKey) { fitAll(); return; }
    if ((ev.key === 'ArrowDown' || ev.key === 'ArrowUp') && !pinBox.hidden) {
      const rows = [...pinBox.querySelectorAll('[data-kb-walk]')];
      if (!rows.length) return;
      ev.preventDefault();
      const i = rows.indexOf(document.activeElement);
      const next = ev.key === 'ArrowDown' ? (i + 1) % rows.length : (i <= 0 ? rows.length - 1 : i - 1);
      rows[next].focus();
    }
  });

  new MutationObserver(() => {
    dark = document.documentElement.getAttribute('data-theme') !== 'light';
    P = palette();
    renderer.setSetting('labelColor', { color: P.label });
    renderer.setSetting('edgeLabelColor', { color: P.label });
    renderer.refresh({ skipIndexation: true });
    drawMinimap();
  }).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });

  const fromLocation = () => {
    const hash = decodeURIComponent(window.location.hash.slice(1));
    const q = new URLSearchParams(window.location.search).get('entity');
    const raw = hash || q;
    if (!raw) return null;
    const id = raw.startsWith('entity:') ? raw : `entity:${raw}`;
    return g.hasNode(id) ? id : null;
  };
  window.addEventListener('hashchange', () => {
    const id = fromLocation();
    if (id && id !== selected) select(id);
  });

  // A shared link should reproduce what was on screen, not just the centre:
  // read every filter the URL carries before the first paint.
  function applyUrlOverrides() {
    const q = new URLSearchParams(window.location.search);
    if (q.has('depth')) S.depth = clamp(parseInt(q.get('depth'), 10) || S.depth, 1, 3);
    if (q.get('orphans') === '0') S.orphans = false;
    if (q.get('cmp') === '0') S.comparisons = false;
    if (q.has('hideRel')) q.get('hideRel').split(',').forEach((r) => setRel(r, false));
    if (q.has('hideType')) {
      q.get('hideType').split(',').forEach((t) => {
        if (!ENTITY_ORDER.includes(t)) return;
        hiddenTypes.add(t);
        const box = groupsEl.querySelector(`[data-kb-type="${t}"]`);
        if (box) box.checked = false;
      });
      S.hiddenTypes = [...hiddenTypes];
    }
    if (q.has("x") && q.has("y") && q.has("r")) {
      const cx = parseFloat(q.get("x")), cy = parseFloat(q.get("y")), cr = parseFloat(q.get("r"));
      if ([cx, cy, cr].every(Number.isFinite)) {
        setTimeout(() => camera.setState({ x: cx, y: cy, ratio: clamp(cr, RATIO_MIN, RATIO_MAX) }), 80);
      }
    }
    if (q.has("until") && allDates.includes(q.get("until"))) {
      const idx = allDates.indexOf(q.get("until"));
      if (idx !== -1) setTimeout(() => setTimelineIndex(idx), 100);
    }
    syncInputs();
    if (!S.comparisons) setRel('COMPARES_TO', false);
  }
  applyUrlOverrides();
  allowedRels = new Set([...relsEl.querySelectorAll('input:checked:not([data-kb-group])')].map((i) => i.value));
  computeVisDeg();
  renderMeta();
  renderCentre();
  renderNav();
  const initial = fromLocation();
  if (initial) {
    select(initial);
  } else {
    let restored = false;
    try {
      const saved = JSON.parse(localStorage.getItem(CAMERA_STORE_KEY) || 'null');
      if (saved && [saved.x, saved.y, saved.ratio].every(Number.isFinite)) {
        camera.setState({ ...saved, ratio: clamp(saved.ratio, RATIO_MIN, RATIO_MAX) });
        restored = true;
      }
    } catch (err) { /* ignore */ }
    if (!restored) fitAll();
  }
  // ---- Diff Banner ----
  if (data.diff_summary) {
    const banner = root.querySelector('[data-kb-diff-banner]');
    if (banner) {
      banner.hidden = false;
      const addEl = banner.querySelector('[data-kb-diff-added]');
      const remEl = banner.querySelector('[data-kb-diff-removed]');
      const chgEl = banner.querySelector('[data-kb-diff-changed]');
      if (addEl) addEl.textContent = `+${data.diff_summary.nodes_added} added`;
      if (remEl) remEl.textContent = `-${data.diff_summary.nodes_removed} removed`;
      if (chgEl) chgEl.textContent = `~${data.diff_summary.nodes_changed} changed`;
    }
  }

  // ---- Community Detection Toggle ----
  const clustersBtn = root.querySelector('[data-kb-clusters-btn]');
  if (clustersBtn) {
    clustersBtn.addEventListener('click', () => {
      communityMode = !communityMode;
      clustersBtn.classList.toggle('is-active', communityMode);
      if (communityMode && communityMap.size === 0) {
        const part = computeCommunitiesFallback(g);
        communityMap = new Map(Object.entries(part));
        const numClusters = new Set(communityMap.values()).size;
        showToast(`Identified ${numClusters} topical clusters`);
      }
      renderer.refresh();
    });
  }

  // ---- Centrality & Hub Insights Modal ----
  const insightsBtn = root.querySelector('[data-kb-insights-btn]');
  const insightsModal = document.querySelector('[data-kb-insights-modal]');
  const insightsClose = document.querySelector('[data-kb-insights-close]');
  if (insightsBtn && insightsModal) {
    insightsBtn.addEventListener('click', () => {
      const { degree: dList, pagerank: prList, betweenness: bwList } = computeCentrality();
      const degContainer = insightsModal.querySelector('[data-kb-hubs-degree]');
      const prContainer = insightsModal.querySelector('[data-kb-hubs-pagerank]');
      const bwContainer = insightsModal.querySelector('[data-kb-hubs-betweenness]');

      function renderList(items, container, fmt) {
        if (!container) return;
        container.innerHTML = items.map(it => `
          <div class="kb-insight-item" data-kb-insight-jump="${it.id}">
            <span class="kb-insight-label">${esc(it.label)}</span>
            <span class="kb-insight-score">${fmt(it.score)}</span>
          </div>
        `).join('');
      }

      renderList(dList, degContainer, s => `${s} edges`);
      renderList(prList, prContainer, s => (s * 100).toFixed(2));
      renderList(bwList, bwContainer, s => s.toString());
      insightsModal.hidden = false;
    });
  }
  if (insightsClose && insightsModal) {
    insightsClose.addEventListener('click', () => { insightsModal.hidden = true; });
    insightsModal.addEventListener('click', (e) => {
      if (e.target === insightsModal) insightsModal.hidden = true;
    });
  }
  document.addEventListener('click', (e) => {
    const jumpBtn = e.target.closest('[data-kb-insight-jump]');
    if (jumpBtn) {
      const nid = jumpBtn.getAttribute('data-kb-insight-jump');
      if (insightsModal) insightsModal.hidden = true;
      select(nid);
    }
  });

  // ---- Layout Mode Switcher ----
  const layoutSelect = root.querySelector('[data-kb-layout-select]');
  if (layoutSelect) {
    layoutSelect.addEventListener('change', (e) => {
      switchLayout(e.target.value);
    });
  }

  // ---- Flow Particles Animation Loop ----
  const particlesCanvas = root.querySelector('[data-kb-particles]');
  let particleOffset = 0;
  function renderParticles() {
    if (particlesCanvas && stage) {
      if (particlesCanvas.width !== stage.clientWidth || particlesCanvas.height !== stage.clientHeight) {
        particlesCanvas.width = stage.clientWidth;
        particlesCanvas.height = stage.clientHeight;
      }
      const ctx = particlesCanvas.getContext('2d');
      ctx.clearRect(0, 0, particlesCanvas.width, particlesCanvas.height);

      let activeEdges = [];
      if (pathMode && pathEdgeSet && pathEdgeSet.size) {
        activeEdges = [...pathEdgeSet];
      } else if (selected) {
        activeEdges = g.edges(selected).filter(e => edgeVisible(e));
      }

      if (activeEdges.length > 0 && activeEdges.length <= 40) {
        particleOffset = (particleOffset + 0.014) % 1;
        ctx.fillStyle = dark ? '#38bdf8' : '#0284c7';
        ctx.shadowColor = dark ? '#38bdf8' : '#0284c7';
        ctx.shadowBlur = 5;

        for (const e of activeEdges) {
          const [s, t] = g.extremities(e);
          if (!nodeVisible(s) || !nodeVisible(t)) continue;
          const sa = g.getNodeAttributes(s);
          const ta = g.getNodeAttributes(t);
          const sp = renderer.graphToViewport(sa);
          const tp = renderer.graphToViewport(ta);

          const px = sp.x + (tp.x - sp.x) * particleOffset;
          const py = sp.y + (tp.y - sp.y) * particleOffset;

          ctx.beginPath();
          ctx.arc(px, py, 2.8, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
    requestAnimationFrame(renderParticles);
  }
  requestAnimationFrame(renderParticles);

  drawMinimap();

}

if (typeof window !== 'undefined') {
  document.addEventListener('DOMContentLoaded', () => {
    initKbGraph(document.querySelector('[data-kb-graph]'));
  });
}
