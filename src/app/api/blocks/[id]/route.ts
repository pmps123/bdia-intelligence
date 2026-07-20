import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { content, order, type } = await req.json().catch(() => ({}));
  const data: { content?: string; order?: number; type?: string } = {};
  if (content !== undefined) data.content = JSON.stringify(content);
  if (typeof order === "number") data.order = order;
  if (typeof type === "string") data.type = type;
  const block = await prisma.block.update({ where: { id }, data });
  return NextResponse.json({ block: { ...block, content: safeJson(block.content, {}) } });
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  await prisma.block.delete({ where: { id } });
  return NextResponse.json({ ok: true });
}
