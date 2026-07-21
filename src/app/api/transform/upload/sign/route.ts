import { NextRequest, NextResponse } from "next/server";
import { createSignedUploadUrl } from "@/lib/storage";

export const runtime = "nodejs";

const ALLOWED = ["xlsx", "xls", "xlsm", "xlsb", "csv"];

/** Step 1 of upload: a URL the browser can PUT the file straight to Supabase Storage with — see /api/transform/upload for step 2. */
export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => null)) as { fileName?: string } | null;
  const fileName = body?.fileName;
  if (!fileName) return NextResponse.json({ error: "fileName is required" }, { status: 400 });

  const ext = fileName.split(".").pop()?.toLowerCase() ?? "";
  if (!ALLOWED.includes(ext)) {
    return NextResponse.json({ error: `Unsupported file type .${ext} — use ${ALLOWED.join(", ")}` }, { status: 400 });
  }

  try {
    const { key, uploadUrl } = await createSignedUploadUrl(fileName);
    return NextResponse.json({ key, uploadUrl });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : String(e) }, { status: 502 });
  }
}
