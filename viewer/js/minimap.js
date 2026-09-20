// Canvas minimap with calibrated viewport rectangle and camera pan synchronization.
import { MINIMAP_SIZE } from './constants.js';
import { clamp } from './utils.js';

export function createMinimapController({
  minimapCanvas,
  graph,
  renderer,
  stage,
  getDark,
  isNodeVisible,
  moveCamera,
}) {
  if (!minimapCanvas) {
    return {
      draw: () => {},
      init: () => {},
    };
  }

  const minimapCtx = minimapCanvas.getContext('2d');
  let mmSize = MINIMAP_SIZE;

  function init() {
    const dpr = window.devicePixelRatio || 1;
    mmSize = minimapCanvas.getBoundingClientRect().width || MINIMAP_SIZE;
    minimapCanvas.width = mmSize * dpr;
    minimapCanvas.height = mmSize * dpr;
    minimapCtx.scale(dpr, dpr);

    const jump = (ev) => {
      const rect = minimapCanvas.getBoundingClientRect();
      if (typeof moveCamera === 'function') {
        moveCamera({
          x: clamp((ev.clientX - rect.left) / rect.width, 0, 1),
          y: clamp((ev.clientY - rect.top) / rect.height, 0, 1),
        }, 200);
      }
    };

    let mmDragging = false;
    minimapCanvas.addEventListener('mousedown', (ev) => { mmDragging = true; jump(ev); });
    window.addEventListener('mousemove', (ev) => { if (mmDragging) jump(ev); });
    window.addEventListener('mouseup', () => { mmDragging = false; });
  }

  function draw() {
    if (!minimapCtx) return;
    renderer.refresh({ skipIndexation: true });
    minimapCtx.clearRect(0, 0, mmSize, mmSize);

    let xLo = null, xHi = null, yLo = null, yHi = null;
    graph.forEachNode((n) => {
      if (isNodeVisible && !isNodeVisible(n)) return;
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

    if (!xLo || xLo.id === xHi.id || yLo.id === yHi.id) return;
    const vp = (id) => renderer.graphToViewport(graph.getNodeAttributes(id));
    const xLoVp = vp(xLo.id).x, xHiVp = vp(xHi.id).x, yLoVp = vp(yLo.id).y, yHiVp = vp(yHi.id).y;
    const A = (xHiVp - xLoVp) / (xHi.x - xLo.x), B = xLoVp - A * xLo.x;
    const C = (yHiVp - yLoVp) / (yHi.y - yLo.y), D = yLoVp - C * yLo.y;
    if (![A, B, C, D].every(Number.isFinite)) return;
    const w = stage.clientWidth || 800, h = stage.clientHeight || 600;

    const x0 = clamp((0 - B) / A, -0.5, 1.5) * mmSize;
    const x1 = clamp((w - B) / A, -0.5, 1.5) * mmSize;
    const y0 = clamp((0 - D) / C, -0.5, 1.5) * mmSize;
    const y1 = clamp((h - D) / C, -0.5, 1.5) * mmSize;

    const isDark = typeof getDark === 'function' ? getDark() : true;
    minimapCtx.strokeStyle = isDark ? 'rgba(226,232,240,0.85)' : 'rgba(30,41,59,0.75)';
    minimapCtx.lineWidth = 1;
    minimapCtx.strokeRect(Math.min(x0, x1), Math.min(y0, y1), Math.abs(x1 - x0), Math.abs(y1 - y0));
  }

  return {
    init,
    draw,
  };
}
