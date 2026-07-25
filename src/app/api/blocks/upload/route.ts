import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin, NOTE_ATTACHMENTS_BUCKET } from "@/lib/supabase";
import { generateUUID } from "@/lib/utils";

export async function POST(req: NextRequest) {
  const form = await req.formData();
  const file = form.get("file");
  if (!(file instanceof File)) return NextResponse.json({ error: "file is required" }, { status: 400 });

  const ext = file.name.includes(".") ? file.name.slice(file.name.lastIndexOf(".")) : "";
  const path = `${generateUUID()}${ext}`;
  const buffer = Buffer.from(await file.arrayBuffer());

  const { error } = await supabaseAdmin.storage
    .from(NOTE_ATTACHMENTS_BUCKET)
    .upload(path, buffer, { contentType: file.type || "application/octet-stream" });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const { data } = supabaseAdmin.storage.from(NOTE_ATTACHMENTS_BUCKET).getPublicUrl(path);
  return NextResponse.json({ url: data.publicUrl, name: file.name, size: file.size });
}
