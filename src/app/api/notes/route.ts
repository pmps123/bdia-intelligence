import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";
import { emptyBlockContent, type NoteType } from "@/lib/types";

const NOTE_TYPES: NoteType[] = ["text", "heading", "bullet", "table", "image"];

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get("ws") ?? "rafli";
  const notes = await prisma.note.findMany({ where: { workspace: ws }, orderBy: { order: "asc" } });
  return NextResponse.json({ notes: notes.map((n) => ({ ...n, content: safeJson(n.content, {}) })) });
}

export async function POST(req: NextRequest) {
  const { workspace, type } = await req.json().catch(() => ({}));
  if (!NOTE_TYPES.includes(type)) return NextResponse.json({ error: "Invalid note type" }, { status: 400 });
  const ws = workspace || "rafli";
  const last = await prisma.note.findFirst({ where: { workspace: ws }, orderBy: { order: "desc" } });
  const note = await prisma.note.create({
    data: { workspace: ws, type, order: (last?.order ?? -1) + 1, content: JSON.stringify(emptyBlockContent(type)) },
  });
  return NextResponse.json({ note: { ...note, content: safeJson(note.content, {}) } });
}
