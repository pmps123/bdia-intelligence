import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

/**
 * Review decisions. Accepting/replacing feeds the learning engine: the pair
 * becomes a Master Mapping that future projects reuse automatically.
 */
export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const { action, internalRowId } = await req.json().catch(() => ({}));

  const result = await prisma.matchResult.findUnique({ where: { id } });
  if (!result) return NextResponse.json({ error: "Result not found" }, { status: 404 });

  if (action === "reject") {
    await prisma.matchResult.update({
      where: { id },
      data: { status: "UNMATCHED", internalRowId: null, source: "MANUAL" },
    });
    return NextResponse.json({ ok: true });
  }

  if (action !== "accept" && action !== "replace") {
    return NextResponse.json({ error: "action must be accept, reject or replace" }, { status: 400 });
  }

  const targetInternalId = action === "replace" ? internalRowId : result.internalRowId;
  if (!targetInternalId) return NextResponse.json({ error: "No internal product selected" }, { status: 400 });

  const [vendorRow, internalRow] = await Promise.all([
    prisma.dataRow.findUnique({ where: { id: result.vendorRowId }, include: { dataset: true } }),
    prisma.dataRow.findUnique({ where: { id: targetInternalId } }),
  ]);
  if (!vendorRow || !internalRow) return NextResponse.json({ error: "Row not found" }, { status: 404 });

  await prisma.matchResult.update({
    where: { id },
    data: {
      status: action === "replace" ? "MANUAL" : "MATCHED",
      internalRowId: targetInternalId,
      source: "MANUAL",
      confidence: 1,
    },
  });

  if (vendorRow.nameNorm && internalRow.nameNorm) {
    const vendorName = vendorRow.dataset.vendorName ?? "";
    await prisma.masterMapping.upsert({
      where: { vendorName_vendorKey: { vendorName, vendorKey: vendorRow.nameNorm } },
      update: {
        vendorCode: vendorRow.code,
        internalKey: internalRow.nameNorm,
        internalLabel: internalRow.nameRaw ?? "",
        internalCode: internalRow.code,
        usageCount: { increment: 1 },
      },
      create: {
        vendorName,
        vendorKey: vendorRow.nameNorm,
        vendorLabel: vendorRow.nameRaw ?? "",
        vendorCode: vendorRow.code,
        internalKey: internalRow.nameNorm,
        internalLabel: internalRow.nameRaw ?? "",
        internalCode: internalRow.code,
      },
    });
  }

  return NextResponse.json({ ok: true });
}
