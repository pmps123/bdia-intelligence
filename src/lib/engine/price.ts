import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";
import { qtyInRange } from "@/lib/engine/qty-rules";

/**
 * Price validation: a full outer join between every vendor row and every
 * internal row, not just the ones a match happened to cover.
 *
 * - Vendor rows with an accepted internal match (MATCHED / PARTIAL / MANUAL)
 *   get the usual price comparison (SAME / HIGHER / LOWER / MISSING).
 * - Vendor rows with no accepted internal match still appear, flagged
 *   NOT_IN_INTERNAL — the vendor offered a product the internal price list
 *   doesn't have.
 * - Internal rows nothing matched to still appear, flagged NOT_IN_VENDOR —
 *   nothing came in from the vendor for that product, so there's no price
 *   change to report.
 *
 * The reference dataset is never fixed — the user picks which uploaded
 * dataset and which mapped price field acts as the reference for this run.
 */

const ACCEPTED_MATCH_STATUSES = new Set(["MATCHED", "PARTIAL", "MANUAL"]);

export async function runPriceValidation(opts: {
  sessionId: string;
  referenceDatasetId: string;
  vendorPriceField: string;
  internalPriceField: string;
  tolerancePct: number;
  name: string;
}): Promise<{ runId: string; stats: Record<string, number> }> {
  const session = await prisma.matchSession.findUniqueOrThrow({ where: { id: opts.sessionId } });

  const [allResults, vendorRows, internalRows, referenceRows] = await Promise.all([
    prisma.matchResult.findMany({ where: { sessionId: opts.sessionId } }),
    prisma.dataRow.findMany({ where: { datasetId: session.vendorDatasetId } }),
    prisma.dataRow.findMany({ where: { datasetId: session.internalDatasetId } }),
    prisma.dataRow.findMany({ where: { datasetId: opts.referenceDatasetId } }),
  ]);

  const internalById = new Map(internalRows.map((r) => [r.id, r]));
  const resultByVendorId = new Map(allResults.map((r) => [r.vendorRowId, r]));

  // reference rows are looked up by id when the reference dataset IS the matching
  // internal dataset (the common case), otherwise joined by normalized name
  const refById = new Map(referenceRows.map((r) => [r.id, r]));
  const refByNorm = new Map<string, (typeof referenceRows)[number]>();
  for (const r of referenceRows) if (r.nameNorm) refByNorm.set(r.nameNorm, r);
  // quantity gradation (Customized Price): a product may have several reference
  // rows, one per quantity range — group them so the vendor qty can pick the right one
  const refGroupByNorm = new Map<string, typeof referenceRows>();
  for (const r of referenceRows) {
    if (!r.nameNorm) continue;
    const g = refGroupByNorm.get(r.nameNorm);
    if (g) g.push(r);
    else refGroupByNorm.set(r.nameNorm, [r]);
  }

  const resolveRef = (internal: (typeof internalRows)[number] | undefined, vendorNameNorm: string | null) => {
    let ref = internal && refById.has(internal.id) ? refById.get(internal.id) : undefined;
    if (!ref && internal?.nameNorm) ref = refByNorm.get(internal.nameNorm);
    if (!ref && vendorNameNorm) ref = refByNorm.get(vendorNameNorm);
    // if the matched product carries quantity ranges, re-select the sibling row
    // whose range contains the vendor quantity (rules come from the uploaded data)
    return ref;
  };

  // products already covered by an accepted vendor match are skipped on the
  // internal side — grouped by name because quantity-gradation products span
  // several DataRow siblings (one per qty tier) that all represent one product
  const matchedInternalNorms = new Set<string>();
  for (const res of allResults) {
    if (!ACCEPTED_MATCH_STATUSES.has(res.status) || !res.internalRowId) continue;
    const internal = internalById.get(res.internalRowId);
    if (internal?.nameNorm) matchedInternalNorms.add(internal.nameNorm);
  }

  const run = await prisma.priceValidationRun.create({
    data: {
      name: opts.name,
      sessionId: opts.sessionId,
      referenceDatasetId: opts.referenceDatasetId,
      vendorPriceField: opts.vendorPriceField,
      internalPriceField: opts.internalPriceField,
      tolerancePct: opts.tolerancePct,
    },
  });

  const stats = { total: 0, same: 0, higher: 0, lower: 0, missing: 0, notInInternal: 0, notInVendor: 0 };
  const items: {
    runId: string;
    matchResultId: string | null;
    vendorRowId: string | null;
    internalRowId: string | null;
    vendorLabel: string;
    internalLabel: string;
    vendorPrice: number | null;
    internalPrice: number | null;
    diff: number | null;
    diffPct: number | null;
    status: string;
  }[] = [];

  // ---- vendor side: every vendor row, matched or not ----
  for (const v of vendorRows) {
    const vendorPrices = safeJson<Record<string, number>>(v.prices, {});
    const vendorPrice = vendorPrices[opts.vendorPriceField] ?? null;
    const res = resultByVendorId.get(v.id);

    if (res && ACCEPTED_MATCH_STATUSES.has(res.status) && res.internalRowId) {
      const internal = internalById.get(res.internalRowId);
      let ref = resolveRef(internal, v.nameNorm);
      if (ref?.nameNorm) {
        const group = refGroupByNorm.get(ref.nameNorm) ?? [];
        const ranged = group.filter((g) => g.qtyMin !== null || g.qtyMax !== null);
        if (ranged.length > 0 && v.qty !== null) {
          const hit = ranged.find((g) => qtyInRange(v.qty!, g.qtyMin, g.qtyMax));
          if (hit) ref = hit;
        }
      }

      const refPrices = ref ? safeJson<Record<string, number>>(ref.prices, {}) : {};
      const internalPrice = refPrices[opts.internalPriceField] ?? null;

      let status = "MISSING";
      let diff: number | null = null;
      let diffPct: number | null = null;
      if (vendorPrice !== null && internalPrice !== null) {
        diff = vendorPrice - internalPrice;
        diffPct = internalPrice !== 0 ? (diff / internalPrice) * 100 : null;
        const withinTolerance = diffPct !== null ? Math.abs(diffPct) <= opts.tolerancePct : diff === 0;
        status = withinTolerance || diff === 0 ? "SAME" : diff > 0 ? "HIGHER" : "LOWER";
      }
      stats.total++;
      if (status === "SAME") stats.same++;
      else if (status === "HIGHER") stats.higher++;
      else if (status === "LOWER") stats.lower++;
      else stats.missing++;

      const baseLabel = internal?.nameRaw ?? ref?.nameRaw ?? "";
      items.push({
        runId: run.id,
        matchResultId: res.id,
        vendorRowId: v.id,
        internalRowId: internal?.id ?? null,
        vendorLabel: v.nameRaw ?? "",
        // show which quantity range priced this row (Customized Price)
        internalLabel: ref?.qtyRuleLabel ? `${baseLabel} (${ref.qtyRuleLabel})` : baseLabel,
        vendorPrice,
        internalPrice,
        diff: diff !== null ? Number(diff.toFixed(2)) : null,
        diffPct: diffPct !== null ? Number(diffPct.toFixed(2)) : null,
        status,
      });
    } else {
      // vendor offered this product but nothing in the internal price list matched it
      stats.total++;
      stats.notInInternal++;
      items.push({
        runId: run.id,
        matchResultId: res?.id ?? null,
        vendorRowId: v.id,
        internalRowId: null,
        vendorLabel: v.nameRaw ?? "",
        internalLabel: "",
        vendorPrice,
        internalPrice: null,
        diff: null,
        diffPct: null,
        status: "NOT_IN_INTERNAL",
      });
    }
  }

  // ---- internal side: every internal row nothing matched to ----
  for (const i of internalRows) {
    if (i.nameNorm && matchedInternalNorms.has(i.nameNorm)) continue;
    const ref = resolveRef(i, null);
    const refPrices = ref ? safeJson<Record<string, number>>(ref.prices, {}) : safeJson<Record<string, number>>(i.prices, {});
    const internalPrice = refPrices[opts.internalPriceField] ?? null;
    const label = i.qtyRuleLabel ? `${i.nameRaw ?? ""} (${i.qtyRuleLabel})` : i.nameRaw ?? "";

    stats.total++;
    stats.notInVendor++;
    items.push({
      runId: run.id,
      matchResultId: null,
      vendorRowId: null,
      internalRowId: i.id,
      vendorLabel: "",
      internalLabel: label,
      vendorPrice: null,
      internalPrice,
      diff: null,
      diffPct: null,
      status: "NOT_IN_VENDOR",
    });
  }

  const chunk = 500;
  await prisma.$transaction([
    ...Array.from({ length: Math.ceil(items.length / chunk) }, (_, i) =>
      prisma.priceValidationItem.createMany({ data: items.slice(i * chunk, i * chunk + chunk) })
    ),
    prisma.priceValidationRun.update({ where: { id: run.id }, data: { stats: JSON.stringify(stats) } }),
  ]);
  return { runId: run.id, stats };
}
