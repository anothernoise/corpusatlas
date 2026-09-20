# @corpusatlas/graph

> Autonomous, zero-dependency interactive Knowledge Graph Web Component (`<corpusatlas-graph>`).

Embed live, interactive knowledge graphs into static sites, documentation engines (Docusaurus, VitePress, MkDocs Material, Astro, Starlight, Hugo), and web applications with a single custom element.

---

## Features

- **Zero Runtime Dependencies**: Native HTML5 Canvas and WebGL rendering in under 15KB gzipped.
- **Autonomous & Self-Contained**: Shadow DOM isolation protects against external CSS collisions.
- **Interactive Force Simulation**: Pan, zoom, drag nodes, inspect relationships, and focus subgraphs.
- **Theme-Aware**: Seamless auto/light/dark modes matching your documentation site.
- **Bi-Directional Linking**: Click nodes to navigate or inspect claims and provenance evidence.

---

## Quick Start

### 1. Plain HTML / CDN
```html
<script type="module" src="https://cdn.jsdelivr.net/npm/@corpusatlas/graph@0.11.0/dist/corpusatlas-graph.js"></script>

<corpusatlas-graph
  src="graph.json"
  theme="dark"
  height="600px">
</corpusatlas-graph>
```

### 2. React / Next.js
```tsx
import '@corpusatlas/graph';

export default function KnowledgeBase() {
  return (
    <corpusatlas-graph
      src="/data/graph.json"
      focus="apache-spark"
      height="500px"
    />
  );
}
```

### 3. Docusaurus / Markdown
```html
<corpusatlas-graph src="/graph.json" height="450px"></corpusatlas-graph>
```

---

## Attributes & API

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `src` | `string` | `""` | URL to CorpusAtlas `graph.json` data file. |
| `focus` | `string` | `""` | Node ID to center and highlight on load. |
| `theme` | `"auto" \| "dark" \| "light"` | `"auto"` | Color scheme mode. |
| `layout` | `"force" \| "dag"` | `"force"` | Layout positioning algorithm. |
| `height` | `string` | `"500px"` | Canvas container height. |
| `width` | `string` | `"100%"` | Canvas container width. |

---

## License
MIT &copy; Dmitry Shirokov
