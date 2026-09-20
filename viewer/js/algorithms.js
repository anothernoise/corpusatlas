// Graph algorithms: BFS shortest paths, multi-hop routing, Louvain community detection, and centrality metrics.

/**
 * Single-source BFS distance map over visible nodes/edges.
 */
export function bfsDist(graph, root, isNodeVisible, isEdgeVisible) {
  const dist = new Map([[root, 0]]);
  let frontier = [root];
  while (frontier.length) {
    const next = [];
    for (const id of frontier) {
      graph.forEachEdge(id, (e, a, s, t) => {
        if (isEdgeVisible && !isEdgeVisible(e)) return;
        const other = s === id ? t : s;
        if (dist.has(other) || (isNodeVisible && !isNodeVisible(other))) return;
        dist.set(other, dist.get(id) + 1);
        next.push(other);
      });
    }
    frontier = next;
  }
  return dist;
}

/**
 * Shortest path between two entities over the visible graph using BFS.
 */
export function shortestPath(graph, from, to, isNodeVisible, isEdgeVisible) {
  if (from === to) return { nodes: [from], edges: [], hopCount: 0, chain: [from] };
  const distFrom = bfsDist(graph, from, isNodeVisible, isEdgeVisible);
  if (!distFrom.has(to)) return null;
  const distTo = bfsDist(graph, to, isNodeVisible, isEdgeVisible);
  const hopCount = distFrom.get(to);
  const nodes = new Set(), edges = new Set();
  const chainPrev = new Map([[from, null]]);
  let frontier = [from];
  while (frontier.length) {
    const next = [];
    for (const id of frontier) {
      graph.forEachEdge(id, (e, a, s, t) => {
        if (isEdgeVisible && !isEdgeVisible(e)) return;
        const other = s === id ? t : s;
        if ((isNodeVisible && !isNodeVisible(other)) || !distFrom.has(other) || !distTo.has(other)) return;
        const onShortest = distFrom.get(id) + 1 + distTo.get(other) === hopCount;
        if (!onShortest) return;
        if (distFrom.get(other) === distFrom.get(id) + 1) {
          edges.add(e);
          nodes.add(id);
          nodes.add(other);
          if (!chainPrev.has(other)) {
            chainPrev.set(other, { from: id, edge: e });
            next.push(other);
          }
        }
      });
    }
    frontier = next;
  }
  const chain = [to];
  let cur = to;
  while (chainPrev.get(cur)) {
    cur = chainPrev.get(cur).from;
    chain.unshift(cur);
  }
  return { nodes: [...nodes], edges: [...edges], hopCount, chain };
}

/**
 * Multi-hop path linking an array of sequential waypoints.
 */
export function computeMultiPath(graph, waypoints, isNodeVisible, isEdgeVisible) {
  if (!waypoints || waypoints.length < 2) return null;
  const allNodes = new Set();
  const allEdges = new Set();
  let totalHops = 0;
  const fullChain = [];

  for (let i = 0; i < waypoints.length - 1; i++) {
    const leg = shortestPath(graph, waypoints[i], waypoints[i + 1], isNodeVisible, isEdgeVisible);
    if (!leg) return null;
    leg.nodes.forEach(n => allNodes.add(n));
    leg.edges.forEach(e => allEdges.add(e));
    totalHops += leg.hopCount;
    if (i === 0) fullChain.push(...leg.chain);
    else fullChain.push(...leg.chain.slice(1));
  }
  return { nodes: [...allNodes], edges: [...allEdges], hopCount: totalHops, chain: fullChain, waypoints };
}

/**
 * Label-propagation fallback for modular topical community detection.
 */
export function computeCommunitiesFallback(graph) {
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

/**
 * Brandes' algorithm for exact betweenness centrality.
 */
export function computeBetweennessFallback(graph) {
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

/**
 * Multi-dimensional centrality ranking: Degree, PageRank, and Betweenness bridges.
 */
export function computeCentrality(graph, byId, pagerankMap = new Map()) {
  const degreeList = [];
  graph.forEachNode(n => {
    degreeList.push({ id: n, label: (byId.get(n) || {}).label || n, score: graph.degree(n) });
  });
  degreeList.sort((a, b) => b.score - a.score);

  const prList = [];
  graph.forEachNode(n => {
    prList.push({ id: n, label: (byId.get(n) || {}).label || n, score: (pagerankMap.get(n) || 0) });
  });
  prList.sort((a, b) => b.score - a.score);

  const cb = computeBetweennessFallback(graph);
  const bwList = [];
  for (const [n, val] of cb.entries()) {
    bwList.push({ id: n, label: (byId.get(n) || {}).label || n, score: Math.round(val * 10) / 10 });
  }
  bwList.sort((a, b) => b.score - a.score);

  return {
    degree: degreeList.slice(0, 7),
    pagerank: prList.slice(0, 7),
    betweenness: bwList.slice(0, 7)
  };
}
