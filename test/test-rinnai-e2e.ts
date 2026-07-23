/**
 * End-to-end sanity check: parses the real Rinnai PDF (vendor) and the real
 * Rinnai Excel benchmark (internal), runs the actual fuzzy matching engine
 * (scorePair + Otsu thresholds, same code runMatching uses), and prints
 * vendor price vs internal price for every match so price increases are
 * easy to eyeball. Not a replacement for running the real wizard - just a
 * quick check that the parser fix + engine produce a usable result together.
 */
import { readFileSync } from "fs";
import { parseUploadedFile, parseNumeric } from "../src/lib/parse/file-parser";
import { analyzeColumns, type ColumnRole } from "../src/lib/engine/suggest";
import { analyzeCleaning, cleanValue } from "../src/lib/engine/cleaning";
import { splitSlashVariants, tokenize, buildIdf } from "../src/lib/engine/tokens";
import { otsuThreshold } from "../src/lib/engine/similarity";
import { scorePair, type EngineRow } from "../src/lib/engine/matching";

async function loadRows(
  path: string,
  productHint?: string[]
): Promise<{ rows: EngineRow[]; roles: Record<ColumnRole, number | null>; sheetRows: string[][]; headers: string[] }> {
  const buf = readFileSync(path);
  const parsed = await parseUploadedFile(buf, path);
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
  return { rows: out, roles, sheetRows: sheet.rows, headers: sheet.headers };
}

async function main() {
  const vendorPath = "Pricelist Rinnai 3H Zona 1 efektif 22 JULI 2026 REV signed.pdf";
  const internalPath = "Rinnai 3H BP (1784774419220).xlsx";

  const { rows: internalAll, roles: internalRoles, sheetRows: internalSheetRows } = await loadRows(internalPath);
  const { rows: vendorRows, roles: vendorRoles, sheetRows: vendorSheetRows } = await loadRows(vendorPath, internalAll.map((r) => r.nameRaw));

  if (vendorRoles.price === null) throw new Error("No price column detected in vendor PDF - inspect output above.");
  if (internalRoles.price === null) throw new Error("No price column detected in internal Excel - inspect output above.");

  const idf = buildIdf([...vendorRows, ...internalAll].map((r) => r.tokens));

  interface Row { vendor: EngineRow; best: EngineRow | null; score: number; second: number; vendorIdx: number }
  const results: Row[] = [];
  for (const v of vendorRows) {
    let best: EngineRow | null = null;
    let bestScore = 0;
    let second = 0;
    for (const i of internalAll) {
      const { score } = scorePair(v, i, idf);
      if (score > bestScore) {
        second = bestScore;
        bestScore = score;
        best = i;
      } else if (score > second) {
        second = score;
      }
    }
    const vendorIdx = Number(v.id.split(":")[0]);
    results.push({ vendor: v, best, score: bestScore, second, vendorIdx });
  }

  const scores = results.map((r) => r.score);
  const tHigh = Math.max(otsuThreshold(scores, 0.65), 0.4);
  const tLow = Math.min(Math.max(otsuThreshold(scores.filter((s) => s < tHigh), tHigh * 0.5), 0.15), tHigh * 0.85);
  console.log(`\nthresholds: high=${tHigh.toFixed(3)} low=${tLow.toFixed(3)}`);

  const pad = (s: string, n: number) => (s.length > n ? s.slice(0, n - 1) + "…" : s.padEnd(n));
  console.log(
    pad("VENDOR", 26) + pad("BEST INTERNAL MATCH", 40) + pad("SCORE", 7) + pad("STATUS", 13) + pad("VENDOR PRICE", 14) + pad("INTERNAL PRICE", 14) + "DELTA"
  );
  let matched = 0, review = 0, partial = 0, unmatched = 0, priceUp = 0, priceDown = 0, priceSame = 0;
  for (const r of results) {
    const margin = r.score - r.second;
    let status: string;
    if (r.score >= tHigh && margin >= 0.05) { status = "MATCHED"; matched++; }
    else if (r.score >= tHigh) { status = "NEED_REVIEW"; review++; }
    else if (r.score >= tLow) { status = margin < 0.05 ? "NEED_REVIEW" : "PARTIAL"; if (status === "PARTIAL") partial++; else review++; }
    else { status = "UNMATCHED"; unmatched++; }

    const vendorPriceRaw = vendorSheetRows[r.vendorIdx]?.[vendorRoles.price!] ?? "";
    const vendorPrice = parseNumeric(vendorPriceRaw);
    let deltaStr = "";
    let internalPriceStr = "";
    if (r.best && status !== "UNMATCHED") {
      const internalIdx = Number(r.best.id.split(":")[0]);
      const internalPrice = parseNumeric(internalSheetRows[internalIdx]?.[internalRoles.price!] ?? "");
      internalPriceStr = internalPrice !== null ? internalPrice.toLocaleString("id-ID") : "?";
      if (vendorPrice !== null && internalPrice !== null && internalPrice !== 0) {
        const pct = ((vendorPrice - internalPrice) / internalPrice) * 100;
        deltaStr = `${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
        if (pct > 0.5) priceUp++;
        else if (pct < -0.5) priceDown++;
        else priceSame++;
      }
    }
    console.log(
      pad(r.vendor.nameRaw, 26) +
        pad(r.best ? r.best.nameRaw : "(none)", 40) +
        pad(r.score.toFixed(3), 7) +
        pad(status, 13) +
        pad(vendorPrice !== null ? vendorPrice.toLocaleString("id-ID") : String(vendorPriceRaw), 14) +
        pad(internalPriceStr, 14) +
        deltaStr
    );
  }
  console.log(`\nTotal vendor lines (post-split): ${results.length}`);
  console.log(`matched=${matched} need_review=${review} partial=${partial} unmatched=${unmatched}`);
  console.log(`price up=${priceUp} down=${priceDown} same=${priceSame} (only counted for matched/partial/need_review rows with both prices readable)`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
