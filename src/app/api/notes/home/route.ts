import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";

/** The one note per workspace with order -1 is structurally "Home" — never matched by title, so
 *  freely renaming it (like any other page) can never orphan it into creating a duplicate. */
const HOME_ORDER = -1;

/**
 * The workspace landing page — a normal Note the user can freely type into, found or lazily
 * created per workspace so every workspace always has a page to land on (Notion-style default
 * landing, never a tool dashboard).
 */
export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get("ws") ?? "rafli";
  let note = await prisma.note.findFirst({ where: { workspace: ws, order: HOME_ORDER } });
  if (!note) {
    note = await prisma.note.create({
      data: { workspace: ws, title: "Home", type: "text", order: HOME_ORDER, content: JSON.stringify({ text: "" }) },
    });
  }
  return NextResponse.json({ note: { ...note, content: safeJson(note.content, {}) } });
}
