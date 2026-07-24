import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";
import { emptyBlockContent, type NoteType } from "@/lib/types";

const NOTE_TYPES: NoteType[] = ["text", "heading", "bullet", "table", "image"];

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get("ws") ?? "rafli";
  const pages = await prisma.page.findMany({ where: { workspace: ws }, orderBy: { order: "asc" } });
  return NextResponse.json({ notes: pages.map((n) => ({ ...n, content: {} })) });
}

export async function POST(req: NextRequest) {
  const { workspace } = await req.json().catch(() => ({}));
  const ws = workspace || "rafli";
  const last = await prisma.page.findFirst({ where: { workspace: ws }, orderBy: { order: "desc" } });
  const page = await prisma.page.create({
    data: { workspace: ws, order: (last?.order ?? -1) + 1, title: "Untitled" },
  });
  return NextResponse.json({ note: { ...page, content: {} } });
}
