// Evidence context aggregation and HTML card/pin formatting.
import { CITE_CAP, TYPE_LABEL, getTypeColor } from './constants.js';
import { esc, relText, fmtDate, capitalise } from './utils.js';

export function buildContext(data, byId, entityTypes) {
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

export function tierChip(tier) {
  return tier && tier !== 'deterministic'
    ? `<b class="kb-tier kb-tier-${esc(tier)}" title="${esc(TIER_TITLE[tier] || tier)}">${esc(tier)}</b>` : '';
}

export function contextHtml(ctx, { articleCap = CITE_CAP, compact = false } = {}) {
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

export function linksHtml(n) {
  const refs = n.urls || {};
  const links = [];
  if (refs.wikipedia) links.push(`<a href="${esc(refs.wikipedia)}" target="_blank" rel="noopener">Wikipedia &nearr;</a>`);
  if (refs.canonical) links.push(`<a href="${esc(refs.canonical)}" target="_blank" rel="noopener">Website &nearr;</a>`);
  return links.join(' ');
}

export function walkRow(r, byId) {
  const n = byId.get(r.id) || { label: r.id, type: 'Technology' };
  return `<button type="button" class="kb-walk" data-kb-walk="${esc(r.id)}">` +
    `<span class="kb-dot" style="background:${getTypeColor(n.type)}"></span>` +
    `<span class="kb-walk-name">${esc(n.label)}</span>` +
    (r.scope ? `<i class="kb-walk-scope">${esc(r.scope)}</i>` : '') + tierChip(r.tier) + `</button>`;
}

export function nodePinHtml(node, byId, neighboursList, context, degreeMap) {
  const n = byId.get(node) || { id: node, label: node, type: 'Technology' };
  const rows = neighboursList;
  const byRel = new Map();
  for (const r of rows) {
    if (!byRel.has(r.rel)) byRel.set(r.rel, []);
    byRel.get(r.rel).push(r);
  }
  const relSections = [...byRel.entries()]
    .sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
    .map(([rel, rs]) =>
      `<div class="kb-walk-group"><span class="kb-cites-label">${esc(relText(rel))} <span class="kb-walk-n">${rs.length}</span></span>` +
      rs.sort((a, b) => ((degreeMap && degreeMap.get(b.id)) || 0) - ((degreeMap && degreeMap.get(a.id)) || 0))
        .map(r => walkRow(r, byId)).join('') + `</div>`)
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

export function sourceHtml(a, byId) {
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

export function edgePinHtml(edge, graph, byId) {
  const a = graph.getEdgeAttributes(edge);
  const [s, t] = graph.extremities(edge);
  const end = (id) => walkRow({ id }, byId);
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
    sourceHtml(a, byId)
  );
}

export function pathHtml(result, byId, pathWaypoints, graph) {
  const { chain, waypoints } = result;
  const waypointChips = (waypoints || pathWaypoints || []).map((w, idx) => {
    const label = esc((byId.get(w) || {}).label || w);
    return `<span class="kb-waypoint-chip">${label} <button type="button" class="kb-waypoint-del" data-kb-del-waypoint="${idx}" aria-label="Remove waypoint">&times;</button></span>`;
  }).join(' &rarr; ');

  const rows = chain.map((id, i) => {
    let rel = null;
    if (i > 0 && graph) {
      graph.forEachEdge(chain[i - 1], (e, a, s, t) => {
        if (!rel && ((s === chain[i - 1] && t === id) || (s === id && t === chain[i - 1]))) rel = a.rel;
      });
    }
    const hop = rel ? `<div class="kb-edge-rel">${esc(relText(rel))} &darr;</div>` : '';
    return hop + walkRow({ id }, byId);
  }).join('');

  return (
    `<button type="button" class="kb-pin-close" data-kb-pin-close aria-label="Close">&times;</button>` +
    `<span class="kb-card-type" style="--c:var(--accent-primary)">Multi-hop Path (${result.hopCount} hops)</span>` +
    `<div class="kb-waypoints-bar">${waypointChips}</div>` +
    `<div class="kb-walks" role="group" aria-label="Path step-by-step">${rows}</div>`
  );
}
