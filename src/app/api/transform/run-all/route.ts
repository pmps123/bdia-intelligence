import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { PIPELINES, SALES_DASHBOARD_SECTIONS } from "@/lib/transform/pipelines";
import { runTransformAndWait } from "@/lib/transform/runner";

export const runtime = "nodejs";

/**
 * One click runs the whole Sales Dashboard: every fully-assigned section is
 * queued and executed sequentially (each script is heavy — pandas/polars over
 * full exports — so serial is the safe order); sections missing inputs are
 * reported as skipped. Body: { sections: { [sectionId]: { roleKey: uploadId } } }.
 */
export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { sections?: Record<string, Record<string, string>> } | null;
  if (!body?.sections) return NextResponse.json({ error: "sections is required" }, { status: 400 });

  const queued: { sectionId: string; runId: string; script: string; args: string[] }[] = [];
  const skipped: string[] = [];

  for (const sectionId of SALES_DASHBOARD_SECTIONS) {
    const pipeline = PIPELINES[sectionId];
    const files = body.sections[sectionId] ?? {};
    if (!pipeline.roles.every((r) => files[r.key])) {
      skipped.push(sectionId);
      continue;
    }
    const args: string[] = [];
    const fileNames: Record<string, string> = {};
    for (const role of pipeline.roles) {
      const upload = await prisma.upload.findUnique({ where: { id: files[role.key] } });
      if (!upload) return NextResponse.json({ error: `Uploaded file for ${pipeline.title} · ${role.label} not found` }, { status: 400 });
      args.push(`--${role.key}`, upload.storagePath);
      fileNames[role.key] = upload.fileName;
    }
    const run = await prisma.transformRun.create({
      data: { pipeline: pipeline.id, status: "PENDING", files: JSON.stringify(fileNames) },
    });
    queued.push({ sectionId, runId: run.id, script: pipeline.script, args });
  }

  if (queued.length === 0) {
    return NextResponse.json({ error: "No section has all its inputs assigned yet" }, { status: 400 });
  }

  // sequential execution in the background; each run flips PENDING → RUNNING → COMPLETED/FAILED
  void (async () => {
    for (const item of queued) {
      await prisma.transformRun.update({ where: { id: item.runId }, data: { status: "RUNNING" } }).catch(() => null);
      await runTransformAndWait(item.runId, item.script, item.args);
    }
  })();

  return NextResponse.json({
    runs: Object.fromEntries(queued.map((q) => [q.sectionId, q.runId])),
    skipped,
  });
}
