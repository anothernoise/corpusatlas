"""JupyterLab & VS Code interactive notebook widget.

Zero-dependency embedded knowledge graph renderer for Jupyter Notebook,
JupyterLab, Google Colab, and VS Code interactive Python.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Union


class NotebookViewerWidget:
    """Wraps an interactive HTML representation of the knowledge graph."""

    def __init__(self, html_content: str):
        self.html_content = html_content

    def _repr_html_(self) -> str:
        return self.html_content

    def __repr__(self) -> str:
        return "<CorpusAtlas Interactive Graph Widget>"


def _prepare_graph_data(graph: Union[dict[str, Any], str, Path]) -> dict[str, Any]:
    if isinstance(graph, (str, Path)):
        p = Path(graph)
        if not p.exists():
            raise FileNotFoundError(f"graph file not found: {graph}")
        return json.loads(p.read_text(encoding="utf-8"))
    if isinstance(graph, dict):
        return graph
    raise TypeError(f"expected dict or path, got {type(graph)}")


def _generate_widget_html(
    graph_data: dict[str, Any],
    height: Union[int, str] = 600,
    width: str = "100%",
    theme: str = "dark"
) -> str:
    h_str = f"{height}px" if isinstance(height, int) else str(height)
    data_json = json.dumps(graph_data, ensure_ascii=False)

    # Inlines autonomous canvas-based viewer element
    return f"""
<div class="corpusatlas-notebook-container" style="width:{width}; height:{h_str}; margin: 10px 0;">
  <corpusatlas-graph id="ca_graph_widget" height="{h_str}" width="{width}" theme="{theme}"></corpusatlas-graph>
  <script type="module">
    class CorpusAtlasGraph extends HTMLElement {{
      constructor() {{
        super();
        this.attachShadow({{ mode: 'open' }});
        this._nodes = [];
        this._edges = [];
        this._selected = null;
        this._transform = {{ x: 0, y: 0, k: 1 }};
        this._isDragging = false;
        this._dragStart = {{ x: 0, y: 0 }};
      }}
      connectedCallback() {{
        this.render();
      }}
      setData(data) {{
        const rawNodes = data.nodes || [];
        const rawEdges = data.edges || [];
        const w = this.canvas.width || 600;
        const h = this.canvas.height || 400;
        const count = rawNodes.length;

        this._nodes = rawNodes.map((n, i) => {{
          let x = n.x, y = n.y;
          if (x === undefined || y === undefined) {{
            const angle = (2 * Math.PI * i) / (count || 1);
            const radius = Math.min(w, h) * 0.35;
            x = w / 2 + radius * Math.cos(angle);
            y = h / 2 + radius * Math.sin(angle);
          }}
          return {{ ...n, x: Number(x), y: Number(y), radius: Math.max(5, Math.min(14, (n.degree || 1) * 1.5 + 4)) }};
        }});

        const nodeMap = new Map(this._nodes.map(n => [n.id, n]));
        this._edges = rawEdges
          .filter(e => nodeMap.has(e.src) && nodeMap.has(e.dst))
          .map(e => ({{ ...e, source: nodeMap.get(e.src), target: nodeMap.get(e.dst) }}));

        this.draw();
      }}
      render() {{
        const isDark = (this.getAttribute('theme') || 'dark') === 'dark';
        const bg = isDark ? '#0b0f19' : '#f8fafc';
        const border = isDark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.1)';
        const text = isDark ? '#f1f5f9' : '#0f172a';
        this.shadowRoot.innerHTML = `
          <style>
            :host {{ display: block; position: relative; font-family: sans-serif; }}
            .container {{ position: relative; width: 100%; height: ${h_str}; background: ${{bg}}; border: 1px solid ${{border}}; border-radius: 8px; overflow: hidden; }}
            canvas {{ width: 100%; height: 100%; display: block; cursor: grab; }}
            .inspector {{ position: absolute; bottom: 10px; left: 10px; right: 10px; background: ${{isDark ? 'rgba(15,23,42,0.92)' : 'rgba(255,255,255,0.95)'}}; border: 1px solid ${{border}}; border-radius: 6px; padding: 6px 10px; font-size: 12px; color: ${{text}}; display: flex; justify-content: space-between; align-items: center; }}
            .inspector[hidden] {{ display: none; }}
          </style>
          <div class="container">
            <canvas></canvas>
            <div class="inspector" hidden>
              <div><strong class="title"></strong> · <span class="meta"></span></div>
              <button type="button" class="close" style="background:none;border:none;color:${{text}};cursor:pointer;">&times;</button>
            </div>
          </div>
        `;
        this.canvas = this.shadowRoot.querySelector('canvas');
        this.ctx = this.canvas.getContext('2d');
        this.inspector = this.shadowRoot.querySelector('.inspector');
        this.canvas.width = this.offsetWidth || 800;
        this.canvas.height = parseInt('${h_str}') || 500;
        this.setupInteractions();
      }}
      setupInteractions() {{
        const c = this.canvas;
        c.addEventListener('mousedown', (e) => {{ this._isDragging = true; this._dragStart = {{ x: e.clientX, y: e.clientY }}; }});
        window.addEventListener('mousemove', (e) => {{
          if (!this._isDragging) return;
          this._transform.x += e.clientX - this._dragStart.x;
          this._transform.y += e.clientY - this._dragStart.y;
          this._dragStart = {{ x: e.clientX, y: e.clientY }};
          this.draw();
        }});
        window.addEventListener('mouseup', () => {{ this._isDragging = false; }});
        c.addEventListener('wheel', (e) => {{
          e.preventDefault();
          const zoom = e.deltaY < 0 ? 1.1 : 0.9;
          this._transform.k = Math.max(0.2, Math.min(5, this._transform.k * zoom));
          this.draw();
        }}, {{ passive: false }});
        c.addEventListener('click', (e) => {{
          const rect = c.getBoundingClientRect();
          const cx = (e.clientX - rect.left - this._transform.x) / this._transform.k;
          const cy = (e.clientY - rect.top - this._transform.y) / this._transform.k;
          const hit = this._nodes.find(n => (n.x - cx)**2 + (n.y - cy)**2 <= n.radius**2);
          if (hit) {{
            this._selected = hit;
            this.inspector.hidden = false;
            this.inspector.querySelector('.title').textContent = hit.label || hit.id;
            this.inspector.querySelector('.meta').textContent = (hit.meta && hit.meta.description) || hit.type || '';
          }} else {{
            this._selected = null;
            this.inspector.hidden = true;
          }}
          this.draw();
        }});
        this.shadowRoot.querySelector('.close').addEventListener('click', () => {{
          this._selected = null;
          this.inspector.hidden = true;
          this.draw();
        }});
      }}
      draw() {{
        if (!this.ctx || !this.canvas) return;
        const ctx = this.ctx;
        ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        ctx.save();
        ctx.translate(this._transform.x, this._transform.y);
        ctx.scale(this._transform.k, this._transform.k);
        const isDark = (this.getAttribute('theme') || 'dark') === 'dark';
        ctx.lineWidth = 1;
        for (const e of this._edges) {{
          const isConn = this._selected && (e.source === this._selected || e.target === this._selected);
          ctx.strokeStyle = isConn ? '#3b82f6' : (isDark ? 'rgba(255,255,255,0.15)' : 'rgba(0,0,0,0.1)');
          ctx.lineWidth = isConn ? 2 : 1;
          ctx.beginPath();
          ctx.moveTo(e.source.x, e.source.y);
          ctx.lineTo(e.target.x, e.target.y);
          ctx.stroke();
        }}
        for (const n of this._nodes) {{
          const sel = this._selected === n;
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.radius, 0, 2 * Math.PI);
          ctx.fillStyle = sel ? '#10b981' : (isDark ? '#60a5fa' : '#2563eb');
          ctx.fill();
          if (sel) {{ ctx.strokeStyle = '#fff'; ctx.lineWidth = 2; ctx.stroke(); }}
          ctx.font = '10px sans-serif';
          ctx.fillStyle = isDark ? '#e2e8f0' : '#1e293b';
          ctx.textAlign = 'center';
          ctx.fillText(n.label || n.id, n.x, n.y + n.radius + 11);
        }}
        ctx.restore();
      }}
    }}
    if (!customElements.get('corpusatlas-graph')) {{
      customElements.define('corpusatlas-graph', CorpusAtlasGraph);
    }}
    const graphData = {data_json};
    const el = document.getElementById('ca_graph_widget');
    if (el) {{
      setTimeout(() => el.setData(graphData), 10);
    }}
  </script>
</div>
"""


def show(
    graph: Union[dict[str, Any], str, Path],
    height: Union[int, str] = 600,
    width: str = "100%",
    mode: str = "2d",
    theme: str = "dark"
) -> Any:
    """Renders the graph inside Jupyter Notebook, JupyterLab, Colab, or VS Code interactive window.

    Returns an HTML widget with an embedded interactive view.
    """
    data = _prepare_graph_data(graph)
    html_markup = _generate_widget_html(data, height=height, width=width, theme=theme)

    try:
        from IPython.display import HTML
        return HTML(html_markup)
    except ImportError:
        return NotebookViewerWidget(html_markup)


def to_html(
    graph: Union[dict[str, Any], str, Path],
    out_path: Union[str, Path],
    height: Union[int, str] = "100vh",
    width: str = "100%",
    theme: str = "dark"
) -> Path:
    """Exports an interactive standalone HTML file for browser viewing."""
    data = _prepare_graph_data(graph)
    widget_html = _generate_widget_html(data, height=height, width=width, theme=theme)
    full_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>CorpusAtlas Knowledge Graph</title>
  <style>
    body, html {{ margin: 0; padding: 0; width: 100%; height: 100%; background: {'#0b0f19' if theme == 'dark' else '#f8fafc'}; overflow: hidden; }}
  </style>
</head>
<body>
{widget_html}
</body>
</html>
"""
    dest = Path(out_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(full_html, encoding="utf-8")
    return dest
