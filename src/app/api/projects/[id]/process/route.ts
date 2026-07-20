import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { createDatasetFromUpload } from "@/lib/engine/dataset";
import { runMatching } from "@/lib/engine/matching";
import type { ColumnMapping } from "@/lib/types";

export const runtime = "nodejs";

interface SideConfig {
  sheetName: string;
  headers: string[];
  roles: {
    product: number;
    code?: number | null;
    price?: number | null;
    category?: number | null;
    qty?: number | null;
    qtyRule?: number | null;
    qtyFrom?: number | null;
    qtyTo?: number | null;
  };
}

function buildMapping(cfg: SideConfig, withQtyRules: boolean): ColumnMapping[] {
  const roleByIndex = new Map<number, string>();
  roleByIndex.set(cfg.roles.product, "productName");
  if (cfg.roles.code != null) roleByIndex.set(cfg.roles.code, "productCode");
  if (cfg.roles.price != null) roleByIndex.set(cfg.roles.price, "basicPrice");
  if (cfg.roles.category != null) roleByIndex.set(cfg.roles.category, "category");
  if (cfg.roles.qty != null) roleByIndex.set(cfg.roles.qty, "qty");
  if (withQtyRules) {
    // quantity gradation columns only apply to a Customized Price reference
    if (cfg.roles.qtyRule != null) roleByIndex.set(cfg.roles.qtyRule, "qtyRule");
    if (cfg.roles.qtyFrom != null) roleByIndex.set(cfg.roles.qtyFrom, "qtyFrom");
    if (cfg.roles.qtyTo != null) roleByIndex.set(cfg.roles.qtyTo, "qtyTo");
  }
  return cfg.headers.map((h, i) => ({
    sourceIndex: i,
    sourceName: h,
    field: (roleByIndex.get(i) as ColumnMapping["field"]) ?? null,
    rename: h,
    ignore: false, // extra columns ride along, they cost nothing
  }));
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const project = await prisma.project.findUnique({ where: { id } });
  if (!project?.internalUploadId || !project?.vendorUploadId) {
    return NextResponse.json({ error: "Upload both files first" }, { status: 400 });
  }
  const body = (await req.json().catch(() => null)) as { internal: SideConfig; vendor: SideConfig } | null;
  if (!body?.internal || !body?.vendor || body.internal.roles?.product == null || body.vendor.roles?.product == null) {
    return NextResponse.json({ error: "Product column is required on both files" }, { status: 400 });
  }

  const job = await prisma.job.create({ data: { type: "PROCESS", message: "Starting" } });
  const { internalUploadId, vendorUploadId } = project;

  void (async () => {
    try {
      // clean re-run: drop previous session/datasets for this project
      if (project.sessionId) await prisma.matchSession.delete({ where: { id: project.sessionId } }).catch(() => null);
      for (const dsId of [project.internalDatasetId, project.vendorDatasetId]) {
        if (dsId) await prisma.dataset.delete({ where: { id: dsId } }).catch(() => null);
      }

      await prisma.job.update({ where: { id: job.id }, data: { message: "Reading internal file", progress: 2 } });
      const internalDatasetId = await createDatasetFromUpload({
        uploadId: internalUploadId,
        worksheetName: body.internal.sheetName,
        mapping: buildMapping(body.internal, project.priceSource === "CUSTOM"),
        kind: "INTERNAL",
        datasetName: `${project.name} — internal`,
      });

      await prisma.job.update({ where: { id: job.id }, data: { message: "Reading vendor file", progress: 25 } });
      const vendorDatasetId = await createDatasetFromUpload({
        uploadId: vendorUploadId,
        worksheetName: body.vendor.sheetName,
        mapping: buildMapping(body.vendor, false),
        kind: "VENDOR",
        vendorName: project.name,
        datasetName: `${project.name} — vendor`,
      });

      const session = await prisma.matchSession.create({
        data: { name: project.name, vendorDatasetId, internalDatasetId, status: "RUNNING" },
      });
      await prisma.project.update({
        where: { id },
        data: { internalDatasetId, vendorDatasetId, sessionId: session.id },
      });

      await runMatching(job.id, session.id); // marks job COMPLETED with stats
      await prisma.project.update({ where: { id }, data: { step: "review" } });
    } catch (e) {
      await prisma.job.update({
        where: { id: job.id },
        data: { status: "FAILED", message: e instanceof Error ? e.message : "Processing failed" },
      });
    }
  })();

  return NextResponse.json({ jobId: job.id });
}
