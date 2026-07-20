import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";
import { suggestSheets } from "@/lib/engine/suggest";

async function uploadWithSuggestions(uploadId: string | null, otherProductSample?: string[]) {
  if (!uploadId) return null;
  const upload = await prisma.upload.findUnique({ where: { id: uploadId }, include: { worksheets: true } });
  if (!upload) return null;
  const sheets = upload.worksheets
    .sort((a, b) => a.sheetIndex - b.sheetIndex)
    .map((w) => ({
      name: w.name,
      rowCount: w.rowCount,
      headers: safeJson<string[]>(w.headers, []),
      preview: safeJson<string[][]>(w.preview, []),
    }));
  return {
    id: upload.id,
    fileName: upload.fileName,
    fileSize: upload.fileSize,
    suggestions: suggestSheets(sheets, otherProductSample),
    sheets,
  };
}

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const project = await prisma.project.findUnique({ where: { id } });
  if (!project) return NextResponse.json({ error: "Project not found" }, { status: 404 });

  const internal = await uploadWithSuggestions(project.internalUploadId);
  // cross-dataset similarity: vendor columns are compared against the internal product sample
  const bestInternal = internal?.suggestions[0];
  const productCol = bestInternal?.columns.find((c) => c.suggestedRole === "product");
  const sample =
    internal && bestInternal && productCol
      ? internal.sheets.find((s) => s.name === bestInternal.name)?.preview.map((r) => r[productCol.index] ?? "") ?? []
      : undefined;
  const vendor = await uploadWithSuggestions(project.vendorUploadId, sample);

  const session = project.sessionId
    ? await prisma.matchSession.findUnique({ where: { id: project.sessionId }, select: { id: true, status: true, stats: true } })
    : null;

  return NextResponse.json({
    project,
    internal,
    vendor,
    session: session ? { ...session, stats: safeJson(session.stats, null) } : null,
  });
}

export async function PATCH(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const { step, name } = await req.json().catch(() => ({}));
  const project = await prisma.project.update({
    where: { id },
    data: { ...(step ? { step } : {}), ...(name ? { name } : {}) },
  });
  return NextResponse.json({ project });
}

export async function DELETE(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const project = await prisma.project.findUnique({ where: { id } });
  if (project) {
    // cascade: uploads own datasets/rows; session owns results/validations
    for (const uploadId of [project.internalUploadId, project.vendorUploadId]) {
      if (uploadId) await prisma.upload.delete({ where: { id: uploadId } }).catch(() => null);
    }
    if (project.sessionId) await prisma.matchSession.delete({ where: { id: project.sessionId } }).catch(() => null);
    await prisma.project.delete({ where: { id } });
  }
  return NextResponse.json({ ok: true });
}
