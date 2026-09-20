// String formatting, DOM utilities, math helpers, and loader functions.
import { TYPE_SHORT, DEFAULTS, STORE_KEY } from './constants.js';

export const esc = (s) => String(s == null ? '' : s)
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

export const relText = (rel) => (rel || '').replace(/_/g, ' ').toLowerCase();

export const fmtDate = (d) => new Date(`${d}T00:00:00Z`).toLocaleDateString('en-US', {
  month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC'
});

export const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export const capitalise = (s) => (s ? s[0].toUpperCase() + s.slice(1) : s);

export function alpha(hex, a) {
  const h = (hex || '#888888').replace('#', '');
  const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
}

// Deterministic seed positions, so the same graph always settles the same way.
export function hashSeed(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return () => {
    h += 0x6d2b79f5;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error(`failed to load ${src}`));
    document.head.appendChild(s);
  });
}

export const resolveGraph = () => (window.graphology && (window.graphology.Graph || window.graphology));
export const resolveSigma = () => (window.Sigma && (window.Sigma.Sigma || window.Sigma));

export function shortLabel(label) {
  let s = label || '';
  if (s.length > 34) {
    const cut = s.search(/[:—–]/);
    if (cut > 10) s = s.slice(0, cut).trim();
  }
  return s.length > 34 ? `${s.slice(0, 32).trimEnd()}…` : s;
}

// Suffix the type only on names that actually collide, so labels stay short.
export function dedupeLabels(nodes) {
  const short = new Map(nodes.map((n) => [n.id, shortLabel(n.label)]));
  const counts = new Map();
  for (const n of nodes) {
    const key = (short.get(n.id) || '').toLowerCase();
    counts.set(key, (counts.get(key) || 0) + 1);
  }
  return new Map(nodes.map((n) => {
    const s = short.get(n.id);
    return [n.id, counts.get((s || '').toLowerCase()) > 1 ? `${s} · ${TYPE_SHORT[n.type] || n.type}` : s];
  }));
}

export function loadSettings() {
  let s = { ...DEFAULTS };
  try {
    const raw = JSON.parse(localStorage.getItem(STORE_KEY) || 'null');
    if (raw && typeof raw === 'object') s = { ...s, ...raw };
  } catch (err) { /* private mode or blocked storage: defaults */ }
  if (typeof window !== 'undefined' && window.location) {
    const q = new URLSearchParams(window.location.search);
    if (q.has('depth')) s.depth = clamp(parseInt(q.get('depth'), 10) || s.depth, 1, 3);
    if (q.get('orphans') === '0') s.orphans = false;
    if (q.get('cmp') === '0') s.comparisons = false;
    if (q.get('cmp') === '1') s.comparisons = true;
  }
  return s;
}
