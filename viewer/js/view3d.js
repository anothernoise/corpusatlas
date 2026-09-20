// 3D Force-Directed Graph WebGL view controller.
import { getTypeColor } from './constants.js';

const THREE_D_CDN = 'https://cdn.jsdelivr.net/npm/3d-force-graph@1.73.4/+esm';

export function create3DGraphController({
  container,
  graph,
  byId = new Map(),
  onNodeClick = () => {},
}) {
  let instance = null;
  let is3DActive = false;

  async function init() {
    if (!container) return;
    if (!instance) {
      try {
        const { default: ForceGraph3D } = await import(THREE_D_CDN);
        instance = ForceGraph3D()(container);
      } catch {
        return false;
      }
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
        val: Math.max(1, Math.sqrt(graph.degree(n) || 1) * 2),
      });
    });

    graph.forEachEdge((e, a, s, t) => {
      gData.links.push({
        source: s,
        target: t,
        name: a.rel || '',
        color: 'rgba(148, 163, 184, 0.4)',
      });
    });

    instance
      .graphData(gData)
      .nodeLabel('name')
      .nodeColor('color')
      .nodeVal('val')
      .linkDirectionalParticles(2)
      .linkDirectionalParticleSpeed(0.005)
      .onNodeClick((node) => {
        if (node && node.id) onNodeClick(node.id);
      })
      .backgroundColor('#090d16');

    return true;
  }

  async function show() {
    if (!container) return;
    container.hidden = false;
    is3DActive = true;
    const ok = await init();
    if (!ok && container) container.hidden = true;
  }

  function hide() {
    if (!container) return;
    container.hidden = true;
    is3DActive = false;
    if (instance) {
      instance.pauseAnimation();
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
  };
}
