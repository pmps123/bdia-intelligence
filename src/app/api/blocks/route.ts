import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";
import { emptyBlockContent, type BlockType } from "@/lib/types";

const BLOCK_TYPES: BlockType[] = ["text", "heading", "bullet", "table", "image"];

export async function GET(req: NextRequest) {
  const pageId = req.nextUrl.searchParams.get("pageId");
  if (!pageId) return NextResponse.json({ error: "pageId is required" }, { status: 400 });
  const blocks = await prisma.block.findMany({ where: { pageId }, orderBy: { order: "asc" } });
  return NextResponse.json({ blocks: blocks.map((b) => ({ ...b, content: safeJson(b.content, {}) })) });
}

export async function POST(req: NextRequest) {
  const { pageId, type } = await req.json().catch(() => ({}));
  if (!pageId) return NextResponse.json({ error: "pageId is required" }, { status: 400 });
  if (!BLOCK_TYPES.includes(type)) return NextResponse.json({ error: "Invalid block type" }, { status: 400 });
  const page = await prisma.page.findUnique({ where: { id: pageId } });
  if (!page) return NextResponse.json({ error: "Page not found" }, { status: 404 });
  const last = await prisma.block.findFirst({ where: { pageId }, orderBy: { order: "desc" } });
  const block = await prisma.block.create({
    data: {
      pageId,
      workspace: page.workspace,
      type,
      order: (last?.order ?? -1) + 1,
      content: JSON.stringify(emptyBlockContent(type)),
    },
  });
  return NextResponse.json({ block: { ...block, content: safeJson(block.content, {}) } });
}
