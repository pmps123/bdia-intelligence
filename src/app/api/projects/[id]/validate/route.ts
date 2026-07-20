import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { runPriceValidation } from "@/lib/engine/price";
import { safeJson } from "@/lib/utils";

export const runtime = "nodejs";

/**
 * Attach matching status + confidence (from the match session) to each price
 * item. Full-join rows on the internal side have no matchResultId (nothing
 * in the vendor file ever pointed at them) — those just get "-".
 */
async function enrichItems<T extends { matchResultId: string | null }>(items: T[]) {
  const ids = items.map((i) => i.matchResultId).filter((id): id is string => id !== null);
  const results = await prisma.matchResult.findMany({
    where: { id: { in: ids } },
    select: { id: true, status: true, confidence: true },
  });
  const byId = new Map(results.map((r) => [r.id, r]));
  return items.map((it) => ({
    ...it,
    matchStatus: (it.matchResultId && byId.get(it.matchResultId)?.status) || "",
    confidence: (it.matchResultId && byId.get(it.matchResultId)?.confidence) ?? null,
  }));
}

/** Re-runs price validation automatically: reference = the internal file, field = the detected price column. */
export async function POST(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const project = await prisma.project.findUnique({ where: { id } });
  if (!project?.sessionId || !project.internalDatasetId) {
    return NextResponse.json({ error: "Run matching first" }, { status: 400 });
  }

  if (project.validationRunId) {
    await prisma.priceValidationRun.delete({ where: { id: project.validationRunId } }).catch(() => null);
  }

  const { runId, stats } = await runPriceValidation({
    sessionId: project.sessionId,
    referenceDatasetId: project.internalDatasetId,
    vendorPriceField: "basicPrice",
    internalPriceField: "basicPrice",
    tolerancePct: 0,
    name: project.name,
  });
  await prisma.project.update({ where: { id }, data: { validationRunId: runId, step: "price" } });

  const run = await prisma.priceValidationRun.findUniqueOrThrow({ where: { id: runId }, include: { items: true } });
  return NextResponse.json({ runId, stats, items: await enrichItems(run.items) });
}

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const project = await prisma.project.findUnique({ where: { id } });
  if (!project?.validationRunId) return NextResponse.json({ run: null });
  const run = await prisma.priceValidationRun.findUnique({ where: { id: project.validationRunId }, include: { items: true } });
  return NextResponse.json({
    run: run ? { ...run, stats: safeJson(run.stats, null), items: await enrichItems(run.items) } : null,
  });
}
