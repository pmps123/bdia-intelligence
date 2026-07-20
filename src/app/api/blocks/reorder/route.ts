import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function PUT(req: NextRequest) {
  const { ids } = await req.json().catch(() => ({}));
  if (!Array.isArray(ids)) return NextResponse.json({ error: "ids must be an array" }, { status: 400 });
  await prisma.$transaction(ids.map((id: string, order: number) => prisma.block.update({ where: { id }, data: { order } })));
  return NextResponse.json({ ok: true });
}
