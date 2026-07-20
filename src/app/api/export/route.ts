import { NextRequest, NextResponse } from "next/server";
import { getSourceData } from "@/lib/export/sources";
import { runExport } from "@/lib/export/exporter";
import type { ExportConfig } from "@/lib/types";

export const runtime = "nodejs";

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body?.source?.type || !body?.source?.id || !body?.config) {
    return NextResponse.json({ error: "source and config are required" }, { status: 400 });
  }
  const config = body.config as ExportConfig;

  try {
    const data = await getSourceData(body.source.type, body.source.id);
    const { buffer, contentType, ext } = await runExport({ config, rows: data.rows });
    const fileName = `${(config.title || data.name || "export").replace(/[^\w\- ]+/g, "").trim() || "export"}.${ext}`;
    return new NextResponse(new Uint8Array(buffer), {
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": `attachment; filename="${encodeURIComponent(fileName)}"`,
      },
    });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : "Export failed" }, { status: 500 });
  }
}
