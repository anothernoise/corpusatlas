// Full-text fuzzy search engine with score ranking and typeahead highlights.

/**
 * Fuzzy scoring algorithm calculating score between query and target string.
 * Returns a score between 0 (no match) and 1 (exact match).
 */
export function fuzzyScore(query, target) {
  if (!query || !target) return 0;
  const q = query.toLowerCase().trim();
  const t = target.toLowerCase();

  if (t === q) return 1.0;
  if (t.startsWith(q)) return 0.95;

  // Word boundary match bonus
  const words = t.split(/[\s_\-:/.]+/);
  for (const w of words) {
    if (w === q) return 0.90;
    if (w.startsWith(q)) return 0.85;
  }

  if (t.includes(q)) return 0.75;

  // Subsequence match with gap penalty
  let qIdx = 0;
  let tIdx = 0;
  let matches = 0;
  let consecutive = 0;
  let score = 0;

  while (qIdx < q.length && tIdx < t.length) {
    if (q[qIdx] === t[tIdx]) {
      matches++;
      consecutive++;
      score += 1 + consecutive * 0.5;
      qIdx++;
    } else {
      consecutive = 0;
    }
    tIdx++;
  }

  if (qIdx === q.length) {
    const coverage = matches / t.length;
    return Math.min(0.70, (score / (q.length * 2)) * 0.5 + coverage * 0.2);
  }

  return 0;
}

/**
 * Create an in-memory searchable index over entities and evidence.
 */
export function createSearchEngine(entities = [], context = new Map()) {
  const index = entities.map((e) => {
    const ctx = context.get(e.id) || { articles: [], radar: [], assessments: [] };
    const articles = (ctx.articles || []).map((a) => a.label || '').join(' ');
    const radar = (ctx.radar || []).map((r) => r.label || '').join(' ');
    const description = (e.meta && e.meta.description) || '';
    const aliases = ((e.meta && e.meta.aliases) || []).join(' ');

    return {
      id: e.id,
      label: e.label || e.id,
      type: e.type || 'Technology',
      description,
      haystack: `${e.label} ${e.id} ${aliases} ${e.type} ${description} ${radar} ${articles}`.toLowerCase(),
      entity: e,
    };
  });

  function search(query, { limit = 8, filterTypes = null } = {}) {
    if (!query || !query.trim()) return [];
    const q = query.toLowerCase().trim();

    const results = [];
    for (const doc of index) {
      if (filterTypes && filterTypes.has(doc.type)) continue;

      let bestScore = fuzzyScore(q, doc.label);
      if (doc.entity.meta && doc.entity.meta.aliases) {
        for (const alias of doc.entity.meta.aliases) {
          bestScore = Math.max(bestScore, fuzzyScore(q, alias) * 0.95);
        }
      }

      if (bestScore === 0 && doc.haystack.includes(q)) {
        bestScore = 0.35;
      }

      if (bestScore > 0.2) {
        results.push({
          id: doc.id,
          label: doc.label,
          type: doc.type,
          description: doc.description,
          score: bestScore,
        });
      }
    }

    results.sort((a, b) => b.score - a.score || a.label.localeCompare(b.label));
    return results.slice(0, limit);
  }

  return {
    search,
    count: () => index.length,
  };
}
