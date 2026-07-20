import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

export async function GET(req: NextRequest) {
  // audits are isolated per workspace
  const ws = req.nextUrl.searchParams.get("ws") ?? "rafli";
  const projects = await prisma.project.findMany({ where: { workspace: ws }, orderBy: { updatedAt: "desc" }, take: 50 });
  return NextResponse.json({ projects });
}

export async function POST(req: NextRequest) {
  const { name, priceSource, workspace } = await req.json().catch(() => ({}));
  if (!name?.trim()) return NextResponse.json({ error: "Project name is required" }, { status: 400 });
  if (!["PRICE_LIST", "BASIC", "CUSTOM"].includes(priceSource)) {
    return NextResponse.json({ error: "Choose an internal price source" }, { status: 400 });
  }
  const project = await prisma.project.create({
    data: { name: name.trim(), priceSource, workspace: workspace || "rafli" },
  });
  return NextResponse.json({ project });
}
