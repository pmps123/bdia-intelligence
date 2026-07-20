import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { parseUploadedFile } from "@/lib/parse/file-parser";
import { mkdir, writeFile } from "fs/promises";
import path from "path";

export const runtime = "nodejs";

const STORAGE_DIR = path.join(process.cwd(), "storage", "uploads");
const ALLOWED = ["xlsx", "xls", "csv", "pdf"];

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const project = await prisma.project.findUnique({ where: { id } });
  if (!project) return NextResponse.json({ error: "Project not found" }, { status: 404 });

  const form = await req.formData();
  const file = form.get("file");
  const side = form.get("side"); // internal | vendor
  if (!(file instanceof File) || (side !== "internal" && side !== "vendor")) {
    return NextResponse.json({ error: "file and side (internal|vendor) are required" }, { status: 400 });
  }
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!ALLOWED.includes(ext)) {
    return NextResponse.json({ error: `Unsupported file type .${ext} — use ${ALLOWED.join(", ")}` }, { status: 400 });
  }

  const buffer = Buffer.from(await file.arrayBuffer());
  let parsed;
  try {
    parsed = await parseUploadedFile(buffer, file.name);
  } catch (e) {
    return NextResponse.json({ error: `Could not read ${file.name}: ${e instanceof Error ? e.message : e}` }, { status: 400 });
  }
  if (!parsed.sheets.some((s) => s.rowCount > 0)) {
    return NextResponse.json({ error: "No data rows detected in this file" }, { status: 400 });
  }

  await mkdir(STORAGE_DIR, { recursive: true });
  const storagePath = path.join(STORAGE_DIR, `${Date.now()}-${file.name}`);
  await writeFile(storagePath, buffer);

  const upload = await prisma.upload.create({
    data: {
      fileName: file.name,
      fileType: ext,
      fileSize: buffer.length,
      storagePath,
      worksheets: {
        create: parsed.sheets.map((s) => ({
          name: s.name,
          sheetIndex: s.index,
          rowCount: s.rowCount,
          columnCount: s.columnCount,
          headers: JSON.stringify(s.headers),
          preview: JSON.stringify(s.rows.slice(0, 100)),
        })),
      },
    },
  });

  // replacing a file resets everything downstream of it
  const old = side === "internal" ? project.internalUploadId : project.vendorUploadId;
  if (old) await prisma.upload.delete({ where: { id: old } }).catch(() => null);
  if (project.sessionId) await prisma.matchSession.delete({ where: { id: project.sessionId } }).catch(() => null);

  await prisma.project.update({
    where: { id },
    data: {
      [side === "internal" ? "internalUploadId" : "vendorUploadId"]: upload.id,
      sessionId: null,
      validationRunId: null,
      internalDatasetId: side === "internal" ? null : project.internalDatasetId,
      vendorDatasetId: side === "vendor" ? null : project.vendorDatasetId,
      step: side === "internal" ? "vendor" : "detect",
    },
  });

  return NextResponse.json({ ok: true });
}
