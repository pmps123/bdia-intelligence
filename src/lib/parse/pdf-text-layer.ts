import { PositionedWord, detectColumnBoundaries, wordsToRow, alignBlocksToCommonColumns, parseNumeric } from "./table-reconstruction";

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

/**
 * Group a page's positioned words into visual rows purely from Y position - no assumption about
 * font, line height, or document layout. PDF's own coordinate space increases upward, so the
 * topmost row has the highest y0; sorting descending walks the page top-to-bottom the way a
 * reader would.
 *
 * The tolerance for "same row" comes from the page's own typical row spacing (median gap between
 * distinct Y positions), not a fixed pixel count - a word's Y can drift a fraction of a point
 * from its neighbors on the same visual line purely from font-run boundaries (confirmed directly:
 * "No" at y=620.2 sitting beside "Product" at y=619.9, both meant to be read as one row), and a
 * fixed tolerance tuned for one document's font size wouldn't generalize to another's.
 */
export function clusterRowsByPosition(words: PositionedWord[]): PositionedWord[][] {
  if (words.length === 0) return [];
  const sorted = [...words].sort((a, b) => b.y0 - a.y0);
  const distinctYs = [...new Set(sorted.map((w) => w.y0))].sort((a, b) => b - a);
  const gaps: number[] = [];
  for (let i = 1; i < distinctYs.length; i++) gaps.push(distinctYs[i - 1] - distinctYs[i]);
  gaps.sort((a, b) => a - b);
  const medianGap = gaps.length > 0 ? gaps[Math.floor(gaps.length / 2)] : 10;
  const tolerance = Math.max(1, medianGap / 2);

  const rows: PositionedWord[][] = [];
  let current: PositionedWord[] = [];
  let rowAnchorY = sorted[0].y0;
  for (const w of sorted) {
    if (current.length === 0) {
      current.push(w);
      rowAnchorY = w.y0;
      continue;
    }
    // compare against the row's first word, not the previous word - avoids slow drift across a
    // long row where each successive word is "close enough" to the last but the row as a whole
    // has wandered several times the tolerance from where it started.
    if (Math.abs(rowAnchorY - w.y0) <= tolerance) {
      current.push(w);
    } else {
      rows.push([...current].sort((a, b) => a.x0 - b.x0));
      current = [w];
      rowAnchorY = w.y0;
    }
  }
  if (current.length > 0) rows.push([...current].sort((a, b) => a.x0 - b.x0));
  return rows;
}

/**
 * Detect leading, non-numeric rows above the first row that actually contains a number, and merge
 * only the ones immediately adjacent to that first data row into one label per column - handling
 * a real header that wraps onto 2+ printed lines (e.g. "Nett Price" over "Exclude PPn Include
 * PPn") while leaving masthead lines further up (document title, effective date, letterhead)
 * alone, since those don't share the header rows' fill pattern (a masthead line is typically one
 * wide cell, not several populated columns matching the table's own width).
 */
export function extractWrappedHeader(rows: string[][]): { headers: string[]; dataStartIndex: number } | null {
  const width = rows.reduce((m, r) => Math.max(m, r.length), 0);
  if (width === 0) return null;

  let firstDataRow = -1;
  for (let i = 0; i < rows.length; i++) {
    if (rows[i].some((c) => c !== "" && parseNumeric(c) !== null)) {
      firstDataRow = i;
      break;
    }
  }
  if (firstDataRow <= 0) return null; // no rows above the data, or no numeric data row found at all

  const isHeaderLike = (row: string[]) => {
    const populated = row.filter((c) => c !== "").length;
    return populated >= Math.max(2, Math.floor(width * 0.5));
  };

  const headerRowIdxs: number[] = [];
  for (let i = firstDataRow - 1; i >= 0; i--) {
    if (!isHeaderLike(rows[i])) break; // masthead - stop climbing, don't fold it into the header
    headerRowIdxs.unshift(i);
  }
  if (headerRowIdxs.length === 0) return null;

  const headers = Array.from({ length: width }, (_, c) =>
    headerRowIdxs
      .map((i) => rows[i][c] ?? "")
      .filter((v) => v !== "")
      .join(" ")
  );
  return { headers, dataStartIndex: firstDataRow };
}

/**
 * Fill forward a "label" row's values into sibling rows in the same un-separated group whose
 * columns are empty exactly where the label row is filled - the merged-cell pattern common in
 * PDFs exported from Excel, e.g. one "No / Product Name" row spanning several "Type / Price" rows
 * beneath it. Direction-agnostic: the label row can sit anywhere within its group, not just at
 * the top - confirmed directly on a real document (Panasonic Pump) where it sat between the 2nd
 * and 3rd of three sibling rows, a leftover baseline artifact from a flattened merged cell.
 *
 * ponytail: tuned against a single real example. A vendor whose merged-cell shape doesn't reduce
 * to exactly one complementary "label" row per group (e.g. two partial label rows) is left
 * untouched rather than guessed at - see design doc for the fuller reasoning.
 */
export function fillStaggeredGroups(rows: string[][]): string[][] {
  const groups: string[][][] = [];
  let current: string[][] = [];
  for (const row of rows) {
    if (row.every((c) => c === "")) {
      if (current.length > 0) groups.push(current);
      current = [];
      groups.push([row]); // keep the blank row itself, as its own single-row "group"
    } else {
      current.push(row);
    }
  }
  if (current.length > 0) groups.push(current);

  const result: string[][] = [];
  for (const group of groups) {
    if (group.length <= 1) {
      result.push(...group);
      continue;
    }
    const masks = group.map((r) => r.map((c) => c !== ""));
    let labelIdx = -1;
    for (let i = 0; i < group.length; i++) {
      const labelMask = masks[i];
      const others = masks.filter((_, j) => j !== i);
      const complementary = others.every(
        (m) =>
          labelMask.every((filled, c) => !filled || !m[c]) && // label's filled cols are empty in every other row
          m.some((filled, c) => filled && !labelMask[c]) // every other row fills at least one col the label leaves empty
      );
      if (complementary) {
        labelIdx = i;
        break;
      }
    }
    if (labelIdx === -1) {
      result.push(...group); // doesn't match the expected pattern - leave as-is, don't force it
      continue;
    }
    const label = group[labelIdx];
    result.push(...group.map((row) => row.map((c, ci) => (c === "" && label[ci] !== "" ? label[ci] : c))));
  }
  return result;
}

/**
 * Full text-layer reconstruction pipeline: real x/y positions → rows (by Y) → columns (by X gaps,
 * reused from the OCR path) → wrapped-header merge → merged-cell fill-forward → multi-page align
 * (reused from the OCR path). Returns null when the reconstruction looks degenerate (no positioned
 * text at all, or column detection can't find real boundaries despite plenty of words per row) so
 * the caller can fall back to the existing whitespace-split heuristic instead of trusting a
 * garbled result.
 */
export async function reconstructTextLayerTable(
  buffer: Buffer
): Promise<{ matrix: string[][]; headers: string[] | null } | null> {
  const pages = await extractPositionedItems(buffer);
  const pageRowsOfWords = pages.map((p) => clusterRowsByPosition(p)).filter((rows) => rows.length > 0);
  if (pageRowsOfWords.length === 0) return null;

  let firstPageHeaders: string[] | null = null;
  const blocks: string[][][] = [];
  let totalWords = 0;
  let totalRows = 0;

  for (let p = 0; p < pageRowsOfWords.length; p++) {
    const rowsOfWords = pageRowsOfWords[p];
    for (const r of rowsOfWords) {
      totalWords += r.length;
      totalRows += 1;
    }
    const boundaries = detectColumnBoundaries(rowsOfWords);
    if (boundaries.length === 0) {
      blocks.push([]); // this page's positions didn't yield usable columns - skip it, not the whole document
      continue;
    }
    const pageRows = rowsOfWords.map((r) => wordsToRow(r, boundaries)).filter((r) => r.some((c) => c !== ""));
    // A repeated header on page 2+ of a long, continued table (common in multi-page price lists)
    // gets detected and stripped the same way as page 1's real header - only page 1's labels are
    // kept as the final column headers, matching alignBlocksToCommonColumns' own assumption that
    // only the first block's header lines up with the merged table's final column indices.
    const header = extractWrappedHeader(pageRows);
    const dataRows = header ? pageRows.slice(header.dataStartIndex) : pageRows;
    if (p === 0) firstPageHeaders = header?.headers ?? null;
    blocks.push(dataRows);
  }

  if (blocks.every((b) => b.length === 0)) return null;
  const merged = alignBlocksToCommonColumns(blocks);
  const width = merged.reduce((m, r) => Math.max(m, r.length), 0);
  const avgWordsPerRow = totalRows > 0 ? totalWords / totalRows : 0;
  // Degenerate: column detection collapsed everything into ~1 column despite rows that clearly
  // have several distinct words each - a real reconstruction never looks like this; the existing
  // whitespace-split fallback does better on whatever's going on with this particular PDF.
  if (width <= 1 && avgWordsPerRow > 3) return null;

  return { matrix: fillStaggeredGroups(merged), headers: firstPageHeaders };
}