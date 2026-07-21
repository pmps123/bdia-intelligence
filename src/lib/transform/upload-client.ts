export interface UploadResult {
  id: string;
  fileName: string;
  fileSize: number;
  sheetText: string;
  detectedRole: string | null;
  detectionScore: number;
  dateLabel: string | null;
}

/**
 * Uploads a file straight to Supabase Storage from the browser — Vercel Functions
 * cap request bodies at ~4.5MB, too small for the xlsx exports this app deals with.
 */
export async function uploadTransformFile(file: File, pipelineId?: string): Promise<UploadResult> {
  const signRes = await fetch("/api/transform/upload/sign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fileName: file.name }),
  });
  if (!signRes.ok) throw new Error((await signRes.json().catch(() => ({}))).error || "Could not prepare upload");
  const { key, uploadUrl } = (await signRes.json()) as { key: string; uploadUrl: string };

  const putRes = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/octet-stream" },
    body: file,
  });
  if (!putRes.ok) throw new Error(`Upload to storage failed (${putRes.status})`);

  const finalizeRes = await fetch("/api/transform/upload", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key, fileName: file.name, pipeline: pipelineId }),
  });
  if (!finalizeRes.ok) throw new Error((await finalizeRes.json().catch(() => ({}))).error || "Could not process upload");
  return finalizeRes.json();
}
