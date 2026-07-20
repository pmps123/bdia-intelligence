import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";
import type { MatchCandidate } from "@/lib/types";

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const session = await prisma.matchSession.findUnique({ where: { id } });
  if (!session) return NextResponse.json({ error: "Session not found" }, { status: 404 });

  const results = await prisma.matchResult.findMany({ where: { sessionId: id }, orderBy: { score: "desc" } });
  const rowIds = new Set<string>();
  for (const r of results) {
    rowIds.add(r.vendorRowId);
    if (r.internalRowId) rowIds.add(r.internalRowId);
  }
  const rows = await prisma.dataRow.findMany({ where: { id: { in: [...rowIds] } } });
  const rowMap = new Map(rows.map((r) => [r.id, r]));

  return NextResponse.json({
    session: { ...session, stats: safeJson(session.stats, null) },
    results: results.map((r) => {
      const v = rowMap.get(r.vendorRowId);
      const i = r.internalRowId ? rowMap.get(r.internalRowId) : undefined;
      return {
        id: r.id,
        status: r.status,
        source: r.source,
        score: r.score,
        confidence: r.confidence,
        internalRowId: r.internalRowId,
        vendorLabel: v?.nameRaw ?? "",
        vendorPrices: safeJson<Record<string, number>>(v?.prices ?? null, {}),
        internalLabel: i?.nameRaw ?? "",
        candidates: safeJson<MatchCandidate[]>(r.candidates, []),
      };
    }),
  });
}
