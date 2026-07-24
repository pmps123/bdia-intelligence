# Prompt untuk Claude Code (komputer kantor)

Copy-paste blok di bawah ini ke Claude Code di komputer kantor. Ada 2 bagian:
**Bagian A** (cek bug spesifik) dan **Bagian B** (audit kualitas menyeluruh).
Kerjakan A dulu, baru B.

---

## Bagian A — cek: kadang nama kolom vendor tidak tertangkap

Konteks: saya (di laptop, sesi chat terpisah) sudah memperbaiki beberapa bug
parsing PDF vendor di `src/lib/parse/file-parser.ts`, sudah di-commit dan
di-push ke `origin/main`. Commit terakhir yang seharusnya ada di riwayat:
cek dengan `git log --oneline -8`, cari `Add handoff doc for diagnosing
stale Detection-step Price role on desktop` sebagai commit paling atas.

**Catatan penting (koreksi dari user):** dropdown Price yang ke-auto-detect
ke kolom "Netto" alih-alih "Price List" BUKAN masalah — itu tetap bisa
dipilih manual, tidak masalah. **Yang jadi masalah sebenarnya**: kadang nama
kolom vendor (header) itu sendiri tidak tertangkap sama sekali — muncul
sebagai "Column 1" / "Column 2" generik, bukan teks asli seperti "Price
List" / "Netto Zona 1 Include PPN". Ini soal keandalan ekstraksi header dari
OCR, bukan soal pemilihan role.

### Kenapa ini bisa terjadi (dugaan saya)

Header vendor PDF (misal "BUILT-IN HOB" / "COOKER HOOD" / "Price List" /
"Netto Zona 1") dibaca lewat OCR (`extractHeaderLabels` di
`file-parser.ts`), dan sepanjang sesi ini saya sudah beberapa kali konfirmasi
langsung bahwa **Tesseract.js OCR TIDAK deterministik antar proses** — crop
gambar yang persis sama bisa memberi hasil pembacaan berbeda kalau
dijalankan di proses Node terpisah (walau identik kalau diulang dalam proses
yang sama). Jadi kemungkinan besar: kadang OCR gagal membaca teks header sama
sekali di region itu pada RUN tertentu, sehingga `extractHeaderLabels`
mengembalikan `null`/kosong, dan sistem fallback ke nama generik "Column N".

### Yang perlu dicek/reproduksi

1. Pastikan sudah di commit terbaru (`git pull origin main`), dan app
   sudah di-restart/rebuild kalau perlu (lihat catatan dev vs production
   build di bawah).
2. Jalankan parsing PDF vendor **berkali-kali berturut-turut** (minimal
   5x) dari script standalone, dan catat apakah header yang dihasilkan
   BERUBAH-UBAH antar run (bukti langsung non-determinism OCR):
   ```
   for /l %i in (1,1,5) do npx tsx -e "import('./src/lib/parse/file-parser.ts').then(async ({parsePdf}) => { const fs=await import('fs'); const buf=fs.readFileSync('Pricelist Rinnai 3H Zona 1 efektif 22 JULI 2026 REV signed.pdf'); const p=await parsePdf(buf); console.log(JSON.stringify(p.sheets[0].headers)); });"
   ```
   (kalau `for /l` tidak jalan di shell yang dipakai, jalankan manual 5x
   berturut-turut saja, satu-satu, catat outputnya).
3. Kalau memang headernya berubah-ubah / kadang jadi "Column N" generik:
   telusuri `extractHeaderLabels` dan `detectRowBands` di
   `src/lib/parse/file-parser.ts` — cari titik di mana OCR pass untuk
   region header bisa gagal total (mengembalikan 0 kata / confidence
   terlalu rendah semua) dan pertimbangkan retry tambahan (mirip pola retry
   scale 6x→4x yang sudah ada untuk row band biasa) khusus untuk header
   region, atau turunkan sedikit ambang confidence khusus di situ, atau
   tambah percobaan di scale lain sebelum menyerah ke fallback generik.
4. **Sebelum ubah kode**, tulis dulu satu paragraf ringkas: apa akar
   masalah yang ditemukan (bukan cuma gejalanya), baru implementasikan
   fix paling sederhana yang menyelesaikan akar itu.

### Cek dev vs production build (kalau proses A ini butuh restart app)

`package.json` punya `npm run dev` (hot-reload otomatis) dan `npm start`
(production, **butuh** `npm run build` manual setelah `git pull` sebelum
perubahan kode kepakai). Cek command apa yang sedang jalan untuk app ini;
kalau `npm start`, jalankan `npm run build` dulu sebelum restart.

---

## Bagian B — audit kualitas: seberapa kompeten tool Price Audit ini?

User minta evaluasi menyeluruh: **seberapa hebat/kompeten project ini untuk
Price Audit**, dan apakah ada yang bisa ditingkatkan supaya proses matching
produk (vendor ↔ internal) makin akurat — **khususnya saat data vendor
berbentuk PDF** (jalur OCR, bukan Excel/CSV yang datanya sudah bersih).

Lakukan audit ini dengan membaca kode dan (kalau memungkinkan) menjalankan
uji nyata terhadap data yang ada di repo ini (`Pricelist Rinnai 3H Zona 1
efektif 22 JULI 2026 REV signed.pdf` sebagai vendor, `Rinnai 3H BP
(1784774419220).xlsx` sebagai internal — sudah ada di root project). Fokus
area yang perlu dinilai:

1. **Akurasi ekstraksi PDF vendor** (`src/lib/parse/file-parser.ts`):
   seberapa lengkap & akurat baris/kolom yang ter-ekstrak dibanding isi PDF
   aslinya? Cek langsung: bandingkan jumlah baris yang berhasil di-parse vs
   jumlah produk asli di PDF (buka PDF-nya, hitung manual atau screenshot),
   dan cek beberapa baris acak apakah kode produk & harganya cocok persis.
2. **Kualitas fuzzy matching** (`src/lib/engine/matching.ts`,
   `src/lib/engine/tokens.ts`, `src/lib/engine/similarity.ts`): dari
   produk vendor yang berhasil ter-ekstrak, berapa persen yang match ke
   produk internal dengan skor tinggi (MATCHED) vs butuh review manual vs
   sama sekali tidak match? Apakah ada pola kegagalan match yang jelas
   (misal: kode dengan banyak varian warna/ukuran digabung satu baris vendor
   tapi terpisah banyak baris di internal — apakah sudah ditangani?).
3. **Ketahanan terhadap noise OCR**: apakah sistem sudah cukup baik
   membedakan baris data asli vs sampah OCR (tanda tangan, garis border
   misbaca, dll)? Apakah ada baris yang seharusnya produk asli malah
   ter-filter sebagai sampah (over-filtering), atau sebaliknya sampah yang
   lolos jadi baris data?
4. **Generalisasi ke vendor lain**: banyak logic saat ini (row-band
   detection, column boundary detection, threshold-threshold seperti
   `typical * 1.5`, minimum 100 untuk angka valid, dsb) di-tuning berdasar
   SATU dokumen PDF Rinnai ini. Apakah ada asumsi yang terlalu spesifik ke
   layout PDF ini yang berisiko gagal total di vendor lain dengan layout
   PDF berbeda (kolom lebih banyak, tanpa tabel bergaris, font/scan quality
   beda, dll)?
5. **Rekomendasi konkret**: dari semua temuan di atas, susun daftar
   perbaikan yang paling berdampak untuk kemampuan matching produk PDF,
   diurutkan dari yang paling penting. Untuk masing-masing, sebutkan: apa
   masalahnya, kenapa itu penting untuk price audit, dan kira-kira seberapa
   besar effort untuk memperbaikinya (kecil/sedang/besar).

Laporkan hasilnya sebagai ringkasan poin-poin (skor/penilaian per area di
atas + daftar rekomendasi terurut), bukan dokumen panjang. Kalau ada
temuan yang butuh keputusan/prioritas dari user, tanyakan sebelum langsung
mengubah kode secara besar-besaran.
