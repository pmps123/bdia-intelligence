# Prompt untuk Claude Code (komputer kantor)

Copy-paste blok di bawah ini ke Claude Code di komputer kantor.

---

Saya (di laptop, sesi chat terpisah) sudah memperbaiki beberapa bug di file
`src/lib/parse/file-parser.ts` dan `src/app/project/[id]/page.tsx`, sudah
di-commit dan di-push ke `origin/main`. Commit terakhir yang seharusnya ada
di riwayat: `e3ebaf4 Fix stale auto-suggested roles and code columns never
refreshing`.

Masalah yang dilaporkan user: di halaman Detection (`/project/[id]`, step 3),
untuk file vendor PDF (Rinnai pricelist), dropdown **Price** ke-auto-detect
ke kolom **"Netto Zona 1 Include PPN"**, padahal seharusnya ke kolom
**"Price List PPN)"**. Ini bug lama yang menurut analisa saya (di laptop)
SEHARUSNYA sudah kefix di commit `e3ebaf4`, karena saya sudah verifikasi
langsung dengan script standalone (`parsePdf` + `analyzeColumns` dipanggil
langsung, bukan lewat browser) — hasilnya SELALU benar (Price → "Price List
PPN)"), dijalankan 2x terpisah, hasil konsisten.

Tapi user melaporkan browser di komputer kantor masih menampilkan hasil yang
salah SETELAH re-upload file vendor dari awal (project baru, bukan re-load
project lama). Ini janggal karena harusnya tidak ada stale state React kalau
project-nya baru.

## Tolong cek urutan berikut, di komputer kantor:

1. **Pastikan commit terbaru benar-benar ter-pull**:
   ```
   git log --oneline -5
   git status
   ```
   Pastikan `e3ebaf4` (atau commit yang lebih baru) ada di `git log`, dan
   `git status` bersih (tidak ada uncommitted changes yang mengganjal pull).
   Kalau belum ada, `git pull origin main` dulu.

2. **Cek proses Next.js yang sedang jalan itu `next dev` atau `next start`.**
   Ini dugaan utama saya: `package.json` punya both `npm run dev` (hot-reload
   otomatis begitu file berubah) dan `npm start` (production, HARUS di-build
   ulang manual dengan `npm run build` sebelum perubahan kode kepakai). Kalau
   yang jalan adalah `npm start` (production) dan setelah `git pull` TIDAK
   dijalankan `npm run build`, maka kode lama yang lama tetap jalan walau
   source code sudah update — persis gejala yang dilaporkan user.

   Cara cek: lihat proses yang listen di port yang dipakai (defaultnya 3000,
   tapi user akses via `10.1.37:3000` jadi mungkin custom host/port). Kalau
   pakai PowerShell:
   ```
   Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Get-Process -Id $_ }
   ```
   atau cek langsung command yang dipakai untuk start app (screen/terminal
   yang masih terbuka, atau task scheduler/pm2/service kalau di-daemon-kan).

3. **Kalau itu `npm start` (production)**: jalankan `npm run build` lalu
   restart proses `npm start`-nya. Kalau itu `npm run dev`: coba restart saja
   (`Ctrl+C` lalu `npm run dev` lagi) untuk memastikan tidak ada state Next.js
   dev server yang nyangkut, terutama kalau ada perubahan di route API
   (`src/app/api/**`) yang kadang tidak selalu ke-hot-reload sempurna.

4. **Setelah restart/rebuild**, buat project BARU di aplikasi (jangan reuse
   project lama — project lama mungkin sudah punya data upload yang di-parse
   dengan kode versi lama, tersimpan di database, dan TIDAK otomatis
   re-parse hanya karena kode berubah). Upload ulang kedua file
   (`Rinnai 3H BP (1784774419220).xlsx` sebagai internal,
   `Pricelist Rinnai 3H Zona 1 efektif 22 JULI 2026 REV signed.pdf` sebagai
   vendor), lalu screenshot halaman Detection (step 3) lagi.

5. **Kalau MASIH salah setelah semua di atas** (build fresh, project baru,
   commit terbaru ter-pull) — berarti dugaan saya (production build basi)
   SALAH, dan ini genuinely bug baru yang belum saya temukan dari laptop.
   Kalau begitu, tolong jalankan diagnosa ini di komputer kantor dan laporkan
   hasilnya balik ke saya (di laptop) untuk saya lanjutkan investigasi:

   ```
   npx tsx -e "
   import('./src/lib/parse/file-parser.ts').then(async ({ parsePdf }) => {
     const fs = await import('fs');
     const buf = fs.readFileSync('Pricelist Rinnai 3H Zona 1 efektif 22 JULI 2026 REV signed.pdf');
     const parsed = await parsePdf(buf);
     console.log(JSON.stringify(parsed.sheets[0].headers));
   });
   "
   ```
   (jalankan dari root project, pastikan kedua file PDF/xlsx ada di folder
   yang sama seperti biasanya). Kirim balik output persis apa adanya (header
   array-nya), plus hasil `git log --oneline -3` dan konfirmasi command apa
   persis yang dipakai untuk menjalankan app (`npm run dev` / `npm start` /
   lainnya).

## Konteks tambahan (kalau relevan)

Root cause ASLI dari salah-deteksi kolom Price (waktu ini masih bug) sudah
saya temukan dan fix di beberapa commit hari ini:
- `b11dab3` — kurung tutup hilang di kode produk OCR
- `16a9993` — baris tabel yang rapat (tanpa gap) tidak terpecah dengan benar
- `4747f48` — highlight kuning untuk marker "*"/"**"/"***"
- `6764d05` — angka OCR yang nyasar gabung jadi satu angka raksasa, filter baris sampah
- `e3ebaf4` — React state (dropdown role Product/Price/Code) yang nyangkut ke
  pilihan lama dan tidak ikut update walau hasil parsing membaik

Kalau butuh detail lebih dalam soal kenapa/bagaimana masing-masing bug di
atas terjadi, semua penjelasannya ada di comment sekitar kode yang diubah
(cari string comment yang menyebut "confirmed on the first real document
tested against this" di `src/lib/parse/file-parser.ts`).
