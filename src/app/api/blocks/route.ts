import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";
import { emptyBlockContent, type BlockType } from "@/lib/types";

const BLOCK_TYPES: BlockType[] = ["text", "heading", "bullet", "table", "image"];

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get("ws") ?? "rafli";
  const blocks = await prisma.block.findMany({ where: { workspace: ws }, orderBy: { order: "asc" } });
  return NextResponse.json({ blocks: blocks.map((b) => ({ ...b, content: safeJson(b.content, {}) })) });
}

export async function POST(req: NextRequest) {
  const { workspace, type } = await req.json().catch(() => ({}));
  if (!BLOCK_TYPES.includes(type)) return NextResponse.json({ error: "Invalid block type" }, { status: 400 });
  const ws = workspace || "rafli";
  const last = await prisma.block.findFirst({ where: { workspace: ws }, orderBy: { order: "desc" } });
  const block = await prisma.block.create({
    data: { workspace: ws, type, order: (last?.order ?? -1) + 1, content: JSON.stringify(emptyBlockContent(type)) },
  });
  return NextResponse.json({ block: { ...block, content: safeJson(block.content, {}) } });
}
