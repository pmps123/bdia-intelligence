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
