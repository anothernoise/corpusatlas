// Graph layouts: ForceAtlas2 settings, hierarchical DAG, radial radar, and layout transitions.

/**
 * Compute ForceAtlas2 simulation settings with Barnes-Hut optimization.
 */
export function fa2Settings(graph, S) {
  const order = (graph && graph.order) || 1;
  return {
    gravity: S.center,
    scalingRatio: S.repel,
    strongGravityMode: order < 300,
    barnesHutOptimize: true,
    barnesHutTheta: 0.8,
    slowDown: 1 + Math.log(order),
    edgeWeightInfluence: 1,
  };
}

/**
 * Precompute coordinate tables for instant layout switching.
 */
export function computeLayoutPositions(graph, byId, context) {
  const positions = {
    force: new Map(),
    dag: new Map(),
    radar: new Map(),
    circular: new Map(),
  };

  // 1. Force snapshot
  graph.forEachNode((n, a) => {
    positions.force.set(n, { x: a.x, y: a.y });
  });

  // 2. DAG (Hierarchical) Layout
  const depths = new Map();
  graph.forEachNode(n => {
    if (graph.inDegree(n) === 0) depths.set(n, 0);
  });
  if (depths.size === 0) {
    graph.forEachNode((n, i) => { if (i % 5 === 0) depths.set(n, 0); });
  }
  const queue = [...depths.keys()];
  let head = 0;
  while (head < queue.length) {
    const u = queue[head++];
    const d = depths.get(u);
    if (d >= 8) continue;
    graph.forEachEdge(u, (e, a, s, t) => {
      if (s !== u) return;
      if (!depths.has(t)) {
        depths.set(t, d + 1);
        queue.push(t);
      }
    });
  }
  graph.forEachNode(n => { if (!depths.has(n)) depths.set(n, 0); });

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
      positions.dag.set(n, { x, y });
    });
  });

  // 3. Radar Layout
  const R_MAX = 700;
  const quadrantAngles = {
    'techniques': Math.PI / 4,
    'tools': 3 * Math.PI / 4,
    'platforms': 5 * Math.PI / 4,
    'languages-and-frameworks': 7 * Math.PI / 4,
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

  graph.forEachNode((n, idx) => {
    const meta = (byId.get(n) || {}).meta || {};
    const ctxRadar = (context && context.get(n)?.radar || [])[0] || {};
    const q = (meta.quadrant || ctxRadar.quadrant || '').toLowerCase();
    const r = (meta.ring || ctxRadar.ring || '').toLowerCase();
    const baseAngle = quadrantAngles[q] !== undefined ? quadrantAngles[q] : ((idx % 4) * Math.PI / 2 + Math.PI / 4);
    const baseRadius = ringRadii[r] !== undefined ? ringRadii[r] : (0.5 * R_MAX);

    let hash = 0;
    for (let c = 0; c < n.length; c++) hash = (hash * 31 + n.charCodeAt(c)) & 0xffffffff;
    const jitterAngle = ((hash % 100) / 100 - 0.5) * (Math.PI / 3);
    const jitterR = (((hash >> 4) % 100) / 100 - 0.5) * 80;

    const angle = baseAngle + jitterAngle;
    const radius = Math.max(40, baseRadius + jitterR);
    positions.radar.set(n, {
      x: Math.round(radius * Math.cos(angle)),
      y: Math.round(radius * Math.sin(angle))
    });
  });

  // 4. Circular Layout
  const order = graph.order || 1;
  const circRadius = Math.max(200, Math.min(1200, order * 4));
  let nodeIdx = 0;
  graph.forEachNode(n => {
    const angle = (nodeIdx / order) * Math.PI * 2;
    positions.circular.set(n, {
      x: Math.round(circRadius * Math.cos(angle)),
      y: Math.round(circRadius * Math.sin(angle))
    });
    nodeIdx++;
  });

  // 5. Semantic Space (Vector Embeddings)
  positions.semantic = new Map();
  graph.forEachNode((n) => {
    const meta = (byId.get(n) || {}).meta || {};
    if (meta.semantic_x != null && meta.semantic_y != null) {
      positions.semantic.set(n, { x: Number(meta.semantic_x), y: Number(meta.semantic_y) });
    } else {
      let hash = 0;
      for (let i = 0; i < n.length; i++) hash = (hash << 5) - hash + n.charCodeAt(i);
      const angle = (Math.abs(hash) % 360) * (Math.PI / 180);
      const rad = 140 + (Math.abs(hash >> 3) % 360);
      positions.semantic.set(n, {
        x: Math.round(rad * Math.cos(angle)),
        y: Math.round(rad * Math.sin(angle))
      });
    }
  });

  return positions;
}

/**
 * Animated layout tween transitions.
 */
export function switchLayout(graph, renderer, targetMode, layoutPositions, onDone) {
  if (!layoutPositions[targetMode] || layoutPositions[targetMode].size === 0) return;
  const targetMap = layoutPositions[targetMode];
  const startPos = new Map();
  graph.forEachNode((n, a) => { startPos.set(n, { x: a.x, y: a.y }); });

  const startTime = performance.now();
  const duration = 480;

  function step(now) {
    const p = Math.min(1, (now - startTime) / duration);
    const ease = 1 - Math.pow(1 - p, 3);
    graph.forEachNode((n) => {
      const s = startPos.get(n);
      const t = targetMap.get(n) || s;
      graph.setNodeAttribute(n, 'x', s.x + (t.x - s.x) * ease);
      graph.setNodeAttribute(n, 'y', s.y + (t.y - s.y) * ease);
    });
    renderer.refresh();
    if (p < 1) {
      requestAnimationFrame(step);
    } else {
      try { renderer.setCustomBBox(renderer.getBBox()); } catch (e) {}
      if (typeof onDone === 'function') onDone();
    }
  }
  requestAnimationFrame(step);
}
