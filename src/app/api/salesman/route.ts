import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get("ws") ?? "rafli";
  const bulan = req.nextUrl.searchParams.get("bulan");
  const page = Math.max(1, Number(req.nextUrl.searchParams.get("page")) || 1);
  const limit = Math.min(200, Math.max(1, Number(req.nextUrl.searchParams.get("limit")) || 50));
  const where = { workspace: ws, ...(bulan ? { bulan } : {}) };
  const [rows, total, bulanList] = await Promise.all([
    prisma.salesmanRow.findMany({
      where,
      orderBy: [{ bulan: "asc" }, { branch: "asc" }, { legacyCode: "asc" }],
      skip: (page - 1) * limit,
      take: limit,
    }),
    prisma.salesmanRow.count({ where }),
    prisma.salesmanRow.findMany({ where: { workspace: ws }, select: { bulan: true }, distinct: ["bulan"] }),
  ]);
  return NextResponse.json({ rows, total, page, limit, bulanOptions: bulanList.map((b) => b.bulan) });
}

export async function POST(req: NextRequest) {
  const { workspace, bulan } = await req.json().catch(() => ({}));
  if (!workspace) return NextResponse.json({ error: "workspace is required" }, { status: 400 });
  // legacyCode is part of the unique key — seed a placeholder so two blank rows in the same bulan don't collide
  const placeholderCode = `NEW-${crypto.randomUUID().slice(0, 8)}`;
  const row = await prisma.salesmanRow.create({
    data: { workspace, bulan: bulan || "", branch: "", division: "", legacyCode: placeholderCode, aktif: "Aktif", source: "MANUAL" },
  });
  return NextResponse.json({ row });
}
