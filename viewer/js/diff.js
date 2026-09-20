/**
 * Interactive Visual Graph Diff Module.
 * Computes and renders differences between graph revisions directly in the browser.
 * Zero external dependencies. Strict mode.
 */
'use strict';

/**
 * Normalises an edge into a canonical identity key.
 * @param {Object} e
 * @returns {string}
 */
export function edgeKey(e) {
  return `${e.src || ''}|${e.rel || ''}|${e.dst || ''}|${e.scope || ''}`;
}

/**
 * Strips transient layout/degree properties to compare semantic content.
 * @param {Object} n
 * @returns {Object}
 */
export function nodeContentSignature(n) {
  if (!n) return {};
  const copy = { ...n };
  delete copy.degree;
  delete copy.x;
  delete copy.y;
  delete copy.z;
  delete copy.vx;
  delete copy.vy;
  delete copy.vz;
  delete copy.diff;
  return copy;
}

/**
 * Computes node and edge diff between oldGraph and newGraph.
 * @param {Object} oldGraph
 * @param {Object} newGraph
 * @returns {Object} { nodes: Array, edges: Array, diff_summary: Object }
 */
export function computeGraphDiff(oldGraph, newGraph) {
  const oldNodes = new Map((oldGraph && oldGraph.nodes ? oldGraph.nodes : []).map(n => [n.id, n]));
  const newNodes = new Map((newGraph && newGraph.nodes ? newGraph.nodes : []).map(n => [n.id, n]));

  const nodes = [];
  let addedCount = 0;
  let removedCount = 0;
  let changedCount = 0;

  // Process all new nodes
  for (const [id, newNode] of newNodes.entries()) {
    const nd = { ...newNode };
    if (!oldNodes.has(id)) {
      nd.diff = 'added';
      addedCount++;
    } else {
      const oldNode = oldNodes.get(id);
      const oldSig = JSON.stringify(nodeContentSignature(oldNode));
      const newSig = JSON.stringify(nodeContentSignature(newNode));
      if (oldSig !== newSig) {
        nd.diff = 'changed';
        nd._oldNode = oldNode;
        changedCount++;
      } else {
        nd.diff = 'same';
      }
    }
    nodes.push(nd);
  }

  // Process removed nodes from oldGraph
  for (const [id, oldNode] of oldNodes.entries()) {
    if (!newNodes.has(id)) {
      const nd = { ...oldNode, diff: 'removed' };
      nodes.push(nd);
      removedCount++;
    }
  }

  // Edge comparison
  const oldEdges = new Map((oldGraph && oldGraph.edges ? oldGraph.edges : []).map(e => [edgeKey(e), e]));
  const newEdges = new Map((newGraph && newGraph.edges ? newGraph.edges : []).map(e => [edgeKey(e), e]));

  const edges = [];
  let edgesAdded = 0;
  let edgesRemoved = 0;

  for (const [k, newEdge] of newEdges.entries()) {
    const ed = { ...newEdge };
    if (!oldEdges.has(k)) {
      ed.diff = 'added';
      edgesAdded++;
    } else {
      ed.diff = 'same';
    }
    edges.push(ed);
  }

  for (const [k, oldEdge] of oldEdges.entries()) {
    if (!newEdges.has(k)) {
      const ed = { ...oldEdge, diff: 'removed' };
      edges.push(ed);
      edgesRemoved++;
    }
  }

  return {
    nodes,
    edges,
    diff_summary: {
      nodes_added: addedCount,
      nodes_removed: removedCount,
      nodes_changed: changedCount,
      edges_added: edgesAdded,
      edges_removed: edgesRemoved,
    }
  };
}

/**
 * Filter nodes and edges by visual diff filter mode.
 * @param {Array} nodes
 * @param {Array} edges
 * @param {string} mode 'all' | 'added' | 'removed' | 'changed'
 * @returns {Object} { nodes: Array, edges: Array }
 */
export function applyDiffFilter(nodes, edges, mode) {
  if (!mode || mode === 'all') {
    return { nodes, edges };
  }

  let nodeFilterFn;
  if (mode === 'added') {
    nodeFilterFn = n => n.diff === 'added';
  } else if (mode === 'removed') {
    nodeFilterFn = n => n.diff === 'removed';
  } else if (mode === 'changed') {
    nodeFilterFn = n => n.diff === 'changed' || n.diff === 'added' || n.diff === 'removed';
  } else {
    return { nodes, edges };
  }

  const filteredNodes = nodes.filter(nodeFilterFn);
  const activeIds = new Set(filteredNodes.map(n => n.id));
  const filteredEdges = edges.filter(e => activeIds.has(e.src) && activeIds.has(e.dst));

  return { nodes: filteredNodes, edges: filteredEdges };
}

/**
 * Formats side-by-side attribute differences for the node inspector drawer.
 * @param {Object} oldNode
 * @param {Object} newNode
 * @returns {string} HTML snippet
 */
export function renderNodeAttributeDiff(oldNode, newNode) {
  if (!newNode && !oldNode) return '';
  if (!oldNode) {
    return `<div class="kb-diff-attribute added"><strong>Added Node</strong>: ${escapeHtml(newNode.label || newNode.id)}</div>`;
  }
  if (!newNode) {
    return `<div class="kb-diff-attribute removed"><strong>Removed Node</strong>: ${escapeHtml(oldNode.label || oldNode.id)}</div>`;
  }

  const fields = ['label', 'type', 'description', 'url'];
  const changes = [];

  for (const f of fields) {
    const oldVal = oldNode[f] || '';
    const newVal = newNode[f] || '';
    if (oldVal !== newVal) {
      changes.push(`
        <div class="kb-diff-field">
          <span class="kb-diff-field-name">${escapeHtml(f)}</span>:
          <span class="kb-diff-old"><del>${escapeHtml(String(oldVal)) || '(empty)'}</del></span> &rarr;
          <span class="kb-diff-new"><ins>${escapeHtml(String(newVal)) || '(empty)'}</ins></span>
        </div>
      `);
    }
  }

  // Tags diff
  const oldTags = new Set(oldNode.tags || []);
  const newTags = new Set(newNode.tags || []);
  const addedTags = [...newTags].filter(t => !oldTags.has(t));
  const removedTags = [...oldTags].filter(t => !newTags.has(t));
  if (addedTags.length || removedTags.length) {
    changes.push(`
      <div class="kb-diff-field">
        <span class="kb-diff-field-name">tags</span>:
        ${removedTags.map(t => `<span class="kb-diff-tag removed"><del>-${escapeHtml(t)}</del></span>`).join(' ')}
        ${addedTags.map(t => `<span class="kb-diff-tag added"><ins>+${escapeHtml(t)}</ins></span>`).join(' ')}
      </div>
    `);
  }

  return changes.length ? changes.join('') : '<div class="kb-diff-none">No attribute modifications</div>';
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
