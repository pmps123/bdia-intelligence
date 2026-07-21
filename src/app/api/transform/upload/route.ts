import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { parseUploadedFile } from "@/lib/parse/file-parser";
import { PIPELINES, detectRole, extractFileDate } from "@/lib/transform/pipelines";
import { saveUpload } from "@/lib/storage";

export const runtime = "nodejs";

const ALLOWED = ["xlsx", "xls", "xlsm", "xlsb", "csv"];

/**
 * Upload one input file for a Data Transform pipeline.
 * The file's purpose (role) is auto-detected from its filename keyword and
 * worksheet/header content — never from the full name, date or numeric ID.
 */
export async function POST(req: NextRequest) {
  const form = await req.formData();
  const file = form.get("file");
  const pipelineId = String(form.get("pipeline") ?? "");
  const pipeline = pipelineId ? PIPELINES[pipelineId] : null; // optional: shared pool detects per section client-side
  if (!(file instanceof File) || (pipelineId && !pipeline)) {
    return NextResponse.json({ error: "a file (and a valid pipeline, if given) are required" }, { status: 400 });
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

  let storagePath;
  try {
    storagePath = await saveUpload(buffer, file.name);
  } catch (e) {
    return NextResponse.json({ error: `Could not store ${file.name}: ${e instanceof Error ? e.message : e}` }, { status: 502 });
  }

  const upload = await prisma.upload.create({
    data: { fileName: file.name, fileType: ext, fileSize: buffer.length, storagePath },
  });

  // sheet names + headers feed the role detection alongside the filename
  const sheetText = parsed.sheets.map((s) => `${s.name} ${s.headers.join(" ")}`).join(" ").slice(0, 4000);
  const detection = pipeline ? detectRole(pipeline, file.name, sheetText) : null;

  return NextResponse.json({
    id: upload.id,
    fileName: file.name,
    fileSize: buffer.length,
    sheetText, // lets the client re-run detection per dashboard section
    detectedRole: detection?.role ?? null,
    detectionScore: detection?.score ?? 0,
    dateLabel: extractFileDate(file.name), // metadata only, shown for confirmation
  });
}
