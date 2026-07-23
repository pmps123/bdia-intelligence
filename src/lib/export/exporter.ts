import ExcelJS from "exceljs";
import { jsPDF } from "jspdf";
import autoTable from "jspdf-autotable";
import type { ExportConfig } from "@/lib/types";

export interface ExportInput {
  config: ExportConfig;
  rows: Record<string, unknown>[];
  logoDataUrl?: string | null;
}

function prepareRows(input: ExportInput): { columns: { key: string; title: string; width: number }[]; rows: Record<string, unknown>[] } {
  const cfg = input.config;
  const columns = cfg.columns.filter((c) => c.include).map((c) => ({ key: c.key, title: c.title || c.key, width: c.width || 20 }));
  let rows = [...input.rows];

  if (cfg.filterColumn && cfg.filterValue) {
    const needle = cfg.filterValue.toLowerCase();
    rows = rows.filter((r) => String(r[cfg.filterColumn!] ?? "").toLowerCase().includes(needle));
  }
  if (cfg.sortBy) {
    const dir = cfg.sortDir === "desc" ? -1 : 1;
    rows.sort((a, b) => {
      const av = a[cfg.sortBy!];
      const bv = b[cfg.sortBy!];
      const an = typeof av === "number" ? av : Number(av);
      const bn = typeof bv === "number" ? bv : Number(bv);
      if (!Number.isNaN(an) && !Number.isNaN(bn)) return (an - bn) * dir;
      return String(av ?? "").localeCompare(String(bv ?? "")) * dir;
    });
  }
  if (cfg.groupBy) {
    // stable-sort by group key so grouped blocks stay together
    const dir = 1;
    rows.sort((a, b) => String(a[cfg.groupBy!] ?? "").localeCompare(String(b[cfg.groupBy!] ?? "")) * dir);
  }
  return { columns, rows };
}

function numericColumns(columns: { key: string }[], rows: Record<string, unknown>[]): Set<string> {
  const set = new Set<string>();
  for (const c of columns) {
    const sample = rows.filter((r) => r[c.key] !== null && r[c.key] !== undefined && r[c.key] !== "").slice(0, 50);
    if (sample.length > 0 && sample.every((r) => typeof r[c.key] === "number" || !Number.isNaN(Number(r[c.key])))) set.add(c.key);
  }
  return set;
}

export async function exportExcel(input: ExportInput): Promise<Buffer> {
  const cfg = input.config;
  const { columns, rows } = prepareRows(input);
  const wb = new ExcelJS.Workbook();
  const ws = wb.addWorksheet(cfg.title || "Export", {
    pageSetup: {
      orientation: cfg.orientation,
      paperSize: (cfg.paperSize === "a4" ? 9 : cfg.paperSize === "letter" ? 1 : cfg.paperSize === "legal" ? 5 : 8) as ExcelJS.PaperSize,
    },
    headerFooter: { oddHeader: cfg.header || undefined, oddFooter: cfg.footer || undefined },
  });

  let rowCursor = 1;
  if (cfg.includeLogo && input.logoDataUrl) {
    const match = input.logoDataUrl.match(/^data:image\/(png|jpeg);base64,(.+)$/);
    if (match) {
      const imgId = wb.addImage({ base64: match[2], extension: match[1] === "jpeg" ? "jpeg" : "png" });
      ws.addImage(imgId, { tl: { col: 0, row: 0 }, ext: { width: 140, height: 50 } });
      rowCursor = 4;
    }
  }
  if (cfg.title) {
    const titleRow = ws.getRow(rowCursor);
    titleRow.getCell(1).value = cfg.title;
    titleRow.font = { bold: true, size: 14, color: { argb: "FF1D4ED8" } };
    rowCursor += 2;
  }

  const headerRowNumber = rowCursor;
  const headerRow = ws.getRow(rowCursor);
  columns.forEach((c, i) => {
    const cell = headerRow.getCell(i + 1);
    cell.value = c.title;
    cell.font = { bold: true, color: { argb: "FFFFFFFF" } };
    cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FF2563EB" } };
    cell.border = { bottom: { style: "thin" } };
    ws.getColumn(i + 1).width = c.width;
  });
  rowCursor++;
  // header stays visible while scrolling, and is sortable/filterable out of the box
  ws.views = [{ state: "frozen", ySplit: headerRowNumber }];
  if (columns.length > 0) {
    ws.autoFilter = { from: { row: headerRowNumber, column: 1 }, to: { row: headerRowNumber, column: columns.length } };
  }

  const numCols = numericColumns(columns, rows);
  let currentGroup: string | null = null;
  for (const r of rows) {
    if (cfg.groupBy) {
      const g = String(r[cfg.groupBy] ?? "");
      if (g !== currentGroup) {
        currentGroup = g;
        const groupRow = ws.getRow(rowCursor);
        groupRow.getCell(1).value = g || "(empty)";
        groupRow.font = { bold: true };
        groupRow.getCell(1).fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFDBEAFE" } };
        rowCursor++;
      }
    }
    const row = ws.getRow(rowCursor);
    const needles = cfg.highlightIfContains ?? [];
    const rowHighlight = needles.length > 0 && Object.values(r).some((v) => {
      const s = String(v ?? "");
      return needles.some((needle) => s.includes(needle));
    });
    columns.forEach((c, i) => {
      const v = r[c.key];
      const cell = row.getCell(i + 1);
      cell.value = numCols.has(c.key) && v !== "" && v !== null && v !== undefined ? Number(v) : ((v as ExcelJS.CellValue) ?? "");
      if (rowHighlight || cfg.highlightColumns?.includes(c.key)) {
        cell.fill = { type: "pattern", pattern: "solid", fgColor: { argb: "FFFECACA" } };
      }
    });
    rowCursor++;
  }

  if (cfg.summaryRow && rows.length > 0) {
    const sumRow = ws.getRow(rowCursor);
    sumRow.font = { bold: true };
    columns.forEach((c, i) => {
      if (numCols.has(c.key)) {
        const total = rows.reduce((acc, r) => acc + (Number(r[c.key]) || 0), 0);
        sumRow.getCell(i + 1).value = Number(total.toFixed(2));
      } else if (i === 0) {
        sumRow.getCell(1).value = `TOTAL (${rows.length} rows)`;
      }
      sumRow.getCell(i + 1).border = { top: { style: "double" } };
    });
  }

  const arr = await wb.xlsx.writeBuffer();
  return Buffer.from(arr);
}

export function exportCsv(input: ExportInput): Buffer {
  const { columns, rows } = prepareRows(input);
  const esc = (v: unknown) => {
    const s = String(v ?? "");
    return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const lines = [columns.map((c) => esc(c.title)).join(",")];
  for (const r of rows) lines.push(columns.map((c) => esc(r[c.key])).join(","));
  if (input.config.summaryRow && rows.length > 0) {
    const numCols = numericColumns(columns, rows);
    lines.push(
      columns
        .map((c, i) => {
          if (numCols.has(c.key)) return String(rows.reduce((acc, r) => acc + (Number(r[c.key]) || 0), 0).toFixed(2));
          return i === 0 ? `TOTAL (${rows.length} rows)` : "";
        })
        .join(",")
    );
  }
  return Buffer.from("﻿" + lines.join("\r\n"), "utf8");
}

export function exportPdf(input: ExportInput): Buffer {
  const cfg = input.config;
  const { columns, rows } = prepareRows(input);
  const doc = new jsPDF({ orientation: cfg.orientation, format: cfg.paperSize, unit: "pt" });

  let startY = 40;
  if (cfg.includeLogo && input.logoDataUrl) {
    try {
      doc.addImage(input.logoDataUrl, "PNG", 40, 20, 90, 32);
      startY = 66;
    } catch {
      // logo could not be embedded; continue without it
    }
  }
  if (cfg.header) {
    doc.setFontSize(9);
    doc.setTextColor(120);
    doc.text(cfg.header, doc.internal.pageSize.getWidth() / 2, 24, { align: "center" });
  }
  if (cfg.title) {
    doc.setFontSize(14);
    doc.setTextColor(29, 78, 216);
    doc.text(cfg.title, 40, startY);
    startY += 16;
  }

  const numCols = numericColumns(columns, rows);
  const body: (string | number)[][] = [];
  let currentGroup: string | null = null;
  for (const r of rows) {
    if (cfg.groupBy) {
      const g = String(r[cfg.groupBy] ?? "");
      if (g !== currentGroup) {
        currentGroup = g;
        body.push([g || "(empty)", ...new Array(columns.length - 1).fill("")]);
      }
    }
    body.push(columns.map((c) => (r[c.key] === null || r[c.key] === undefined ? "" : (r[c.key] as string | number))));
  }
  if (cfg.summaryRow && rows.length > 0) {
    body.push(
      columns.map((c, i) => {
        if (numCols.has(c.key)) return Number(rows.reduce((acc, r) => acc + (Number(r[c.key]) || 0), 0).toFixed(2));
        return i === 0 ? `TOTAL (${rows.length} rows)` : "";
      })
    );
  }

  const totalWidth = columns.reduce((a, c) => a + c.width, 0);
  autoTable(doc, {
    startY: startY + 6,
    head: [columns.map((c) => c.title)],
    body,
    styles: { fontSize: 8, cellPadding: 3 },
    headStyles: { fillColor: [37, 99, 235], textColor: 255, fontStyle: "bold" },
    alternateRowStyles: { fillColor: [239, 246, 255] },
    columnStyles: Object.fromEntries(
      columns.map((c, i) => [i, { cellWidth: "auto" as const, minCellWidth: Math.max(30, (c.width / Math.max(totalWidth, 1)) * 300) }])
    ),
    didDrawPage: () => {
      if (cfg.footer) {
        doc.setFontSize(8);
        doc.setTextColor(120);
        doc.text(cfg.footer, doc.internal.pageSize.getWidth() / 2, doc.internal.pageSize.getHeight() - 16, { align: "center" });
      }
    },
  });

  return Buffer.from(doc.output("arraybuffer"));
}

export async function runExport(input: ExportInput): Promise<{ buffer: Buffer; contentType: string; ext: string }> {
  switch (input.config.format) {
    case "xlsx":
      return { buffer: await exportExcel(input), contentType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ext: "xlsx" };
    case "csv":
      return { buffer: exportCsv(input), contentType: "text/csv; charset=utf-8", ext: "csv" };
    case "pdf":
      return { buffer: exportPdf(input), contentType: "application/pdf", ext: "pdf" };
  }
}
