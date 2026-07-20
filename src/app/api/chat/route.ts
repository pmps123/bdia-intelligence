import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { chatCompletion, type ChatCompletionMessage } from "@/lib/chat/openrouter";
import { buildWorkspaceContext } from "@/lib/chat/context";

export const runtime = "nodejs";

const HISTORY_LIMIT = 30; // messages kept as conversation context sent to the model

export async function GET(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get("ws") ?? "rafli";
  const messages = await prisma.chatMessage.findMany({ where: { workspace: ws }, orderBy: { createdAt: "asc" } });
  return NextResponse.json({ messages });
}

export async function POST(req: NextRequest) {
  const { workspace, message } = await req.json().catch(() => ({}));
  if (!workspace || typeof message !== "string" || !message.trim()) {
    return NextResponse.json({ error: "workspace and message are required" }, { status: 400 });
  }

  await prisma.chatMessage.create({ data: { workspace, role: "user", content: message } });

  const [context, history] = await Promise.all([
    buildWorkspaceContext(workspace),
    prisma.chatMessage.findMany({
      where: { workspace },
      orderBy: { createdAt: "desc" },
      take: HISTORY_LIMIT,
    }),
  ]);

  const conversation: ChatCompletionMessage[] = [
    {
      role: "system",
      content:
        "Kamu adalah asisten AI internal untuk tim Business Development Internal Auditor (BDIA). " +
        "Jawab singkat, relevan, dan gunakan konteks workspace berikut bila membantu:\n\n" + context,
    },
    ...history.reverse().map((m): ChatCompletionMessage => ({ role: m.role === "user" ? "user" : "assistant", content: m.content })),
  ];

  try {
    const { content, model } = await chatCompletion(conversation);
    const saved = await prisma.chatMessage.create({ data: { workspace, role: "assistant", content, model } });
    return NextResponse.json({ message: saved });
  } catch (err) {
    const errMessage = err instanceof Error ? err.message : "AI request failed";
    const saved = await prisma.chatMessage.create({
      data: { workspace, role: "assistant", content: `Maaf, semua model AI gagal merespons.\n\n${errMessage}` },
    });
    return NextResponse.json({ message: saved }, { status: 200 });
  }
}

export async function DELETE(req: NextRequest) {
  const ws = req.nextUrl.searchParams.get("ws") ?? "rafli";
  await prisma.chatMessage.deleteMany({ where: { workspace: ws } });
  return NextResponse.json({ ok: true });
}
