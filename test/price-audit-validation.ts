/**
 * Real-data accuracy check for Price Audit matching — runs the actual
 * detection + matching engine (not a re-implementation) against the two
 * files sitting in the project root: "Panasonic BP (....).xlsx" (internal)
 * and "update price panasonic.xlsx" (vendor). Prints every vendor line,
 * what it was split into, what it matched, the score, and the classification
 * the app would assign, so mismatches are easy to spot by eye.
 *
 * Run: npx tsc test/price-audit-validation.ts --outDir .tmp-check --module commonjs --target es2020 --esModuleInterop --skipLibCheck
 *      node .tmp-check/test/price-audit-validation.js
 */
import { readFileSync } from "fs";
import { parseUploadedFile, parseNumeric } from "../src/lib/parse/file-parser";
import { analyzeColumns, type ColumnRole } from "../src/lib/engine/suggest";
import { analyzeCleaning, cleanValue } from "../src/lib/engine/cleaning";
import { splitSlashVariants, tokenize, buildIdf } from "../src/lib/engine/tokens";
import { otsuThreshold } from "../src/lib/engine/similarity";
import { scorePair, type EngineRow } from "../src/lib/engine/matching";

async function loadRows(path: string, productHint?: string[]): Promise<{ rows: EngineRow[]; roles: Record<ColumnRole, number | null> }> {
  const buf = readFileSync(path);
  const parsed = await parseUploadedFile(buf, path);
  // biggest sheet wins, same rule suggestSheets uses
  const sheet = parsed.sheets.reduce((best, s) => (s.rowCount > best.rowCount ? s : best));
  const cols = analyzeColumns(sheet.headers, sheet.rows, productHint);
  const roles: Record<ColumnRole, number | null> = { product: null, code: null, price: null, category: null, qty: null, qtyRule: null, qtyFrom: null, qtyTo: null, extra: null };
  for (const c of cols) if (c.suggestedRole !== "extra" && roles[c.suggestedRole] === null) roles[c.suggestedRole] = c.index;

  console.log(`\n=== ${path} ===`);
  console.log(`sheet: ${sheet.name} (${sheet.rowCount} rows)`);
  console.log(`detected roles:`, Object.fromEntries(Object.entries(roles).filter(([, v]) => v !== null).map(([k, v]) => [k, `${sheet.headers[v as number]} (col ${v})`])));

  if (roles.product === null) throw new Error(`No product column detected in ${path}`);
  const nameValues = sheet.rows.map((r) => r[roles.product!] ?? "");
  const report = analyzeCleaning(nameValues);
  const ruleIds = report.rules.map((r) => r.id);

  const out: EngineRow[] = [];
  sheet.rows.forEach((row, idx) => {
    const nameRaw = (row[roles.product!] ?? "").trim();
    if (!nameRaw) return;
    const variants = splitSlashVariants(nameRaw);
    for (const variantName of variants) {
      const nameNorm = cleanValue(variantName, ruleIds);
      out.push({
        id: `${idx}:${variantName}`,
        nameRaw: variantName,
        nameNorm,
        tokens: tokenize(nameNorm),
        code: roles.code !== null ? (row[roles.code] ?? "").trim() || null : null,
        variant: null,
        brand: null,
        description: null,
      });
    }
  });
  return { rows: out, roles };
}

async function main() {
  const internalPath = "Panasonic BP (1783387728403).xlsx";
  const vendorPath = "update price panasonic.xlsx";

  const { rows: internalAll } = await loadRows(internalPath);
  const { rows: vendorRows } = await loadRows(vendorPath, internalAll.map((r) => r.nameRaw));

  // scope the internal side to the categories actually relevant here (Fan family) purely
  // to keep the printed report short — the engine itself always scores against everything
  const internalRows = internalAll;

  const idf = buildIdf([...vendorRows, ...internalRows].map((r) => r.tokens));

  interface Row { vendor: EngineRow; best: EngineRow | null; score: number; second: number }
  const results: Row[] = [];
  for (const v of vendorRows) {
    let best: EngineRow | null = null;
    let bestScore = 0;
    let second = 0;
    for (const i of internalRows) {
      const { score } = scorePair(v, i, idf);
      if (score > bestScore) {
        second = bestScore;
        bestScore = score;
        best = i;
      } else if (score > second) {
        second = score;
      }
    }
    results.push({ vendor: v, best, score: bestScore, second });
  }

  const scores = results.map((r) => r.score);
  const tHigh = Math.max(otsuThreshold(scores, 0.65), 0.4);
  const tLow = Math.min(Math.max(otsuThreshold(scores.filter((s) => s < tHigh), tHigh * 0.5), 0.15), tHigh * 0.85);
  console.log(`\nthresholds: high=${tHigh.toFixed(3)} low=${tLow.toFixed(3)}`);

  const pad = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s.padEnd(n));
  console.log(pad("VENDOR", 32) + pad("BEST INTERNAL MATCH", 44) + pad("SCORE", 8) + pad("MARGIN", 8) + "STATUS");
  let matched = 0, review = 0, partial = 0, unmatched = 0;
  for (const r of results) {
    const margin = r.score - r.second;
    let status: string;
    if (r.score >= tHigh && margin >= 0.05) { status = "MATCHED"; matched++; }
    else if (r.score >= tHigh) { status = "NEED_REVIEW"; review++; }
    else if (r.score >= tLow) { status = margin < 0.05 ? "NEED_REVIEW" : "PARTIAL"; if (status === "PARTIAL") partial++; else review++; }
    else { status = "UNMATCHED"; unmatched++; }
    console.log(
      pad(r.vendor.nameRaw, 32) +
        pad(r.best ? r.best.nameRaw : "(none)", 44) +
        pad(r.score.toFixed(3), 8) +
        pad(margin.toFixed(3), 8) +
        status
    );
  }
  console.log(`\nTotal vendor lines (post-split): ${results.length}`);
  console.log(`matched=${matched} need_review=${review} partial=${partial} unmatched=${unmatched}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
