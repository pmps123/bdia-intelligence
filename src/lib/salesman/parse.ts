import type { ParsedFile, ParsedSheet } from "@/lib/types";

/**
 * Salesman table join: three source files, none of them sharing a stable
 * column layout, so sheets/columns are located by header signature (same
 * philosophy as src/lib/parse/file-parser.ts) rather than by sheet name.
 */

export interface SalesmanRowInput {
  bulan: string;
  branch: string;
  division: string;
  legacyCode: string;
  newCode: string | null;
  salesName: string | null;
  nik: string | null;
  tanggalMasuk: string | null;
  tanggalKeluar: string | null;
  aktif: string;
  needsReview: boolean;
}

export interface ImportStats {
  parsed: number;
  needsReview: number;
}

function norm(h: string): string {
  return h
    .toLowerCase()
    .trim()
    // strip zero-width / non-breaking spaces that Excel sometimes emits
    .replace(/[\u00a0\u200b\ufeff]/g, "")
    // collapse multiple spaces
    .replace(/\s+/g, " ");
}

/**
 * Find a sheet that contains ALL of the required columns.
 * Matching is case-insensitive and uses "contains" so that minor
 * variations (extra spaces, slightly different wording) still match.
 */
function findSheet(file: ParsedFile, required: string[]): ParsedSheet | undefined {
  const req = required.map(norm);
  return file.sheets.find((s) =>
    req.every((r) => s.headers.some((h) => norm(h).includes(r) || r.includes(norm(h))))
  );
}

/**
 * Find a column index by name, trying exact match first then partial / alias.
 * `aliases` are alternative names accepted when the primary name is absent.
 */
function colIndex(sheet: ParsedSheet, name: string, aliases: string[] = []): number {
  const candidates = [name, ...aliases];
  for (const c of candidates) {
    // exact
    const exact = sheet.headers.findIndex((h) => norm(h) === norm(c));
    if (exact !== -1) return exact;
    // contains
    const contains = sheet.headers.findIndex((h) => norm(h).includes(norm(c)) || norm(c).includes(norm(h)));
    if (contains !== -1) return contains;
  }
  return -1;
}

interface KaryawanEntry {
  legacy: string;
  newCode: string;
  nik: string;
  nama: string;
  active: boolean;
}

function parseKaryawan(file: ParsedFile): KaryawanEntry[] {
  // Try to find the correct sheet using flexible column matching.
  // The required columns may be spelled slightly differently across file versions.
  const sheet =
    findSheet(file, ["Salesman Id R1", "Legacy", "NIK", "Status"]) ??
    findSheet(file, ["salesman id", "legacy", "nik", "status"]) ??
    // Fallback: any sheet that has at least "Legacy" and "NIK" (minimal identification)
    findSheet(file, ["Legacy", "NIK"]);

  if (!sheet) {
    const sheetSummary = file.sheets
      .map((s) => `"${s.name}" [${s.headers.slice(0, 8).join(" | ")}${s.headers.length > 8 ? " …" : ""}]`)
      .join("\n  ");
    throw new Error(
      `NEW Data Karyawan: tidak ditemukan sheet yang memiliki kolom "Salesman Id R1", "Legacy", "NIK", "Status".\n` +
        `Sheet yang ditemukan di file:\n  ${sheetSummary}\n` +
        `Pastikan file yang diupload adalah "NEW Data Karyawan" (bukan file lain).`
    );
  }

  // Column matching with aliases for variations across Excel versions
  const iLegacy  = colIndex(sheet, "Legacy",         ["legacy code", "kode lama"]);
  const iNewCode = colIndex(sheet, "Salesman Id R1",  ["salesman id r1", "id r1", "new code", "kode baru"]);
  const iNik     = colIndex(sheet, "NIK",             ["nik", "no nik"]);
  const iNama    = colIndex(sheet, "Nama",            ["nama salesman", "name", "sales name"]);
  const iStatus  = colIndex(sheet, "Status",          ["status aktif", "aktif"]);

  if (iLegacy === -1 || iNewCode === -1) {
    throw new Error(
      `NEW Data Karyawan: kolom "Legacy" (idx=${iLegacy}) atau "Salesman Id R1" (idx=${iNewCode}) tidak ditemukan.\n` +
        `Header yang ada: ${sheet.headers.join(" | ")}`
    );
  }

  return sheet.rows
    .map((r) => ({
      legacy:  (r[iLegacy]  ?? "").trim(),
      newCode: iNewCode !== -1 ? (r[iNewCode] ?? "").trim() : "",
      nik:     iNik     !== -1 ? (r[iNik]     ?? "").trim() : "",
      nama:    iNama    !== -1 ? (r[iNama]    ?? "").trim() : "",
      active:  iStatus  !== -1
        ? ["active", "aktif", "y", "yes", "1"].includes((r[iStatus] ?? "").trim().toLowerCase())
        : true, // if no status column, assume active
    }))
    .filter((r) => r.legacy);
}

/** Resolve duplicate Legacy codes: prefer the single Active row; otherwise flag for manual review. */
function resolveKaryawan(entries: KaryawanEntry[]): Map<string, KaryawanEntry | null> {
  const byLegacy = new Map<string, KaryawanEntry[]>();
  for (const e of entries) {
    const list = byLegacy.get(e.legacy) ?? [];
    list.push(e);
    byLegacy.set(e.legacy, list);
  }
  const resolved = new Map<string, KaryawanEntry | null>();
  for (const [legacy, list] of byLegacy) {
    if (list.length === 1) {
      resolved.set(legacy, list[0]);
      continue;
    }
    const activeOnes = list.filter((e) => e.active);
    resolved.set(legacy, activeOnes.length === 1 ? activeOnes[0] : null);
  }
  return resolved;
}

interface BranchDivision {
  branch: string;
  division: string;
}

interface Hierarchy {
  branchByCode: Map<string, BranchDivision>;
  monthlyRows: { bulan: string; legacyCode: string }[];
}

function parseHierarchy(file: ParsedFile): Hierarchy {
  const summary = findSheet(file, ["Branch", "Division", "Sales Person Code"]);
  if (!summary) throw new Error('Mapping Sales Co SPV BM: sheet with columns "Branch", "Division", "Sales Person Code" not found');
  const iBranch = colIndex(summary, "Branch");
  const iDivision = colIndex(summary, "Division");
  const iCode = colIndex(summary, "Sales Person Code");
  const branchByCode = new Map<string, BranchDivision>();
  for (const r of summary.rows) {
    const code = (r[iCode] ?? "").trim();
    if (!code || branchByCode.has(code)) continue;
    branchByCode.set(code, { branch: (r[iBranch] ?? "").trim(), division: (r[iDivision] ?? "").trim() });
  }

  const monthly = findSheet(file, ["Month", "Sales Person Code"]);
  if (!monthly) throw new Error('Mapping Sales Co SPV BM: sheet with columns "Month", "Sales Person Code" not found');
  const mBulan = colIndex(monthly, "Month");
  const mCode = colIndex(monthly, "Sales Person Code");
  const monthlyRows = monthly.rows
    .map((r) => ({ bulan: (r[mBulan] ?? "").trim(), legacyCode: (r[mCode] ?? "").trim() }))
    .filter((r) => r.bulan && r.legacyCode);

  return { branchByCode, monthlyRows };
}

interface BerjalanRow {
  bulan: string; // the dynamic month-name column header itself
  legacyCode: string;
  branch: string;
  division: string;
  salesName: string;
  nik: string;
  tanggalMasuk: string;
  tanggalKeluar: string;
}

const BERJALAN_FIXED_HEADERS = ["masuk", "keluar", "nik", "no rek", "sales pengganti", "data hr", "status"];

function parseBerjalan(file: ParsedFile): BerjalanRow[] {
  const sheet = findSheet(file, ["Branch", "Divisi", "Kode Sales", "NIK"]);
  if (!sheet) throw new Error('Mapping Salesman Berjalan: sheet with columns "Branch", "Divisi", "Kode Sales", "NIK" not found');
  const iBranch = colIndex(sheet, "Branch");
  const iDivision = colIndex(sheet, "Divisi");
  const iCode = colIndex(sheet, "Kode Sales");
  const iNik = colIndex(sheet, "NIK");
  const iMasuk = colIndex(sheet, "Masuk");
  const iKeluar = colIndex(sheet, "Keluar");
  // the sales-name column is whichever month is "running" — its header is a month name, not a fixed label
  const iName = iCode + 1;
  const nameHeader = (sheet.headers[iName] ?? "").trim();
  if (!nameHeader || BERJALAN_FIXED_HEADERS.includes(norm(nameHeader))) {
    throw new Error('Mapping Salesman Berjalan: could not find the month-name column right after "Kode Sales"');
  }
  return sheet.rows
    .map((r) => ({
      bulan: nameHeader,
      legacyCode: (r[iCode] ?? "").trim(),
      branch: (r[iBranch] ?? "").trim(),
      division: (r[iDivision] ?? "").trim(),
      salesName: (r[iName] ?? "").trim(),
      nik: (r[iNik] ?? "").trim(),
      tanggalMasuk: iMasuk !== -1 ? (r[iMasuk] ?? "").trim() : "",
      tanggalKeluar: iKeluar !== -1 ? (r[iKeluar] ?? "").trim() : "",
    }))
    .filter((r) => r.legacyCode);
}

export function buildSalesmanRows(files: {
  karyawan: ParsedFile;
  hierarchy: ParsedFile;
  berjalan: ParsedFile;
}): { rows: SalesmanRowInput[]; stats: ImportStats } {
  const karyawan = resolveKaryawan(parseKaryawan(files.karyawan));
  const hierarchy = parseHierarchy(files.hierarchy);
  const berjalan = parseBerjalan(files.berjalan);

  const byKey = new Map<string, SalesmanRowInput>();
  const key = (bulan: string, legacyCode: string) => `${bulan} ${legacyCode}`;

  const toRow = (
    bulan: string,
    legacyCode: string,
    branch: string,
    division: string,
    salesNameOverride: string | null,
    nikOverride: string | null,
    tanggalMasuk: string | null = null,
    tanggalKeluar: string | null = null
  ): SalesmanRowInput => {
    const dup = karyawan.has(legacyCode) && karyawan.get(legacyCode) === null;
    const k = karyawan.get(legacyCode) ?? undefined;
    return {
      bulan,
      branch,
      division,
      legacyCode,
      newCode: k?.newCode || null,
      salesName: salesNameOverride || k?.nama || null,
      nik: nikOverride || k?.nik || null,
      tanggalMasuk: tanggalMasuk || null,
      tanggalKeluar: tanggalKeluar || null,
      aktif: k ? (k.active ? "Aktif" : "Tidak Aktif") : "Aktif",
      needsReview: dup,
    };
  };

  // historical months: branch/division from the Summary lookup, sales name falls back to NEW Data Karyawan
  for (const { bulan, legacyCode } of hierarchy.monthlyRows) {
    const bd = hierarchy.branchByCode.get(legacyCode) ?? { branch: "", division: "" };
    byKey.set(key(bulan, legacyCode), toRow(bulan, legacyCode, bd.branch, bd.division, null, null));
  }

  // current month: authoritative branch/division/name straight from the file itself
  for (const r of berjalan) {
    byKey.set(
      key(r.bulan, r.legacyCode),
      toRow(r.bulan, r.legacyCode, r.branch, r.division, r.salesName, r.nik, r.tanggalMasuk, r.tanggalKeluar)
    );
  }

  const rows = [...byKey.values()];
  return { rows, stats: { parsed: rows.length, needsReview: rows.filter((r) => r.needsReview).length } };
}
