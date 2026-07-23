/**
 * Price-audit anomaly detection. Pure, deterministic, no I/O — runs on the price-validation
 * items and flags rows worth a human's attention *independent of how confident the matching
 * engine was*: a confidently-matched row with an implausible price swing is exactly the kind of
 * thing an auditor must still see. Two signals, both derived from the data itself (no fixed
 * catalog, vendor or category is ever assumed):
 *
 *  1. Extreme move  — |% change| past a plausibility ceiling. Almost always either a real event
 *     worth negotiating or a wrong match / misread number worth correcting; either way, flag it.
 *  2. Statistical outlier — the % change sits far (z-score) from the mean change of its peers.
 *     Peers are the same category when categories are present and populated enough to be
 *     meaningful, otherwise the whole run. A vendor raising one item 3σ more than everything else
 *     it raised is a targeted increase the blanket "% up" stat hides.
 */

// ponytail: fixed plausibility ceiling for "always double-check this move" - revisit if legitimate
// vendor increases regularly exceed it (seen so far on real files: ~18%, far below).
export const EXTREME_DIFF_PCT = 80;

// z-score cutoffs: >=3σ is a strong outlier (rank with the extreme moves), >=2σ is worth a look.
const Z_HIGH = 3;
const Z_MEDIUM = 2;

// a category grouping is only trustworthy when there are at least this many priced peers in it -
// a z-score over 2-3 points is noise. Below this, the item falls back to the whole-run group.
const MIN_GROUP = 5;

export type AnomalySeverity = "high" | "medium" | "none";

export interface AnomalyInput {
  id: string;
  diffPct: number | null;
  category?: string | null;
}

export interface AnomalyResult {
  severity: AnomalySeverity;
  reason: string;
  z: number | null;
}

export interface AnomalySummary {
  high: number;
  medium: number;
  total: number; // items that carried a real price comparison (a diffPct)
}

interface GroupStats {
  mean: number;
  sd: number;
  n: number;
}

function statsOf(values: number[]): GroupStats {
  const n = values.length;
  if (n === 0) return { mean: 0, sd: 0, n: 0 };
  const mean = values.reduce((a, v) => a + v, 0) / n;
  const variance = values.reduce((a, v) => a + (v - mean) * (v - mean), 0) / n;
  return { mean, sd: Math.sqrt(variance), n };
}

/** Analyze a run's items; returns a per-item verdict (keyed by id) plus a run-level tally. */
export function analyzeAnomalies(items: AnomalyInput[]): { byId: Map<string, AnomalyResult>; summary: AnomalySummary } {
  const priced = items.filter((it) => it.diffPct !== null);

  // group by category only when categories are actually present and each group is big enough to
  // be statistically meaningful; otherwise everything shares one whole-run group ("")
  const byCategory = new Map<string, number[]>();
  for (const it of priced) {
    const key = (it.category ?? "").trim();
    const arr = byCategory.get(key);
    if (arr) arr.push(it.diffPct as number);
    else byCategory.set(key, [it.diffPct as number]);
  }
  const usableCategories = [...byCategory.entries()].filter(([k, v]) => k !== "" && v.length >= MIN_GROUP);
  const useCategories = usableCategories.length >= 2;

  const globalStats = statsOf(priced.map((it) => it.diffPct as number));
  const groupStats = new Map<string, GroupStats>();
  if (useCategories) for (const [k, v] of byCategory) groupStats.set(k, statsOf(v));

  const byId = new Map<string, AnomalyResult>();
  let high = 0;
  let medium = 0;

  for (const it of items) {
    if (it.diffPct === null) {
      byId.set(it.id, { severity: "none", reason: "", z: null });
      continue;
    }
    const pct = it.diffPct;
    const key = (it.category ?? "").trim();
    const g = useCategories && key !== "" && (groupStats.get(key)?.n ?? 0) >= MIN_GROUP ? groupStats.get(key)! : globalStats;
    const z = g.sd > 0 ? (pct - g.mean) / g.sd : 0;
    const absZ = Math.abs(z);

    let severity: AnomalySeverity = "none";
    let reason = "";
    if (Math.abs(pct) >= EXTREME_DIFF_PCT) {
      severity = "high";
      reason = `Perubahan ${pct > 0 ? "kenaikan" : "penurunan"} ${Math.abs(pct).toFixed(1)}% — di luar batas wajar, cek manual`;
    } else if (g.sd > 0 && absZ >= Z_HIGH) {
      severity = "high";
      reason = `Menyimpang ${absZ.toFixed(1)}σ dari rata-rata perubahan peer (${g.mean.toFixed(1)}%) — outlier kuat`;
    } else if (g.sd > 0 && absZ >= Z_MEDIUM) {
      severity = "medium";
      reason = `Menyimpang ${absZ.toFixed(1)}σ dari rata-rata perubahan peer (${g.mean.toFixed(1)}%)`;
    }

    if (severity === "high") high++;
    else if (severity === "medium") medium++;
    byId.set(it.id, { severity, reason, z: g.sd > 0 ? z : null });
  }

  return { byId, summary: { high, medium, total: priced.length } };
}
