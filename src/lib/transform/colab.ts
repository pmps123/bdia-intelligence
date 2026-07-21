import { getSignedUrl } from "@/lib/storage";
import type { PipelineDef, PipelineRole } from "./pipelines";

/**
 * Vercel's Node functions have no Python interpreter, so pipeline scripts can't
 * run there — this builds a ready-to-paste Colab cell instead (see README's
 * "Alternatif: menjalankan pipeline di Google Colab" section for the manual version).
 */
export const COLAB_NOTEBOOK_URL = "https://colab.research.google.com/drive/1qb1LEHezZpBYOML7lcCKruSEZPvtwW3R?usp=sharing";

export function isColabMode(): boolean {
  return !!process.env.VERCEL;
}

export interface ColabInstructions {
  notebookUrl: string;
  pipelineTitle: string;
  script: string;
  files: { label: string; fileName: string }[];
  command: string;
}

export async function buildColabInstructions(
  pipeline: PipelineDef,
  uploads: { role: PipelineRole; fileName: string; storagePath: string }[]
): Promise<ColabInstructions> {
  const files = await Promise.all(
    uploads.map(async (u) => ({
      role: u.role,
      fileName: u.fileName,
      url: await getSignedUrl(u.storagePath, 1800),
    }))
  );
  const downloads = files.map((f) => `urllib.request.urlretrieve("${f.url}", "${f.fileName}")`).join("\n");
  const args = files.map((f) => `--${f.role.key} "${f.fileName}"`).join(" ");
  return {
    notebookUrl: COLAB_NOTEBOOK_URL,
    pipelineTitle: pipeline.title,
    script: pipeline.script,
    files: files.map((f) => ({ label: f.role.label, fileName: f.fileName })),
    command: `import urllib.request\n${downloads}\n!python "${pipeline.script}" ${args}`,
  };
}
