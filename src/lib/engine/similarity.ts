/** Generic string-similarity primitives. Nothing product-specific lives here. */

export function levenshtein(a: string, b: string): number {
  if (a === b) return 0;
  if (a.length === 0) return b.length;
  if (b.length === 0) return a.length;
  let prev = new Array(b.length + 1);
  let curr = new Array(b.length + 1);
  for (let j = 0; j <= b.length; j++) prev[j] = j;
  for (let i = 1; i <= a.length; i++) {
    curr[0] = i;
    for (let j = 1; j <= b.length; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      curr[j] = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost);
    }
    [prev, curr] = [curr, prev];
  }
  return prev[b.length];
}

export function levenshteinRatio(a: string, b: string): number {
  if (!a && !b) return 1;
  const maxLen = Math.max(a.length, b.length);
  if (maxLen === 0) return 1;
  return 1 - levenshtein(a, b) / maxLen;
}

/** Dice coefficient over character bigrams — robust to word order noise. */
export function diceCoefficient(a: string, b: string): number {
  if (a === b) return 1;
  if (a.length < 2 || b.length < 2) return a === b ? 1 : 0;
  const bigrams = (s: string) => {
    const map = new Map<string, number>();
    for (let i = 0; i < s.length - 1; i++) {
      const bg = s.slice(i, i + 2);
      map.set(bg, (map.get(bg) ?? 0) + 1);
    }
    return map;
  };
  const mapA = bigrams(a);
  const mapB = bigrams(b);
  let intersect = 0;
  for (const [bg, countA] of mapA) {
    const countB = mapB.get(bg) ?? 0;
    intersect += Math.min(countA, countB);
  }
  return (2 * intersect) / (a.length - 1 + b.length - 1);
}

export function jaccardTokens(a: string[], b: string[]): number {
  if (a.length === 0 && b.length === 0) return 1;
  const setA = new Set(a);
  const setB = new Set(b);
  let inter = 0;
  for (const t of setA) if (setB.has(t)) inter++;
  const union = setA.size + setB.size - inter;
  return union === 0 ? 0 : inter / union;
}

/**
 * Token-aware similarity: exact token overlap weighted by token informativeness (IDF-like),
 * with fuzzy credit for near-identical tokens (typos).
 */
export function weightedTokenSimilarity(
  a: string[],
  b: string[],
  idf?: Map<string, number>
): number {
  if (a.length === 0 || b.length === 0) return 0;
  const weight = (t: string) => (idf?.get(t) ?? 1) * (1 + Math.min(t.length, 10) / 10);
  const setB = new Set(b);
  const usedB = new Set<string>();
  let matched = 0;
  let total = 0;
  for (const t of a) {
    const w = weight(t);
    total += w;
    if (setB.has(t) && !usedB.has(t)) {
      matched += w;
      usedB.add(t);
      continue;
    }
    // fuzzy token credit for typos on longer tokens
    let best = 0;
    let bestTok = "";
    for (const u of b) {
      if (usedB.has(u)) continue;
      if (Math.abs(u.length - t.length) > 2 || t.length < 4) continue;
      const r = levenshteinRatio(t, u);
      if (r > best) {
        best = r;
        bestTok = u;
      }
    }
    if (best >= 0.8) {
      matched += w * best * 0.9;
      usedB.add(bestTok);
    }
  }
  let totalB = 0;
  for (const t of b) totalB += weight(t);
  const denom = (total + totalB) / 2;
  return denom === 0 ? 0 : Math.min(1, matched / denom);
}

/** Otsu's method over a score histogram: derives a threshold from the data itself. */
export function otsuThreshold(scores: number[], fallback = 0.5): number {
  if (scores.length < 4) return fallback;
  const bins = 40;
  const hist = new Array<number>(bins).fill(0);
  for (const s of scores) {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor(s * bins)));
    hist[idx]++;
  }
  const total = scores.length;
  let sum = 0;
  for (let i = 0; i < bins; i++) sum += i * hist[i];
  let sumB = 0;
  let wB = 0;
  let maxVar = -1;
  let threshold = fallback * bins;
  for (let i = 0; i < bins; i++) {
    wB += hist[i];
    if (wB === 0) continue;
    const wF = total - wB;
    if (wF === 0) break;
    sumB += i * hist[i];
    const mB = sumB / wB;
    const mF = (sum - sumB) / wF;
    const between = wB * wF * (mB - mF) * (mB - mF);
    if (between > maxVar) {
      maxVar = between;
      threshold = i;
    }
  }
  return (threshold + 1) / bins;
}
