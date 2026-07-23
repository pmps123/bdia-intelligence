import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";
import { priceStatusLabel, type MatchCandidate } from "@/lib/types";
import { EXTREME_DIFF_PCT } from "@/lib/engine/anomaly";

// any internal-data header that reads as a product code, whatever the vendor calls it
// (Prod. Variant Code, Alias Code, SKU, ...) - discovered from the sheet's own headers, never a fixed list
const CODE_HEADER_RE = /code|kode|sku|part\s*no|artikel|item\s*no/i;

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
      select: { id: true, status: true, confidence: true, source: true, detail: true },
    });
    const matchById = new Map(matchResults.map((m) => [m.id, m]));

    // pull in whatever "code" columns the internal sheet actually has (Prod. Variant Code, Alias
    // Code, SKU, ...) - discovered from the internal dataset's own original headers, not a fixed
    // list, so it works for any vendor's data
    const internalRowIds = [...new Set(run.items.map((it) => it.internalRowId).filter((rid): rid is string => rid !== null))];
    const internalRows = internalRowIds.length > 0 ? await prisma.dataRow.findMany({ where: { id: { in: internalRowIds } } }) : [];
    const internalDataById = new Map(internalRows.map((r) => [r.id, safeJson<Record<string, string>>(r.data, {})]));
    const codeHeaders: string[] = [];
    const seenHeaders = new Set<string>();
    for (const data of internalDataById.values()) {
      for (const key of Object.keys(data)) {
        if (CODE_HEADER_RE.test(key) && !seenHeaders.has(key)) {
          seenHeaders.add(key);
          codeHeaders.push(key);
        }
      }
    }

    const out = run.items.map((it) => {
      const m = it.matchResultId ? matchById.get(it.matchResultId) : undefined;
      const internalData = it.internalRowId ? internalDataById.get(it.internalRowId) : undefined;
      // the AI's own one-sentence reason, when it was the one that made the call on an ambiguous
      // match - the detail blob is {...signals} normally, {...signals, aiReason} when AI ran
      const aiReason = m?.detail ? safeJson<{ aiReason?: string }>(m.detail, {}).aiReason : undefined;
      const row: Record<string, unknown> = {
        "Vendor Product": it.vendorLabel,
        "Internal Product": it.internalLabel,
      };
      for (const header of codeHeaders) row[header] = internalData?.[header] ?? "";
      Object.assign(row, {
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
        // where this match came from: MASTER (remembered from a past manual confirm), AI
        // (validated an ambiguous fuzzy match), ENGINE (fuzzy match alone), MANUAL (auditor set it)
        "Match Source": m?.source ?? "",
        "Match Note": aiReason ?? "",
        // flagged independent of match confidence: a >80% price swing is worth a manual look
        // regardless of how sure the matching engine is - it might be a real event, or it might
        // be a wrong match or a misread number, and either way an auditor should see it
        "Price Alert": it.diffPct !== null && Math.abs(it.diffPct) >= EXTREME_DIFF_PCT ? "Cek Manual - Perubahan Ekstrem" : "",
      });
      return row;
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
