import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";

export async function PATCH(req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { title, content, order, type } = await req.json().catch(() => ({}));
  const data: { title?: string; content?: string; order?: number; type?: string } = {};
  if (typeof title === "string") data.title = title;
  if (content !== undefined) data.content = JSON.stringify(content);
  if (typeof order === "number") data.order = order;
  if (typeof type === "string") data.type = type;
  const note = await prisma.note.update({ where: { id }, data });
  return NextResponse.json({ note: { ...note, content: safeJson(note.content, {}) } });
}

export async function DELETE(_req: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  await prisma.note.delete({ where: { id } });
  return NextResponse.json({ ok: true });
}
