import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { title, content, order, type } = await req.json().catch(() => ({}));
  const data: { title?: string; order?: number } = {};
  if (typeof title === "string") data.title = title;
  if (typeof order === "number") data.order = order;
  const page = await prisma.page.update({ where: { id }, data });
  return NextResponse.json({ note: { ...page, content: {} } });
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  await prisma.page.delete({ where: { id } });
  return NextResponse.json({ ok: true });
}
