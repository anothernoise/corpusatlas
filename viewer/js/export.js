// Subgraph and diagram export: PNG, SVG, Gephi GEXF, and GraphML XML.
import { esc } from './utils.js';

function downloadFile(content, filename, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/**
 * Export visible viewport canvas as high-resolution PNG.
 */
export function exportPng(canvas, filename = 'corpusatlas-graph.png') {
  if (!canvas) return;
  const url = canvas.toDataURL('image/png');
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

/**
 * Export visible graph as scalable vector graphics (SVG).
 */
export function exportSvg(graph, renderer, isNodeVisible, isEdgeVisible, filename = 'corpusatlas-graph.svg') {
  if (!graph || !renderer) return;
  const nodes = [];
  const edges = [];

  graph.forEachNode((n) => {
    if (isNodeVisible && !isNodeVisible(n)) return;
    const d = renderer.getNodeDisplayData(n);
    if (!d || !Number.isFinite(d.x) || !Number.isFinite(d.y)) return;
    nodes.push(d);
  });

  graph.forEachEdge((e, a, s, t) => {
    if (isEdgeVisible && !isEdgeVisible(e)) return;
    if (isNodeVisible && (!isNodeVisible(s) || !isNodeVisible(t))) return;
    const sd = renderer.getNodeDisplayData(s);
    const td = renderer.getNodeDisplayData(t);
    if (!sd || !td) return;
    edges.push({ s: sd, t: td, rel: a.rel || '', color: a.color || '#94a3b8' });
  });

  const width = renderer.width || 1200;
  const height = renderer.height || 800;

  const svgParts = [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}">`,
    `<rect width="100%" height="100%" fill="#0f172a"/>`,
    '<g id="edges">',
  ];

  for (const e of edges) {
    svgParts.push(
      `<line x1="${e.s.x.toFixed(1)}" y1="${e.s.y.toFixed(1)}" x2="${e.t.x.toFixed(1)}" y2="${e.t.y.toFixed(1)}" stroke="${e.color}" stroke-opacity="0.35" stroke-width="1"/>`
    );
  }

  svgParts.push('</g><g id="nodes">');

  for (const n of nodes) {
    const r = Math.max(2, (n.size || 4)).toFixed(1);
    svgParts.push(
      `<circle cx="${n.x.toFixed(1)}" cy="${n.y.toFixed(1)}" r="${r}" fill="${n.color || '#38bdf8'}"/>`
    );
    if (n.label) {
      svgParts.push(
        `<text x="${(n.x + parseFloat(r) + 3).toFixed(1)}" y="${(n.y + 3).toFixed(1)}" fill="#e2e8f0" font-family="sans-serif" font-size="10">${esc(n.label)}</text>`
      );
    }
  }

  svgParts.push('</g></svg>');
  downloadFile(svgParts.join('\n'), filename, 'image/svg+xml');
}

/**
 * Export graph to standard Gephi GEXF format.
 */
export function exportGexf(graph, byId = new Map(), filename = 'corpusatlas-graph.gexf') {
  if (!graph) return;
  const out = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<gexf xmlns="http://www.gexf.net/1.2draft" version="1.2">',
    '  <graph mode="static" defaultedgetype="directed">',
    '    <nodes>',
  ];

  graph.forEachNode((n) => {
    const meta = (byId.get(n) || {});
    const label = esc(meta.label || n);
    out.push(`      <node id="${esc(n)}" label="${label}"/>`);
  });

  out.push('    </nodes>', '    <edges>');

  let idx = 0;
  graph.forEachEdge((e, a, s, t) => {
    out.push(`      <edge id="e_${idx++}" source="${esc(s)}" target="${esc(t)}" label="${esc(a.rel || '')}" weight="${a.weight || 1}"/>`);
  });

  out.push('    </edges>', '  </graph>', '</gexf>');
  downloadFile(out.join('\n'), filename, 'application/xml');
}

/**
 * Export graph to standard GraphML XML format.
 */
export function exportGraphml(graph, byId = new Map(), filename = 'corpusatlas-graph.graphml') {
  if (!graph) return;
  const out = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
    '  <key id="d_label" for="node" attr.name="label" attr.type="string"/>',
    '  <key id="d_type" for="node" attr.name="type" attr.type="string"/>',
    '  <key id="d_rel" for="edge" attr.name="relation" attr.type="string"/>',
    '  <graph id="G" edgedefault="directed">',
  ];

  graph.forEachNode((n) => {
    const meta = (byId.get(n) || {});
    const label = esc(meta.label || n);
    const type = esc(meta.type || 'Technology');
    out.push(`    <node id="${esc(n)}"><data key="d_label">${label}</data><data key="d_type">${type}</data></node>`);
  });

  let idx = 0;
  graph.forEachEdge((e, a, s, t) => {
    out.push(`    <edge id="e_${idx++}" source="${esc(s)}" target="${esc(t)}"><data key="d_rel">${esc(a.rel || '')}</data></edge>`);
  });

  out.push('  </graph>', '</graphml>');
  downloadFile(out.join('\n'), filename, 'application/xml');
}
