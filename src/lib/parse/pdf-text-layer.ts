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
