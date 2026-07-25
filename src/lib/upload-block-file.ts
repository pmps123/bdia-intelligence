/**
 * Upload a file to the block attachments endpoint and return the stored URL and metadata.
 * Throws if the upload fails.
 */
export async function uploadBlockFile(file: File): Promise<{
  url: string;
  name: string;
  size: number;
}> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/blocks/upload", { method: "POST", body: form });
  if (!res.ok) {
    throw new Error(`Upload failed with status ${res.status}`);
  }
  return res.json();
}
