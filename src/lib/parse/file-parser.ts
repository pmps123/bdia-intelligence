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

function sheetFromMatrix(
  name: string,
  index: number,
  matrix: string[][],
  opts?: { useSafeOcrHeader?: boolean; explicitHeaders?: string[] }
): ParsedSheet {
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
  // Real header text recovered from the PDF's own header region (see extractHeaderLabels) beats
  // any heuristic guess - these rows never need stripping since they came from a separate crop,
  // not from a row within this matrix.
  if (opts?.explicitHeaders && opts.explicitHeaders.some((h) => h !== "")) {
    const headers = Array.from({ length: width }, (_, i) => opts.explicitHeaders![i] || `Column ${i + 1}`);
    return { name, index, rowCount: normalized.length, columnCount: width, headers, headerRowIndex: -1, rows: normalized };
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

/**
 * Detect where one printed table row ends and the next begins, from the image itself: a row of
 * pixels that's darker than its neighbors (a local peak in per-row ink density) marks either a
 * ruled divider or the visual "gap" between two lines of text - either way, a boundary. Catches
 * both because thin dotted cell borders AND blank space between text baselines both show up as a
 * peak relative to the (near-blank) space right around them; nothing here assumes ruled lines
 * exist at all.
 */
function detectRowBands(
  px: Buffer,
  width: number,
  height: number
): { bands: { top: number; bottom: number }[]; headerRegion: { top: number; bottom: number } | null } {
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
  // Pass 1: collapse local maxima that belong to the same stroke/character (a few px apart) into
  // one boundary per visual text line, using the original small fixed floor.
  const linePeaks: number[] = [0];
  for (const y of peaks) if (y - linePeaks[linePeaks.length - 1] > 5) linePeaks.push(y);

  // Pass 2: a ruled cell border sits as its own strong ink peak just a few px from the adjacent
  // text row's own line-peak (confirmed on the first real document tested against this, in a
  // grid-bordered table region), and pass 1's fixed floor alone counted it as an extra row boundary
  // there - one printed row was split into several near-empty bands, and the resulting noise words
  // went on to corrupt column-boundary detection for the whole block downstream. The minimum gap
  // that counts as a genuinely new row scales off the median line-to-line gap actually observed in
  // THIS image (computed from pass 1's output, not the raw same-character noise pass 1 already
  // absorbed) instead of a fixed pixel count, so it adapts to any font size or scan resolution - a
  // table that's uniformly this dense throughout (the original reason for a small floor) keeps a
  // small median too, so its own lines stay ungrouped; only a spurious minority of anomalously
  // tight gaps against an otherwise-normal rhythm get merged away.
  // ponytail: a global median under-merges a densely multi-boxed group whose OWN border-vs-text
  // gap runs no wider than its real row-to-row gap (confirmed on a real document: one such group
  // stayed split into half-height bands, scattering a product's code and prices across rows that
  // never reunited downstream) - a local window was tried and rejected here (see git history),
  // since within that same group both gap kinds are similarly tight and no gap-distance threshold,
  // local or global, can tell them apart; would need a different signal (e.g. peak sharpness) to
  // fix, not just a smaller floor.
  const lineGaps = linePeaks.slice(2).map((y, i) => y - linePeaks[i + 1]).sort((a, b) => a - b);
  const medianLineGap = lineGaps.length >= 3 ? lineGaps[Math.floor(lineGaps.length / 2)] : 0;
  const minLineGap = Math.max(5, medianLineGap * 0.6);
  const boundaries: number[] = [0];
  for (const y of linePeaks.slice(1)) if (y - boundaries[boundaries.length - 1] > minLineGap) boundaries.push(y);
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
  // that tall, and not simply blank margin, almost certainly hides that many un-detected rows.
  const heights = rawBands.map((b) => b.bottom - b.top).sort((a, b) => a - b);
  const typical = heights[Math.floor(heights.length * 0.4)] ?? 0;
  if (process.env.DEBUG_ROWS) console.error(`typical=${typical} heights=${heights.join(",")}`);

  // The very first band, when it's this same oversized mixed-content case, is exactly the
  // logo/title/column-header region above the table - genuinely worth reading as one multi-line
  // block (see extractHeaderLabels) instead of only mining a stray first data row out of it.
  const first = rawBands[0];
  const headerRegion =
    first && first.top <= 3 && typical > 0 && first.bottom - first.top > typical * 1.5
      ? { top: first.top, bottom: first.bottom }
      : null;

  const bands: { top: number; bottom: number }[] = [];
  for (const b of rawBands) {
    // The header region is OCR'd separately as one cohesive block (see extractHeaderLabels) -
    // slicing it into row-bands here too used to feed mangled logo/title fragments into the data
    // rows as phantom leading entries (confirmed on the first real document tested against this).
    if (headerRegion && b.top === headerRegion.top && b.bottom === headerRegion.bottom) continue;
    const h = b.bottom - b.top;
    const avgInk = rowFrac.slice(b.top, b.bottom).reduce((a, v) => a + v, 0) / Math.max(1, h);
    if (typical > 0 && h > typical * 1.5 && avgInk > 0.02) {
      // An oversized band isn't always a uniform run of identical rows, though - the region right
      // below a page's logo/title regularly mixes a faint logo, a section header and the first
      // real data row in one un-detected span (confirmed on the first real document tested
      // against this: mechanically dividing that mix into equal pieces cut straight through the
      // first product row and lost it). Try a second, more sensitive peak search scoped to just
      // this span before assuming it's a uniform cluster - genuinely mixed content almost always
      // still has SOME internal gap, just fainter than the standard row-to-row one. Only fall back
      // to blind equal-division when even that finds nothing (the truly undivided dense case this
      // was originally written for).
      const subPeaks: number[] = [];
      for (let y = b.top + 1; y < b.bottom - 1; y++) {
        if (rowFrac[y] > 0.12 && rowFrac[y] >= rowFrac[y - 1] && rowFrac[y] >= rowFrac[y + 1]) subPeaks.push(y);
      }
      const subBoundaries: number[] = [b.top];
      for (const y of subPeaks) if (y - subBoundaries[subBoundaries.length - 1] > 5) subBoundaries.push(y);
      subBoundaries.push(b.bottom);

      const subBands: { top: number; bottom: number }[] = [];
      if (subBoundaries.length > 2) {
        for (let i = 0; i < subBoundaries.length - 1; i++) {
          const top = Math.max(b.top, subBoundaries[i] - 2);
          const bottom = Math.min(b.bottom, subBoundaries[i + 1] + 2);
          if (bottom - top >= 6) subBands.push({ top, bottom });
        }
      }
      // A resplit that produces pieces far smaller than a real row is the same border-artifact
      // noise the row-rhythm-adaptive gap above already rejected once (a ruled cell border sitting
      // right next to the real text line's own peak, not a genuinely separate row - confirmed on
      // the first real document tested against this, a grid-bordered region whose extra border
      // peaks came back at this more sensitive threshold even after being merged away up above).
      // Equal division, which can only produce plausibly row-sized pieces by construction, is the
      // safer fallback than trusting a resplit that doesn't.
      if (subBands.length > 1 && subBands.every((sb) => sb.bottom - sb.top >= typical * 0.5)) {
        bands.push(...subBands);
      } else {
        const n = Math.max(1, Math.round(h / typical));
        const step = h / n;
        for (let k = 0; k < n; k++) bands.push({ top: Math.round(b.top + k * step), bottom: Math.round(b.top + (k + 1) * step) });
      }
    } else {
      bands.push(b);
    }
  }
  return { bands, headerRegion };
}

/**
 * Read the header region - logo, title and column labels, all mixed together - as one cohesive
 * multi-line block instead of the disconnected ~20px strips the row-band pass uses for data.
 * PSM.SINGLE_BLOCK is built for exactly this (short multi-line text), unlike PSM.SINGLE_LINE.
 * Recognized words are bucketed into the SAME column boundaries the data rows use, then joined in
 * reading order (top-to-bottom within a column) so a header that wraps onto two printed lines -
 * e.g. "Netto" / "Zona 1" - reconstructs as one label per column. Nothing here depends on any
 * specific header wording, so it works for any vendor's PDF with a header-above-data layout.
 */
async function extractHeaderLabels(
  worker: Awaited<ReturnType<typeof import("tesseract.js").createWorker>>,
  px: Buffer,
  width: number,
  height: number,
  headerRegion: { top: number; bottom: number },
  boundaries: number[]
): Promise<string[] | null> {
  const sharp = (await import("sharp")).default;
  const { PSM } = await import("tesseract.js");

  // The header region can bundle real column labels together with page furniture sitting above
  // them - a vendor's logo, a tagline, an "effective as of" date, never the same text twice.
  // Split the region into its own physical print lines (same sub-peak technique as the oversized-
  // band case above, just more sensitive since this crop is small and homogeneous) and drop the
  // topmost line: a genuine multi-line header (e.g. "Price List" / "(excl PPN)") sits directly
  // above the data rows, while masthead content sits a further, real gap above THAT. Nothing here
  // reads or assumes what that first line says, so it holds for any vendor's layout.
  const darkFracRow = (y: number) => {
    let c = 0;
    const off = y * width;
    for (let x = 0; x < width; x++) if (px[off + x] < 190) c++;
    return c / width;
  };
  const rowFrac = Array.from({ length: headerRegion.bottom - headerRegion.top }, (_, i) => darkFracRow(headerRegion.top + i));
  const peaks: number[] = [];
  for (let i = 1; i < rowFrac.length - 1; i++) {
    if (rowFrac[i] > 0.12 && rowFrac[i] >= rowFrac[i - 1] && rowFrac[i] >= rowFrac[i + 1]) peaks.push(headerRegion.top + i);
  }
  const lineBoundaries: number[] = [headerRegion.top];
  for (const y of peaks) if (y - lineBoundaries[lineBoundaries.length - 1] > 5) lineBoundaries.push(y);
  lineBoundaries.push(headerRegion.bottom);
  // +6px past the boundary itself: it sits ON the discarded line's ink-density peak (which, right
  // at a ruled table border, IS the border rule), so cropping exactly there slices through it and
  // OCR reads the cut border as stray garbled characters - confirmed directly.
  const cropTop = lineBoundaries.length > 2 ? Math.min(headerRegion.bottom - 6, lineBoundaries[1] + 6) : headerRegion.top;

  const cropped = await sharp(px, { raw: { width, height, channels: 1 } })
    .extract({ left: 0, top: cropTop, width, height: headerRegion.bottom - cropTop })
    .resize({ width: width * 6 })
    .png()
    .toBuffer();

  await worker.setParameters({ tessedit_pageseg_mode: PSM.SINGLE_BLOCK });
  let words: OcrWord[];
  try {
    words = await recognizeRowWords(worker, cropped);
  } finally {
    // every other caller of this worker expects row-band mode; restore it before returning.
    await worker.setParameters({ tessedit_pageseg_mode: PSM.SINGLE_LINE });
  }
  if (words.length === 0) return null;

  const bucketOf = (w: OcrWord) => {
    const cx = (w.x0 + w.x1) / 2;
    const col = boundaries.findIndex((b) => cx < b);
    return col === -1 ? boundaries.length : col;
  };

  // A masthead can be more than one physical line tall (e.g. a logo line plus a tagline line
  // right below it) - dropping only the single line above already stripped only the first of
  // those, so the second one's garbled OCR text still bled into column 0's label (confirmed
  // directly on a real document: a tagline read as "ER ENE." and prefixed the real "BUILT-IN
  // HOB" header). A genuine header line labels several columns at once; a masthead line's text
  // sits within just one of them (usually the leftmost, under the logo). Keep peeling further
  // leading lines off - by the SAME column buckets the final labels use, never by wording - as
  // long as each one touches at most one column, always leaving at least the last physical line
  // in the region (the real header can never be dropped entirely this way).
  const scale = 6; // the crop was upscaled by this same fixed factor in both dimensions
  let cutAt = cropTop;
  for (let j = 1; j < lineBoundaries.length - 2; j++) {
    const lineWords = words.filter((w) => {
      const origY = cropTop + w.y0 / scale;
      return origY >= lineBoundaries[j] && origY < lineBoundaries[j + 1];
    });
    if (lineWords.length > 0 && new Set(lineWords.map(bucketOf)).size > 1) break;
    cutAt = lineBoundaries[j + 1];
  }
  const headerWords = cutAt > cropTop ? words.filter((w) => cropTop + w.y0 / scale >= cutAt) : words;
  if (headerWords.length === 0) return null;

  const cols: OcrWord[][] = Array.from({ length: boundaries.length + 1 }, () => []);
  for (const w of headerWords) {
    cols[bucketOf(w)].push(w);
  }
  const labels = cols.map((colWords) =>
    [...colWords].sort((a, b) => a.y0 - b.y0 || a.x0 - b.x0).map((w) => w.text).join(" ")
  );
  return labels.some((l) => l !== "") ? labels : null;
}

const BRACKET_OPENERS: Record<string, string> = { ")": "(", "]": "[", "}": "{" };

/** Recognize one already-isolated row-band crop, returning its words filtered the same way every recognition pass is: confidence >= 40, not pure punctuation. */
async function recognizeRowWords(worker: Awaited<ReturnType<typeof import("tesseract.js").createWorker>>, cropped: Buffer): Promise<OcrWord[]> {
  const { data } = await worker.recognize(cropped, {}, { blocks: true });
  const words: OcrWord[] = [];
  for (const block of data.blocks ?? []) {
    for (const para of block.paragraphs) {
      for (const line of para.lines) {
        for (const w of line.words) {
          const text = w.text.trim();
          if (process.env.DEBUG_WORDS) console.error(`    raw word ${JSON.stringify(text)} conf=${w.confidence.toFixed(1)}`);
          if (text === "" || w.confidence < 40) continue; // low confidence: border-line/signature noise, not real text
          if (/^[^\p{L}\p{N}]+$/u.test(text)) {
            const prev = words[words.length - 1];
            // A lone closing bracket that Tesseract split off as its own word (common right after
            // a product code's variant suffix, e.g. "RB-311N(GB" + ")" - confirmed on the first
            // real document tested against this, where nearly every parenthesized code lost its
            // close paren) reads as pure punctuation and was being dropped outright as border
            // noise. Reattach it to the immediately preceding word on this line when that word
            // still has an unmatched opener, instead of losing real content.
            const opener = BRACKET_OPENERS[text];
            if (opener && prev) {
              const opens = prev.text.split(opener).length - 1;
              const closes = prev.text.split(text).length - 1;
              if (opens > closes) {
                prev.text += text;
                prev.x1 = w.bbox.x1;
                continue;
              }
            }
            // A vendor's own footnote marker ("*)", "**)", meaning "price increased") sits right
            // after the product code as its own OCR word and was being dropped the same way. Keep
            // it, space-separated (it's a genuinely separate visual token in the source, unlike a
            // split bracket) - a downstream highlight rule depends on "*" surviving into the
            // exported product name.
            if (text.includes("*") && prev) {
              prev.text += " " + text;
              prev.x1 = w.bbox.x1;
              continue;
            }
            // anything else pure punctuation (an actual misread ruled border) is still dropped.
            continue;
          }
          words.push({ text, confidence: w.confidence, x0: w.bbox.x0, x1: w.bbox.x1, y0: w.bbox.y0, y1: w.bbox.y1 });
        }
      }
    }
  }
  return words;
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
): Promise<{ rows: string[][]; headerLabels: string[] | null }> {
  const sharp = (await import("sharp")).default;
  const { data: px, info } = await sharp(image).greyscale().raw().toBuffer({ resolveWithObject: true });
  const { width, height } = info;
  const { bands, headerRegion } = detectRowBands(px, width, height);
  if (process.env.DEBUG_ROWS) console.error(`block ${width}x${height}, ${bands.length} bands:`, bands.map((b) => `${b.top}-${b.bottom}`).join(", "));

  const STANDARD_SCALE = 6;
  const RETRY_SCALE = 4;
  const cropAt = (band: { top: number; bottom: number }, scale: number) =>
    sharp(px, { raw: { width, height, channels: 1 } })
      .extract({ left: 0, top: band.top, width, height: band.bottom - band.top })
      // small table text (~8-9pt at typical scan resolution) reads far more reliably upscaled first
      .resize({ width: width * scale })
      .png()
      .toBuffer();

  const standardPass: OcrWord[][] = [];
  for (const band of bands) standardPass.push(await recognizeRowWords(worker, await cropAt(band, STANDARD_SCALE)));

  // A genuine product row's field count matches most other rows in this same block - a code plus
  // however many price columns this vendor prints - not a fixed guess, since that count varies
  // vendor to vendor. The modal row width across the whole block catches a row that lost just ONE
  // of several fields, which a fixed "fewer than 2" floor never could: confirmed directly on a
  // real document, several rows here kept a code and exactly one of two price columns - 2 words,
  // never below the old floor - and silently kept the other price blank forever.
  const widthCounts = new Map<number, number>();
  for (const r of standardPass) if (r.length > 0) widthCounts.set(r.length, (widthCounts.get(r.length) ?? 0) + 1);
  let modalWidth = 0;
  let modalCount = 0;
  for (const [w, c] of widthCounts) if (c > modalCount || (c === modalCount && w > modalWidth)) { modalWidth = w; modalCount = c; }
  const retryFloor = Math.max(2, modalWidth);

  const rows: OcrWord[][] = [];
  for (let i = 0; i < bands.length; i++) {
    const band = bands[i];
    const standardWords = standardPass[i];
    let words = standardWords;
    // Retrying the identical crop gets the identical result - confirmed directly, Tesseract's
    // recognition is deterministic for identical input within a process, even across separate
    // worker instances - but a *different* upscale factor is a genuinely different input, and
    // confidence on borderline text swings meaningfully with it (confirmed directly: the same
    // row's price scored 3%, 96%, and 0% confidence at 6x, 4x and 8x respectively), so it's worth
    // an independent second attempt rather than a repeat.
    if (words.length < retryFloor) {
      const retryWords = await recognizeRowWords(worker, await cropAt(band, RETRY_SCALE));
      if (retryWords.length > words.length) {
        // detectColumnBoundaries/wordsToRow compare x-positions across every row in the block, so
        // a retry recognized at a different scale must have its coordinates normalized back to the
        // standard scale first - otherwise this row's words land in the wrong column bucket
        // relative to every row recognized at the standard scale (confirmed directly).
        const factor = STANDARD_SCALE / RETRY_SCALE;
        words = retryWords.map((w) => ({ ...w, x0: w.x0 * factor, x1: w.x1 * factor, y0: w.y0 * factor, y1: w.y1 * factor }));
        // The two scales don't just differ in confidence on the SAME text - they can each glyph-
        // read the same product code differently and both be partly wrong (confirmed directly: one
        // real cell read as "IRB31IN(GB)" at 6x - garbled digits, but the closing paren present -
        // and "RB-311N(GB" at 4x - correct digits, closing paren glyph simply never recognized).
        // The word-count tie-break above picked the 4x reading here for its digits, silently
        // losing a closing bracket the 6x reading actually had. Only that specific missing closer
        // is borrowed back, not the rest of the discarded word, since it typically lost the
        // tie-break for a reason (worse digits).
        const code = words[0];
        const otherCode = standardWords[0];
        if (code && otherCode) {
          const opens = (code.text.match(/\(/g) ?? []).length;
          const closes = (code.text.match(/\)/g) ?? []).length;
          const otherOpens = (otherCode.text.match(/\(/g) ?? []).length;
          const otherCloses = (otherCode.text.match(/\)/g) ?? []).length;
          if (opens > closes && otherCloses >= otherOpens && otherCode.text.endsWith(")")) {
            words[0] = { ...code, text: code.text + ")" };
          }
        }
      }
    }
    if (process.env.DEBUG_ROWS) {
      console.error(`[band ${band.top}-${band.bottom}] ${words.map((w) => w.text).join(" ")}`);
    }
    if (words.length > 0) rows.push(words);
  }
  const boundaries = detectColumnBoundaries(rows);
  if (process.env.DEBUG_ROWS) console.error(`block ${width}x${height} boundaries: ${boundaries.map((b) => b.toFixed(0)).join(", ")}`);
  const dataRows = rows.map((row) => wordsToRow(row, boundaries)).filter((row) => row.some((c) => c !== ""));
  const headerLabels = headerRegion ? await extractHeaderLabels(worker, px, width, height, headerRegion, boundaries) : null;
  return { rows: dataRows, headerLabels };
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

/** OCR fallback for scanned/signed PDFs that have no text layer at all. */
async function ocrPdfTable(
  buffer: Buffer
): Promise<{ matrix: string[][]; headerLabels: string[] | null; categoryHints: (string | null)[] }> {
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
    // alignBlocksToCommonColumns maps every later block onto the FIRST block's column layout, so
    // only the first block's header labels line up with the merged table's final column indices.
    let headerLabels: string[] | null = null;
    let firstBlockSeen = false;
    // A page with several side-by-side blocks (see alignBlocksToCommonColumns) is often really one
    // table split for space, but each block can still be its own product category ("BUILT-IN HOB"
    // vs "COOKER HOOD") - and that name only ever appears reliably in the block's OWN header region
    // (whole-block OCR, see extractHeaderLabels), never as a legible standalone row further down
    // the merged data. Remember it per block so parsePdf can seed the right category at each
    // block's boundary instead of trying to re-read the same text a second, less reliable way.
    const blockCategoryHints: (string | null)[] = [];
    for (const image of images) {
      for (const block of await splitAtColumnGutter(image)) {
        if (process.env.DEBUG_ROWS) console.error(`=== ocrTableBlock #${blocks.length} ===`);
        const result = await ocrTableBlock(worker, block);
        if (process.env.DEBUG_ROWS) console.error(`block #${blocks.length} rows:`, JSON.stringify(result.rows));
        blocks.push(result.rows);
        blockCategoryHints.push(result.headerLabels?.[0]?.trim() || null);
        if (!firstBlockSeen) {
          firstBlockSeen = true;
          headerLabels = result.headerLabels;
        }
      }
    }
    // alignBlocksToCommonColumns pushes every row of every non-empty block, in order, with none
    // dropped - so each block's row count alone is enough to map merged rows back to their block.
    const categoryHints = blocks.flatMap((b, i) => b.map(() => blockCategoryHints[i]));
    return { matrix: alignBlocksToCommonColumns(blocks), headerLabels, categoryHints };
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
  let ocrHeaderLabels: string[] | null = null;
  let ocrCategoryHints: (string | null)[] | null = null;
  const isOcr = text.trim() === "";
  if (isOcr) {
    const result = await ocrPdfTable(buffer);
    matrix = result.matrix;
    ocrHeaderLabels = result.headerLabels;
    ocrCategoryHints = result.categoryHints;
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

  // A category break - a section title ("COOKER HOOD", "ELECTRIC WATER HEATER") sitting between
  // two blocks of what the tabular filter below flattens into one continuous table (see
  // alignBlocksToCommonColumns, built for exactly this "one table split across the page for
  // space" case) - has two possible sources. The reliable one is each OCR block's own header
  // region (ocrCategoryHints, whole-block OCR - see extractHeaderLabels): it resets the category
  // right at a block boundary even though the text that names it never appears anywhere in the
  // block's own data rows. Within a block, a further sub-category still only shows up as a lone
  // populated, non-numeric data row (e.g. "BUILT IN OVEN" partway down the Built-in Hob block) -
  // required to be a real word or two (length >= 5) containing a space, not the odd short OCR
  // fragment ("Sr", "DU") a signature or misread border leaves behind, which used to be mistaken
  // for a new category and fragmented one section into several bogus ones. The space requirement
  // additionally rules out a genuine product code whose price/netto happened to OCR as empty on
  // this particular row (confirmed: "RH-KT2959-GBV" alone in its row, with no price data recovered
  // at all, otherwise reads as a plausible "category title" too) - a category title in this kind
  // of document is a multi-word phrase, a product code virtually never contains a space. A code
  // still carrying its own price-increase marker ("RES-A10C-02C *" - see the OCR word-merge above)
  // also has a space though, so the digit check matters too: a category title never contains a
  // digit, a product code always does. Nothing here reads what a label actually says beyond that
  // shape, so it holds for any vendor's layout.
  let currentCategory = "";
  let lastHint: string | null = null;
  const categoryByRow = matrix.map((r, i) => {
    const hint = ocrCategoryHints?.[i] ?? null;
    if (hint && hint !== lastHint) currentCategory = hint;
    lastHint = hint;
    const nonEmpty = r.filter((c) => c !== "");
    if (
      nonEmpty.length === 1 &&
      nonEmpty[0].length >= 5 &&
      /\s/.test(nonEmpty[0]) &&
      !/\d/.test(nonEmpty[0]) &&
      parseNumeric(nonEmpty[0]) === null
    ) {
      currentCategory = nonEmpty[0];
    }
    return currentCategory;
  });

  // keep only rows that look tabular (at least half of the max width actually populated) — the
  // rest is page furniture (titles, section headers, footnotes). Counts populated cells, not
  // array length: the OCR path always returns full-width rows padded with empty strings, so a
  // one-word title row has the same length as a real product row and must be judged by content.
  const populated = (r: string[]) => r.filter((c) => c !== "").length;
  const tabularMask = matrix.map((r) => populated(r) >= Math.max(2, Math.floor(width / 2)));
  const useTabular = tabularMask.filter(Boolean).length >= 3;
  const source = useTabular ? matrix.filter((_, i) => tabularMask[i]) : matrix;
  const sourceCategories = useTabular ? categoryByRow.filter((_, i) => tabularMask[i]) : categoryByRow;

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
  // ocrHeaderLabels was built in the same column space as the un-pruned matrix (one label per
  // detectColumnBoundaries bucket), so it must be pruned the same way to stay index-synced.
  const prunedHeaderLabels =
    ocrHeaderLabels && keepCols.length > 0 ? keepCols.map((c) => ocrHeaderLabels![c] ?? "") : ocrHeaderLabels;

  // A row with no numeric value anywhere carries zero price information - whatever text landed in
  // its other cells (a signature stroke, a misread border, a stray footnote fragment - "DU", "Ld",
  // "DLI" on the first real document tested against this) is noise, not an unreadable product,
  // and only clutters a price audit that's fundamentally about comparing numbers. The 3-digit
  // floor rules out a lone stray digit ("1", "2") passing as a "price" while staying far below any
  // real price or code in this kind of document. Real spreadsheets never hit this path - it's
  // scoped to the reconstructed-from-OCR matrix's own noise, not a general row filter.
  const hasUsableNumber = (r: string[]) => r.some((c) => { const n = parseNumeric(c); return n !== null && Math.abs(n) >= 100; });
  const keepRows = isOcr ? pruned.map(hasUsableNumber) : pruned.map(() => true);
  const numericFiltered = keepRows.every(Boolean) ? pruned : pruned.filter((_, i) => keepRows[i]);
  const numericFilteredCategories = keepRows.every(Boolean) ? sourceCategories : sourceCategories.filter((_, i) => keepRows[i]);

  // Only worth a column when the document actually had section breaks - most vendor PDFs are one
  // flat list and would otherwise get a column of empty strings.
  const hasCategories = numericFilteredCategories.some((c) => c !== "");
  const withCategory = hasCategories ? numericFiltered.map((r, i) => [...r, numericFilteredCategories[i]]) : numericFiltered;
  const headerLabelsWithCategory =
    hasCategories && prunedHeaderLabels ? [...prunedHeaderLabels, "Category"] : prunedHeaderLabels;

  // Header auto-detection (detectHeader) assumes a header row is textually distinguishable from
  // data rows - true for real spreadsheets, but not for this OCR-reconstructed matrix, where every
  // row looks structurally alike (a code plus a couple of numbers) and per-block headers were
  // already stripped by the tabular/sparse-column filters above. On the first real document tested
  // against this, detectHeader picked an ordinary product row as "the header" and every row above
  // it - several genuine products - silently vanished (rows before headerRowIndex are discarded).
  // Skipping header detection for OCR output only avoids that; a real text-layer PDF table keeps
  // normal header detection, since its structure is exact, not reconstructed. When the header
  // region itself was OCR'd successfully (extractHeaderLabels), those real labels are used
  // directly instead of falling back to generic "Column N" placeholders.
  return {
    fileType: "pdf",
    sheets: [
      sheetFromMatrix("PDF Content", 0, withCategory, { useSafeOcrHeader: isOcr, explicitHeaders: headerLabelsWithCategory ?? undefined }),
    ],
  };
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
