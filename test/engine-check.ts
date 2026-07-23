/**
 * Smallest runnable check for the non-trivial pure logic added for the
 * expanded scope: slash-variant splitting, quantity-rule parsing and
 * transform file-role detection.
 *
 * Run: npx tsc test/engine-check.ts --outDir .tmp-check --module commonjs --target es2020 --esModuleInterop --skipLibCheck && node .tmp-check/test/engine-check.js
 */
import * as assert from "assert";
import { splitSlashVariants, codeSimilarity, tokenize } from "../src/lib/engine/tokens";
import { parseQtyRule, qtyInRange } from "../src/lib/engine/qty-rules";
import { PIPELINES, detectRole, extractFileDate, scoreRole } from "../src/lib/transform/pipelines";
import { analyzeAnomalies, EXTREME_DIFF_PCT } from "../src/lib/engine/anomaly";

// --- slash-separated variant splitting ---
assert.deepStrictEqual(splitSlashVariants("EU 309 W/K"), ["EU 309 W", "EU 309 K"]);
assert.deepStrictEqual(splitSlashVariants("EU 309 W/K/L"), ["EU 309 W", "EU 309 K", "EU 309 L"]);
assert.deepStrictEqual(splitSlashVariants("ABC X1/Y2"), ["ABC X1", "ABC Y2"]);
assert.deepStrictEqual(splitSlashVariants("PIPA PVC 1/2"), ["PIPA PVC 1/2"]); // fraction — untouched
assert.deepStrictEqual(splitSlashVariants("REPORT 10/07/2026"), ["REPORT 10/07/2026"]); // date — untouched
assert.deepStrictEqual(splitSlashVariants("W/K"), ["W/K"]); // no shared base name
assert.deepStrictEqual(splitSlashVariants("PLAIN NAME"), ["PLAIN NAME"]);

// --- quantity-rule parsing (rules always come from the data, never assumed) ---
assert.deepStrictEqual(parseQtyRule(">= 10", null, null), { min: 10, max: null, label: ">= 10" });
assert.deepStrictEqual(parseQtyRule(">=", "10", null), { min: 10, max: null, label: ">= 10" });
assert.deepStrictEqual(parseQtyRule("between 5 and 9", null, null), { min: 5, max: 9, label: "5 - 9" });
assert.deepStrictEqual(parseQtyRule("between", "5", "9"), { min: 5, max: 9, label: "5 - 9" });
assert.deepStrictEqual(parseQtyRule("<= 4", null, null), { min: null, max: 4, label: "<= 4" });
assert.deepStrictEqual(parseQtyRule(null, "1", "4"), { min: 1, max: 4, label: "1 - 4" });
assert.deepStrictEqual(parseQtyRule(null, "10", null), { min: 10, max: null, label: ">= 10" });
assert.strictEqual(parseQtyRule("", null, null), null);
assert.ok(qtyInRange(7, 5, 9) && !qtyInRange(4, 5, 9) && qtyInRange(100, 10, null));

// --- transform file-role detection (keyword prefix + content, never full filename) ---
const bf = PIPELINES["business-flow"];
assert.strictEqual(detectRole(bf, "SO Summary - 9 Jul 2026 (1783602991950).xlsx", "").role, "so");
assert.strictEqual(detectRole(bf, "Packing Summary - 9 Jul 2026 (123).xlsx", "").role, "packing");
assert.strictEqual(detectRole(bf, "Invoice Summary - 10 July 2026 (999).xlsx", "").role, "invoice");
const ds = PIPELINES["daily-sales-performance"];
assert.strictEqual(detectRole(ds, "Invoice - 10 July 2026 (23443543534).xlsx", "").role, "invoice");
assert.strictEqual(detectRole(ds, "Target 2026.xlsx", "").role, "target");
assert.strictEqual(detectRole(ds, "List Brand Name Active (1775788460191).xlsx", "").role, "brand");
assert.strictEqual(extractFileDate("Invoice - 10 July 2026 (23443543534).xlsx"), "10 July 2026");

// shared file tray: plain "Invoice" must NOT be claimed by daily-sales when it is a summary,
// and the summary must outrank the plain invoice for monitoring/business-flow
assert.strictEqual(detectRole(ds, "Invoice Summary - 10 July 2026 (999).xlsx", "").role, null, "daily-sales must reject Invoice Summary");
const mon = PIPELINES["monitoring-sales"];
const invRole = mon.roles.find((r) => r.key === "invoice")!;
assert.ok(
  scoreRole(invRole, "Invoice Summary - 10 July 2026 (999).xlsx", "") >
    scoreRole(invRole, "Invoice - 10 July 2026 (123).xlsx", ""),
  "invoice summary should outrank plain invoice for monitoring"
);
const mkt = PIPELINES["marketing"];
assert.strictEqual(detectRole(mkt, "SO - 9 Jul 2026 (178).xlsx", "").role, "so");
const mktSo = mkt.roles.find((r) => r.key === "so")!;
assert.strictEqual(scoreRole(mktSo, "SO Summary - 9 Jul 2026 (178).xlsx", ""), 0, "marketing so must reject SO Summary");
const trk = PIPELINES["tracker"];
assert.strictEqual(detectRole(trk, "Visit Plan Report - 12 July 2026 (55).xlsx", "").role, "visitplan");

// --- code-identity signal, robust to asymmetric column layouts ---
// both sides have a dedicated code column: exact match wins big
{
  const r = codeSimilarity("EU-309", [], "EU309", []);
  assert.strictEqual(r.score, 1);
  assert.strictEqual(r.weight, 4);
}
// internal has a dedicated Code column; vendor has none but embeds the code
// in its product name instead — must still be found via the name tokens
{
  const vTokens = tokenize("PANASONIC EU309 2500W");
  const r = codeSimilarity(null, vTokens, "EU-309", []);
  assert.ok(r.score >= 0.99, `expected near-exact code match, got ${r.score}`);
  assert.ok(r.weight > 0, "asymmetric code match must carry nonzero weight");
}
// same the other way around: vendor has the dedicated code, internal embeds it in the name
{
  const iTokens = tokenize("PIPA PVC EU309 1/2 INCH");
  const r = codeSimilarity("EU309", [], null, iTokens);
  assert.ok(r.score >= 0.99);
  assert.ok(r.weight > 0);
}
// neither side has a matching code anywhere — no false signal
{
  const r = codeSimilarity("XJ-100", [], null, tokenize("GENERIC PRODUCT NAME"));
  assert.strictEqual(r.weight, 0);
}
// neither side has any code at all — signal simply absent, no crash
{
  const r = codeSimilarity(null, tokenize("PLAIN NAME"), null, tokenize("PLAIN NAME TOO"));
  assert.strictEqual(r.score, 0);
  assert.strictEqual(r.weight, 0);
}

// --- price anomaly detection (independent of match confidence) ---
{
  // a cluster of small, similar increases + one extreme move: only the extreme is "high"
  const r = analyzeAnomalies([
    { id: "a", diffPct: 5 },
    { id: "b", diffPct: 6 },
    { id: "c", diffPct: 5.5 },
    { id: "d", diffPct: 4.5 },
    { id: "e", diffPct: 6.2 },
    { id: "x", diffPct: EXTREME_DIFF_PCT + 20 }, // extreme move
  ]);
  assert.strictEqual(r.byId.get("x")!.severity, "high", "extreme move must be high");
  assert.strictEqual(r.byId.get("a")!.severity, "none", "in-line increase is not an anomaly");
  assert.ok(r.summary.high >= 1);
  assert.strictEqual(r.summary.total, 6, "all six carried a price comparison");
}
{
  // rows with no price comparison (diffPct null) are never flagged and never counted
  const r = analyzeAnomalies([
    { id: "n1", diffPct: null },
    { id: "n2", diffPct: null },
  ]);
  assert.strictEqual(r.byId.get("n1")!.severity, "none");
  assert.strictEqual(r.summary.total, 0);
  assert.strictEqual(r.summary.high + r.summary.medium, 0);
}
{
  // a statistical outlier (far from peers) is flagged even when well below the extreme ceiling
  const items = [
    ...Array.from({ length: 10 }, (_, i) => ({ id: `p${i}`, diffPct: 10 + (i % 2) })), // tight cluster ~10-11%
    { id: "out", diffPct: 40 }, // way off, but < EXTREME_DIFF_PCT
  ];
  const r = analyzeAnomalies(items);
  assert.notStrictEqual(r.byId.get("out")!.severity, "none", "statistical outlier must be flagged");
}

console.log("engine-check OK");
