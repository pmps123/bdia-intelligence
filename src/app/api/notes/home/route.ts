import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";

const HOME_ORDER = -1;

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get("ws") ?? "rafli";
  let page = await prisma.page.findFirst({ where: { workspace: ws, order: HOME_ORDER } });
  if (!page) {
    page = await prisma.page.create({
      data: { workspace: ws, title: "Home", order: HOME_ORDER },
    });
  }
  return NextResponse.json({ note: { ...page, content: {} } });
}
