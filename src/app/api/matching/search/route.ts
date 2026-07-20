import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { cleanValue } from "@/lib/engine/cleaning";

/** Search internal products of a dataset (used by review's replace flow). */
export async function GET(req: NextRequest) {
  const datasetId = req.nextUrl.searchParams.get("datasetId");
  const q = req.nextUrl.searchParams.get("q") ?? "";
  if (!datasetId) return NextResponse.json({ error: "datasetId is required" }, { status: 400 });

  const norm = cleanValue(q, ["symbol", "dash", "slash"]);
  const rows = await prisma.dataRow.findMany({
    where: { datasetId, ...(norm ? { nameNorm: { contains: norm } } : {}) },
    take: 30,
    orderBy: { rowIndex: "asc" },
  });
  return NextResponse.json({ rows: rows.map((r) => ({ id: r.id, label: r.nameRaw, code: r.code })) });
}
