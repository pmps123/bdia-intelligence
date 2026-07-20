import { prisma } from "@/lib/db";
import { parseUploadedFile, parseNumeric } from "@/lib/parse/file-parser";
import { analyzeCleaning, cleanValue } from "@/lib/engine/cleaning";
import { tokenize, splitSlashVariants } from "@/lib/engine/tokens";
import { parseQtyRule } from "@/lib/engine/qty-rules";
import type { ColumnMapping } from "@/lib/types";
import { PRICE_FIELDS } from "@/lib/types";
import { readFile } from "fs/promises";

/**
 * Build a dataset from an uploaded worksheet + the user's column mapping.
 * The mapping is user-provided per upload — no column layout is ever assumed.
 */
export async function createDatasetFromUpload(opts: {
  uploadId: string;
  worksheetName: string;
  mapping: ColumnMapping[];
  kind: "VENDOR" | "INTERNAL";
  vendorName?: string;
  datasetName: string;
  jobId?: string;
}): Promise<string> {
  const upload = await prisma.upload.findUniqueOrThrow({ where: { id: opts.uploadId } });
  const buffer = await readFile(upload.storagePath);
  const parsed = await parseUploadedFile(buffer, upload.fileName);
  const sheet = parsed.sheets.find((s) => s.name === opts.worksheetName);
  if (!sheet) throw new Error(`Worksheet "${opts.worksheetName}" not found in ${upload.fileName}`);

  const progress = async (p: number, message: string) => {
    if (opts.jobId) await prisma.job.update({ where: { id: opts.jobId }, data: { progress: p, message } });
  };

  const active = opts.mapping.filter((m) => !m.ignore);
  const byField = (f: string) => active.find((m) => m.field === f);
  const nameCol = byField("productName");

  await progress(10, "Analyzing data for cleaning rules");
  const nameValues = nameCol ? sheet.rows.map((r) => r[nameCol.sourceIndex] ?? "") : [];
  const report = analyzeCleaning(nameValues);
  const ruleIds = report.rules.map((r) => r.id);

  const dataset = await prisma.dataset.create({
    data: {
      name: opts.datasetName,
      kind: opts.kind,
      vendorName: opts.vendorName || (byField("vendor") ? undefined : null),
      uploadId: opts.uploadId,
      worksheetName: sheet.name,
      mapping: JSON.stringify(opts.mapping),
      cleaningReport: JSON.stringify(report),
    },
  });

  await progress(25, "Normalizing rows");
  const rows = sheet.rows;
  const creates: {
    datasetId: string;
    rowIndex: number;
    data: string;
    nameRaw: string | null;
    nameNorm: string | null;
    code: string | null;
    variant: string | null;
    brand: string | null;
    category: string | null;
    tokens: string | null;
    prices: string | null;
    qty: number | null;
    qtyMin: number | null;
    qtyMax: number | null;
    qtyRuleLabel: string | null;
  }[] = [];

  for (let idx = 0; idx < rows.length; idx++) {
    const row = rows[idx];
    const data: Record<string, string> = {};
    for (const m of active) {
      const key = m.field ?? m.rename ?? m.sourceName;
      data[key] = row[m.sourceIndex] ?? "";
    }
    const nameRaw = nameCol ? (row[nameCol.sourceIndex] ?? "").trim() : "";
    if (nameRaw === "" && Object.values(data).every((v) => v === "")) continue;

    const prices: Record<string, number> = {};
    for (const pf of PRICE_FIELDS) {
      const col = byField(pf);
      if (col) {
        const n = parseNumeric(row[col.sourceIndex]);
        if (n !== null) prices[pf] = n;
      }
    }
    const qtyCol = byField("qty");
    const codeCol = byField("productCode");
    const variantCol = byField("productVariant");
    const brandCol = byField("brand");
    const categoryCol = byField("category");
    const vendorCol = byField("vendor");
    if (vendorCol && row[vendorCol.sourceIndex]) data["vendor"] = row[vendorCol.sourceIndex];

    // quantity gradation (Customized Price): interpreted per row from the data
    const ruleCol = byField("qtyRule");
    const fromCol = byField("qtyFrom");
    const toCol = byField("qtyTo");
    const qtyRange =
      ruleCol || fromCol || toCol
        ? parseQtyRule(ruleCol ? row[ruleCol.sourceIndex] : null, fromCol ? row[fromCol.sourceIndex] : null, toCol ? row[toCol.sourceIndex] : null)
        : null;

    // slash-separated variants ("EU 309 W/K") become one row per variant,
    // inheriting every other value; each is matched independently later
    const variantNames = nameRaw ? splitSlashVariants(nameRaw) : [""];
    for (const variantName of variantNames) {
      const nameNorm = variantName ? cleanValue(variantName, ruleIds) : null;
      creates.push({
        datasetId: dataset.id,
        rowIndex: idx,
        data: JSON.stringify(data),
        nameRaw: variantName || null,
        nameNorm,
        code: codeCol ? (row[codeCol.sourceIndex] ?? "").trim() || null : null,
        variant: variantCol ? (row[variantCol.sourceIndex] ?? "").trim() || null : null,
        brand: brandCol ? (row[brandCol.sourceIndex] ?? "").trim() || null : null,
        category: categoryCol ? (row[categoryCol.sourceIndex] ?? "").trim() || null : null,
        tokens: nameNorm ? JSON.stringify(tokenize(nameNorm)) : null,
        prices: Object.keys(prices).length ? JSON.stringify(prices) : null,
        qty: qtyCol ? parseNumeric(row[qtyCol.sourceIndex]) : null,
        qtyMin: qtyRange?.min ?? null,
        qtyMax: qtyRange?.max ?? null,
        qtyRuleLabel: qtyRange?.label ?? null,
      });
    }
  }

  const chunk = 200;
  for (let i = 0; i < creates.length; i += chunk) {
    await prisma.dataRow.createMany({ data: creates.slice(i, i + chunk) });
    await progress(25 + ((i + chunk) / Math.max(creates.length, 1)) * 70, `Saving rows ${Math.min(i + chunk, creates.length)}/${creates.length}`);
  }

  await prisma.dataset.update({ where: { id: dataset.id }, data: { rowCount: creates.length } });
  await progress(100, "Completed");
  return dataset.id;
}
