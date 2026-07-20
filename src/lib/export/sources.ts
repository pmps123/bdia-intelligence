import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";
import { priceStatusLabel, type MatchCandidate } from "@/lib/types";

export interface SourceData {
  name: string;
  columns: string[];
  rows: Record<string, unknown>[];
}

/**
 * Builds exportable rows for any source. Columns are always derived from the
 * actual data present — the union of keys across rows — never a fixed list.
 */
export async function getSourceData(type: string, id: string): Promise<SourceData> {
  if (type === "dataset") {
    const dataset = await prisma.dataset.findUniqueOrThrow({ where: { id } });
    const rows = await prisma.dataRow.findMany({ where: { datasetId: id }, orderBy: { rowIndex: "asc" } });
    const out = rows.map((r) => {
      const data = safeJson<Record<string, string>>(r.data, {});
      const prices = safeJson<Record<string, number>>(r.prices, {});
      return { "#": r.rowIndex + 1, ...data, ...prices, "Normalized Name": r.nameNorm ?? "" };
    });
    return { name: dataset.name, columns: unionColumns(out), rows: out };
  }

  if (type === "session") {
    const session = await prisma.matchSession.findUniqueOrThrow({ where: { id } });
    const results = await prisma.matchResult.findMany({ where: { sessionId: id }, orderBy: { score: "desc" } });
    const rowIds = new Set<string>();
    for (const r of results) {
      rowIds.add(r.vendorRowId);
      if (r.internalRowId) rowIds.add(r.internalRowId);
    }
    const rows = await prisma.dataRow.findMany({ where: { id: { in: [...rowIds] } } });
    const rowMap = new Map(rows.map((r) => [r.id, r]));
    const out = results.map((r) => {
      const v = rowMap.get(r.vendorRowId);
      const i = r.internalRowId ? rowMap.get(r.internalRowId) : undefined;
      const vPrices = safeJson<Record<string, number>>(v?.prices ?? null, {});
      const iPrices = safeJson<Record<string, number>>(i?.prices ?? null, {});
      const candidates = safeJson<MatchCandidate[]>(r.candidates, []);
      const row: Record<string, unknown> = {
        "Vendor Product": v?.nameRaw ?? "",
        "Vendor Code": v?.code ?? "",
        "Internal Product": i?.nameRaw ?? "",
        "Internal Code": i?.code ?? "",
        Status: r.status,
        Source: r.source,
        Score: r.score,
        Confidence: r.confidence,
        "Top Candidate": candidates[0]?.label ?? "",
      };
      for (const [k, val] of Object.entries(vPrices)) row[`Vendor ${k}`] = val;
      for (const [k, val] of Object.entries(iPrices)) row[`Internal ${k}`] = val;
      return row;
    });
    return { name: session.name, columns: unionColumns(out), rows: out };
  }

  if (type === "validation") {
    const run = await prisma.priceValidationRun.findUniqueOrThrow({ where: { id }, include: { items: true } });
    // full join: internal-only rows have no matchResultId at all
    const matchResultIds = run.items.map((it) => it.matchResultId).filter((mid): mid is string => mid !== null);
    const matchResults = await prisma.matchResult.findMany({
      where: { id: { in: matchResultIds } },
      select: { id: true, status: true, confidence: true },
    });
    const matchById = new Map(matchResults.map((m) => [m.id, m]));
    const out = run.items.map((it) => {
      const m = it.matchResultId ? matchById.get(it.matchResultId) : undefined;
      return {
        "Vendor Product": it.vendorLabel,
        "Internal Product": it.internalLabel,
        "Vendor Price": it.vendorPrice ?? "",
        "Internal Price": it.internalPrice ?? "",
        // the updated price always takes the vendor price
        "Updated Price": it.vendorPrice ?? "",
        "Price Difference": it.diff ?? "",
        "% Increase": it.diffPct !== null && it.diffPct > 0 ? it.diffPct : "",
        "% Decrease": it.diffPct !== null && it.diffPct < 0 ? Math.abs(it.diffPct) : "",
        "Price Status": priceStatusLabel(it.status),
        "Matching Status": m?.status ?? "",
        Confidence: m ? Number((m.confidence * 100).toFixed(0)) / 100 : "",
      };
    });
    return { name: run.name, columns: unionColumns(out), rows: out };
  }

  if (type === "master") {
    const mappings = await prisma.masterMapping.findMany({ orderBy: { createdAt: "desc" } });
    const out = mappings.map((m) => ({
      Vendor: m.vendorName || "(any)",
      "Vendor Product": m.vendorLabel,
      "Internal Product": m.internalLabel,
      "Internal Code": m.internalCode ?? "",
      "Usage Count": m.usageCount,
      Created: m.createdAt.toISOString().slice(0, 10),
    }));
    return { name: "Master Mapping", columns: unionColumns(out), rows: out };
  }

  throw new Error(`Unknown export source type: ${type}`);
}

function unionColumns(rows: Record<string, unknown>[]): string[] {
  const cols: string[] = [];
  const seen = new Set<string>();
  for (const r of rows) {
    for (const k of Object.keys(r)) {
      if (!seen.has(k)) {
        seen.add(k);
        cols.push(k);
      }
    }
  }
  return cols;
}
