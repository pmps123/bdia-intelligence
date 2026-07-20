import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

const EDITABLE_FIELDS = ["bulan", "branch", "division", "legacyCode", "newCode", "salesName", "nik", "tanggalMasuk", "tanggalKeluar", "aktif"] as const;

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const body = await req.json().catch(() => ({}));
  const data: Record<string, string> = {};
  for (const field of EDITABLE_FIELDS) {
    if (typeof body[field] === "string") data[field] = body[field];
  }
  if (Object.keys(data).length === 0) return NextResponse.json({ error: "No editable field provided" }, { status: 400 });
  const row = await prisma.salesmanRow.update({ where: { id }, data: { ...data, source: "MANUAL" } });
  return NextResponse.json({ row });
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  await prisma.salesmanRow.delete({ where: { id } });
  return NextResponse.json({ ok: true });
}
