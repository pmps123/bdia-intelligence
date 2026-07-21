import { mkdtemp, writeFile } from "fs/promises";
import { tmpdir } from "os";
import path from "path";

/**
 * Uploaded files live in Supabase Storage (bucket "uploads"), not local disk —
 * Vercel's deployment filesystem is read-only outside /tmp, so writeFile()
 * to process.cwd() throws in production. `storagePath` is now a storage key.
 */
const BUCKET = "uploads";
const SUPABASE_URL = process.env.SUPABASE_URL;
const SERVICE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY;

function headers(extra?: Record<string, string>) {
  if (!SUPABASE_URL || !SERVICE_KEY) throw new Error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are not set");
  return { Authorization: `Bearer ${SERVICE_KEY}`, apikey: SERVICE_KEY, ...extra };
}

/**
 * Vercel Functions cap request bodies at ~4.5MB — too small for the xlsx exports
 * this app deals with. The browser uploads straight to Supabase Storage with this
 * signed URL instead of relaying the bytes through our server.
 */
export async function createSignedUploadUrl(fileName: string): Promise<{ key: string; uploadUrl: string }> {
  const key = `${Date.now()}-${fileName}`;
  const res = await fetch(`${SUPABASE_URL}/storage/v1/object/upload/sign/${BUCKET}/${encodeURIComponent(key)}`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: "{}",
  });
  if (!res.ok) throw new Error(`Supabase Storage sign-upload failed (${res.status}): ${await res.text()}`);
  const { url } = (await res.json()) as { url: string };
  return { key, uploadUrl: `${SUPABASE_URL}/storage/v1${url}` };
}

export async function saveUpload(buffer: Buffer, fileName: string): Promise<string> {
  const key = `${Date.now()}-${fileName}`;
  const res = await fetch(`${SUPABASE_URL}/storage/v1/object/${BUCKET}/${encodeURIComponent(key)}`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/octet-stream" }),
    body: new Uint8Array(buffer),
  });
  if (!res.ok) throw new Error(`Supabase Storage upload failed (${res.status}): ${await res.text()}`);
  return key;
}

export async function readUpload(key: string): Promise<Buffer> {
  const res = await fetch(`${SUPABASE_URL}/storage/v1/object/${BUCKET}/${encodeURIComponent(key)}`, {
    headers: headers(),
  });
  if (!res.ok) throw new Error(`Supabase Storage download failed (${res.status}): ${await res.text()}`);
  return Buffer.from(await res.arrayBuffer());
}

/** Time-limited public download link — used to hand a file to an external runner (e.g. Colab). */
export async function getSignedUrl(key: string, expiresInSeconds: number): Promise<string> {
  const res = await fetch(`${SUPABASE_URL}/storage/v1/object/sign/${BUCKET}/${encodeURIComponent(key)}`, {
    method: "POST",
    headers: headers({ "Content-Type": "application/json" }),
    body: JSON.stringify({ expiresIn: expiresInSeconds }),
  });
  if (!res.ok) throw new Error(`Supabase Storage sign failed (${res.status}): ${await res.text()}`);
  const { signedURL } = (await res.json()) as { signedURL: string };
  return `${SUPABASE_URL}/storage/v1${signedURL}`;
}

/** Pipeline scripts run as a local process and need a real file on disk — materialize one. */
export async function downloadToTempFile(key: string, fileName: string): Promise<string> {
  const buffer = await readUpload(key);
  const dir = await mkdtemp(path.join(tmpdir(), "bdia-"));
  const filePath = path.join(dir, fileName);
  await writeFile(filePath, buffer);
  return filePath;
}
