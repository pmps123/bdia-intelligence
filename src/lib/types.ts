import { generateUUID } from "@/lib/utils";

/** Internal price sources a Price Audit project can be based on. */
export const PRICE_SOURCES = {
  PRICE_LIST: "Price List by Product",
  BASIC: "Basic Price",
  CUSTOM: "Customized Price",
} as const;

export type PriceSource = keyof typeof PRICE_SOURCES;

export const priceSourceLabel = (s: string | null | undefined): string =>
  PRICE_SOURCES[(s ?? "") as PriceSource] ?? PRICE_SOURCES.BASIC;

/** Semantic fields a user can map a detected column to. Purely labels — never tied to any specific file. */
export const SEMANTIC_FIELDS = [
  "productName",
  "productCode",
  "productVariant",
  "brand",
  "category",
  "vendor",
  "basicPrice",
  "invoicePrice",
  "invoicePriceVat",
  "nettPrice",
  "qty",
  "qtyRule",
  "qtyFrom",
  "qtyTo",
  "description",
  "status",
] as const;

export type SemanticField = (typeof SEMANTIC_FIELDS)[number];

export const FIELD_LABELS: Record<SemanticField, string> = {
  productName: "Product Name",
  productCode: "Product Code",
  productVariant: "Product Variant",
  brand: "Brand",
  category: "Category",
  vendor: "Vendor",
  basicPrice: "Basic Price",
  invoicePrice: "Invoice Price",
  invoicePriceVat: "Invoice Price + VAT",
  nettPrice: "Nett Price",
  qty: "Qty",
  qtyRule: "Qty Rule",
  qtyFrom: "Qty From",
  qtyTo: "Qty To",
  description: "Description",
  status: "Status",
};

export const PRICE_FIELDS: SemanticField[] = ["basicPrice", "invoicePrice", "invoicePriceVat", "nettPrice"];

/** One detected column and what the user decided to do with it. */
export interface ColumnMapping {
  sourceIndex: number;
  sourceName: string; // header text detected in the file
  field: SemanticField | null; // semantic assignment, null = custom/extra column
  rename: string; // display name (user may rename); defaults to sourceName
  ignore: boolean;
}

export interface ParsedSheet {
  name: string;
  index: number;
  rowCount: number;
  columnCount: number;
  headers: string[];
  headerRowIndex: number;
  rows: string[][]; // data rows (below the detected header row)
}

export interface ParsedFile {
  fileType: string;
  sheets: ParsedSheet[];
}

export interface CleaningRule {
  id: string;
  label: string;
  description: string;
  occurrences: number;
}

export interface CleaningReport {
  rules: CleaningRule[];
  sampleSize: number;
}

export interface MatchCandidate {
  rowId: string;
  label: string;
  code?: string | null;
  score: number;
}

/**
 * Price validation result table is a full join between vendor and internal
 * rows — SAME/HIGHER/LOWER/MISSING cover the matched pairs; NOT_IN_INTERNAL
 * and NOT_IN_VENDOR cover the join's unmatched sides.
 */
export const PRICE_STATUS_LABELS: Record<string, string> = {
  SAME: "Same",
  HIGHER: "Higher",
  LOWER: "Lower",
  MISSING: "Missing",
  NOT_IN_INTERNAL: "Tidak ada di internal",
  NOT_IN_VENDOR: "Tidak ada kenaikan harga",
};

export const priceStatusLabel = (status: string): string => PRICE_STATUS_LABELS[status] ?? status;

export interface ExportColumnConfig {
  key: string;
  title: string;
  include: boolean;
  width: number; // characters (excel) / relative (pdf)
}

/* ---------- Notion-like blocks (workspace page, notes) ---------- */

export type BlockType = "text" | "heading" | "bullet" | "table" | "image";

export interface TextBlockContent {
  text: string;
}

export interface ImageBlockContent {
  url: string;
  caption: string;
}

export interface BulletItem {
  id: string;
  text: string;
  checked: boolean;
}

export interface BulletBlockContent {
  items: BulletItem[];
}

/** A database-style column's data type — same small vocabulary as Notion's property types. */
export type ColumnType = "text" | "number" | "select" | "status" | "date" | "person" | "checkbox" | "url";

export interface TableColumnDef {
  id: string;
  name: string;
  /** Defaults to "text" when absent — every table created before typed columns existed keeps working unchanged. */
  type?: ColumnType;
  /** Known values for "select" | "status" | "person" — new values typed into a cell are appended here automatically. */
  options?: string[];
  /** option label -> TagColorKey, for "select" | "status" | "person" columns only. */
  optionColors?: Record<string, string>;
  width?: number;
}

export interface TableRowDef {
  id: string;
  cells: Record<string, string>;
}

/** A saved way of looking at the same rows — Notion-style view tabs (Table, Timeline, ...). */
export interface TableViewDef {
  id: string;
  name: string;
  type: "table" | "timeline" | "board" | "list";
  /** Timeline only: which "date" columns a row's bar spans. A single-date column can fill both. */
  startColumnId?: string;
  endColumnId?: string;
  /** Board only: which column to group cards by */
  groupByColumnId?: string;
}

export interface SubTableDef {
  id: string;
  name: string;
  columns: TableColumnDef[];
  rows: TableRowDef[];
  /** Defaults to one implicit "Table View" when absent, so existing tables render unchanged. */
  views?: TableViewDef[];
  activeViewId?: string;
}

export interface TableBlockContent {
  columns: TableColumnDef[];
  rows: TableRowDef[];
  /** Notion "database view"-style tab switcher — set when a block holds more than one table. */
  tables?: SubTableDef[];
  activeTableId?: string;
}

/** A block's onChange either replaces content outright, or (safer when a single interaction can
 *  fire more than one update in the same tick) resolves against the truly-latest content. */
export type BlockContentUpdater = BlockContent | ((prev: BlockContent) => BlockContent);

export type BlockContent = TextBlockContent | BulletBlockContent | TableBlockContent | ImageBlockContent;

export interface BlockDto {
  id: string;
  workspace: string;
  order: number;
  type: BlockType;
  content: BlockContent;
}

export const emptyBlockContent = (type: BlockType): BlockContent => {
  if (type === "bullet") return { items: [] };
  if (type === "table") return { columns: [{ id: generateUUID(), name: "Column 1" }], rows: [] };
  if (type === "image") return { url: "", caption: "" };
  return { text: "" };
};

/* ---------- Notes (per-workspace, freeform) — same block shapes as the workspace page ---------- */

export type NoteType = BlockType;

export interface NoteDto {
  id: string;
  workspace: string;
  title: string;
  order: number;
  type: NoteType;
  content: BlockContent;
}

export interface ExportConfig {
  format: "xlsx" | "csv" | "pdf";
  columns: ExportColumnConfig[];
  groupBy: string | null;
  sortBy: string | null;
  sortDir: "asc" | "desc";
  filterColumn: string | null;
  filterValue: string;
  summaryRow: boolean;
  includeLogo: boolean;
  orientation: "portrait" | "landscape";
  paperSize: "a4" | "letter" | "legal" | "a3";
  header: string;
  footer: string;
  title: string;
  /** Any row with one of these substrings in one of its cells (e.g. a computed anomaly flag) gets a red background - unset by default. */
  highlightIfContains?: string[];
  /** Column keys whose cells always get a red background, regardless of content - unset by default. */
  highlightColumns?: string[];
  /** A row gets a red background when both of these column keys are non-empty (e.g. a genuine vendor<->internal match, not a one-sided row) - unset by default. */
  highlightIfBothPresent?: [string, string];
  /** A row gets a yellow background (instead of red) when the given column contains one of these substrings (e.g. a vendor's own "*"/"**"/"***" price-increase marker) - unset by default. Red takes precedence when a row matches both. */
  highlightYellowIfContains?: { column: string; needles: string[] };
}
