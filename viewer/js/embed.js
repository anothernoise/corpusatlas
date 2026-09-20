/**
 * CorpusAtlas Graph Web Component (<corpusatlas-graph>)
 * Autonomous, zero-dependency Custom Element for embedding interactive
 * knowledge graphs into documentation platforms (Docusaurus, VitePress, Hugo, Starlight, mdBook).
 * Zero runtime dependencies. Strict mode.
 */
'use strict';

class CorpusAtlasGraph extends HTMLElement {
  static get observedAttributes() {
    return ['src', 'layout', 'theme', 'height', 'width', 'focus'];
  }

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
    this._data = null;
    this._nodes = [];
    this._edges = [];
    this._selected = null;
    this._animFrame = null;
    this._transform = { x: 0, y: 0, k: 1 };
    this._isDragging = false;
    this._dragStart = { x: 0, y: 0 };
  }

  connectedCallback() {
    this.render();
    if (this.hasAttribute('src')) {
      this.loadData(this.getAttribute('src'));
    }
  }

  disconnectedCallback() {
    if (this._animFrame) {
      cancelAnimationFrame(this._animFrame);
    }
  }

  attributeChangedCallback(name, oldVal, newVal) {
    if (oldVal === newVal) return;
    if (name === 'src' && this.isConnected) {
      this.loadData(newVal);
    } else if (name === 'height' || name === 'width') {
      this.updateDimensions();
    } else if (name === 'focus' && this._data) {
      this.focusNode(newVal);
    }
  }

  async loadData(src) {
    if (!src) return;
    try {
      const resp = await fetch(src);
      if (!resp.ok) return;
      this._data = await resp.json();
      this.initGraph(this._data);
    } catch (e) {
      // fetch or parse failure
    }
  }

  setData(data) {
    this._data = data;
    this.initGraph(data);
  }

  initGraph(data) {
    const rawNodes = data.nodes || [];
    const rawEdges = data.edges || [];

    const width = this.canvas.width || 600;
    const height = this.canvas.height || 400;

    // Layout nodes
    const count = rawNodes.length;
    this._nodes = rawNodes.map((n, i) => {
      let x = n.x;
      let y = n.y;
      if (x === undefined || y === undefined) {
        const angle = (2 * Math.PI * i) / (count || 1);
        const radius = Math.min(width, height) * 0.35;
        x = width / 2 + radius * Math.cos(angle);
        y = height / 2 + radius * Math.sin(angle);
      }
      return {
        ...n,
        x: Number(x),
        y: Number(y),
        radius: Math.max(5, Math.min(14, (n.degree || 1) * 1.5 + 4)),
      };
    });

    const nodeMap = new Map(this._nodes.map(n => [n.id, n]));
    this._edges = rawEdges
      .filter(e => nodeMap.has(e.src) && nodeMap.has(e.dst))
      .map(e => ({
        ...e,
        source: nodeMap.get(e.src),
        target: nodeMap.get(e.dst),
      }));

    this.draw();

    const initialFocus = this.getAttribute('focus');
    if (initialFocus) {
      this.focusNode(initialFocus);
    }
  }

  focusNode(nodeId) {
    const target = this._nodes.find(n => n.id === nodeId || n.label === nodeId);
    if (!target) return;
    this._selected = target;
    const width = this.canvas.width;
    const height = this.canvas.height;
    this._transform.x = width / 2 - target.x * this._transform.k;
    this._transform.y = height / 2 - target.y * this._transform.k;
    this.updateInspector(target);
    this.draw();
    this.dispatchEvent(new CustomEvent('node-selected', { detail: { node: target } }));
  }

  updateDimensions() {
    if (!this.canvas) return;
    const h = this.getAttribute('height') || '500px';
    const w = this.getAttribute('width') || '100%';
    const container = this.shadowRoot.querySelector('.graph-container');
    if (container) {
      container.style.height = h;
      container.style.width = w;
      this.canvas.width = container.clientWidth || 600;
      this.canvas.height = container.clientHeight || 500;
      this.draw();
    }
  }

  render() {
    const theme = this.getAttribute('theme') || 'dark';
    const isDark = theme === 'dark';
    const bg = isDark ? '#0b0f19' : '#f8fafc';
    const border = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';
    const text = isDark ? '#f1f5f9' : '#0f172a';
    const subtext = isDark ? '#94a3b8' : '#64748b';

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          position: relative;
          font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        .graph-container {
          position: relative;
          width: ${this.getAttribute('width') || '100%'};
          height: ${this.getAttribute('height') || '500px'};
          background: ${bg};
          border: 1px solid ${border};
          border-radius: 8px;
          overflow: hidden;
          box-sizing: border-box;
        }
        canvas {
          width: 100%;
          height: 100%;
          display: block;
          cursor: grab;
        }
        canvas:active {
          cursor: grabbing;
        }
        .inspector {
          position: absolute;
          bottom: 12px;
          left: 12px;
          right: 12px;
          background: ${isDark ? 'rgba(15, 23, 42, 0.92)' : 'rgba(255, 255, 255, 0.95)'};
          backdrop-filter: blur(8px);
          border: 1px solid ${border};
          border-radius: 6px;
          padding: 8px 12px;
          font-size: 13px;
          color: ${text};
          display: flex;
          align-items: center;
          justify-content: space-between;
          box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        .inspector[hidden] {
          display: none;
        }
        .badge {
          display: inline-block;
          font-size: 10px;
          font-weight: 700;
          text-transform: uppercase;
          padding: 2px 6px;
          border-radius: 4px;
          margin-right: 6px;
          background: #3b82f6;
          color: #fff;
        }
        .meta {
          color: ${subtext};
          font-size: 11px;
        }
      </style>
      <div class="graph-container">
        <canvas></canvas>
        <div class="inspector" hidden>
          <div>
            <span class="badge">Node</span>
            <strong class="title">Title</strong>
            <div class="meta">Description</div>
          </div>
          <button type="button" class="close-btn" style="background:none; border:none; color:${subtext}; cursor:pointer; font-size:16px;">&times;</button>
        </div>
      </div>
    `;

    this.canvas = this.shadowRoot.querySelector('canvas');
    this.ctx = this.canvas.getContext('2d');
    this.inspector = this.shadowRoot.querySelector('.inspector');

    const closeBtn = this.shadowRoot.querySelector('.close-btn');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => {
        this.inspector.hidden = true;
        this._selected = null;
        this.draw();
      });
    }

    this.setupInteractions();
    setTimeout(() => this.updateDimensions(), 0);
  }

  setupInteractions() {
    const c = this.canvas;

    c.addEventListener('mousedown', (e) => {
      this._isDragging = true;
      this._dragStart = { x: e.clientX, y: e.clientY };
    });

    window.addEventListener('mousemove', (e) => {
      if (!this._isDragging) return;
      const dx = e.clientX - this._dragStart.x;
      const dy = e.clientY - this._dragStart.y;
      this._dragStart = { x: e.clientX, y: e.clientY };
      this._transform.x += dx;
      this._transform.y += dy;
      this.draw();
    });

    window.addEventListener('mouseup', () => {
      this._isDragging = false;
    });

    c.addEventListener('wheel', (e) => {
      e.preventDefault();
      const rect = c.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
      const newK = Math.max(0.2, Math.min(5, this._transform.k * zoomFactor));

      this._transform.x = mouseX - (mouseX - this._transform.x) * (newK / this._transform.k);
      this._transform.y = mouseY - (mouseY - this._transform.y) * (newK / this._transform.k);
      this._transform.k = newK;
      this.draw();
    }, { passive: false });

    c.addEventListener('click', (e) => {
      const rect = c.getBoundingClientRect();
      const clickX = (e.clientX - rect.left - this._transform.x) / this._transform.k;
      const clickY = (e.clientY - rect.top - this._transform.y) / this._transform.k;

      let hit = null;
      for (const n of this._nodes) {
        const dx = n.x - clickX;
        const dy = n.y - clickY;
        if (dx * dx + dy * dy <= n.radius * n.radius) {
          hit = n;
          break;
        }
      }

      if (hit) {
        this.focusNode(hit.id);
      } else {
        this._selected = null;
        if (this.inspector) this.inspector.hidden = true;
        this.draw();
      }
    });
  }

  updateInspector(node) {
    if (!this.inspector) return;
    this.inspector.hidden = false;
    const titleEl = this.inspector.querySelector('.title');
    const metaEl = this.inspector.querySelector('.meta');
    const badgeEl = this.inspector.querySelector('.badge');
    if (titleEl) titleEl.textContent = node.label || node.id;
    if (badgeEl) badgeEl.textContent = node.type || 'Entity';
    if (metaEl) metaEl.textContent = (node.meta && node.meta.description) || `${node.degree || 0} connections`;
  }

  draw() {
    if (!this.ctx || !this.canvas) return;
    const ctx = this.ctx;
    const w = this.canvas.width;
    const h = this.canvas.height;
    ctx.clearRect(0, 0, w, h);

    ctx.save();
    ctx.translate(this._transform.x, this._transform.y);
    ctx.scale(this._transform.k, this._transform.k);

    const isDark = (this.getAttribute('theme') || 'dark') === 'dark';

    // Draw edges
    ctx.lineWidth = 1;
    for (const e of this._edges) {
      const isConnected = this._selected && (e.source === this._selected || e.target === this._selected);
      ctx.strokeStyle = isConnected
        ? '#3b82f6'
        : (isDark ? 'rgba(255, 255, 255, 0.12)' : 'rgba(0, 0, 0, 0.1)');
      ctx.lineWidth = isConnected ? 2 : 1;
      ctx.beginPath();
      ctx.moveTo(e.source.x, e.source.y);
      ctx.lineTo(e.target.x, e.target.y);
      ctx.stroke();
    }

    // Draw nodes
    for (const n of this._nodes) {
      const isSelected = this._selected === n;
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.radius, 0, 2 * Math.PI);
      ctx.fillStyle = isSelected ? '#10b981' : (isDark ? '#60a5fa' : '#2563eb');
      ctx.fill();

      if (isSelected) {
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Draw label
      ctx.font = '10px sans-serif';
      ctx.fillStyle = isDark ? '#e2e8f0' : '#1e293b';
      ctx.textAlign = 'center';
      ctx.fillText(n.label || n.id, n.x, n.y + n.radius + 12);
    }

    ctx.restore();
  }
}

if (typeof customElements !== 'undefined' && !customElements.get('corpusatlas-graph')) {
  customElements.define('corpusatlas-graph', CorpusAtlasGraph);
}

export { CorpusAtlasGraph };
