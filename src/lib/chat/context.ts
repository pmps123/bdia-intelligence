import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";

/**
 * Builds a compact text summary of the current workspace's data so the chat
 * model can answer questions about it. Kept short on purpose — this rides
 * along with every message as a system prompt, so it stays a summary
 * (counts, titles, recent items), never a full data dump.
 */
export async function buildWorkspaceContext(workspace: string): Promise<string> {
  const [notes, blocks, salesmanTotal, salesmanByBulan, projects] = await Promise.all([
    prisma.note.findMany({ where: { workspace }, orderBy: { order: "asc" }, take: 20 }),
    prisma.block.findMany({ where: { workspace }, orderBy: { order: "asc" }, take: 20 }),
    prisma.salesmanRow.count({ where: { workspace } }),
    prisma.salesmanRow.groupBy({ by: ["bulan"], where: { workspace }, _count: { _all: true } }),
    prisma.project.findMany({ where: { workspace }, orderBy: { updatedAt: "desc" }, take: 3 }),
  ]);

  const sections: string[] = [];

  if (notes.length > 0) {
    const lines = notes.map((n) => {
      const content = safeJson<Record<string, unknown>>(n.content, {});
      const preview =
        n.type === "text" || n.type === "heading"
          ? String(content.text ?? "").slice(0, 120)
          : n.type === "bullet"
            ? `${(content.items as unknown[] | undefined)?.length ?? 0} item(s)`
            : n.type === "table"
              ? `${(content.rows as unknown[] | undefined)?.length ?? 0} row(s)`
              : "";
      return `- [${n.type}] ${n.title}${preview ? `: ${preview}` : ""}`;
    });
    sections.push(`Notes (${notes.length}):\n${lines.join("\n")}`);
  }

  if (blocks.length > 0) {
    const textBlocks = blocks.filter((b) => b.type === "text" || b.type === "heading");
    const lines = textBlocks
      .map((b) => {
        const content = safeJson<{ text?: string }>(b.content, {});
        return content.text ? `- [${b.type}] ${content.text.slice(0, 120)}` : null;
      })
      .filter((l): l is string => !!l);
    if (lines.length > 0) sections.push(`Page content:\n${lines.join("\n")}`);
  }

  if (salesmanTotal > 0) {
    const byBulan = salesmanByBulan.map((g) => `${g.bulan} (${g._count._all})`).join(", ");
    sections.push(`Salesman mapping: ${salesmanTotal} entries total, by month: ${byBulan}`);
  }

  if (projects.length > 0) {
    const lines = projects.map(
      (p) => `- "${p.name}" — step: ${p.step}, price source: ${p.priceSource}, updated ${p.updatedAt.toISOString().slice(0, 10)}`
    );
    sections.push(`Recent Price Audit projects:\n${lines.join("\n")}`);
  }

  if (sections.length === 0) return "Workspace is empty — no notes, page content, salesman data, or price audit projects yet.";
  return sections.join("\n\n");
}
