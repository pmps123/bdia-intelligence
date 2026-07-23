import * as XLSX from "xlsx";
import os from "os";
import type { ParsedFile, ParsedSheet } from "@/lib/types";

/**
 * Metadata-driven file parser.
 * Nothing here assumes worksheet names, column names, order or file layout.
 * Every sheet is detected, the header row is inferred per sheet from the data itself.
 */

function cellToString(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (v instanceof Date) return v.toISOString().slice(0, 10);
  return String(v).trim();
}

/** Score a row for "looks like a header": mostly non-empty, textual, unique values. */
function headerScore(row: string[], nextRows: string[][]): number {
  const nonEmpty = row.filter((c) => c !== "");
  if (nonEmpty.length < 2) return -1;
  const fillRatio = nonEmpty.length / row.length;
  const textRatio = nonEmpty.filter((c) => Number.isNaN(Number(c.replace(/[.,]/g, "")))).length / nonEmpty.length;
  const unique = new Set(nonEmpty.map((c) => c.toLowerCase())).size / nonEmpty.length;
  // header rows are typically followed by rows with a similar amount of filled columns
  const below = nextRows.slice(0, 5);
  const belowFill =
    below.length === 0
      ? 0
      : below.reduce((acc, r) => acc + r.filter((c) => c !== "").length, 0) / (below.length * Math.max(row.length, 1));
  // a real header's own labels almost never reappear as data further down "their" column;
  // a data row's values (status flags, repeated placeholders, category codes) often do.
  const sample = nextRows.slice(0, 10);
  const repeats = row.filter((v, col) => v !== "" && sample.some((r) => (r[col] ?? "") === v)).length;
  const selfRepeatRatio = nonEmpty.length ? repeats / nonEmpty.length : 0;
  return fillRatio * 2 + textRatio * 2 + unique * 2 + belowFill - selfRepeatRatio * 3;
}

function detectHeader(matrix: string[][]): { headerRowIndex: number; headers: string[] } {
  const scan = Math.min(matrix.length, 15);
  let bestIdx = 0;
  let bestScore = -Infinity;
  for (let i = 0; i < scan; i++) {
    const s = headerScore(matrix[i], matrix.slice(i + 1));
    if (s > bestScore) {
      bestScore = s;
      bestIdx = i;
    }
  }
  const raw = matrix[bestIdx] ?? [];
  const headers = raw.map((h, i) => (h !== "" ? h : `Column ${i + 1}`));
  return { headerRowIndex: bestIdx, headers };
}

/**
 * A safer header pick for OCR-reconstructed tables, where every row otherwise looks alike (a
 * code plus a couple of numbers) and the generic headerScore heuristic can mistake an ordinary
 * product row for the header - silently discarding every row above it, which happened on the
 * first real document tested against this. A genuine header for this kind of price list never
 * has a price in it; almost every real data row does. Only strip a row as "the header" when every
 * one of its populated cells is non-numeric, and only within the first few rows - a genuine
 * header is always right at the top, and restricting the window keeps an ordinary product row
 * whose price columns happened to fail OCR from being mistaken for one further down.
 */
function detectSafeOcrHeader(matrix: string[][]): { headerRowIndex: number; headers: string[] } | null {
  const scan = Math.min(matrix.length, 5);
  for (let i = 0; i < scan; i++) {
    const row = matrix[i];
    const populated = row.filter((c) => c !== "");
    if (populated.length < 2) continue;
    if (populated.every((c) => parseNumeric(c) === null)) {
      return { headerRowIndex: i, headers: row.map((h, ci) => (h !== "" ? h : `Column ${ci + 1}`)) };
    }
  }
  return null;
}

function sheetFromMatrix(name: string, index: number, matrix: string[][], opts?: { useSafeOcrHeader?: boolean }): ParsedSheet {
  // drop fully empty rows and trailing empty columns
  const cleaned = matrix.filter((r) => r.some((c) => c !== ""));
  const width = cleaned.reduce((m, r) => Math.max(m, r.length), 0);
  const normalized = cleaned.map((r) => {
    const row = [...r];
    while (row.length < width) row.push("");
    return row.map(cellToString);
  });
  if (normalized.length === 0) {
    return { name, index, rowCount: 0, columnCount: 0, headers: [], headerRowIndex: 0, rows: [] };
  }
  if (opts?.useSafeOcrHeader) {
    const safe = detectSafeOcrHeader(normalized);
    if (safe) {
      const rows = normalized.slice(safe.headerRowIndex + 1);
      return { name, index, rowCount: rows.length, columnCount: width, headers: safe.headers, headerRowIndex: safe.headerRowIndex, rows };
    }
    const headers = Array.from({ length: width }, (_, i) => `Column ${i + 1}`);
    return { name, index, rowCount: normalized.length, columnCount: width, headers, headerRowIndex: -1, rows: normalized };
  }
  const { headerRowIndex, headers } = detectHeader(normalized);
  const rows = normalized.slice(headerRowIndex + 1);
  return { name, index, rowCount: rows.length, columnCount: headers.length, headers, headerRowIndex, rows };
}

export function parseSpreadsheet(buffer: Buffer, fileType: string): ParsedFile {
  const wb = XLSX.read(buffer, { type: "buffer", cellDates: true, raw: false });
  const sheets: ParsedSheet[] = wb.SheetNames.map((sheetName, idx) => {
    const ws = wb.Sheets[sheetName];
    const matrix = XLSX.utils.sheet_to_json<unknown[]>(ws, { header: 1, defval: "", blankrows: false }) as unknown[][];
    return sheetFromMatrix(sheetName, idx, matrix.map((r) => r.map(cellToString)));
  });
  return { fileType, sheets };
}

/** Pull embedded page-scan images out of a PDF. Only JPEG/JPEG2000 streams are usable as-is;
 * other encodings (e.g. CCITT fax bitmaps) would need a decoder we don't have, so they're skipped. */
async function extractPageImages(buffer: Buffer): Promise<Buffer[]> {
  const { PDFDocument, PDFDict, PDFName, PDFRawStream } = await import("pdf-lib");
  const pdf = await PDFDocument.load(buffer, { ignoreEncryption: true, updateMetadata: false });
  const images: Buffer[] = [];
  for (const page of pdf.getPages()) {
    const xobjects = page.node.Resources()?.lookup(PDFName.of("XObject"));
    if (!(xobjects instanceof PDFDict)) continue;
    for (const name of xobjects.keys()) {
      const xobj = xobjects.lookup(name);
      if (!(xobj instanceof PDFRawStream)) continue;
      const subtype = xobj.dict.lookup(PDFName.of("Subtype"));
      if (!(subtype instanceof PDFName) || subtype.asString() !== "/Image") continue;
      const filter = xobj.dict.lookup(PDFName.of("Filter"));
      const filterName = filter instanceof PDFName ? filter.asString() : undefined;
      if (filterName === "/DCTDecode" || filterName === "/JPXDecode") images.push(Buffer.from(xobj.contents));
    }
  }
  return images;
}

/**
 * Scanned pricelists are often two tables printed side by side on one page, which OCR reads as
 * one jumbled block if handed the full page. Detect a vertical whitespace gutter near the middle
 * and split there so each table gets OCR'd on its own.
 * ponytail: single-gutter split only (2 blocks) - a page with 3+ side-by-side tables falls back to one block.
 */
async function splitAtColumnGutter(buffer: Buffer): Promise<Buffer[]> {
  const sharp = (await import("sharp")).default;
  const img = sharp(buffer).greyscale();
  const { width, height } = await img.metadata();
  if (!width || !height) return [buffer];
  const { data } = await img.raw().toBuffer({ resolveWithObject: true });
  const darkCount = new Array(width).fill(0);
  for (let y = 0; y < height; y++) {
    const rowOffset = y * width;
    for (let x = 0; x < width; x++) if (data[rowOffset + x] < 200) darkCount[x]++;
  }
  const lo = Math.floor(width * 0.25);
  const hi = Math.floor(width * 0.75);
  let bestStart = -1;
  let bestLen = 0;
  let curStart = -1;
  for (let x = lo; x <= hi; x++) {
    const isGutter = darkCount[x] / height < 0.01;
    if (isGutter) {
      if (curStart === -1) curStart = x;
      if (x - curStart + 1 > bestLen) {
        bestLen = x - curStart + 1;
        bestStart = curStart;
      }
    } else {
      curStart = -1;
    }
  }
  if (bestLen < Math.max(8, width * 0.005)) return [buffer];
  const mid = bestStart + Math.floor(bestLen / 2);
  const left = await sharp(buffer).extract({ left: 0, top: 0, width: mid, height }).toBuffer();
  const right = await sharp(buffer).extract({ left: mid, top: 0, width: width - mid, height }).toBuffer();
  return [left, right];
}

interface OcrWord {
  text: string;
  confidence: number;
  x0: number;
  x1: number;
  y0: number;
  y1: number;
}

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
    // be joined with a space: parseNumeric strips whitespace before parsing, so "2.057 490" turns
    // into "2.057490" and the trailing group is read as decimal digits instead of another
    // thousands-group - a 1,000x error, confirmed against the first real document tested against
    // this. Every fragment being digits-and-separators-only means this is one broken-up number,
    // not several cells - concatenate their bare digits directly instead of guessing a separator.
    if (fragments.length > 1 && fragments.every((f) => /^[\d.,]+$/.test(f))) {
      return fragments.map((f) => f.replace(/[.,]/g, "")).join("");
    }
    return fragments.join(" ");
  });
}

/**
 * Detect where one printed table row ends and the next begins, from the image itself: a row of
 * pixels that's darker than its neighbors (a local peak in per-row ink density) marks either a
 * ruled divider or the visual "gap" between two lines of text - either way, a boundary. Catches
 * both because thin dotted cell borders AND blank space between text baselines both show up as a
 * peak relative to the (near-blank) space right around them; nothing here assumes ruled lines
 * exist at all.
 */
function detectRowBands(px: Buffer, width: number, height: number): { top: number; bottom: number }[] {
  const darkFracRow = (y: number) => {
    let c = 0;
    const off = y * width;
    for (let x = 0; x < width; x++) if (px[off + x] < 190) c++;
    return c / width;
  };
  const rowFrac = Array.from({ length: height }, (_, y) => darkFracRow(y));
  const peaks: number[] = [];
  for (let y = 1; y < height - 1; y++) {
    if (rowFrac[y] > 0.25 && rowFrac[y] >= rowFrac[y - 1] && rowFrac[y] >= rowFrac[y + 1]) peaks.push(y);
  }
  const boundaries: number[] = [0];
  for (const y of peaks) if (y - boundaries[boundaries.length - 1] > 5) boundaries.push(y);
  boundaries.push(height);

  const rawBands: { top: number; bottom: number }[] = [];
  for (let i = 0; i < boundaries.length - 1; i++) {
    const top = Math.max(0, boundaries[i] - 3);
    const bottom = Math.min(height, boundaries[i + 1] + 3);
    if (bottom - top >= 6) rawBands.push({ top, bottom });
  }

  // Rows that abut with no ruled line and no real gap between them (confirmed on the densest
  // section of the first real document tested against this: ~10 product rows packed with zero
  // detectable boundary between any of them) leave one huge band with no internal peaks at all -
  // and OCR-ing a many-row region as if it were one line returns nothing. A typical single-row
  // height is already known from every band elsewhere in this same image; a band several times
  // that tall, and not simply blank margin, almost certainly hides that many un-detected rows -
  // mechanically re-slice it into even-height pieces instead of losing the whole region.
  const heights = rawBands.map((b) => b.bottom - b.top).sort((a, b) => a - b);
  const typical = heights[Math.floor(heights.length * 0.4)] ?? 0;
  const bands: { top: number; bottom: number }[] = [];
  for (const b of rawBands) {
    const h = b.bottom - b.top;
    const avgInk = rowFrac.slice(b.top, b.bottom).reduce((a, v) => a + v, 0) / Math.max(1, h);
    if (typical > 0 && h > typical * 1.8 && avgInk > 0.02) {
      const n = Math.max(1, Math.round(h / typical));
      const step = h / n;
      for (let k = 0; k < n; k++) bands.push({ top: Math.round(b.top + k * step), bottom: Math.round(b.top + (k + 1) * step) });
    } else {
      bands.push(b);
    }
  }
  return bands;
}

/**
 * OCR one image block, reconstructing a table grid from word bounding boxes instead of flat text.
 * Recognizing the whole block in one Tesseract call regularly merged or silently dropped entire
 * rows on the densest real table tested against this (rows packed ~18px apart at scan resolution)
 * - true regardless of upscale factor, since it's Tesseract's own line-layout analysis choking on
 * the tight spacing, not a resolution problem. OCR-ing one row band at a time with PSM.SINGLE_LINE
 * sidesteps that layout analysis entirely: row boundaries are found from the image's own ink
 * profile (detectRowBands) instead of left to Tesseract, and every row gets recognized in
 * isolation, so a neighboring row's height or gap can no longer make this one vanish.
 */
async function ocrTableBlock(
  worker: Awaited<ReturnType<typeof import("tesseract.js").createWorker>>,
  image: Buffer
): Promise<string[][]> {
  const sharp = (await import("sharp")).default;
  const { data: px, info } = await sharp(image).greyscale().raw().toBuffer({ resolveWithObject: true });
  const { width, height } = info;
  const bands = detectRowBands(px, width, height);

  const rows: OcrWord[][] = [];
  for (const band of bands) {
    const cropped = await sharp(px, { raw: { width, height, channels: 1 } })
      .extract({ left: 0, top: band.top, width, height: band.bottom - band.top })
      // small table text (~8-9pt at typical scan resolution) reads far more reliably upscaled first
      .resize({ width: width * 6 })
      .png()
      .toBuffer();
    const { data } = await worker.recognize(cropped, {}, { blocks: true });
    const words: OcrWord[] = [];
    for (const block of data.blocks ?? []) {
      for (const para of block.paragraphs) {
        for (const line of para.lines) {
          for (const w of line.words) {
            const text = w.text.trim();
            if (text === "" || w.confidence < 40) continue; // low confidence: border-line/signature noise, not real text
            if (/^[^\p{L}\p{N}]+$/u.test(text)) continue; // pure punctuation: almost always a misread ruled border, not content
            words.push({ text, confidence: w.confidence, x0: w.bbox.x0, x1: w.bbox.x1, y0: w.bbox.y0, y1: w.bbox.y1 });
          }
        }
      }
    }
    if (words.length > 0) rows.push(words);
  }
  const boundaries = detectColumnBoundaries(rows);
  return rows.map((row) => wordsToRow(row, boundaries)).filter((row) => row.some((c) => c !== ""));
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
 * each time. Each OCR block gets its own column boundaries (detectColumnBoundaries
 * runs per block, since blocks are separate image crops with unrelated pixel
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
 * vendor's wrapped table - nothing here is Rinnai- or category-specific, and
 * literal OCR'd header text (which rarely reproduces identically block to
 * block) is never relied on.
 */
function alignBlocksToCommonColumns(blocks: string[][][]): string[][] {
  const nonEmpty = blocks.filter((b) => b.length > 0);
  if (nonEmpty.length === 0) return [];
  const [first, ...rest] = nonEmpty;
  const canonicalWidth = first.reduce((m, r) => Math.max(m, r.length), 0);
  const canonicalProfiles = Array.from({ length: canonicalWidth }, (_, c) => profileColumn(first, c));

  const merged: string[][] = [...first];
  for (const block of rest) {
    const width = block.reduce((m, r) => Math.max(m, r.length), 0);
    const profiles = Array.from({ length: width }, (_, c) => profileColumn(block, c));
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

/** OCR fallback for scanned/signed PDFs that have no text layer at all. */
async function ocrPdfTable(buffer: Buffer): Promise<string[][]> {
  const images = await extractPageImages(buffer);
  if (images.length === 0) {
    throw new Error(
      "No selectable text found in this PDF, and its embedded image isn't in a format OCR can read (only JPEG/JPEG2000 scans are supported). Provide the data as XLSX/CSV instead."
    );
  }
  const { createWorker, PSM } = await import("tesseract.js");
  const worker = await createWorker("eng", 1, { cachePath: os.tmpdir() });
  try {
    // every recognize() call below targets one already-isolated row band (see ocrTableBlock),
    // never a multi-line block - SINGLE_LINE skips Tesseract's own (unreliable, on this kind of
    // densely-packed table) line-layout analysis entirely instead of fighting it.
    await worker.setParameters({ tessedit_pageseg_mode: PSM.SINGLE_LINE });
    const blocks: string[][][] = [];
    for (const image of images) {
      for (const block of await splitAtColumnGutter(image)) {
        blocks.push(await ocrTableBlock(worker, block));
      }
    }
    return alignBlocksToCommonColumns(blocks);
  } finally {
    await worker.terminate();
  }
}

/**
 * PDF parsing: extract text lines and reconstruct a table heuristically.
 * When a real text layer exists, columns are split on runs of 2+ spaces or
 * tab characters - the delimiter is detected from the document itself, never
 * assumed. Scanned/signed PDFs have no text layer to split that way, so
 * their table grid is reconstructed from OCR word geometry instead (see
 * ocrPdfTable) rather than guessed from spacing in flattened OCR text.
 */
export async function parsePdf(buffer: Buffer): Promise<ParsedFile> {
  const pdfParse = (await import("pdf-parse/lib/pdf-parse.js")).default as (b: Buffer) => Promise<{ text: string }>;
  const { text } = await pdfParse(buffer);

  let matrix: string[][];
  const isOcr = text.trim() === "";
  if (isOcr) {
    matrix = await ocrPdfTable(buffer);
  } else {
    const lines = text
      .split(/\r?\n/)
      .map((l) => l.trimEnd())
      .filter((l) => l.trim() !== "");
    matrix = lines.map((line) => line.split(/\t| {2,}/).map((c) => c.trim()).filter((c, i, arr) => !(c === "" && i === arr.length - 1)));
  }

  if (matrix.length === 0) {
    throw new Error(
      "No text could be read from this PDF, even with OCR. Try a clearer scan, or provide the data as XLSX/CSV instead."
    );
  }
  const width = matrix.reduce((m, r) => Math.max(m, r.length), 0);
  // keep only rows that look tabular (at least half of the max width actually populated) — the
  // rest is page furniture (titles, section headers, footnotes). Counts populated cells, not
  // array length: the OCR path always returns full-width rows padded with empty strings, so a
  // one-word title row has the same length as a real product row and must be judged by content.
  const populated = (r: string[]) => r.filter((c) => c !== "").length;
  const tabular = matrix.filter((r) => populated(r) >= Math.max(2, Math.floor(width / 2)));
  const source = tabular.length >= 3 ? tabular : matrix;

  // Drop columns populated in only a sliver of rows: real columns in a price list are populated
  // throughout, so a column filled in a handful of rows out of dozens is virtually always OCR/
  // alignment noise (a garbled multi-line cell landing in its own stray column, in the one real
  // document tested against this) - not a genuine column. Left in, a near-empty-but-unique column
  // like that can outscore the real product column in the (unrelated) automatic role detector
  // downstream, since "only ever one distinct value" scores as perfectly unique.
  const finalWidth = source.reduce((m, r) => Math.max(m, r.length), 0);
  const keepCols = Array.from({ length: finalWidth }, (_, c) => c).filter(
    (c) => source.filter((r) => (r[c] ?? "") !== "").length / source.length >= 0.1
  );
  const pruned = keepCols.length > 0 ? source.map((r) => keepCols.map((c) => r[c] ?? "")) : source;

  // Header auto-detection (detectHeader) assumes a header row is textually distinguishable from
  // data rows - true for real spreadsheets, but not for this OCR-reconstructed matrix, where every
  // row looks structurally alike (a code plus a couple of numbers) and per-block headers were
  // already stripped by the tabular/sparse-column filters above. On the first real document tested
  // against this, detectHeader picked an ordinary product row as "the header" and every row above
  // it - several genuine products - silently vanished (rows before headerRowIndex are discarded).
  // Skipping header detection for OCR output only avoids that; a real text-layer PDF table keeps
  // normal header detection, since its structure is exact, not reconstructed.
  return { fileType: "pdf", sheets: [sheetFromMatrix("PDF Content", 0, pruned, { useSafeOcrHeader: isOcr })] };
}

export async function parseUploadedFile(buffer: Buffer, fileName: string): Promise<ParsedFile> {
  const ext = fileName.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "pdf") return parsePdf(buffer);
  return parseSpreadsheet(buffer, ext || "xlsx");
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
    // whichever separator comes last is the decimal separator
    if (lastComma > lastDot) s = s.replace(/\./g, "").replace(",", ".");
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
