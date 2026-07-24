# PDF Text-Layer Table Reconstruction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Progress (updated as tasks complete via subagent-driven-development):** Task 1 ✅ complete, reviewed clean. Task 2 ✅ complete, reviewed clean. Tasks 3-9: see `- [ ]` checkboxes below and `.superpowers/sdd/progress.md` (local, gitignored ledger) for the authoritative up-to-the-minute status.

**Goal:** Replace the whitespace-guessing column splitter for text-layer PDFs with one that reconstructs tables from the PDF's real per-character x/y positions, so vendor PDFs whose extracted text has no reliable spacing (headers currently come out as mashed digits or letterhead addresses) parse correctly.

**Architecture:** A new module (`table-reconstruction.ts`) holds source-agnostic position→table primitives (already proven in the OCR path, just renamed/relocated so both paths can share them). A second new module (`pdf-text-layer.ts`) uses `pdf-parse`'s per-item positions (currently discarded) to build row/column structure, merge wrapped header lines, and backfill spanning-cell labels. `file-parser.ts`'s `parsePdf` tries this path first for non-scanned PDFs and falls back to today's whitespace-split behavior if it can't produce a usable result.

**Tech Stack:** TypeScript, `pdf-parse` (already a dependency, used here via its `pagerender` hook to reach `pdf.js`'s `getTextContent()`), `jiti` (new devDependency, for running `.ts` test scripts with `@/` alias resolution — see Task 1).

## Global Constraints

- Every requirement below comes from `docs/superpowers/specs/2026-07-24-pdf-text-layer-table-reconstruction-design.md` — read it if anything here is ambiguous.
- Zero behavior change to the OCR path (`ocrPdfTable`, `detectRowBands`, `extractHeaderLabels`, `ocrTableBlock`, `recognizeRowWords`) except the `OcrWord` → `PositionedWord` rename, which must not change runtime behavior.
- Zero behavior change to `parseSpreadsheet` (the Excel/CSV path).
- `test/test-rinnai-e2e.ts` and `test/engine-check.ts` must produce **identical** output before and after every task that touches shared code (Tasks 2 and 9 especially).
- `npx tsc --noEmit -p .` must stay clean except for 4 pre-existing errors in `src/app/api/matching/results/[id]/route.ts` and `src/lib/engine/matching.ts` (a `vendorCode` Prisma-schema mismatch, unrelated to this work — confirmed pre-existing before this plan).
- **Local file dependency:** several test steps below read real vendor PDFs from `Data Vendor/` in the project root (`Panasonic Pump.pdf`, `Sanei.pdf`). This folder is local to the machine (not committed to git). If you're executing this plan in a fresh clone or an isolated worktree, copy `Data Vendor/` over from the main working copy first — the steps will fail with `ENOENT` otherwise.
- This machine sometimes runs low on RAM (other processes competing for it). If `npx tsc` or a test run crashes with `FATAL ERROR: ... out of memory` / `Zone Allocation failed`, that's an environment issue, not a code bug — retry once; if it persists, check `systeminfo | grep -i memory` before assuming the code is wrong.

---

## Task 1: Test runner (`test/run.mjs`) + `jiti` devDependency

The existing test scripts (`test/engine-check.ts`, `test/test-rinnai-e2e.ts`) document `npx tsc file.ts --outDir ... && node ...` as their run command in their own header comments, but this **does not work** — plain `tsc`-then-`node` cannot resolve the project's `@/*` path alias (`file-parser.ts` imports `@/lib/types`, `tokens.ts` imports `@/lib/engine/similarity`, etc.), so `node` fails with `Cannot find module '@/lib/...'`. `jiti` (already in `node_modules` as a transitive dependency of Next.js) resolves this cleanly. Every task in this plan runs test scripts through a small `jiti`-based runner instead.

**Files:**
- Modify: `package.json`
- Create: `test/run.mjs`

**Interfaces:**
- Produces: `node test/run.mjs <path/to/script.ts>` — the standard way every later task in this plan runs a `.ts` test script. Run from the project root (`Z:\Rafli\bdia app`).

- [x] **Step 1: Add `jiti` as a devDependency**

Open `package.json`. In the `"devDependencies"` object, the entries are alphabetically ordered. Insert `"jiti": "^2.7.0",` right after `"@types/react-dom": "^19.1.0",` and before `"prisma": "^6.7.0",`:

```json
  "devDependencies": {
    "@tailwindcss/postcss": "^4.1.5",
    "@types/node": "^22.15.0",
    "@types/pdf-parse": "^1.1.4",
    "@types/react": "^19.1.0",
    "@types/react-dom": "^19.1.0",
    "jiti": "^2.7.0",
    "prisma": "^6.7.0",
    "tailwindcss": "^4.1.5",
    "tw-animate-css": "^1.2.9",
    "typescript": "^5.8.3"
  }
```

- [x] **Step 2: Run install to lock it in `package-lock.json`**

Run: `npm install --package-lock-only`
Expected: exits 0, `package-lock.json` gets a diff adding `jiti`. (`--package-lock-only` skips reinstalling `node_modules`, which already has `jiti` present as a transitive dependency — this just records it as a direct one.)

- [x] **Step 3: Create the runner**

Create `test/run.mjs`:

```js
import { createJiti } from "jiti";
import { resolve } from "node:path";

const target = process.argv[2];
if (!target) {
  console.error("Usage: node test/run.mjs <path/to/script.ts>");
  process.exit(1);
}
const jiti = createJiti(import.meta.url, {
  alias: { "@": resolve(process.cwd(), "src") },
});
await jiti.import(resolve(process.cwd(), target));
```

- [x] **Step 4: Verify it works against the existing self-check (this is also your pre-change regression baseline)**

Run: `node test/run.mjs test/engine-check.ts`
Expected: prints `engine-check OK` and exits 0.

Run: `node test/run.mjs test/test-rinnai-e2e.ts`
Expected: exits 0, prints a `VENDOR / BEST INTERNAL MATCH / SCORE / STATUS / ...` table ending in a line like `matched=34 need_review=6 partial=7 unmatched=10`. **Save this exact output** (copy the terminal output to a scratch file, or just note the summary numbers) — Task 2's regression check compares against it.

Note: this second command depends on two files sitting in the project root: `Pricelist Rinnai 3H Zona 1 efektif 22 JULI 2026 REV signed.pdf` and `Rinnai 3H BP (1784774419220).xlsx`. If they're not there (they're local business files, not committed to git), check `Data Vendor/` or ask the user where they've moved to — the script's `main()` function has the exact filenames it expects.

- [x] **Step 5: Commit**

```bash
git add package.json package-lock.json test/run.mjs
git commit -m "Add jiti-based test runner (existing tsc+node instructions don't resolve @/ alias)"
```

---

## Task 2: Extract `table-reconstruction.ts` (shared position→table primitives)

`detectColumnBoundaries`, `wordsToRow`, and `alignBlocksToCommonColumns` (plus the `OcrWord` interface and `parseNumeric`, which `alignBlocksToCommonColumns` depends on transitively through `profileColumn`) currently live in `file-parser.ts` and only serve the OCR path. They're already source-agnostic — nothing in their bodies assumes OCR. Move them to a new file so `pdf-text-layer.ts` (Task 3+) can use them too, without creating a circular import (`file-parser.ts` will need to import from `pdf-text-layer.ts` in Task 9, so the shared code can't live in `file-parser.ts` and be imported back from `pdf-text-layer.ts`).

`parseNumeric` is currently imported by `src/lib/engine/suggest.ts` and both existing test scripts via `from "@/lib/parse/file-parser"` — that import path must keep working, so `file-parser.ts` re-exports it after the move.

**Files:**
- Create: `src/lib/parse/table-reconstruction.ts`
- Modify: `src/lib/parse/file-parser.ts`

**Interfaces:**
- Produces: `PositionedWord` (interface: `{ text: string; confidence?: number; x0: number; x1: number; y0: number; y1: number }`), `parseNumeric(value: string | null | undefined): number | null`, `detectColumnBoundaries(lines: PositionedWord[][]): number[]`, `wordsToRow(words: PositionedWord[], boundaries: number[]): string[]`, `alignBlocksToCommonColumns(blocks: string[][][]): string[][]` — all exported from `src/lib/parse/table-reconstruction.ts`. Tasks 3-9 import from here, not from `file-parser.ts`.

- [x] **Step 1: Create `table-reconstruction.ts`**

```ts
/**
 * Generic table-reconstruction primitives - column/row layout inferred purely from item
 * positions, with no assumption about where those positions came from (OCR word boxes or a real
 * PDF's own text layer). Both src/lib/parse/file-parser.ts (OCR path) and
 * src/lib/parse/pdf-text-layer.ts (text-layer PDF path) feed this the same shape.
 */

/** A single piece of text with its position - from OCR (Tesseract word boxes) or a real PDF's
 * text layer (pdf.js item positions). Column/row reconstruction only needs position, never the
 * source, so both feed the same functions here. */
export interface PositionedWord {
  text: string;
  confidence?: number;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

/** Parse a numeric value out of arbitrary formatting (1.234,56 / 1,234.56 / Rp 1.000 / etc.). */
export function parseNumeric(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  let s = String(value).trim();
  if (s === "") return null;
  s = s.replace(/[^\d.,\-()]/g, "");
  if (s === "" || s === "-" ) return null;
  const negative = /^\(.*\)$/.test(s);
  s = s.replace(/[()]/g, "");
  const lastComma = s.lastIndexOf(",");
  const lastDot = s.lastIndexOf(".");
  if (lastComma > -1 && lastDot > -1) {
    // whichever separator comes last is usually the decimal separator - except when the group
    // after it is exactly 3 digits, which a real decimal fraction in this domain never is (prices
    // don't carry thousandths) and a genuine thousands group always is. OCR occasionally misreads
    // just the LAST "." of an all-thousands number as "," (confirmed directly on a real document:
    // "3.139.000" read as "3.139,000") - the plain "last wins" rule then reads it as a fraction
    // three orders of magnitude too small instead of the thousands group it actually is.
    const lastSep = Math.max(lastComma, lastDot);
    const trailingDigits = s.length - lastSep - 1;
    if (trailingDigits === 3) s = s.replace(/[.,]/g, "");
    else if (lastComma > lastDot) s = s.replace(/\./g, "").replace(",", ".");
    else s = s.replace(/,/g, "");
  } else if (lastComma > -1) {
    const decimals = s.length - lastComma - 1;
    s = decimals === 3 && s.length > 4 ? s.replace(/,/g, "") : s.replace(",", ".");
  } else if (lastDot > -1) {
    const decimals = s.length - lastDot - 1;
    if (decimals === 3 && s.length > 4) s = s.replace(/\./g, "");
  }
  const n = Number(s);
  if (Number.isNaN(n)) return null;
  return negative ? -n : n;
}

/**
 * Column boundaries derived from where text actually sits, not from
 * spacing in flattened text. A printed table's cell content never crosses a
 * ruled column border, so the x-ranges words occupy leave real empty gaps
 * exactly at the column dividers - find those gaps, no layout assumed.
 *
 * Coverage is counted per row, not unioned across all words: a table title
 * or footnote that spans the full block width would otherwise fill in every
 * gap for the whole block (it did, on the first real document tested against
 * this). A gap only "counts" as filled where enough distinct rows actually
 * have content there - one wide outlier row can't erase it.
 */
export function detectColumnBoundaries(lines: PositionedWord[][]): number[] {
  const words = lines.flat();
  if (words.length === 0) return [];
  const minX = Math.floor(Math.min(...words.map((w) => w.x0)));
  const maxX = Math.ceil(Math.max(...words.map((w) => w.x1)));
  const span = maxX - minX;
  if (span <= 0) return [];
  const coverage = new Array<number>(span).fill(0);
  for (const line of lines) {
    const touched = new Array<boolean>(span).fill(false);
    for (const w of line) {
      const from = Math.max(0, Math.floor(w.x0) - minX);
      const to = Math.min(span, Math.ceil(w.x1) - minX);
      for (let x = from; x < to; x++) touched[x] = true;
    }
    for (let x = 0; x < span; x++) if (touched[x]) coverage[x]++;
  }
  // ponytail: fixed 15%-of-rows outlier tolerance and fixed min-gap width; revisit if a
  // vendor's table regularly has more than a couple of full-width title/footnote rows.
  const maxOutlierLines = Math.max(1, Math.floor(lines.length * 0.15));
  const minGap = Math.max(10, span * 0.015);
  const boundaries: number[] = [];
  let gapStart = -1;
  for (let x = 0; x <= span; x++) {
    const empty = x < span && coverage[x] <= maxOutlierLines;
    if (empty) {
      if (gapStart === -1) gapStart = x;
    } else {
      if (gapStart !== -1 && x - gapStart >= minGap) boundaries.push(minX + (gapStart + x) / 2);
      gapStart = -1;
    }
  }
  return boundaries;
}

/** Bucket a line's words into columns by which boundary range their center falls in. */
export function wordsToRow(words: PositionedWord[], boundaries: number[]): string[] {
  const cols: string[][] = Array.from({ length: boundaries.length + 1 }, () => []);
  for (const w of [...words].sort((a, b) => a.x0 - b.x0)) {
    const cx = (w.x0 + w.x1) / 2;
    const col = boundaries.findIndex((b) => cx < b);
    cols[col === -1 ? boundaries.length : col].push(w.text);
  }
  return cols.map((fragments) => {
    // A price that OCR split into two word fragments (a stray gap detected mid-number) must not
    // be joined with a space: parseNumeric strips whitespace (and most punctuation) the exact same
    // way it strips a real thousands separator, so "2.057 490" and "2.057490" parse identically -
    // the trailing group reads as decimal digits instead of another thousands-group, a 1,000x
    // error, confirmed against the first real document tested against this. Only that exact shape
    // gets concatenated: exactly two fragments, the second a bare 3-digit thousands-group
    // continuation. Three or more numeric fragments in one cell, or a second fragment that isn't a
    // plain 3-digit group, mean unrelated values landed in the same column instead (confirmed on a
    // real document: two different rows' figures merged into "28100002131367") - and because
    // parseNumeric strips whitespace too, space-joining them doesn't actually help: it silently
    // re-merges into that exact same wrong giant number downstream. Empty is the only genuinely
    // safe output here - a missing value shows as "Missing" in the audit, not a confidently wrong
    // one many orders of magnitude off.
    if (fragments.length > 1 && fragments.every((f) => /^[\d.,]+$/.test(f))) {
      if (fragments.length === 2 && /^\d{3}$/.test(fragments[1])) {
        return fragments.map((f) => f.replace(/[.,]/g, "")).join("");
      }
      return "";
    }
    return fragments.join(" ");
  });
}

interface ColumnProfile {
  numericRatio: number;
  avgLength: number;
  nonEmptyRatio: number;
}

function profileColumn(rows: string[][], col: number): ColumnProfile {
  const values = rows.map((r) => r[col] ?? "").filter((v) => v !== "");
  if (values.length === 0 || rows.length === 0) return { numericRatio: 0, avgLength: 0, nonEmptyRatio: 0 };
  const numeric = values.filter((v) => parseNumeric(v) !== null && /\d/.test(v) && (v.match(/\p{L}/gu) ?? []).length <= 2).length;
  return {
    numericRatio: numeric / values.length,
    avgLength: values.reduce((a, v) => a + v.length, 0) / values.length,
    nonEmptyRatio: values.length / rows.length,
  };
}

function profileSimilarity(a: ColumnProfile, b: ColumnProfile): number {
  const numDiff = Math.abs(a.numericRatio - b.numericRatio);
  const lenDiff = Math.abs(a.avgLength - b.avgLength) / Math.max(a.avgLength, b.avgLength, 1);
  const fillDiff = Math.abs(a.nonEmptyRatio - b.nonEmptyRatio);
  return 1 - (numDiff * 0.5 + Math.min(lenDiff, 1) * 0.3 + fillDiff * 0.2);
}

/**
 * Vendor price lists often wrap one long table across several printed blocks
 * - two tables side by side because a single column wouldn't fit down the
 * page, or one table continuing across pages - repeating the same columns
 * each time. Each block gets its own column boundaries (detectColumnBoundaries
 * runs per block, since blocks are separate crops/pages with unrelated
 * coordinates), so a later block can end up with a different column count or
 * order than the first even though it's logically the same table - confirmed
 * against the first real document tested against this, where the second
 * block's product/price ended up in different column indices and silently
 * vanished under the first block's column mapping.
 *
 * Align every block's columns onto the first block's layout by matching each
 * column's content profile (numeric ratio, average length, fill ratio),
 * preferring the same ordinal position when it's already a plausible match
 * (a repeated print template almost always keeps its column order; content
 * profile only overrides that when position disagrees with the data, e.g. a
 * stray extra column shifted everything after it by one). This works for any
 * vendor's wrapped table - nothing here is vendor- or category-specific, and
 * literal header text (which rarely reproduces identically block to block)
 * is never relied on.
 */
export function alignBlocksToCommonColumns(blocks: string[][][]): string[][] {
  const nonEmpty = blocks.filter((b) => b.length > 0);
  if (nonEmpty.length === 0) return [];
  const [first, ...rest] = nonEmpty;
  const canonicalWidth = first.reduce((m, r) => Math.max(m, r.length), 0);
  const canonicalProfiles = Array.from({ length: canonicalWidth }, (_, c) => profileColumn(first, c));

  if (process.env.DEBUG_ROWS) console.error(`align: canonical width=${canonicalWidth} profiles=${JSON.stringify(canonicalProfiles)}`);
  const merged: string[][] = [...first];
  for (const block of rest) {
    const width = block.reduce((m, r) => Math.max(m, r.length), 0);
    const profiles = Array.from({ length: width }, (_, c) => profileColumn(block, c));
    if (process.env.DEBUG_ROWS) console.error(`align: block width=${width} profiles=${JSON.stringify(profiles)}`);
    const usedCanonical = new Set<number>();
    // ponytail: fixed similarity floors (0.45 same-position, 0.55 any-position) for "this is the
    // same column" - revisit if a vendor's block layout regularly needs a looser/stricter match.
    const mapping = profiles.map((p, i) => {
      if (i < canonicalWidth && !usedCanonical.has(i) && profileSimilarity(p, canonicalProfiles[i]) >= 0.45) {
        usedCanonical.add(i);
        return i;
      }
      let best = -1;
      let bestScore = 0.55;
      canonicalProfiles.forEach((cp, ci) => {
        if (usedCanonical.has(ci)) return;
        const score = profileSimilarity(p, cp);
        if (score > bestScore) {
          bestScore = score;
          best = ci;
        }
      });
      if (best !== -1) usedCanonical.add(best);
      return best;
    });
    if (process.env.DEBUG_ROWS) console.error(`align: mapping=${JSON.stringify(mapping)}`);
    // A column that doesn't confidently match anything in the canonical layout is dropped, not
    // appended as a new trailing column: on the first real document tested against this, one
    // malformed OCR row (a two-SKU cell that wrapped across two printed lines) produced exactly
    // one stray value in an otherwise-empty extra column, and that single "perfectly unique, 100%
    // filled" phantom column then outscored the real product column in the (unrelated) automatic
    // column-role detector downstream. A dropped cell loses one field on an already-malformed row;
    // a phantom column can silently take over the wrong role for the entire merged table.
    for (const row of block) {
      const out = new Array<string>(canonicalWidth).fill("");
      row.forEach((cell, i) => {
        const target = mapping[i];
        if (target !== -1 && target !== undefined) out[target] = cell;
      });
      merged.push(out);
    }
  }
  return merged;
}
```

- [x] **Step 2: Remove the moved code from `file-parser.ts`**

Open `src/lib/parse/file-parser.ts`. Delete these five blocks exactly as they appear (use Read + Edit, matching the exact current text — don't guess at line numbers, they've shifted during earlier sessions):

**Block A** — the `OcrWord` interface (currently right before the `detectColumnBoundaries` doc comment):
```ts
interface OcrWord {
  text: string;
  confidence: number;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

```
Delete this whole block (including the trailing blank line).

**Block B** — `detectColumnBoundaries` and its doc comment:
```ts
/**
 * Column boundaries derived from where OCR'd text actually sits, not from
 * spacing in flattened text. A printed table's cell content never crosses a
 * ruled column border, so the x-ranges words occupy leave real empty gaps
 * exactly at the column dividers - find those gaps, no layout assumed.
 *
 * Coverage is counted per row, not unioned across all words: a table title
 * or footnote that spans the full block width would otherwise fill in every
 * gap for the whole block (it did, on the first real document tested against
 * this). A gap only "counts" as filled where enough distinct rows actually
 * have content there - one wide outlier row can't erase it.
 */
function detectColumnBoundaries(lines: OcrWord[][]): number[] {
  const words = lines.flat();
  if (words.length === 0) return [];
  const minX = Math.floor(Math.min(...words.map((w) => w.x0)));
  const maxX = Math.ceil(Math.max(...words.map((w) => w.x1)));
  const span = maxX - minX;
  if (span <= 0) return [];
  const coverage = new Array<number>(span).fill(0);
  for (const line of lines) {
    const touched = new Array<boolean>(span).fill(false);
    for (const w of line) {
      const from = Math.max(0, Math.floor(w.x0) - minX);
      const to = Math.min(span, Math.ceil(w.x1) - minX);
      for (let x = from; x < to; x++) touched[x] = true;
    }
    for (let x = 0; x < span; x++) if (touched[x]) coverage[x]++;
  }
  // ponytail: fixed 15%-of-rows outlier tolerance and fixed min-gap width; revisit if a
  // vendor's table regularly has more than a couple of full-width title/footnote rows.
  const maxOutlierLines = Math.max(1, Math.floor(lines.length * 0.15));
  const minGap = Math.max(10, span * 0.015);
  const boundaries: number[] = [];
  let gapStart = -1;
  for (let x = 0; x <= span; x++) {
    const empty = x < span && coverage[x] <= maxOutlierLines;
    if (empty) {
      if (gapStart === -1) gapStart = x;
    } else {
      if (gapStart !== -1 && x - gapStart >= minGap) boundaries.push(minX + (gapStart + x) / 2);
      gapStart = -1;
    }
  }
  return boundaries;
}

```
Delete this whole block.

**Block C** — `wordsToRow` and its doc comment:
```ts
/** Bucket a line's words into columns by which boundary range their center falls in. */
function wordsToRow(words: OcrWord[], boundaries: number[]): string[] {
  const cols: string[][] = Array.from({ length: boundaries.length + 1 }, () => []);
  for (const w of [...words].sort((a, b) => a.x0 - b.x0)) {
    const cx = (w.x0 + w.x1) / 2;
    const col = boundaries.findIndex((b) => cx < b);
    cols[col === -1 ? boundaries.length : col].push(w.text);
  }
  return cols.map((fragments) => {
    // A price that OCR split into two word fragments (a stray gap detected mid-number) must not
    // be joined with a space: parseNumeric strips whitespace (and most punctuation) the exact same
    // way it strips a real thousands separator, so "2.057 490" and "2.057490" parse identically -
    // the trailing group reads as decimal digits instead of another thousands-group, a 1,000x
    // error, confirmed against the first real document tested against this. Only that exact shape
    // gets concatenated: exactly two fragments, the second a bare 3-digit thousands-group
    // continuation. Three or more numeric fragments in one cell, or a second fragment that isn't a
    // plain 3-digit group, mean unrelated values landed in the same column instead (confirmed on a
    // real document: two different rows' figures merged into "28100002131367") - and because
    // parseNumeric strips whitespace too, space-joining them doesn't actually help: it silently
    // re-merges into that exact same wrong giant number downstream. Empty is the only genuinely
    // safe output here - a missing value shows as "Missing" in the audit, not a confidently wrong
    // one many orders of magnitude off.
    if (fragments.length > 1 && fragments.every((f) => /^[\d.,]+$/.test(f))) {
      if (fragments.length === 2 && /^\d{3}$/.test(fragments[1])) {
        return fragments.map((f) => f.replace(/[.,]/g, "")).join("");
      }
      return "";
    }
    return fragments.join(" ");
  });
}

```
Delete this whole block.

**Block D** — `ColumnProfile`, `profileColumn`, `profileSimilarity`:
```ts
interface ColumnProfile {
  numericRatio: number;
  avgLength: number;
  nonEmptyRatio: number;
}

function profileColumn(rows: string[][], col: number): ColumnProfile {
  const values = rows.map((r) => r[col] ?? "").filter((v) => v !== "");
  if (values.length === 0 || rows.length === 0) return { numericRatio: 0, avgLength: 0, nonEmptyRatio: 0 };
  const numeric = values.filter((v) => parseNumeric(v) !== null && /\d/.test(v) && (v.match(/\p{L}/gu) ?? []).length <= 2).length;
  return {
    numericRatio: numeric / values.length,
    avgLength: values.reduce((a, v) => a + v.length, 0) / values.length,
    nonEmptyRatio: values.length / rows.length,
  };
}

function profileSimilarity(a: ColumnProfile, b: ColumnProfile): number {
  const numDiff = Math.abs(a.numericRatio - b.numericRatio);
  const lenDiff = Math.abs(a.avgLength - b.avgLength) / Math.max(a.avgLength, b.avgLength, 1);
  const fillDiff = Math.abs(a.nonEmptyRatio - b.nonEmptyRatio);
  return 1 - (numDiff * 0.5 + Math.min(lenDiff, 1) * 0.3 + fillDiff * 0.2);
}

```
Delete this whole block.

**Block E** — `alignBlocksToCommonColumns` and its doc comment (the big one starting `/** * Vendor price lists often wrap...`, ending right before `/** OCR fallback for scanned/signed PDFs...`). Delete the whole function and its comment, from the `/**` that starts "Vendor price lists often wrap..." down through the closing `}` of `alignBlocksToCommonColumns`.

- [x] **Step 3: Add the import + re-export at the top of `file-parser.ts`**

Find this line near the top of the file:
```ts
import * as XLSX from "xlsx";
import os from "os";
import type { ParsedFile, ParsedSheet } from "@/lib/types";
```
Replace with:
```ts
import * as XLSX from "xlsx";
import os from "os";
import type { ParsedFile, ParsedSheet } from "@/lib/types";
import { PositionedWord, detectColumnBoundaries, wordsToRow, alignBlocksToCommonColumns, parseNumeric } from "./table-reconstruction";

export { parseNumeric };
```

- [x] **Step 4: Remove the now-duplicate `parseNumeric` definition**

At the bottom of `file-parser.ts`, delete the old `export function parseNumeric(...) {...}` block (everything from `/** Parse a numeric value...` doc comment through its closing `}`) — it's now imported from `table-reconstruction.ts` and re-exported via Step 3.

- [x] **Step 5: Rename remaining `OcrWord` references to `PositionedWord`**

The functions that stay in `file-parser.ts` (`extractHeaderLabels`, `recognizeRowWords`, `ocrTableBlock`) still reference the type by its old name. Since the interface itself moved out (Step 2, Block A) and is now imported as `PositionedWord` (Step 3), every remaining `OcrWord` in the file is now an unresolvable type reference and must become `PositionedWord`.

Run this to see every remaining occurrence and confirm they're all in the three OCR functions listed above (not in code you already deleted):
Run: `grep -n "OcrWord" "src/lib/parse/file-parser.ts"`
Expected: a handful of matches, all inside `extractHeaderLabels`, `recognizeRowWords`, or `ocrTableBlock` (e.g. `words: OcrWord[]`, `cols: OcrWord[][]`, `standardPass: OcrWord[][]`).

Replace every one of them: `OcrWord` → `PositionedWord`. (Use Edit with `replace_all: true` on the string `OcrWord` → `PositionedWord` for this file — every remaining occurrence needs the same substitution, there's no case where it should stay `OcrWord`.)

Run: `grep -n "OcrWord" "src/lib/parse/file-parser.ts"`
Expected: no output (zero matches).

- [x] **Step 6: Typecheck**

Run: `npx tsc --noEmit -p .`
Expected: same 4 pre-existing errors as the Global Constraints section notes (in `route.ts` and `matching.ts`, about `vendorCode`), nothing from `file-parser.ts` or `table-reconstruction.ts`.

- [x] **Step 7: Regression check — output must be byte-identical to Task 1's baseline**

Run: `node test/run.mjs test/engine-check.ts`
Expected: `engine-check OK`.

Run: `node test/run.mjs test/test-rinnai-e2e.ts`
Expected: the exact same summary line you recorded in Task 1 Step 4 (e.g. `matched=34 need_review=6 partial=7 unmatched=10`) and the exact same per-row output. This confirms the move changed nothing about OCR-path behavior.

- [x] **Step 8: Commit**

```bash
git add src/lib/parse/table-reconstruction.ts src/lib/parse/file-parser.ts
git commit -m "Extract table-reconstruction.ts: shared position-based column/row primitives

detectColumnBoundaries, wordsToRow and alignBlocksToCommonColumns never
actually depended on OCR specifically - moving them out (with OcrWord
renamed to the more accurate PositionedWord) lets the upcoming text-layer
PDF path reuse them instead of reimplementing column detection from
scratch. No behavior change: same OCR-path output before and after."
```

---

## Task 3: `extractPositionedItems` — pull real x/y positions out of a PDF

**Files:**
- Create: `src/lib/parse/pdf-text-layer.ts`
- Test: `test/pdf-text-layer-check.ts`

**Interfaces:**
- Consumes: `PositionedWord` from `./table-reconstruction` (Task 2).
- Produces: `extractPositionedItems(buffer: Buffer): Promise<PositionedWord[][]>` — one array per PDF page, in reading order per page (not yet clustered into rows). Task 4+ consume this.

- [ ] **Step 1: Write the failing test**

Create `test/pdf-text-layer-check.ts`:

```ts
/**
 * Real-document checks for the text-layer PDF reconstruction pipeline (src/lib/parse/pdf-text-layer.ts).
 * Run: node test/run.mjs test/pdf-text-layer-check.ts
 */
import * as assert from "assert";
import { readFileSync } from "fs";
import { extractPositionedItems } from "../src/lib/parse/pdf-text-layer";

async function checkExtractPositionedItems() {
  const buf = readFileSync("Data Vendor/Panasonic Pump.pdf");
  const pages = await extractPositionedItems(buf);
  assert.strictEqual(pages.length, 1, `expected 1 page, got ${pages.length}`);
  const items = pages[0];
  assert.ok(items.length > 50, `expected >50 text items on the page, got ${items.length}`);

  const noItem = items.find((w) => w.text === "No");
  assert.ok(noItem, `expected an item with text "No"`);
  assert.ok(Math.abs(noItem!.x0 - 130.6) < 2, `"No" x0 expected ~130.6, got ${noItem!.x0}`);
  assert.ok(Math.abs(noItem!.y0 - 620.2) < 2, `"No" y0 expected ~620.2, got ${noItem!.y0}`);

  const productItem = items.find((w) => w.text === "Product");
  assert.ok(productItem, `expected an item with text "Product"`);

  const codeItem = items.find((w) => w.text === "GA-126JAK-P");
  assert.ok(codeItem, `expected an item with text "GA-126JAK-P" (a real product type code)`);

  console.log("checkExtractPositionedItems OK");
}

checkExtractPositionedItems().catch((e) => {
  console.error(e);
  process.exit(1);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: FAIL — `Cannot find module '../src/lib/parse/pdf-text-layer'` (the file doesn't exist yet).

- [ ] **Step 3: Write the minimal implementation**

Create `src/lib/parse/pdf-text-layer.ts`:

```ts
import type { PositionedWord } from "./table-reconstruction";

interface PdfTextItem {
  str: string;
  transform: number[];
  width: number;
}
interface PdfPageData {
  getTextContent(opts: {
    normalizeWhitespace: boolean;
    disableCombineTextItems: boolean;
  }): Promise<{ items: PdfTextItem[] }>;
}
type PdfParseFn = (
  buffer: Buffer,
  options?: { pagerender?: (pageData: PdfPageData) => Promise<string>; max?: number }
) => Promise<{ text: string }>;

/**
 * Real per-item x/y positions from the PDF's own text layer, one array per page - the exact
 * layout information pdf-parse's flattened `.text` output throws away. `disableCombineTextItems`
 * keeps pdf.js from merging adjacent runs on its own guess of word boundaries; row/column
 * reconstruction (clusterRowsByPosition, detectColumnBoundaries) does that itself from position,
 * the same way it already works for OCR word boxes.
 */
export async function extractPositionedItems(buffer: Buffer): Promise<PositionedWord[][]> {
  const pdfParse = (await import("pdf-parse/lib/pdf-parse.js")).default as PdfParseFn;
  const pages: PositionedWord[][] = [];
  const pagerender = async (pageData: PdfPageData): Promise<string> => {
    const { items } = await pageData.getTextContent({ normalizeWhitespace: false, disableCombineTextItems: true });
    const words: PositionedWord[] = items
      .filter((it) => it.str.trim() !== "")
      .map((it) => ({
        text: it.str.trim(),
        x0: it.transform[4],
        x1: it.transform[4] + it.width,
        y0: it.transform[5],
        y1: it.transform[5],
      }));
    pages.push(words);
    return "";
  };
  await pdfParse(buffer, { pagerender, max: 0 });
  return pages;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: `checkExtractPositionedItems OK`.

- [ ] **Step 5: Typecheck**

Run: `npx tsc --noEmit -p .`
Expected: same 4 pre-existing errors, nothing new.

- [ ] **Step 6: Commit**

```bash
git add src/lib/parse/pdf-text-layer.ts test/pdf-text-layer-check.ts
git commit -m "Add extractPositionedItems: real x/y text positions from pdf-parse's pagerender hook"
```

---

## Task 4: `clusterRowsByPosition` — group items into visual rows

**Files:**
- Modify: `src/lib/parse/pdf-text-layer.ts`
- Modify: `test/pdf-text-layer-check.ts`

**Interfaces:**
- Consumes: `PositionedWord` from `./table-reconstruction`.
- Produces: `clusterRowsByPosition(items: PositionedWord[]): PositionedWord[][]` — rows in top-to-bottom order, each row's words in left-to-right order. Task 7 (orchestrator) calls this per page.

- [ ] **Step 1: Write the failing test**

Add to `test/pdf-text-layer-check.ts` (before the `checkExtractPositionedItems().catch(...)` line at the bottom):

```ts
import { clusterRowsByPosition } from "../src/lib/parse/pdf-text-layer";

function checkClusterRowsByPosition() {
  // Same visual row can have slightly different y across font runs (confirmed directly on
  // Panasonic Pump.pdf: "No" y=620.2, "Product" y=619.9, "Type" y=619.4 - all one printed line).
  const items = [
    { text: "No", x0: 130.6, x1: 142.7, y0: 620.2, y1: 620.2 },
    { text: "Product", x0: 201.8, x1: 236.3, y0: 619.9, y1: 619.9 },
    { text: "Type", x0: 307.9, x1: 329.0, y0: 619.4, y1: 619.4 },
    { text: "1", x0: 134.6, x1: 138.8, y0: 574.8, y1: 574.8 },
    { text: "AUTO", x0: 191.5, x1: 219.0, y0: 574.6, y1: 574.6 },
    { text: "PUMP", x0: 220.3, x1: 246.3, y0: 574.6, y1: 574.6 },
  ];
  const rows = clusterRowsByPosition(items);
  assert.strictEqual(rows.length, 2, `expected 2 rows, got ${rows.length}: ${JSON.stringify(rows.map((r) => r.map((w) => w.text)))}`);
  assert.deepStrictEqual(rows[0].map((w) => w.text), ["No", "Product", "Type"], "row 0 should be the header, left-to-right");
  assert.deepStrictEqual(rows[1].map((w) => w.text), ["1", "AUTO", "PUMP"], "row 1 should be the data row, left-to-right");
  console.log("checkClusterRowsByPosition OK");
}
```

Then replace the final `checkExtractPositionedItems().catch(...)` block at the bottom of the file with:

```ts
checkClusterRowsByPosition();

checkExtractPositionedItems().catch((e) => {
  console.error(e);
  process.exit(1);
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: FAIL — `clusterRowsByPosition is not a function` or a TypeScript "has no exported member" error (not implemented yet).

- [ ] **Step 3: Write the minimal implementation**

Add to `src/lib/parse/pdf-text-layer.ts` (after the imports, before `extractPositionedItems`):

```ts
/**
 * Group items into visual rows purely from y-proximity - no assumption about font size or scan
 * resolution, the typical row-to-row gap is measured from the document itself (same median-based
 * approach already used for OCR row-band detection). PDF y grows upward, so the topmost visual
 * row has the highest y.
 *
 * Words on the same printed line can still carry slightly different y across font runs (confirmed
 * directly on a real document: "No"/"Product"/"Type" on one visual header line read as y=620.2 /
 * 619.9 / 619.4) - half the typical row gap is generous tolerance for that jitter while staying
 * well under a genuine line-to-line gap.
 */
export function clusterRowsByPosition(items: PositionedWord[]): PositionedWord[][] {
  if (items.length === 0) return [];
  const sorted = [...items].sort((a, b) => b.y0 - a.y0);
  const deltas: number[] = [];
  for (let i = 1; i < sorted.length; i++) {
    const d = sorted[i - 1].y0 - sorted[i].y0;
    if (d > 0.5) deltas.push(d);
  }
  const sortedDeltas = [...deltas].sort((a, b) => a - b);
  const typicalGap = sortedDeltas.length > 0 ? sortedDeltas[Math.floor(sortedDeltas.length / 2)] : 10;
  const tolerance = Math.max(1, typicalGap / 2);

  const rows: PositionedWord[][] = [];
  let current: PositionedWord[] = [sorted[0]];
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i - 1].y0 - sorted[i].y0 <= tolerance) {
      current.push(sorted[i]);
    } else {
      rows.push(current);
      current = [sorted[i]];
    }
  }
  rows.push(current);
  return rows.map((row) => [...row].sort((a, b) => a.x0 - b.x0));
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: `checkClusterRowsByPosition OK` then `checkExtractPositionedItems OK`.

- [ ] **Step 5: Typecheck**

Run: `npx tsc --noEmit -p .`
Expected: same 4 pre-existing errors, nothing new.

- [ ] **Step 6: Commit**

```bash
git add src/lib/parse/pdf-text-layer.ts test/pdf-text-layer-check.ts
git commit -m "Add clusterRowsByPosition: group PDF text items into visual rows by y-proximity"
```

---

## Task 5: `mergeHeaderRows` — collapse wrapped header lines, find where data starts

**Files:**
- Modify: `src/lib/parse/pdf-text-layer.ts`
- Modify: `test/pdf-text-layer-check.ts`

**Interfaces:**
- Consumes: `parseNumeric` from `./table-reconstruction`.
- Produces: `mergeHeaderRows(matrix: string[][]): { headers: string[]; dataRows: string[][] } | null` — `null` means no numeric row was found anywhere in the scan window (not a price table, e.g. a prose letter). Task 7 (orchestrator) calls this per page.

- [ ] **Step 1: Write the failing test**

Add to `test/pdf-text-layer-check.ts`:

```ts
import { mergeHeaderRows } from "../src/lib/parse/pdf-text-layer";

function checkMergeHeaderRows() {
  // A wrapped 2-line column header ("Nett Price" / "Exclude PPn") should merge into one label per
  // column; masthead text above it (a document title, here) isn't specially stripped - it just
  // ends up folded into whichever column its x-position happens to land in.
  const matrix = [
    ["Some Title", "", ""],
    ["No", "Product", "Price"],
    ["", "", "(Rp)"],
    ["1", "Widget", "500"],
    ["2", "Gadget", "700"],
  ];
  const result = mergeHeaderRows(matrix);
  assert.ok(result !== null, "expected a result, got null");
  assert.deepStrictEqual(result!.headers, ["Some Title No", "Product", "Price (Rp)"]);
  assert.deepStrictEqual(result!.dataRows, [
    ["1", "Widget", "500"],
    ["2", "Gadget", "700"],
  ]);

  // A prose document (a cover letter, not a price list) has no row with any numeric cell -
  // mergeHeaderRows must say so (null) rather than pretending some paragraph is "the header".
  const prose = [
    ["Sehubungan dengan hasil evaluasi harga secara berkala", "", ""],
    ["serta adanya perubahan pada struktur biaya", "", ""],
  ];
  assert.strictEqual(mergeHeaderRows(prose), null, "expected null for a non-tabular document");

  console.log("checkMergeHeaderRows OK");
}
```

Add `checkMergeHeaderRows();` to the run block at the bottom, alongside `checkClusterRowsByPosition();`.

- [ ] **Step 2: Run test to verify it fails**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: FAIL — `mergeHeaderRows is not a function`.

- [ ] **Step 3: Write the minimal implementation**

Add to `src/lib/parse/pdf-text-layer.ts`:

```ts
import { parseNumeric } from "./table-reconstruction";

/**
 * Find where the header block ends and real data starts, then collapse every row above that
 * point into one header row per column (top-to-bottom, space-joined) - handling a header that
 * wraps onto 2+ printed lines (e.g. "Nett Price" / "Exclude PPn" reconstructing as one "Nett
 * Price Exclude PPn" label). A genuine header row never has a price in it; a real data row almost
 * always does (same principle as detectSafeOcrHeader in file-parser.ts, applied here to a
 * text-layer-reconstructed matrix instead of an OCR one).
 *
 * Deliberately does NOT try to separate a page masthead (title, date) from the real column-header
 * lines above the data - both get folded into the header text together. A masthead's words land
 * in whichever column bucket their x-position happens to fall into, which is rarely every column,
 * so the noise this adds is usually confined to 1-2 columns rather than spread across the whole
 * header - acceptable in exchange for not needing per-vendor masthead-shape logic.
 */
export function mergeHeaderRows(matrix: string[][]): { headers: string[]; dataRows: string[][] } | null {
  const SCAN_LIMIT = 30;
  const scan = Math.min(matrix.length, SCAN_LIMIT);
  let dataStart = -1;
  for (let i = 0; i < scan; i++) {
    const hasNumeric = matrix[i].some((c) => c !== "" && parseNumeric(c) !== null);
    if (hasNumeric) {
      dataStart = i;
      break;
    }
  }
  if (dataStart === -1) return null;

  const width = matrix.reduce((m, r) => Math.max(m, r.length), 0);
  const headerRows = matrix.slice(0, dataStart);
  const headers = Array.from({ length: width }, (_, c) =>
    headerRows.map((r) => r[c] ?? "").filter((v) => v !== "").join(" ")
  );
  return { headers, dataRows: matrix.slice(dataStart) };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: `checkMergeHeaderRows OK` plus the two earlier `OK` lines.

- [ ] **Step 5: Typecheck**

Run: `npx tsc --noEmit -p .`
Expected: same 4 pre-existing errors, nothing new.

- [ ] **Step 6: Commit**

```bash
git add src/lib/parse/pdf-text-layer.ts test/pdf-text-layer-check.ts
git commit -m "Add mergeHeaderRows: collapse wrapped header lines, detect where data starts"
```

---

## Task 6: `backfillSparseRows` — fill spanning-cell labels into their sub-rows

**Files:**
- Modify: `src/lib/parse/pdf-text-layer.ts`
- Modify: `test/pdf-text-layer-check.ts`

**Interfaces:**
- Produces: `backfillSparseRows(matrix: string[][]): string[][]`. Task 7 (orchestrator) calls this on the merged data matrix.

- [ ] **Step 1: Write the failing test**

Add to `test/pdf-text-layer-check.ts`:

```ts
import { backfillSparseRows } from "../src/lib/parse/pdf-text-layer";

function checkBackfillSparseRows() {
  // Real pattern from Panasonic Pump.pdf: a merged-cell label row ("1"/"AUTO PUMP", filling only
  // the No/Nama columns) sits alongside 3 rows that only fill Type/Harga - back-fill copies the
  // label into every row in that run.
  const matrix = [
    ["1", "AUTO PUMP", "", "", ""],
    ["", "", "GA-126JAK-P", "573.500", "636.585"],
    ["", "", "GA-13OJACK.P", "916.000", "1.016.760"],
    ["", "", "GA-13OJAK-P2", "640.000", "770.400"],
  ];
  const result = backfillSparseRows(matrix);
  assert.deepStrictEqual(result, [
    ["1", "AUTO PUMP", "", "", ""],
    ["1", "AUTO PUMP", "GA-126JAK-P", "573.500", "636.585"],
    ["1", "AUTO PUMP", "GA-13OJACK.P", "916.000", "1.016.760"],
    ["1", "AUTO PUMP", "GA-13OJAK-P2", "640.000", "770.400"],
  ]);

  // Two rows with the SAME shape (both look like a "label") aren't a label/data pair - nothing
  // should be backfilled; ambiguous is left alone, not guessed at.
  const ambiguous = [
    ["1", "A", "", ""],
    ["2", "B", "", ""],
  ];
  assert.deepStrictEqual(backfillSparseRows(ambiguous), ambiguous);

  // A blank row (all cells empty) ends a cluster - a row on the far side of one doesn't inherit a
  // label it was never actually grouped with.
  const withDivider = [
    ["1", "AUTO", "", ""],
    ["", "", "X1", "100"],
    ["", "", "", ""],
    ["", "", "X2", "200"],
  ];
  const backfilled = backfillSparseRows(withDivider);
  assert.deepStrictEqual(backfilled[1], ["1", "AUTO", "X1", "100"], "row right after the label, same cluster, should backfill");
  assert.deepStrictEqual(backfilled[3], ["", "", "X2", "200"], "row after the blank divider, no label in its own cluster, stays empty");

  console.log("checkBackfillSparseRows OK");
}
```

Add `checkBackfillSparseRows();` to the run block.

- [ ] **Step 2: Run test to verify it fails**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: FAIL — `backfillSparseRows is not a function`.

- [ ] **Step 3: Write the minimal implementation**

Add to `src/lib/parse/pdf-text-layer.ts`:

```ts
/**
 * A merged/spanning Excel cell (e.g. one product-group label covering several model+price rows
 * below it) flattens, once exported to PDF, into one row that only fills the label's own columns
 * plus several rows that only fill the OTHER columns - confirmed directly on a real document. Its
 * y-position within that run isn't reliable either (it sat between two of the three rows it
 * labeled, not above them, on the one real example seen) - so this fills by CLUSTER membership,
 * not by "copy down from the row above".
 *
 * Rows are grouped into clusters split at blank rows (every cell empty). Within a cluster, if
 * there's exactly one row whose populated columns are disjoint from every other row's (a "label"
 * row) and every other row in the cluster has SOME content of its own (a "data" row missing
 * exactly what the label has), the label's values are copied into each data row's matching empty
 * columns. A cluster that doesn't match this shape - no clear single label, or ambiguous overlap -
 * is left untouched rather than guessed at.
 */
export function backfillSparseRows(matrix: string[][]): string[][] {
  const isBlankRow = (row: string[]) => row.every((c) => c === "");
  const populatedCols = (row: string[]) => new Set(row.map((c, i) => (c !== "" ? i : -1)).filter((i) => i !== -1));

  const result = matrix.map((r) => [...r]);

  const processCluster = (start: number, end: number) => {
    if (end - start < 2) return;
    const rows = result.slice(start, end);
    const colSets = rows.map(populatedCols);
    const labelIdx = colSets.findIndex((cols, i) => {
      if (cols.size === 0) return false;
      return colSets.every((other, j) => {
        if (i === j) return true;
        if (other.size === 0) return false;
        for (const c of cols) if (other.has(c)) return false;
        return true;
      });
    });
    if (labelIdx === -1) return;
    const label = rows[labelIdx];
    for (let i = 0; i < rows.length; i++) {
      if (i === labelIdx) continue;
      for (const c of colSets[labelIdx]) {
        if (rows[i][c] === "") result[start + i][c] = label[c];
      }
    }
  };

  let clusterStart = 0;
  for (let i = 0; i <= result.length; i++) {
    if (i === result.length || isBlankRow(result[i])) {
      processCluster(clusterStart, i);
      clusterStart = i + 1;
    }
  }
  return result;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: `checkBackfillSparseRows OK` plus the three earlier `OK` lines.

- [ ] **Step 5: Typecheck**

Run: `npx tsc --noEmit -p .`
Expected: same 4 pre-existing errors, nothing new.

- [ ] **Step 6: Commit**

```bash
git add src/lib/parse/pdf-text-layer.ts test/pdf-text-layer-check.ts
git commit -m "Add backfillSparseRows: fill merged-cell labels into their sub-rows, cluster-aware"
```

---

## Task 7: `reconstructTextLayerMatrix` orchestrator — single-page end-to-end

**Files:**
- Modify: `src/lib/parse/pdf-text-layer.ts`
- Modify: `test/pdf-text-layer-check.ts`

**Interfaces:**
- Consumes: `extractPositionedItems`, `clusterRowsByPosition`, `mergeHeaderRows`, `backfillSparseRows` (all from this same file), `detectColumnBoundaries`, `wordsToRow`, `alignBlocksToCommonColumns` from `./table-reconstruction`.
- Produces: `reconstructTextLayerMatrix(buffer: Buffer): Promise<{ matrix: string[][]; headers: string[] } | null>` — `null` means the caller (Task 9, `parsePdf`) should fall back to the whitespace-split heuristic. This is the ONLY function `parsePdf` calls from this file.

For a single page: cluster rows → detect columns → bucket into a string matrix → strip that page's own header block (keeping its headers only if it's page 1) → collect data rows only. Multi-page merge (Task 8) reuses this same per-page logic; this task covers the 1-page case (`Panasonic Pump.pdf`) end-to-end first since it's simpler to verify.

- [ ] **Step 1: Write the failing test**

Add to `test/pdf-text-layer-check.ts`:

```ts
import { reconstructTextLayerMatrix } from "../src/lib/parse/pdf-text-layer";

async function checkReconstructTextLayerMatrix() {
  const buf = readFileSync("Data Vendor/Panasonic Pump.pdf");
  const result = await reconstructTextLayerMatrix(buf);
  assert.ok(result !== null, "expected a result, got null (fallback triggered)");

  // Headers should be real column labels, not mashed data or a letterhead address (the bug this
  // whole feature exists to fix) - "Product" and "Type" should each show up somewhere.
  const headerText = result!.headers.join(" | ");
  assert.ok(headerText.includes("Product"), `expected "Product" in headers, got: ${headerText}`);
  assert.ok(headerText.includes("Type"), `expected "Type" in headers, got: ${headerText}`);
  assert.ok(!headerText.includes("Blok A"), `headers should not contain the office address, got: ${headerText}`);

  // Find the GA-126JAK-P row and confirm the merged-cell backfill worked: the same row should
  // also carry "1" and "AUTO PUMP" (the label from the row that, in the source PDF, sits BETWEEN
  // two of its sibling rows, not above them - confirmed directly during design).
  const row = result!.matrix.find((r) => r.includes("GA-126JAK-P"));
  assert.ok(row, `expected a row containing "GA-126JAK-P", got matrix: ${JSON.stringify(result!.matrix)}`);
  assert.ok(row!.includes("1"), `expected the GA-126JAK-P row to have been backfilled with "1", got: ${JSON.stringify(row)}`);
  assert.ok(row!.some((c) => c.includes("AUTO") && c.includes("PUMP")), `expected the GA-126JAK-P row to have been backfilled with "AUTO PUMP", got: ${JSON.stringify(row)}`);
  assert.ok(row!.includes("573.500"), `expected the GA-126JAK-P row to keep its own price, got: ${JSON.stringify(row)}`);

  console.log("checkReconstructTextLayerMatrix OK");
  console.log("headers:", JSON.stringify(result!.headers));
  console.log("row count:", result!.matrix.length);
}
```

Add to the bottom, after `checkBackfillSparseRows();`:

```ts
checkReconstructTextLayerMatrix()
  .then(() => checkExtractPositionedItems())
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
```

(Remove the old standalone `checkExtractPositionedItems().catch(...)` call at the very bottom — it's now chained above so both async checks run and either failure exits non-zero.)

- [ ] **Step 2: Run test to verify it fails**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: FAIL — `reconstructTextLayerMatrix is not a function`.

- [ ] **Step 3: Write the minimal implementation**

Add to `src/lib/parse/pdf-text-layer.ts`:

```ts
import { PositionedWord, detectColumnBoundaries, wordsToRow, alignBlocksToCommonColumns } from "./table-reconstruction";

/** Reconstruct one page's items into a string matrix: cluster rows, detect columns from THIS
 * page's own word positions, bucket. Returns null if the page has no usable columns at all
 * (fewer than 1 detected boundary despite having rows - the position data doesn't form a table). */
function reconstructPageMatrix(items: PositionedWord[]): string[][] | null {
  const rows = clusterRowsByPosition(items);
  if (rows.length === 0) return null;
  const boundaries = detectColumnBoundaries(rows);
  if (boundaries.length < 1) return null;
  return rows.map((row) => wordsToRow(row, boundaries));
}

/**
 * Reconstruct a text-layer PDF's table from its real per-character positions instead of guessing
 * columns from whitespace in the flattened text (see parsePdf in file-parser.ts, which falls back
 * to that whitespace heuristic when this returns null).
 *
 * Each page is processed independently (own row clustering, own column detection - a later page's
 * pixel/unit coordinates have no relation to an earlier page's) and has its own header block
 * stripped via mergeHeaderRows, so a repeated header on page 2+ of a long document doesn't get
 * counted as a data row. Only page 1's header labels become the final column headers - matching
 * the same "first block wins" rule already used for the OCR path's multi-block documents.
 */
export async function reconstructTextLayerMatrix(
  buffer: Buffer
): Promise<{ matrix: string[][]; headers: string[] } | null> {
  const pages = await extractPositionedItems(buffer);
  if (pages.length === 0) return null;

  let headers: string[] | null = null;
  const pageDataMatrices: string[][][] = [];
  for (const pageItems of pages) {
    const pageMatrix = reconstructPageMatrix(pageItems);
    if (!pageMatrix) continue;
    const split = mergeHeaderRows(pageMatrix);
    if (!split) continue; // this page has no numeric row at all - nothing usable on it
    if (headers === null) headers = split.headers;
    pageDataMatrices.push(split.dataRows);
  }
  if (headers === null) return null; // not even page 1 produced a usable header/data split

  const merged = alignBlocksToCommonColumns(pageDataMatrices);
  const backfilled = backfillSparseRows(merged);
  return { matrix: backfilled, headers };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: `checkReconstructTextLayerMatrix OK`, prints `headers:` and `row count:` lines, then `checkExtractPositionedItems OK`.

Read the printed `headers:` and `row count:` output. Sanity-check by eye: headers should look like real column labels (some combination of "No"/"Product"/"Type"/"Price"-ish text), row count should be in the low double digits (Panasonic Pump.pdf has a handful of product groups, each with 1-3 sub-rows).

- [ ] **Step 5: Typecheck**

Run: `npx tsc --noEmit -p .`
Expected: same 4 pre-existing errors, nothing new.

- [ ] **Step 6: Commit**

```bash
git add src/lib/parse/pdf-text-layer.ts test/pdf-text-layer-check.ts
git commit -m "Add reconstructTextLayerMatrix: orchestrate position-based PDF table reconstruction"
```

---

## Task 8: Multi-page validation with `Sanei.pdf` (33 pages)

No new production code — this task extends the Task 7 test to a real multi-page document, to confirm `alignBlocksToCommonColumns` (reused from the OCR path) and per-page header-stripping actually hold up past 1 page before `parsePdf` starts depending on them (Task 9).

**Files:**
- Modify: `test/pdf-text-layer-check.ts`

**Interfaces:**
- Consumes: `reconstructTextLayerMatrix` (Task 7). No new interfaces produced.

- [ ] **Step 1: Write the failing test**

Add to `test/pdf-text-layer-check.ts`:

```ts
async function checkMultiPageDocument() {
  const buf = readFileSync("Data Vendor/Sanei.pdf");
  const result = await reconstructTextLayerMatrix(buf);
  assert.ok(result !== null, "expected a result, got null (fallback triggered)");

  const headerText = result!.headers.join(" | ").toUpperCase();
  assert.ok(headerText.includes("TYPE"), `expected "TYPE" in headers, got: ${headerText}`);

  // Page 1 alone has 12+ product rows (confirmed directly reading the source PDF) - if page-2+
  // content is being silently dropped, or repeated per-page headers are polluting the row count,
  // this would be far lower or the shape would be visibly wrong. 33 pages of a real price list
  // should clear this easily; this is a conservative floor, not an exact expected count.
  assert.ok(result!.matrix.length >= 40, `expected at least 40 data rows across 33 pages, got ${result!.matrix.length}`);

  // Spot-check a specific known row from page 1 (verified directly against the source PDF).
  const row = result!.matrix.find((r) => r.includes("SE 125 A"));
  assert.ok(row, `expected a row containing "SE 125 A", got matrix length ${result!.matrix.length}`);
  assert.ok(row!.includes("520.000"), `expected the SE 125 A row to have price 520.000, got: ${JSON.stringify(row)}`);

  // Repeated per-page headers (e.g. "NO." / "TYPE" / "HARGA" showing up again on page 5) must NOT
  // appear as if they were product rows.
  const headerLikeDataRows = result!.matrix.filter((r) => r.some((c) => c.toUpperCase() === "TYPE"));
  assert.strictEqual(headerLikeDataRows.length, 0, `expected 0 data rows that are actually repeated headers, got ${headerLikeDataRows.length}`);

  console.log("checkMultiPageDocument OK");
  console.log("Sanei.pdf row count:", result!.matrix.length);
}
```

Chain it into the bottom run block, replacing the previous chain:

```ts
checkReconstructTextLayerMatrix()
  .then(() => checkMultiPageDocument())
  .then(() => checkExtractPositionedItems())
  .catch((e) => {
    console.error(e);
    process.exit(1);
  });
```

- [ ] **Step 2: Run test to verify it fails (or passes for the wrong reason)**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`

If it fails, read the assertion message carefully - this is validating against real (already-implemented) code from Task 7, so a failure here means a genuine gap in that implementation for the multi-page case, not a "not implemented yet" situation. Common possibilities and what they'd mean:
- `headerLikeDataRows.length !== 0`: per-page header-stripping (`mergeHeaderRows` inside `reconstructPageMatrix`'s caller loop) isn't running per page as intended — check that `reconstructTextLayerMatrix`'s loop calls `mergeHeaderRows(pageMatrix)` for every page, not just page 1.
- `matrix.length < 40`: either `extractPositionedItems` isn't returning all 33 pages (check the `pagerender` callback is actually invoked once per page — `max: 0` should mean "no page limit"), or `alignBlocksToCommonColumns` is dropping most later-page rows (check `DEBUG_ROWS=1` output from that function to see the per-block column mapping it's choosing).
- Missing "SE 125 A": something upstream (row clustering or column detection) is misreading page 1 specifically — re-run Task 7's test to confirm that one still passes in isolation first.

- [ ] **Step 3: Fix whatever's failing**

If Step 2 failed, the fix lives in Task 7's `reconstructTextLayerMatrix` or `reconstructPageMatrix` in `src/lib/parse/pdf-text-layer.ts` — this task doesn't add new functions, it just extends coverage of what's already there. Debug with the existing `DEBUG_ROWS=1` env var (already wired through `alignBlocksToCommonColumns` from Task 2's move) if the multi-page merge looks wrong:

Run: `DEBUG_ROWS=1 node test/run.mjs test/pdf-text-layer-check.ts 2>&1 | head -100`

- [ ] **Step 4: Run test to verify it passes**

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: `checkMultiPageDocument OK`, prints `Sanei.pdf row count: <N>`, then the earlier `OK` lines.

- [ ] **Step 5: Commit**

```bash
git add test/pdf-text-layer-check.ts
git commit -m "Validate multi-page reconstruction against Sanei.pdf (33 pages)"
```

(If Step 3 required production code changes, include `src/lib/parse/pdf-text-layer.ts` in this commit too, and write a commit message describing the actual fix instead.)

---

## Task 9: Wire into `parsePdf`, add fallback, full regression + 8-document survey

**Files:**
- Modify: `src/lib/parse/file-parser.ts`
- Create: `test/vendor-survey-check.ts`

**Interfaces:**
- Consumes: `reconstructTextLayerMatrix` from `./pdf-text-layer` (Task 7).

- [ ] **Step 1: Modify `parsePdf`'s non-OCR branch**

Open `src/lib/parse/file-parser.ts`. Add the import:

```ts
import { reconstructTextLayerMatrix } from "./pdf-text-layer";
```

Find this block inside `parsePdf` (the `else` branch, currently right after the `if (isOcr) { ... }` block):

```ts
  } else {
    const lines = text
      .split(/\r?\n/)
      .map((l) => l.trimEnd())
      .filter((l) => l.trim() !== "");
    matrix = lines.map((line) => line.split(/\t| {2,}/).map((c) => c.trim()).filter((c, i, arr) => !(c === "" && i === arr.length - 1)));
  }
```

Replace with:

```ts
  } else {
    // Position-based reconstruction (see pdf-text-layer.ts) uses the PDF's own per-character x/y
    // positions instead of guessing columns from whitespace in the flattened text - the whitespace
    // heuristic below fails outright on documents whose extracted text has no reliable column
    // spacing at all (confirmed directly: two real vendor documents' numbers came through with
    // zero separating characters, e.g. "215,000238,650182,567..."). This does mean pdf-parse runs
    // twice on the same buffer for text-layer PDFs (once above for the isOcr check, once inside
    // extractPositionedItems for positions) - accepted as a simple, low-risk trade-off since
    // there's no stated performance requirement here.
    const reconstructed = await reconstructTextLayerMatrix(buffer);
    if (reconstructed) {
      matrix = reconstructed.matrix;
      ocrHeaderLabels = reconstructed.headers;
    } else {
      const lines = text
        .split(/\r?\n/)
        .map((l) => l.trimEnd())
        .filter((l) => l.trim() !== "");
      matrix = lines.map((line) => line.split(/\t| {2,}/).map((c) => c.trim()).filter((c, i, arr) => !(c === "" && i === arr.length - 1)));
    }
  }
```

(Reusing the existing `ocrHeaderLabels` variable rather than introducing a new one — it already flows into `sheetFromMatrix`'s `explicitHeaders` a few dozen lines below via `headerLabelsWithCategory`, and that logic doesn't care which path populated it.)

- [ ] **Step 2: Typecheck**

Run: `npx tsc --noEmit -p .`
Expected: same 4 pre-existing errors, nothing new.

- [ ] **Step 3: Full regression check**

Run: `node test/run.mjs test/engine-check.ts`
Expected: `engine-check OK`.

Run: `node test/run.mjs test/test-rinnai-e2e.ts`
Expected: **identical** output to Task 1/Task 2's recorded baseline (Rinnai's PDF has no text layer, so `isOcr` is true and this whole change is a no-op for it — this run confirms that).

Run: `node test/run.mjs test/pdf-text-layer-check.ts`
Expected: all `OK` lines from Tasks 3-8 still pass (confirms the wiring didn't disturb the standalone functions).

- [ ] **Step 4: Write the 8-document survey script**

Create `test/vendor-survey-check.ts`:

```ts
/**
 * Prints parseUploadedFile's output for every PDF in Data Vendor/, for human review - not a
 * strict pass/fail suite (there's no hand-verified ground truth for every one of these 8
 * documents), but a few hard assertions cover what's already been verified directly during
 * design/planning. Run: node test/run.mjs test/vendor-survey-check.ts
 */
import * as assert from "assert";
import { readdirSync, readFileSync } from "fs";
import { parseUploadedFile } from "../src/lib/parse/file-parser";

async function main() {
  const dir = "Data Vendor";
  for (const file of readdirSync(dir)) {
    if (!file.toLowerCase().endsWith(".pdf")) continue;
    const buf = readFileSync(`${dir}/${file}`);
    try {
      const parsed = await parseUploadedFile(buf, file);
      for (const sheet of parsed.sheets) {
        console.log(`\n${file} :: sheet "${sheet.name}" rows=${sheet.rowCount} cols=${sheet.columnCount}`);
        console.log(`  headers: ${JSON.stringify(sheet.headers)}`);
        console.log(`  first 3 rows: ${JSON.stringify(sheet.rows.slice(0, 3))}`);
      }
    } catch (e) {
      console.log(`\n${file}: ERROR ${(e as Error).message}`);
    }
  }

  // Hard assertions for documents already verified directly against their source during design.
  const sanei = await parseUploadedFile(readFileSync(`${dir}/Sanei.pdf`), "Sanei.pdf");
  const saneiHeaders = sanei.sheets[0].headers.join(" | ").toUpperCase();
  assert.ok(saneiHeaders.includes("TYPE"), `Sanei.pdf headers should include "TYPE", got: ${saneiHeaders}`);
  assert.ok(!saneiHeaders.includes("SE-180"), `Sanei.pdf headers should not contain mashed-in product data, got: ${saneiHeaders}`);

  const pump = await parseUploadedFile(readFileSync(`${dir}/Panasonic Pump.pdf`), "Panasonic Pump.pdf");
  const pumpHeaders = pump.sheets[0].headers.join(" | ");
  assert.ok(!pumpHeaders.includes("Blok A"), `Panasonic Pump.pdf headers should not be the office address, got: ${pumpHeaders}`);

  // Non-tabular document: should not crash, and should not produce a large confidently-wrong table.
  const letter = await parseUploadedFile(readFileSync(`${dir}/Surat Penyesuaian Harga 1 Juli 2026.pdf`), "Surat Penyesuaian Harga 1 Juli 2026.pdf");
  assert.ok(letter.sheets[0].rowCount < 10, `expected a prose letter to yield few/no rows, got ${letter.sheets[0].rowCount}`);

  console.log("\nvendor-survey-check OK");
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
```

- [ ] **Step 5: Run the survey and review the printed output**

Run: `node test/run.mjs test/vendor-survey-check.ts`

Expected: exits 0, ends with `vendor-survey-check OK`. Before trusting that, **read the printed headers and sample rows for all 8 documents** — the assertions only check 3 of the 8 (Sanei, Panasonic Pump, the letter); Miyako, Panasonic Fan, Sanyo Pump, Rinnai 3H.pdf and Shimizu.pdf are eyeballed, not asserted. Look specifically for:
- Headers that read as real column labels, not mashed digits or letterhead text.
- Row counts in a plausible range for each document (not 0, not absurdly high).
- `Rinnai 3H.pdf` and `Shimizu.pdf` (the 2 scanned/no-text-layer documents in this folder) go through the untouched OCR path — sanity-check their output looks like it did before this plan (same shape of headers/rows you'd expect from the OCR work done in the prior session).

If something looks wrong for one of the un-asserted documents, that's a real finding — decide with the user whether it's in scope to fix now or worth noting as a follow-up, per the design doc's spirit (ask before chasing a new class of edge case that wasn't part of the original 8-document survey's known findings).

- [ ] **Step 6: Commit**

```bash
git add src/lib/parse/file-parser.ts test/vendor-survey-check.ts
git commit -m "Wire reconstructTextLayerMatrix into parsePdf, with whitespace-split fallback

Text-layer PDFs now try position-based table reconstruction first; if it
can't produce a usable result (no text-layer positions at all, or no
numeric row anywhere in the scan window - e.g. a prose letter), parsePdf
falls back to the existing whitespace-split heuristic unchanged. Verified
against all 8 real vendor PDFs in Data Vendor/, plus zero regression on the
OCR path (test-rinnai-e2e.ts) and the existing engine self-check."
```

---

## Self-Review Notes

- **Spec coverage:** Components 1-7 of the design spec map onto Tasks 3 (`extractPositionedItems`), 4 (`clusterRowsByPosition`), 2+3+7 (reuse of `detectColumnBoundaries`/`wordsToRow`), 5 (`mergeHeaderRows`), 6 (`backfillSparseRows`), 8 (multi-page via `alignBlocksToCommonColumns`), and 9 (fallback trigger). The "Non-tujuan" section (prose letters shouldn't be forced into a table) is covered by `mergeHeaderRows` returning `null` when no numeric row exists, verified in Task 9's survey script.
- **Type consistency:** `PositionedWord` is defined once (Task 2, `table-reconstruction.ts`) and only ever imported, never redefined. `mergeHeaderRows`'s return shape (`{ headers, dataRows }`) and `reconstructTextLayerMatrix`'s return shape (`{ matrix, headers } | null`) are each defined once (Tasks 5, 7) and used with those exact shapes everywhere they're consumed (Task 7's orchestrator, Task 9's `parsePdf` wiring).
- **Known limitation carried forward from the spec:** the `backfillSparseRows` cluster-complementary-shape rule is validated against one real document's pattern (`Panasonic Pump.pdf`). If a future vendor PDF's merged-cell layout doesn't fit that exact "disjoint populated columns" shape, rows will simply be left unbackfilled (not corrupted) — matches the design doc's stated risk acceptance.
