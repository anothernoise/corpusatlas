// Constants, palettes, schemas, and default configurations for CorpusAtlas viewer.

export const CDN = {
  graphology: 'https://cdn.jsdelivr.net/npm/graphology@0.25.4/dist/graphology.umd.min.js',
  sigma: 'https://cdn.jsdelivr.net/npm/sigma@3.0.1/dist/sigma.min.js',
};

export const TYPE_COLOR = {
  Concept:             '#14b8a6',
  ArchitecturePattern: '#0d9488',
  Technology:          '#f59e0b',
  Component:           '#f97316',
  Language:            '#fbbf24',
  API:                 '#d97706',
  Protocol:            '#eab308',
  Standard:            '#ca8a04',
  FileFormat:          '#fb923c',
  TableFormat:         '#ea580c',
  Product:             '#ec4899',
  CloudService:        '#db2777',
  Company:             '#6366f1',
  UseCase:             '#06b6d4',
  // Biological & Ecological types
  Mammal:              '#f59e0b',
  Bird:                '#06b6d4',
  Reptile:             '#10b981',
  Amphibian:           '#84cc16',
  Fish:                '#3b82f6',
  Invertebrate:        '#8b5cf6',
  Habitat:             '#14b8a6',
  Diet:                '#ec4899',
  Taxon:               '#a855f7',
  Animal:              '#f97316',
};

export const DYNAMIC_PALETTE = [
  '#f59e0b', '#14b8a6', '#ec4899', '#3b82f6', '#8b5cf6',
  '#10b981', '#f97316', '#06b6d4', '#eab308', '#6366f1',
  '#84cc16', '#a855f7', '#0ea5e9', '#f43f5e', '#d946ef'
];

export function getTypeColor(type) {
  if (TYPE_COLOR[type]) return TYPE_COLOR[type];
  let hash = 0;
  for (let i = 0; i < (type || "").length; i++) hash = (hash * 31 + type.charCodeAt(i)) | 0;
  return DYNAMIC_PALETTE[Math.abs(hash) % DYNAMIC_PALETTE.length];
}

export const TYPE_LABEL = {
  Concept: 'Concept', ArchitecturePattern: 'Architecture pattern', Technology: 'Technology',
  Component: 'Component', Language: 'Language', API: 'API', Protocol: 'Protocol', Standard: 'Standard',
  FileFormat: 'File format', TableFormat: 'Table format', Product: 'Product', CloudService: 'Cloud service',
  Company: 'Company', UseCase: 'Use case',
  Document: 'Article', Assessment: 'Radar assessment', RadarEntry: 'Radar entry', Topic: 'Topic',
  Mammal: 'Mammal', Bird: 'Bird', Reptile: 'Reptile', Amphibian: 'Amphibian', Fish: 'Fish',
  Invertebrate: 'Invertebrate', Habitat: 'Habitat', Diet: 'Diet', Taxon: 'Taxon', Animal: 'Animal',
};

export const TYPE_SHORT = {
  Concept: 'Concept', ArchitecturePattern: 'Pattern', Technology: 'Tech', Component: 'Component',
  Language: 'Language', API: 'API', Protocol: 'Protocol', Standard: 'Standard', FileFormat: 'Format',
  TableFormat: 'Table format', Product: 'Product', CloudService: 'Service', Company: 'Company', UseCase: 'Use case',
  Mammal: 'Mammal', Bird: 'Bird', Reptile: 'Reptile', Amphibian: 'Amphibian', Fish: 'Fish',
  Invertebrate: 'Invert', Habitat: 'Habitat', Diet: 'Diet', Taxon: 'Taxon', Animal: 'Animal',
};

export const ENTITY_ORDER = [
  'Technology', 'Component', 'Product', 'CloudService', 'Concept', 'ArchitecturePattern',
  'Language', 'API', 'Protocol', 'Standard', 'FileFormat', 'TableFormat', 'Company', 'UseCase',
  'Mammal', 'Bird', 'Reptile', 'Amphibian', 'Fish', 'Invertebrate', 'Habitat', 'Diet', 'Taxon', 'Animal'
];

export const DEFAULTS = {
  depth: 1, orphans: true, comparisons: true,
  textFade: 7, nodeSize: 1, linkWidth: 1, arrows: false,
  center: 0.4, repel: 25, link: 1,
  hiddenTypes: [],
};

export const STORE_KEY = 'kb-graph-settings-v2';
export const COMPARES_WEIGHT = 0.25;
export const RATIO_MIN = 0.08;
export const RATIO_MAX = 1.6;
export const CITE_CAP = 10;
export const MINIMAP_SIZE = 116;

export const REL_GROUP_COLOR = {
  Structure: '#38bdf8', Concepts: '#a78bfa', 'Data flow': '#34d399',
  Commercial: '#fb7185', Alternatives: '#fbbf24',
  Trophic: '#ef4444', Ecology: '#10b981', Taxonomy: '#3b82f6', Comparative: '#8b5cf6',
  Other: '#94a3b8',
};

export const COMMUNITY_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6',
  '#06b6d4', '#f97316', '#14b8a6', '#6366f1', '#84cc16',
  '#e11d48', '#0284c7', '#a855f7', '#d97706', '#059669',
  '#4f46e5', '#ca8a04', '#db2777', '#2563eb', '#16a34a'
];
