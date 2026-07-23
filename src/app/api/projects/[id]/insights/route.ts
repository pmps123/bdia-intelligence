import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { chatCompletion } from "@/lib/chat/openrouter";
import { analyzeAnomalies } from "@/lib/engine/anomaly";
import { priceStatusLabel } from "@/lib/types";

export const runtime = "nodejs";

/**
 * AI Executive Summary for a completed price-audit run. Feeds the model the run's real aggregate
 * numbers plus its top anomalies (computed by the same engine the UI shows) and asks for a short
 * narrative + concrete negotiation points. Real OpenRouter call — never a mock; any failure
 * (missing key, all models down) surfaces as an error the UI can toast, the audit itself is
 * unaffected.
 */
export async function POST(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  const project = await prisma.project.findUnique({ where: { id } });
  if (!project?.validationRunId) {
    return NextResponse.json({ error: "Jalankan price validation dulu" }, { status: 400 });
  }
  const run = await prisma.priceValidationRun.findUnique({
    where: { id: project.validationRunId },
    include: { items: true },
  });
  if (!run) return NextResponse.json({ error: "Hasil validasi tidak ditemukan" }, { status: 404 });

  const { byId, summary } = analyzeAnomalies(run.items.map((it) => ({ id: it.id, diffPct: it.diffPct })));

  const counts = { same: 0, higher: 0, lower: 0, notInInternal: 0, notInVendor: 0, missing: 0 };
  for (const it of run.items) {
    if (it.status === "SAME") counts.same++;
    else if (it.status === "HIGHER") counts.higher++;
    else if (it.status === "LOWER") counts.lower++;
    else if (it.status === "NOT_IN_INTERNAL") counts.notInInternal++;
    else if (it.status === "NOT_IN_VENDOR") counts.notInVendor++;
    else counts.missing++;
  }

  // the biggest anomalies, worst first, capped so the prompt stays small
  const topAnomalies = run.items
    .map((it) => ({ it, a: byId.get(it.id) }))
    .filter((x) => x.a && x.a.severity !== "none")
    .sort((a, b) => Math.abs(b.it.diffPct ?? 0) - Math.abs(a.it.diffPct ?? 0))
    .slice(0, 15)
    .map(({ it, a }) => `- ${it.vendorLabel || it.internalLabel} | ${it.diffPct! > 0 ? "+" : ""}${it.diffPct!.toFixed(1)}% | ${a!.severity === "high" ? "TINGGI" : "sedang"} | ${a!.reason}`)
    .join("\n");

  const prompt = `Anda auditor harga senior. Ringkas hasil audit harga vendor berikut untuk manajemen, dalam Bahasa Indonesia yang padat dan actionable.

Nama audit: "${run.name}"
Total baris dibandingkan: ${run.items.length}
- Harga naik (${priceStatusLabel("HIGHER")}): ${counts.higher}
- Harga turun (${priceStatusLabel("LOWER")}): ${counts.lower}
- Harga sama: ${counts.same}
- Ada di vendor tapi tidak di internal: ${counts.notInInternal}
- Ada di internal tapi tidak ditawarkan vendor: ${counts.notInVendor}
Anomali terdeteksi: ${summary.high} tinggi, ${summary.medium} sedang (dari ${summary.total} baris yang punya perbandingan harga).

Anomali teratas (produk | perubahan | severity | alasan):
${topAnomalies || "(tidak ada anomali signifikan)"}

Tulis:
1. Ringkasan eksekutif 2-3 kalimat (angka kunci + temuan utama).
2. 2-4 rekomendasi konkret (fokus ke item anomali tinggi: negosiasi ulang / minta bukti kenaikan / verifikasi data).
Jangan mengarang angka yang tidak ada di atas. Jawab teks biasa, tanpa markdown heading.`;

  try {
    const { content, model } = await chatCompletion([{ role: "user", content: prompt }]);
    return NextResponse.json({ summary: content.trim(), model });
  } catch (err) {
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Gagal generate ringkasan AI" },
      { status: 502 }
    );
  }
}
