// 3D Force-Directed Graph WebGL Cosmos Explorer with Draggable Flight Deck & Matrix4 compatibility.
import { getTypeColor } from './constants.js';
import { loadScript } from './utils.js';

// Polyfill Three.js r174+ matrixWorld.determinantAffine compatibility across bundles
if (typeof Object.prototype.determinantAffine !== 'function') {
  Object.defineProperty(Object.prototype, 'determinantAffine', {
    value: function determinantAffine() {
      const te = this.elements;
      if (!te || te.length < 16) return 1;
      const n11 = te[0], n12 = te[4], n13 = te[8];
      const n21 = te[1], n22 = te[5], n23 = te[9];
      const n31 = te[2], n32 = te[6], n33 = te[10];
      return (
        n11 * (n22 * n33 - n23 * n32) -
        n12 * (n21 * n33 - n23 * n31) +
        n13 * (n21 * n32 - n22 * n31)
      );
    },
    writable: true,
    configurable: true,
    enumerable: false,
  });
}
if (typeof Object.prototype.determinant3x3 !== 'function') {
  Object.defineProperty(Object.prototype, 'determinant3x3', {
    value: function determinant3x3() {
      return this.determinantAffine ? this.determinantAffine() : 1;
    },
    writable: true,
    configurable: true,
    enumerable: false,
  });
}

const THREE_CDN = 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.min.js';
const THREE_D_CDN = 'https://cdn.jsdelivr.net/npm/3d-force-graph@1.73.4/dist/3d-force-graph.min.js';

export function createNodeLabelSprite(node, meta = {}) {
  const THREE = typeof window !== 'undefined' && window.THREE ? window.THREE : null;
  if (!THREE) return null;

  const label = meta.label || node.name || node.id || '';
  if (!label) return null;

  const canvas = document.createElement('canvas');
  const ctx = canvas.getContext('2d');
  const fontSize = 24;
  const paddingX = 14;
  const paddingY = 6;
  const radius = 8;

  ctx.font = `600 ${fontSize}px Inter, -apple-system, BlinkMacSystemFont, sans-serif`;
  const textWidth = ctx.measureText(label).width;
  const dotRadius = 5;
  const dotGap = 8;
  const totalWidth = Math.ceil(textWidth + paddingX * 2 + dotRadius * 2 + dotGap);
  const totalHeight = Math.ceil(fontSize + paddingY * 2);

  canvas.width = totalWidth * 2;
  canvas.height = totalHeight * 2;
  ctx.scale(2, 2);

  // Rounded pill background
  ctx.save();
  ctx.fillStyle = 'rgba(15, 23, 42, 0.86)';
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.22)';
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  if (ctx.roundRect) {
    ctx.roundRect(1, 1, totalWidth - 2, totalHeight - 2, radius);
  } else {
    ctx.rect(1, 1, totalWidth - 2, totalHeight - 2);
  }
  ctx.fill();
  ctx.stroke();

  // Type color indicator
  const dotColor = node.color || getTypeColor(meta.type || 'Technology');
  ctx.fillStyle = dotColor;
  ctx.beginPath();
  ctx.arc(paddingX + dotRadius, totalHeight / 2, dotRadius, 0, Math.PI * 2);
  ctx.fill();

  // Label text
  ctx.fillStyle = '#f8fafc';
  ctx.font = `600 ${fontSize}px Inter, -apple-system, BlinkMacSystemFont, sans-serif`;
  ctx.textBaseline = 'middle';
  ctx.fillText(label, paddingX + dotRadius * 2 + dotGap, totalHeight / 2);
  ctx.restore();

  const texture = new THREE.CanvasTexture(canvas);
  texture.minFilter = THREE.LinearFilter;
  const spriteMaterial = new THREE.SpriteMaterial({
    map: texture,
    depthWrite: false,
    transparent: true,
  });
  const sprite = new THREE.Sprite(spriteMaterial);
  const scale = 0.18;
  sprite.scale.set(totalWidth * scale, totalHeight * scale, 1);
  const val = Number.isFinite(node.val) ? node.val : 4;
  sprite.position.set(0, val + 5, 0);

  return sprite;
}

async function resolveForceGraph3D() {
  if (typeof window !== 'undefined' && window.ForceGraph3D) {
    return window.ForceGraph3D;
  }
  try {
    if (typeof window !== 'undefined' && !window.THREE) {
      await loadScript(THREE_CDN);
    }
  } catch {}
  try {
    await loadScript(THREE_D_CDN);
    if (typeof window !== 'undefined' && window.ForceGraph3D) {
      return window.ForceGraph3D;
    }
  } catch {}
  // ESM fallback
  try {
    const mod = await import('https://cdn.jsdelivr.net/npm/3d-force-graph@1.73.4/+esm');
    if (mod && (mod.default || mod.ForceGraph3D)) {
      return mod.default || mod.ForceGraph3D;
    }
  } catch {}
  return null;
}

export function create3DGraphController({
  container,
  graph,
  byId = new Map(),
  onNodeClick = () => {},
  onFlightChange = () => {},
  getFocusedNodeId = () => null,
}) {
  let instance = null;
  let is3DActive = false;
  let isFlying = false;
  let flightTimer = null;
  let deckEl = null;

  // Traversal configuration & state
  let currentStrategy = 'edges'; // 'edges' | 'relation' | 'cluster' | 'centrality'
  let currentSpeed = 'normal'; // 'slow' | 'normal' | 'fast'
  let selectedRelFilter = '';
  let selectedStartNodeId = '';
  let plannedRoute = [];
  let currentStepIdx = 0;
  let activeTraversedEdge = null;
  let keyHandlerBound = null;

  const SPEED_CONFIGS = {
    slow: { transition: 4200, dwell: 3800 },
    normal: { transition: 2500, dwell: 2200 },
    fast: { transition: 1300, dwell: 1100 },
  };

  function getRelationsList() {
    const rels = new Set();
    graph.forEachEdge((e, a) => {
      if (a && a.rel) rels.add(a.rel);
    });
    return Array.from(rels).sort();
  }

  function getSortedHubs() {
    const nodes = [];
    graph.forEachNode((n) => {
      nodes.push({ id: n, degree: graph.degree(n) || 0 });
    });
    return nodes.sort((a, b) => b.degree - a.degree);
  }

  function buildRoute() {
    const allHubs = getSortedHubs();
    if (allHubs.length === 0) return [];

    let startId = selectedStartNodeId || getFocusedNodeId();
    if (!startId || !graph.hasNode(startId)) {
      startId = allHubs[0].id;
    }

    const route = [];

    if (currentStrategy === 'centrality') {
      const topCount = Math.min(30, allHubs.length);
      for (let i = 0; i < topCount; i++) {
        route.push(allHubs[i].id);
      }
    } else if (currentStrategy === 'cluster') {
      const clusterMap = new Map();
      graph.forEachNode((n) => {
        const meta = byId.get(n) || {};
        const c = meta.cluster !== undefined ? String(meta.cluster) : '0';
        if (!clusterMap.has(c)) clusterMap.set(c, []);
        clusterMap.get(c).push({ id: n, degree: graph.degree(n) || 0 });
      });

      // Pick top exemplar from each community cluster
      clusterMap.forEach((members) => {
        members.sort((a, b) => b.degree - a.degree);
        if (members[0]) route.push(members[0].id);
      });
    } else {
      // 'edges' or 'relation' walk
      const visited = new Set();
      let curr = startId;
      route.push(curr);
      visited.add(curr);

      const maxHops = Math.min(40, graph.order);
      for (let step = 0; step < maxHops; step++) {
        const neighbors = graph.neighbors(curr) || [];
        let candidates = [];

        if (currentStrategy === 'relation' && selectedRelFilter) {
          candidates = neighbors.filter((nbr) => {
            const hasEdge = graph.hasEdge(curr, nbr);
            if (!hasEdge) return false;
            const edgeData = graph.getEdgeAttributes(curr, nbr) || {};
            return edgeData.rel === selectedRelFilter;
          });
        } else {
          candidates = neighbors;
        }

        if (candidates.length === 0) candidates = neighbors;

        // Prefer unvisited
        const unvisited = candidates.filter((n) => !visited.has(n));
        let next = null;
        if (unvisited.length > 0) {
          next = unvisited[Math.floor(Math.random() * unvisited.length)];
        } else if (candidates.length > 0) {
          next = candidates[Math.floor(Math.random() * candidates.length)];
        } else {
          // Jump to next hub
          const nextHub = allHubs.find((h) => !visited.has(h.id));
          if (nextHub) next = nextHub.id;
          else break;
        }

        if (next) {
          route.push(next);
          visited.add(next);
          curr = next;
        } else {
          break;
        }
      }
    }

    return route.length > 0 ? route : [startId];
  }

  function findLinkBetween(srcId, dstId) {
    if (!instance) return null;
    const links = instance.graphData().links || [];
    return (
      links.find((l) => {
        const s = typeof l.source === 'object' ? l.source.id : l.source;
        const t = typeof l.target === 'object' ? l.target.id : l.target;
        return (s === srcId && t === dstId) || (s === dstId && t === srcId);
      }) || null
    );
  }

  function updateEdgeFlow() {
    if (!instance) return;
    instance
      .linkDirectionalParticles((l) => (l === activeTraversedEdge ? 6 : isFlying ? 2 : 1))
      .linkDirectionalParticleSpeed((l) => (l === activeTraversedEdge ? 0.024 : 0.005))
      .linkDirectionalParticleWidth((l) => (l === activeTraversedEdge ? 4.5 : 1.2))
      .linkDirectionalParticleColor((l) =>
        l === activeTraversedEdge ? '#38bdf8' : 'rgba(148, 163, 184, 0.45)'
      )
      .linkColor((l) => (l === activeTraversedEdge ? '#0284c7' : 'rgba(100, 116, 139, 0.25)'))
      .linkWidth((l) => (l === activeTraversedEdge ? 3.0 : 0.8));
  }

  function makeDraggable(el, handle) {
    let isDragging = false;
    let startX = 0,
      startY = 0;
    let initLeft = 0,
      initTop = 0;

    handle.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button, select, input, kbd')) return;
      isDragging = true;
      try {
        handle.setPointerCapture(e.pointerId);
      } catch {}
      startX = e.clientX;
      startY = e.clientY;
      const rect = el.getBoundingClientRect();
      const parentRect = container.getBoundingClientRect();
      initLeft = rect.left - parentRect.left;
      initTop = rect.top - parentRect.top;
      el.style.left = `${initLeft}px`;
      el.style.top = `${initTop}px`;
      el.style.right = 'auto';
      el.style.transform = 'none';
      e.preventDefault();
    });

    handle.addEventListener('pointermove', (e) => {
      if (!isDragging) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      const parentRect = container.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();

      const newLeft = Math.max(10, Math.min(parentRect.width - elRect.width - 10, initLeft + dx));
      const newTop = Math.max(10, Math.min(parentRect.height - elRect.height - 10, initTop + dy));

      el.style.left = `${newLeft}px`;
      el.style.top = `${newTop}px`;
    });

    const stopDrag = (e) => {
      if (!isDragging) return;
      isDragging = false;
      try {
        handle.releasePointerCapture(e.pointerId);
      } catch {}
    };

    handle.addEventListener('pointerup', stopDrag);
    handle.addEventListener('pointercancel', stopDrag);
  }

  function createFlightDeck() {
    if (!container || deckEl) return;
    deckEl = document.createElement('div');
    deckEl.className = 'kb-3d-deck';
    deckEl.setAttribute('data-kb-3d-deck', '');

    const rels = getRelationsList();
    const allHubs = getSortedHubs();

    deckEl.innerHTML = `
      <div class="kb-3d-deck-header" data-kb-3d-drag-handle title="Drag anywhere to reposition">
        <div class="kb-3d-deck-title">
          <span class="kb-3d-deck-icon">✦</span>
          <strong>Cosmos Flight Explorer</strong>
        </div>
        <div class="kb-3d-deck-header-actions">
          <button type="button" class="kb-3d-icon-btn" data-kb-3d-minimize title="Minimize / Expand">&minus;</button>
          <button type="button" class="kb-3d-icon-btn" data-kb-3d-exit-btn title="Exit 3D Mode">&times;</button>
        </div>
      </div>

      <div class="kb-3d-deck-body" data-kb-3d-body>
        <div class="kb-3d-config-section">
          <div class="kb-3d-config-row">
            <label class="kb-3d-label" for="kb-3d-strategy-select">Flight Mode</label>
            <select id="kb-3d-strategy-select" class="kb-3d-select" data-kb-3d-strategy>
              <option value="edges">Follow Edges (Graph Walk)</option>
              <option value="relation">By Edge Relation</option>
              <option value="cluster">Cluster-to-Cluster Hop</option>
              <option value="centrality">Centrality Hubs Tour</option>
            </select>
          </div>

          <div class="kb-3d-config-row" data-kb-3d-rel-row style="display:none;">
            <label class="kb-3d-label" for="kb-3d-rel-select">Relation</label>
            <select id="kb-3d-rel-select" class="kb-3d-select" data-kb-3d-rel-filter>
              <option value="">All Relations</option>
              ${rels.map((r) => `<option value="${r}">${r}</option>`).join('')}
            </select>
          </div>

          <div class="kb-3d-config-row">
            <label class="kb-3d-label" for="kb-3d-start-select">Start Node</label>
            <select id="kb-3d-start-select" class="kb-3d-select" data-kb-3d-start-node>
              <option value="">Current Selection / Top Hub</option>
              ${allHubs
                .slice(0, 30)
                .map((h) => {
                  const m = byId.get(h.id) || {};
                  return `<option value="${h.id}">${m.label || h.id} (${h.degree} edges)</option>`;
                })
                .join('')}
            </select>
          </div>

          <div class="kb-3d-config-row">
            <label class="kb-3d-label" for="kb-3d-speed-select">Flight Speed</label>
            <select id="kb-3d-speed-select" class="kb-3d-select" data-kb-3d-speed>
              <option value="slow">Cinematic (Slow)</option>
              <option value="normal" selected>Balanced (Normal)</option>
              <option value="fast">Swift (Fast)</option>
            </select>
          </div>
        </div>

        <div class="kb-3d-telemetry" data-kb-3d-telemetry>
          <div class="kb-3d-target-row">
            <span class="kb-3d-target-badge" data-kb-3d-node-type>Ready</span>
            <strong class="kb-3d-target-name" data-kb-3d-node-label>Cosmos Explorer</strong>
          </div>
          <div class="kb-3d-edge-readout" data-kb-3d-edge-readout style="display:none;">
            <span class="kb-3d-edge-icon">↳</span>
            <span class="kb-3d-edge-text" data-kb-3d-edge-text></span>
          </div>
          <div class="kb-3d-meta-row">
            <span class="kb-3d-meta-item" data-kb-3d-meta-degree>${graph.order} entities in space</span>
            <span class="kb-3d-meta-item" data-kb-3d-meta-cluster></span>
          </div>
        </div>

        <div class="kb-3d-progress-row">
          <div class="kb-3d-progress-track" data-kb-3d-progress title="Tour progress timeline">
            <div class="kb-3d-progress-bar" data-kb-3d-progress-bar style="width:0%"></div>
          </div>
          <span class="kb-3d-progress-text" data-kb-3d-progress-text>Ready</span>
        </div>

        <div class="kb-3d-controls-row">
          <button type="button" class="kb-3d-btn" data-kb-3d-prev-btn title="Previous Stop (Left Arrow)">⏮</button>
          <button type="button" class="kb-3d-btn is-primary" data-kb-3d-play-btn title="Play / Pause Flight (Space)">
            <span class="kb-3d-play-icon">▶</span>
            <span class="kb-3d-play-label">Start Tour</span>
          </button>
          <button type="button" class="kb-3d-btn" data-kb-3d-next-btn title="Next Stop (Right Arrow)">⏭</button>
          <button type="button" class="kb-3d-btn" data-kb-3d-fit-btn title="Fit View">⊡ Fit</button>
        </div>

        <div class="kb-3d-hint">
          Shortcuts: <kbd>Space</kbd> Play/Pause &middot; <kbd>&larr;</kbd>/<kbd>&rarr;</kbd> Step &middot; <kbd>Esc</kbd> Stop
        </div>
      </div>
    `;

    const handle = deckEl.querySelector('[data-kb-3d-drag-handle]');
    makeDraggable(deckEl, handle);

    const stratSelect = deckEl.querySelector('[data-kb-3d-strategy]');
    const relRow = deckEl.querySelector('[data-kb-3d-rel-row]');
    const relSelect = deckEl.querySelector('[data-kb-3d-rel-filter]');
    const startSelect = deckEl.querySelector('[data-kb-3d-start-node]');
    const speedSelect = deckEl.querySelector('[data-kb-3d-speed]');
    const playBtn = deckEl.querySelector('[data-kb-3d-play-btn]');
    const prevBtn = deckEl.querySelector('[data-kb-3d-prev-btn]');
    const nextBtn = deckEl.querySelector('[data-kb-3d-next-btn]');
    const fitBtn = deckEl.querySelector('[data-kb-3d-fit-btn]');
    const exitBtn = deckEl.querySelector('[data-kb-3d-exit-btn]');
    const minBtn = deckEl.querySelector('[data-kb-3d-minimize]');
    const bodyEl = deckEl.querySelector('[data-kb-3d-body]');

    stratSelect.addEventListener('change', (e) => {
      currentStrategy = e.target.value;
      relRow.style.display = currentStrategy === 'relation' ? 'flex' : 'none';
      plannedRoute = buildRoute();
      currentStepIdx = 0;
      updateDeckUI();
    });

    relSelect.addEventListener('change', (e) => {
      selectedRelFilter = e.target.value;
      plannedRoute = buildRoute();
      currentStepIdx = 0;
      updateDeckUI();
    });

    startSelect.addEventListener('change', (e) => {
      selectedStartNodeId = e.target.value;
      plannedRoute = buildRoute();
      currentStepIdx = 0;
      updateDeckUI();
    });

    speedSelect.addEventListener('change', (e) => {
      currentSpeed = e.target.value;
    });

    playBtn.addEventListener('click', () => {
      toggleFlightMode();
    });

    prevBtn.addEventListener('click', () => {
      stepBack();
    });

    nextBtn.addEventListener('click', () => {
      stepForward();
    });

    fitBtn.addEventListener('click', () => {
      if (isFlying) stopFlightMode();
      if (instance) instance.zoomToFit(1200, 20);
    });

    exitBtn.addEventListener('click', () => {
      hide();
    });

    minBtn.addEventListener('click', () => {
      const isMin = bodyEl.style.display === 'none';
      bodyEl.style.display = isMin ? 'block' : 'none';
      minBtn.textContent = isMin ? '−' : '□';
    });

    container.appendChild(deckEl);
  }

  function updateDeckUI() {
    if (!deckEl) return;
    const playBtn = deckEl.querySelector('[data-kb-3d-play-btn]');
    const playIcon = deckEl.querySelector('.kb-3d-play-icon');
    const playLabel = deckEl.querySelector('.kb-3d-play-label');
    const progressBar = deckEl.querySelector('[data-kb-3d-progress-bar]');
    const progressText = deckEl.querySelector('[data-kb-3d-progress-text]');

    if (playBtn) {
      playBtn.classList.toggle('is-active', isFlying);
      if (playIcon) playIcon.textContent = isFlying ? '⏸' : '▶';
      if (playLabel) playLabel.textContent = isFlying ? 'Pause Tour' : 'Start Tour';
    }

    const total = plannedRoute.length || 1;
    const pct = Math.min(100, Math.round(((currentStepIdx + 1) / total) * 100));
    if (progressBar) progressBar.style.width = `${pct}%`;
    if (progressText) {
      progressText.textContent = `Stop ${Math.min(currentStepIdx + 1, total)} / ${total}`;
    }
  }

  function updateDeckTelemetry(targetNodeId, edge = null) {
    if (!deckEl) return;
    const typeEl = deckEl.querySelector('[data-kb-3d-node-type]');
    const labelEl = deckEl.querySelector('[data-kb-3d-node-label]');
    const edgeRow = deckEl.querySelector('[data-kb-3d-edge-readout]');
    const edgeText = deckEl.querySelector('[data-kb-3d-edge-text]');
    const degEl = deckEl.querySelector('[data-kb-3d-meta-degree]');
    const clusterEl = deckEl.querySelector('[data-kb-3d-meta-cluster]');

    const meta = byId.get(targetNodeId) || {};
    const label = meta.label || targetNodeId || 'Node';
    const type = meta.type || 'Technology';
    const deg = graph.degree(targetNodeId) || 0;

    if (typeEl) {
      typeEl.textContent = type;
      typeEl.style.background = getTypeColor(type);
    }
    if (labelEl) labelEl.textContent = label;
    if (degEl) degEl.textContent = `${deg} connections`;
    if (clusterEl) {
      clusterEl.textContent = meta.cluster !== undefined ? `Cluster #${meta.cluster}` : '';
    }

    if (edge) {
      const srcId = typeof edge.source === 'object' ? edge.source.id : edge.source;
      const dstId = typeof edge.target === 'object' ? edge.target.id : edge.target;
      const srcMeta = byId.get(srcId) || {};
      const dstMeta = byId.get(dstId) || {};
      const rel = edge.name || edge.rel || 'connected_to';

      if (edgeRow && edgeText) {
        edgeText.textContent = `${srcMeta.label || srcId} —(${rel})→ ${dstMeta.label || dstId}`;
        edgeRow.style.display = 'flex';
      }
    } else if (edgeRow) {
      edgeRow.style.display = 'none';
    }

    updateDeckUI();
  }

  function executeFlightStep() {
    if (!instance || !isFlying) return;
    if (plannedRoute.length === 0) {
      plannedRoute = buildRoute();
      currentStepIdx = 0;
    }

    const targetId = plannedRoute[currentStepIdx % plannedRoute.length];
    const prevId =
      currentStepIdx > 0
        ? plannedRoute[(currentStepIdx - 1) % plannedRoute.length]
        : null;

    activeTraversedEdge = prevId ? findLinkBetween(prevId, targetId) : null;
    updateEdgeFlow();

    // Look up 3D coordinates of target node
    const gNodes = instance.graphData().nodes || [];
    const targetNodeObj = gNodes.find((n) => n.id === targetId);

    const timing = SPEED_CONFIGS[currentSpeed] || SPEED_CONFIGS.normal;

    if (targetNodeObj && Number.isFinite(targetNodeObj.x)) {
      const dist = 80;
      const angle = (currentStepIdx * 1.1) % (Math.PI * 2);
      const camPos = {
        x: targetNodeObj.x + dist * Math.cos(angle),
        y: targetNodeObj.y + dist * 0.45,
        z: targetNodeObj.z + dist * Math.sin(angle),
      };

      instance.cameraPosition(camPos, targetNodeObj, timing.transition);
      updateDeckTelemetry(targetId, activeTraversedEdge);
      onNodeClick(targetId);
    } else {
      updateDeckTelemetry(targetId, activeTraversedEdge);
    }

    currentStepIdx++;

    flightTimer = setTimeout(() => {
      if (isFlying) executeFlightStep();
    }, timing.transition + timing.dwell);
  }

  function stepForward() {
    if (!instance) return;
    if (plannedRoute.length === 0) plannedRoute = buildRoute();
    currentStepIdx = (currentStepIdx + 1) % plannedRoute.length;
    const targetId = plannedRoute[currentStepIdx];
    const prevId =
      currentStepIdx > 0
        ? plannedRoute[currentStepIdx - 1]
        : plannedRoute[plannedRoute.length - 1];

    activeTraversedEdge = prevId ? findLinkBetween(prevId, targetId) : null;
    updateEdgeFlow();

    const gNodes = instance.graphData().nodes || [];
    const targetNodeObj = gNodes.find((n) => n.id === targetId);
    if (targetNodeObj && Number.isFinite(targetNodeObj.x)) {
      const dist = 80;
      const angle = (currentStepIdx * 1.1) % (Math.PI * 2);
      const camPos = {
        x: targetNodeObj.x + dist * Math.cos(angle),
        y: targetNodeObj.y + dist * 0.45,
        z: targetNodeObj.z + dist * Math.sin(angle),
      };
      instance.cameraPosition(camPos, targetNodeObj, 1600);
      updateDeckTelemetry(targetId, activeTraversedEdge);
      onNodeClick(targetId);
    }
  }

  function stepBack() {
    if (!instance) return;
    if (plannedRoute.length === 0) plannedRoute = buildRoute();
    currentStepIdx = (currentStepIdx - 1 + plannedRoute.length) % plannedRoute.length;
    const targetId = plannedRoute[currentStepIdx];
    activeTraversedEdge = null;
    updateEdgeFlow();

    const gNodes = instance.graphData().nodes || [];
    const targetNodeObj = gNodes.find((n) => n.id === targetId);
    if (targetNodeObj && Number.isFinite(targetNodeObj.x)) {
      const dist = 80;
      const angle = (currentStepIdx * 1.1) % (Math.PI * 2);
      const camPos = {
        x: targetNodeObj.x + dist * Math.cos(angle),
        y: targetNodeObj.y + dist * 0.45,
        z: targetNodeObj.z + dist * Math.sin(angle),
      };
      instance.cameraPosition(camPos, targetNodeObj, 1600);
      updateDeckTelemetry(targetId, null);
      onNodeClick(targetId);
    }
  }

  function startFlightMode() {
    if (!instance || isFlying) return;
    isFlying = true;
    onFlightChange(true);

    if (plannedRoute.length === 0) {
      plannedRoute = buildRoute();
      currentStepIdx = 0;
    }

    updateDeckUI();
    executeFlightStep();
  }

  function stopFlightMode() {
    if (!isFlying) return;
    isFlying = false;
    if (flightTimer) {
      clearTimeout(flightTimer);
      flightTimer = null;
    }
    activeTraversedEdge = null;
    updateEdgeFlow();
    updateDeckUI();
    onFlightChange(false);
  }

  function toggleFlightMode() {
    if (isFlying) {
      stopFlightMode();
    } else {
      startFlightMode();
    }
    return isFlying;
  }

  async function init() {
    if (!container) return false;
    if (!instance) {
      const ForceGraph3D = await resolveForceGraph3D();
      if (!ForceGraph3D) return false;
      instance = ForceGraph3D()(container);
    }

    const gData = {
      nodes: [],
      links: [],
    };

    graph.forEachNode((n) => {
      const meta = byId.get(n) || {};
      gData.nodes.push({
        id: n,
        name: meta.label || n,
        type: meta.type || 'Technology',
        color: getTypeColor(meta.type || 'Technology'),
        val: Math.max(1, Math.sqrt(graph.degree(n) || 1) * 2.2),
      });
    });

    graph.forEachEdge((e, a, s, t) => {
      gData.links.push({
        source: s,
        target: t,
        name: a.rel || '',
        color: 'rgba(148, 163, 184, 0.35)',
      });
    });

    instance
      .graphData(gData)
      .nodeLabel('name')
      .nodeColor('color')
      .nodeVal('val')
      .nodeThreeObject((node) => {
        const meta = byId.get(node.id) || {};
        return createNodeLabelSprite(node, meta);
      })
      .nodeThreeObjectExtend(true)
      .linkCurvature(0.12)
      .linkDirectionalParticles(2)
      .linkDirectionalParticleSpeed(0.005)
      .linkDirectionalParticleWidth(1.2)
      .linkDirectionalParticleColor(() => 'rgba(148, 163, 184, 0.55)')
      .onNodeClick((node) => {
        if (node && node.id) {
          onNodeClick(node.id);
          selectedStartNodeId = node.id;
          if (deckEl) {
            const startSelect = deckEl.querySelector('[data-kb-3d-start-node]');
            if (startSelect) startSelect.value = node.id;
            updateDeckTelemetry(node.id);
          }
        }
      })
      .backgroundColor('#090d16');

    createFlightDeck();
    updateDeckUI();

    return true;
  }

  function handleKeyDown(e) {
    if (!is3DActive) return;
    const tag = document.activeElement ? document.activeElement.tagName : '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    if (e.code === 'Space') {
      e.preventDefault();
      toggleFlightMode();
    } else if (e.code === 'ArrowRight') {
      e.preventDefault();
      stepForward();
    } else if (e.code === 'ArrowLeft') {
      e.preventDefault();
      stepBack();
    } else if (e.code === 'Escape') {
      e.preventDefault();
      if (isFlying) stopFlightMode();
      else hide();
    }
  }

  async function show() {
    if (!container) return;
    container.hidden = false;
    container.style.display = 'block';
    is3DActive = true;
    const ok = await init();
    if (!ok && container) {
      container.hidden = true;
      container.style.display = 'none';
      return;
    }
    if (instance) {
      instance.resumeAnimation();
    }
    if (!keyHandlerBound) {
      keyHandlerBound = handleKeyDown;
      window.addEventListener('keydown', keyHandlerBound);
    }
  }

  function hide() {
    if (!container) return;
    stopFlightMode();
    container.hidden = true;
    container.style.display = 'none';
    is3DActive = false;
    if (instance) {
      instance.pauseAnimation();
    }
    if (keyHandlerBound) {
      window.removeEventListener('keydown', keyHandlerBound);
      keyHandlerBound = null;
    }
  }

  function toggle() {
    if (is3DActive) {
      hide();
    } else {
      show();
    }
    return is3DActive;
  }

  return {
    show,
    hide,
    toggle,
    isActive: () => is3DActive,
    isFlying: () => isFlying,
    startFlightMode,
    stopFlightMode,
    toggleFlightMode,
    stepForward,
    stepBack,
  };
}
