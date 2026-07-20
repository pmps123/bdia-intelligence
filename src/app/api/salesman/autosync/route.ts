import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { parseSpreadsheet } from "@/lib/parse/file-parser";
import { buildSalesmanRows } from "@/lib/salesman/parse";
import fs from "fs";
import path from "path";

export const runtime = "nodejs";

function readLocalExcel(filename: string) {
  const filePath = path.join(process.cwd(), filename);
  if (!fs.existsSync(filePath)) {
    throw new Error(`File ${filename} tidak ditemukan di root folder proyek.`);
  }
  const buffer = fs.readFileSync(filePath);
  return parseSpreadsheet(buffer, "xlsx");
}

export async function POST(req: NextRequest) {
  const { workspace } = await req.json().catch(() => ({}));
  if (typeof workspace !== "string" || !workspace) {
    return NextResponse.json({ error: "workspace is required" }, { status: 400 });
  }

  try {
    // 1. Read static data karyawan & hierarchy mapping files
    const karyawan = readLocalExcel("NEW DATA KARYAWAN.xlsx");
    const hierarchy = readLocalExcel("Mapping Sales_Co_SPV_BM v1.0.xlsx");

    // 2. Read all walking salesman files (Jan, Feb, Mar)
    const berjalanFiles = [
      "Mapping Salesman Berjalan Jan 2026.xlsx",
      "Mapping Salesman Berjalan Feb 2026.xlsx",
      "Mapping Salesman Berjalan Mar 2026.xlsx",
    ];

    let allRows: any[] = [];
    const existingKeys = new Set<string>();

    for (const file of berjalanFiles) {
      if (fs.existsSync(path.join(process.cwd(), file))) {
        const berjalan = readLocalExcel(file);
        const { rows } = buildSalesmanRows({ karyawan, hierarchy, berjalan });
        for (const r of rows) {
          const key = `${r.bulan} ${r.legacyCode}`;
          if (!existingKeys.has(key)) {
            existingKeys.add(key);
            allRows.push(r);
          }
        }
      }
    }

    if (allRows.length === 0) {
      return NextResponse.json({ error: "Tidak ada baris data salesman yang berhasil diproses dari file lokal." }, { status: 400 });
    }

    // 3. Clear and re-seed or skip existing
    // Let's check what's already in the DB
    const existingInDb = await prisma.salesmanRow.findMany({ where: { workspace }, select: { bulan: true, legacyCode: true } });
    const dbKeys = new Set(existingInDb.map((e) => `${e.bulan} ${e.legacyCode}`));
    const toInsert = allRows.filter((r) => !dbKeys.has(`${r.bulan} ${r.legacyCode}`));

    if (toInsert.length > 0) {
      await prisma.salesmanRow.createMany({ data: toInsert.map((r) => ({ ...r, workspace })) });
    }

    return NextResponse.json({
      inserted: toInsert.length,
      skippedExisting: allRows.length - toInsert.length,
      needsReview: toInsert.filter((r) => r.needsReview).length,
    });
  } catch (e) {
    return NextResponse.json({ error: e instanceof Error ? e.message : "Gagal memproses sinkronisasi data lokal." }, { status: 500 });
  }
}
