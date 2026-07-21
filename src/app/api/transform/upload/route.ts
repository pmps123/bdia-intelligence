import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { parseUploadedFile } from "@/lib/parse/file-parser";
import { PIPELINES, detectRole, extractFileDate } from "@/lib/transform/pipelines";
import { readUpload } from "@/lib/storage";

export const runtime = "nodejs";
export const maxDuration = 60; // parsing a large xlsx can take a while

/**
 * Step 2 of upload: the file is already in Supabase Storage (browser PUT it
 * directly there via /api/transform/upload/sign) — parse it and register the
 * Upload row. The file's purpose (role) is auto-detected from its filename
 * keyword and worksheet/header content — never from the full name, date or
 * numeric ID.
 */
export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { key?: string; fileName?: string; pipeline?: string } | null;
  const pipelineId = body?.pipeline ?? "";
  const pipeline = pipelineId ? PIPELINES[pipelineId] : null; // optional: shared pool detects per section client-side
  if (!body?.key || !body?.fileName || (pipelineId && !pipeline)) {
    return NextResponse.json({ error: "key, fileName (and a valid pipeline, if given) are required" }, { status: 400 });
  }
  const ext = body.fileName.split(".").pop()?.toLowerCase() ?? "";

  let buffer;
  try {
    buffer = await readUpload(body.key);
  } catch (e) {
    return NextResponse.json({ error: `Could not read the uploaded file: ${e instanceof Error ? e.message : e}` }, { status: 502 });
  }

  let parsed;
  try {
    parsed = await parseUploadedFile(buffer, body.fileName);
  } catch (e) {
    return NextResponse.json({ error: `Could not read ${body.fileName}: ${e instanceof Error ? e.message : e}` }, { status: 400 });
  }

  const upload = await prisma.upload.create({
    data: { fileName: body.fileName, fileType: ext, fileSize: buffer.length, storagePath: body.key },
  });

  // sheet names + headers feed the role detection alongside the filename
  const sheetText = parsed.sheets.map((s) => `${s.name} ${s.headers.join(" ")}`).join(" ").slice(0, 4000);
  const detection = pipeline ? detectRole(pipeline, body.fileName, sheetText) : null;

  return NextResponse.json({
    id: upload.id,
    fileName: body.fileName,
    fileSize: buffer.length,
    sheetText, // lets the client re-run detection per dashboard section
    detectedRole: detection?.role ?? null,
    detectionScore: detection?.score ?? 0,
    dateLabel: extractFileDate(body.fileName), // metadata only, shown for confirmation
  });
}
