import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { PIPELINES } from "@/lib/transform/pipelines";
import { startTransformRun } from "@/lib/transform/runner";
import { downloadToTempFile } from "@/lib/storage";
import { buildColabInstructions, isColabMode } from "@/lib/transform/colab";

export const runtime = "nodejs";

/** Start a pipeline run: body { pipeline, files: { roleKey: uploadId } }. */
export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { pipeline?: string; files?: Record<string, string> } | null;
  const pipeline = body?.pipeline ? PIPELINES[body.pipeline] : undefined;
  if (!pipeline || !body?.files) {
    return NextResponse.json({ error: "pipeline and files are required" }, { status: 400 });
  }
  const missing = pipeline.roles.filter((r) => !body.files![r.key]);
  if (missing.length > 0) {
    return NextResponse.json({ error: `Missing file for: ${missing.map((r) => r.label).join(", ")}` }, { status: 400 });
  }

  const resolved: { role: (typeof pipeline.roles)[number]; fileName: string; storagePath: string }[] = [];
  for (const role of pipeline.roles) {
    const upload = await prisma.upload.findUnique({ where: { id: body.files[role.key] } });
    if (!upload) return NextResponse.json({ error: `Uploaded file for ${role.label} not found` }, { status: 400 });
    resolved.push({ role, fileName: upload.fileName, storagePath: upload.storagePath });
  }

  // no Python interpreter on Vercel — hand off to Colab instead of spawning
  if (isColabMode()) {
    const colab = await buildColabInstructions(pipeline, resolved);
    return NextResponse.json({ colab });
  }

  const args: string[] = [];
  const fileNames: Record<string, string> = {};
  for (const { role, fileName, storagePath } of resolved) {
    const localPath = await downloadToTempFile(storagePath, fileName);
    args.push(`--${role.key}`, localPath);
    fileNames[role.key] = fileName;
  }

  const run = await prisma.transformRun.create({
    data: { pipeline: pipeline.id, files: JSON.stringify(fileNames) },
  });
  startTransformRun(run.id, pipeline.script, args);
  return NextResponse.json({ runId: run.id });
}
