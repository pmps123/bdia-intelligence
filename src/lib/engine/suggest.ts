import { parseNumeric } from "@/lib/parse/file-parser";

/**
 * Automatic detection heuristics. Works purely on the sampled rows of an
 * uploaded worksheet — no column name, sheet name or vendor is ever assumed.
 * Header keywords only *boost* a suggestion; the statistics decide.
 */

export type ColumnRole = "product" | "code" | "price" | "category" | "qty" | "qtyRule" | "qtyFrom" | "qtyTo" | "extra";

export interface ColumnStats {
  index: number;
  header: string;
  dataType: "numeric" | "text" | "mixed" | "empty";
  uniqueness: number; // unique / non-empty
  avgLength: number;
  numericRatio: number;
  duplicateRatio: number;
  crossSimilarity: number; // token overlap with the other dataset's product column
  operatorRatio: number; // values that look like quantity rules (>=, between, 5-9, ...)
  suggestedRole: ColumnRole;
}

export interface SheetSuggestion {
  name: string;
  rowCount: number;
  score: number;
  columns: ColumnStats[];
}

function columnValues(rows: string[][], index: number): string[] {
  return rows.map((r) => (r[index] ?? "").trim()).filter((v) => v !== "");
}

const ROLE_HINTS: [ColumnRole, RegExp][] = [
  ["qtyRule", /rule|aturan|syarat/i],
  ["qtyFrom", /from|dari|min\b/i],
  ["qtyTo", /\bto\b|sampai|hingga|s\.?d\.?|max\b/i],
  ["price", /price|harga|amount|nilai|rp|idr|cost/i],
  ["code", /code|kode|sku|part|artikel|item ?no/i],
  ["qty", /qty|quantity|jumlah|stok|stock/i],
  ["category", /categor|kategori|group|kelompok|jenis/i],
  ["product", /name|nama|product|produk|item|barang|deskripsi|description/i],
];

// values that read as a quantity rule: ">= 10", "between 5 and 9", "5 - 9", "<="
const QTY_RULE_VALUE_RE = /^(>=|<=|>|<|=|between|antara)\s*\d*|^\s*\d+\s*[-–]\s*\d+\s*$/i;

export function analyzeColumns(headers: string[], rows: string[][], otherProductSample?: string[]): ColumnStats[] {
  const otherTokens = new Set(
    (otherProductSample ?? [])
      .flatMap((v) => v.toUpperCase().split(/[^\p{L}\p{N}]+/u))
      .filter((t) => t.length > 2)
  );

  const stats: ColumnStats[] = headers.map((header, index) => {
    const values = columnValues(rows, index);
    const n = values.length;
    if (n === 0) {
      return { index, header, dataType: "empty" as const, uniqueness: 0, avgLength: 0, numericRatio: 0, duplicateRatio: 0, crossSimilarity: 0, operatorRatio: 0, suggestedRole: "extra" as const };
    }
    // a value is numeric only if it parses AND is not mostly text ("PIPA 1/2" is a name, "Rp 12.500" is a number)
    const numeric = values.filter((v) => parseNumeric(v) !== null && /\d/.test(v) && (v.match(/\p{L}/gu) ?? []).length <= 2).length;
    const numericRatio = numeric / n;
    const unique = new Set(values.map((v) => v.toUpperCase())).size;
    const uniqueness = unique / n;
    const avgLength = values.reduce((a, v) => a + v.length, 0) / n;
    let crossSimilarity = 0;
    if (otherTokens.size > 0) {
      const tokens = values.flatMap((v) => v.toUpperCase().split(/[^\p{L}\p{N}]+/u)).filter((t) => t.length > 2);
      if (tokens.length > 0) crossSimilarity = tokens.filter((t) => otherTokens.has(t)).length / tokens.length;
    }
    return {
      index,
      header,
      dataType: (numericRatio > 0.85 ? "numeric" : numericRatio < 0.15 ? "text" : "mixed") as ColumnStats["dataType"],
      uniqueness,
      avgLength,
      numericRatio,
      duplicateRatio: 1 - uniqueness,
      crossSimilarity,
      operatorRatio: values.filter((v) => QTY_RULE_VALUE_RE.test(v)).length / n,
      suggestedRole: "extra" as const,
    };
  });

  const hintFor = (header: string): ColumnRole | null => {
    for (const [role, re] of ROLE_HINTS) if (re.test(header)) return role;
    return null;
  };

  // score each column per role, pick the best column per role (product & price required)
  const scoreRole = (s: ColumnStats, role: ColumnRole): number => {
    let score = 0;
    if (role === "product") score = (s.dataType === "text" ? 1 : 0) * (s.uniqueness * 2 + Math.min(s.avgLength, 40) / 40 + s.crossSimilarity * 2);
    if (role === "price") score = s.numericRatio * 2 + s.uniqueness * 0.3 + (s.avgLength >= 3 && s.avgLength <= 15 ? 0.3 : 0);
    if (role === "code") score = (s.dataType !== "numeric" ? 0.3 : 0) + s.uniqueness * 1.5 + (s.avgLength >= 3 && s.avgLength <= 15 ? 0.7 : 0);
    if (role === "qty") score = s.numericRatio * 1.2 + (s.avgLength <= 6 ? 0.4 : 0);
    if (role === "category") score = (s.dataType === "text" ? 1 : 0) * (s.duplicateRatio * 1.5 + (s.avgLength <= 25 ? 0.3 : 0));
    // quantity-gradation columns (Customized Price): content decides, headers only boost
    if (role === "qtyRule") score = s.operatorRatio * 3;
    if (role === "qtyFrom" || role === "qtyTo") score = s.numericRatio * 0.8 + (s.avgLength <= 6 ? 0.3 : 0);
    if (hintFor(s.header) === role) score += 1.5;
    return score;
  };

  // A numeric column whose values are a near-constant ratio of the chosen
  // price column (e.g. "Invoice Price + PPN" = Basic Price × 1.11, or an
  // exact duplicate) is another price figure, not a product code — even
  // though it can look "code-like" on uniqueness/length alone. Detected
  // from the data itself, never from a column name.
  const isPriceDerived = (candidateIdx: number, priceIdx: number): boolean => {
    const ratios: number[] = [];
    for (const row of rows) {
      const a = parseNumeric(row[candidateIdx]);
      const b = parseNumeric(row[priceIdx]);
      if (a === null || b === null || b === 0) continue;
      ratios.push(a / b);
    }
    if (ratios.length < Math.max(5, rows.length * 0.5)) return false; // not enough evidence either way
    const mean = ratios.reduce((sum, x) => sum + x, 0) / ratios.length;
    if (mean === 0) return false;
    const variance = ratios.reduce((sum, x) => sum + (x - mean) * (x - mean), 0) / ratios.length;
    const coeffOfVariation = Math.sqrt(variance) / Math.abs(mean);
    return coeffOfVariation < 0.03;
  };

  const taken = new Set<number>();
  let priceIndex: number | null = null;
  for (const role of ["product", "price", "code", "qtyRule", "qtyFrom", "qtyTo", "qty", "category"] as ColumnRole[]) {
    let best: ColumnStats | null = null;
    let bestScore = 0;
    for (const s of stats) {
      if (taken.has(s.index) || s.dataType === "empty") continue;
      if (role === "code" && priceIndex !== null && s.dataType === "numeric" && isPriceDerived(s.index, priceIndex)) continue;
      const sc = scoreRole(s, role);
      if (sc > bestScore) {
        bestScore = sc;
        best = s;
      }
    }
    // minimum evidence: required roles (product, price) get lower bar than optional ones
    const bar = role === "product" || role === "price" ? 0.8 : 1.6;
    if (best && bestScore >= bar) {
      best.suggestedRole = role;
      taken.add(best.index);
    }
    if (role === "price" && best) priceIndex = best.index;
  }
  return stats;
}

/** Suggest which worksheet to use: most data rows wins, tabular shape breaks ties. */
export function suggestSheets(
  sheets: { name: string; rowCount: number; headers: string[]; preview: string[][] }[],
  otherProductSample?: string[]
): SheetSuggestion[] {
  return sheets
    .map((s) => ({
      name: s.name,
      rowCount: s.rowCount,
      score: s.rowCount * Math.max(s.headers.length, 1),
      columns: analyzeColumns(s.headers, s.preview, otherProductSample),
    }))
    .sort((a, b) => b.score - a.score);
}
