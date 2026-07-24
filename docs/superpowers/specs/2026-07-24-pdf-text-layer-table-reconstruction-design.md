# Desain: Rekonstruksi Tabel dari Posisi Asli Teks PDF (Jalur Text-Layer)

**Status:** Draft untuk review
**Tanggal:** 2026-07-24
**Terkait:** `src/lib/parse/file-parser.ts` — fungsi `parsePdf`, cabang non-OCR (`isOcr === false`)

## Latar Belakang

Price Audit membaca dua jenis PDF vendor: hasil scan (tidak ada text layer, sudah lewat jalur OCR yang diperbaiki di sesi sebelumnya) dan PDF ber-text-layer (dibuat langsung dari aplikasi seperti Excel/Word, punya teks asli yang bisa diekstrak langsung).

Survei terhadap 8 dokumen vendor nyata di folder `Data Vendor/` menunjukkan **6 dari 8 dokumen** (Miyako, Panasonic Fan, Panasonic Pump, Sanei, Sanyo Pump, Surat Penyesuaian Harga) punya text layer — jalur mayoritas, bukan jalur OCR. Jalur ini saat ini rusak parah: `parsePdf` mengekstrak teks jadi satu string flat lalu membelah tiap baris dengan regex `/\t| {2,}/` (tab atau 2+ spasi). Heuristik ini gagal total begitu PDF-nya tidak menyisipkan spasi berlebih antar kolom di stream teksnya — yang ternyata sangat umum:

- **Miyako.pdf**: header jadi `"215,000238,650182,567MCM-721 LST[ 2 ]"` — angka antar kolom nempel tanpa spasi sama sekali.
- **Panasonic Pump.pdf**: header jadi alamat kantor (`"Barat Blok A III, No. 38 -"`) — baris kop surat kepilih sebagai header karena kebetulan bentuknya "textual".
- **Sanyo Pump.pdf**, **Sanei.pdf**: pola serupa — header berisi pecahan data atau kop surat, bukan label kolom asli.

Tidak ada perbaikan pada heuristik spasi yang bisa menyelesaikan kasus Miyako/Panasonic Fan — begitu PDF-nya menyatukan angka tanpa spasi di representasi teksnya, informasi pemisah kolom sudah hilang duluan sebelum sampai ke tahap manapun yang bisa diperbaiki dari string flat.

## Solusi

`pdf-parse` (lewat pdf.js di baliknya) sebenarnya menyediakan posisi x/y persis tiap potongan teks lewat `pageData.getTextContent()` — informasi ini yang justru dibuang saat ini (cuma `.text` yang dipakai). Dikonfirmasi langsung lewat *diagnostic script* terhadap 2 dokumen nyata (Panasonic Pump, Sanei) — posisi x/y ini akurat dan cukup untuk merekonstruksi struktur tabel yang benar, jauh lebih baik daripada tebakan dari spasi.

Rencana: bangun ulang matrix tabel dari posisi x/y asli (bukan dari spasi), pakai teknik yang **sudah terbukti jalan** di jalur OCR (deteksi kolom dari celah-x via `detectColumnBoundaries`, deteksi baris dari kedekatan-posisi) — supaya konsisten dan tidak menulis ulang logika yang sudah divalidasi. Heuristik spasi yang ada sekarang **tidak dihapus**, jadi fallback kalau ekstraksi posisi gagal/degenerate.

## Arsitektur & Alur Data

```
pdf-parse (custom pagerender callback)
  → ambil semua text item PER HALAMAN (text, x, y, width — dari pdf.js langsung)
  → per halaman: cluster item jadi baris (kedekatan-y)
  → per halaman: deteksi batas kolom (reuse detectColumnBoundaries)
  → per halaman: bucket tiap baris ke kolom → matrix string[][]
  → gabung semua halaman jadi satu matrix (reuse alignBlocksToCommonColumns)
  → deteksi & gabung baris header yang wrap 2+ baris jadi 1 baris header per kolom
  → isi-maju sel kosong untuk pola baris "berjenjang" (label + sub-baris data)
  → hasil: matrix + explicitHeaders → sheetFromMatrix (SUDAH ADA, tidak diubah)

Kalau ekstraksi posisi gagal/degenerate di titik manapun di atas → fallback ke
heuristik split-by-whitespace yang berjalan hari ini.
```

Prinsip utama: hasil akhir jalur ini adalah `string[][]` + `explicitHeaders`, bentuk yang PERSIS sama dengan yang sudah diterima `sheetFromMatrix` dari jalur Excel dan jalur OCR — tidak ada pipeline baru di hilir, cuma cara membangun matrix-nya yang diganti.

## Komponen

### 1. Ekstraksi item berposisi (`extractPositionedItems`, baru)

- Panggil `pdfParse(buffer, { pagerender })` dengan callback custom yang memanggil `pageData.getTextContent({ normalizeWhitespace: false, disableCombineTextItems: true })` dan mengumpulkan tiap item (`{ text: item.str, x: item.transform[4], y: item.transform[5], width: item.width }`) ke array per halaman.
- `disableCombineTextItems: true` supaya pdf.js tidak menggabungkan item yang berdekatan secara otomatis — kita yang mengontrol pengelompokan lewat clustering sendiri, konsisten dengan cara kolom dideteksi di jalur OCR.
- Return: `PositionedWord[][]` (satu array per halaman).

### 2. Cluster baris dari posisi (`clusterRowsByPosition`, baru)

- Urutkan item per halaman berdasar Y menurun (sumbu-Y PDF naik ke atas, jadi Y tertinggi = baris teratas).
- Hitung tinggi-baris tipikal dari median selisih-Y antar kelompok item yang berdekatan (pola yang sama dengan median-based estimation yang sudah dipakai berulang di jalur OCR).
- Kelompokkan item yang selisih-Y-nya kurang dari separuh tinggi-baris-tipikal ke baris yang sama (toleransi diperlukan karena kata-kata dalam satu baris visual bisa punya Y sedikit berbeda antar font-run — dikonfirmasi langsung: `"No"` y=620.2 vs `"Product"` y=619.9 pada baris yang sama).
- Dalam satu baris, urutkan item dari X kecil ke besar.

### 3. Deteksi kolom & isi sel — reuse

- `detectColumnBoundaries(lines: PositionedWord[][])`: **dipakai langsung tanpa perubahan logika.** Fungsi ini sudah generik — hanya butuh field posisi (`x0/x1`) per kata per baris, tidak peduli sumbernya OCR atau teks-PDF-asli.
- `wordsToRow(words: PositionedWord[], boundaries: number[])`: **dipakai langsung.** Ada satu logika khusus di dalamnya (gabung 2 fragmen angka yang programmatically terpisah gara-gara OCR salah baca celah) — untuk teks-PDF-asli ini praktis tidak akan pernah terpicu (teks asli tidak pernah pecah jadi fragmen begitu), jadi aman dibiarkan apa adanya, bukan risiko baru.
- **Perubahan penamaan:** interface `OcrWord` di-rename jadi `PositionedWord` (field-nya sudah generik: `text/x0/x1/y0/y1`; field `confidence` tetap ada tapi opsional, cuma dipakai jalur OCR). Tidak ada perubahan perilaku di jalur OCR — murni rename supaya jelas dipakai bersama.

### 4. Deteksi & gabung header multi-baris (baru)

- Reuse prinsip yang sama dengan `detectSafeOcrHeader`: baris header asli tidak pernah punya sel berisi angka; baris data hampir selalu punya. Scan dari baris teratas hasil rekonstruksi, selama semua sel terisi di suatu baris itu non-angka, itu kandidat baris header; berhenti di baris pertama yang punya sel ber-angka (itu baris data pertama).
- Dari kandidat-kandidat baris header itu, **hanya baris yang langsung berdekatan dengan baris data pertama** yang digabung jadi label kolom final (gabung per-kolom, baris atas ke bawah, dipisah spasi) — menangani header yang wrap 2 baris (mis. "Nett Price" / "Exclude PPn Include PPn" jadi satu label "Nett Price Exclude PPn" per kolom). Baris-baris di atasnya (judul dokumen, tanggal periode, dll — masthead) dibuang, sama seperti masthead pada jalur OCR.
- Hasil: array label per kolom, dikirim sebagai `explicitHeaders` ke `sheetFromMatrix` (parameter yang sudah ada, sudah dipakai jalur OCR untuk keperluan yang sama).

### 5. Isi-maju sel untuk baris berjenjang (baru)

Ditemukan lewat pengecekan langsung ke `Panasonic Pump.pdf`: satu baris label produk (mis. `"1"` / `"AUTO PUMP"`, mengisi kolom No+Nama) bisa menaungi beberapa baris tipe/harga di bawahnya yang kolom No+Nama-nya kosong — pola umum PDF hasil export dari Excel dengan *merged cell*. Posisi-Y baris label ini **tidak selalu di atas** grupnya secara rapi — pada Panasonic Pump posisinya malah nyempil di antara sub-baris ke-2 dan ke-3 dari 3 baris (sisa baseline teks dari sel gabungan yang di-flatten).

Aturan yang dipakai (arah-agnostik, bukan cuma "salin ke bawah"):
1. Kelompokkan baris-baris yang berurutan **tanpa baris kosong pemisah di antaranya**.
2. Dalam satu kelompok, kalau ada TEPAT SATU baris berpola "kolom-kolom tertentu terisi, sisanya kosong" (baris label) dan satu atau lebih baris berpola KOMPLEMENTER (kolom yang kosong di baris label justru terisi di baris-baris ini, dan sebaliknya) — isi kolom yang kosong di baris-baris komplementer itu dengan nilai dari baris label, ke SEMUA baris dalam kelompok itu, tidak peduli baris label ada di posisi mana dalam kelompok.
3. Kalau kelompok tidak match pola ini (tidak ada baris label yang jelas, atau lebih dari satu), baris dibiarkan apa adanya — tidak dipaksakan.

**Contoh konkret** (data asli `Panasonic Pump.pdf`, kolom `[No, Nama, Type, Harga1, Harga2]`):

| No | Nama | Type | Harga1 | Harga2 |
|---|---|---|---|---|
| 1 | AUTO PUMP | | | |
| | | GA-126JAK-P | 573.500 | 636.585 |
| | | GA-13OJACK.P | 916.000 | 1.016.760 |
| | | GA-13OJAK-P2 | 640.000 | 770.400 |

(urutan baris di atas tampak seperti ini setelah cluster-baris — walau di file aslinya baris label `1/AUTO PUMP` posisi Y-nya nyempil di antara baris ke-2 dan ke-3, bukan di baris pertama). Baris label (No+Nama terisi, Type+Harga kosong) berdampingan tanpa baris kosong dengan 3 baris data (No+Nama kosong, Type+Harga terisi) → hasil isi-maju: ketiga baris data itu semua mendapat No=1, Nama=AUTO PUMP.

### 6. Gabung multi-halaman (reuse `alignBlocksToCommonColumns`)

- Tiap halaman diproses independen (komponen 2-3) jadi matrix per halaman.
- `alignBlocksToCommonColumns` (sudah ada, dipakai jalur OCR untuk menggabungkan beberapa blok/halaman) dipakai lagi di sini — perlakukan tiap halaman sebagai satu "blok". Fungsi ini sudah menangani penyelarasan kolom antar-blok berdasar profil isi (rasio-numerik, panjang rata-rata, rasio-terisi), bukan asumsi urutan tetap — relevan untuk dokumen panjang seperti `Sanei.pdf` (33 halaman).
- Kalau halaman ke-2 dst mengulang baris header (umum di PDF panjang bersambung) — deteksi & buang pengulangan itu pakai logika komponen 4 yang sama per halaman (baris non-angka di awal), supaya tidak ikut terhitung sebagai baris produk. Hanya header halaman pertama yang dipakai sebagai label kolom final (pola yang sama dengan jalur OCR: "only first block's header labels line up with final column indices").

### 7. Fallback ke heuristik spasi lama

Dipicu kalau:
- `extractPositionedItems` menghasilkan 0 item di semua halaman, ATAU
- Hasil `detectColumnBoundaries` degenerate (misal ≤1 kolom terdeteksi padahal ada puluhan baris berisi banyak kata — tanda posisi datanya tidak masuk akal untuk direkonstruksi).

Kalau salah satu terpicu, jalur ini melompat ke logika `split(/\t| {2,}/)` yang berjalan hari ini — perilaku hari ini jadi jaring pengaman, bukan hilang.

## Non-tujuan

- **Dokumen non-tabular** (`Surat Penyesuaian Harga 1 Juli 2026.pdf` — surat/cover letter berisi prosa) tidak dipaksa jadi tabel. Target untuk dokumen jenis ini: hasil baris/kolom minim atau kosong (karena memang tidak ada struktur tabel untuk direkonstruksi), bukan bug yang perlu dikejar. Tidak ada usaha khusus untuk "mendeteksi dokumen ini bukan tabel" di luar yang sudah didapat gratis dari tidak-ada-pola-kolom-yang-konsisten.
- Tidak mengubah jalur OCR (`ocrPdfTable`, `detectRowBands`, `extractHeaderLabels`, dll) — kecuali rename `OcrWord` → `PositionedWord` yang murni kosmetik/tipe, tanpa perubahan perilaku.
- Tidak mengubah `parseSpreadsheet` (jalur Excel/CSV).

## Rencana Uji & Validasi

1. Jalankan `parseUploadedFile` terhadap **semua 8 dokumen** di `Data Vendor/`, verifikasi manual:
   - Header berupa teks label asli yang masuk akal (bukan angka nempel atau kop surat).
   - Jumlah baris kira-kira sesuai jumlah baris produk asli (dicek visual/manual untuk beberapa dokumen).
   - Sample beberapa baris dicocokkan ke posisi mentahnya (lewat diagnostic script yang sudah dipakai selama brainstorming ini).
2. Regresi wajib nol perubahan pada:
   - Jalur OCR: `test/test-rinnai-e2e.ts` dijalankan ulang, hasil harus identik dengan sebelum perubahan ini (baris, skor, harga).
   - `test/engine-check.ts` tetap lulus.
   - `npx tsc --noEmit` bersih (kecuali error pre-existing yang tidak terkait, sudah dikonfirmasi ada di awal sesi).
3. Kasus `Surat Penyesuaian Harga...pdf`: verifikasi tidak crash, dan tidak menghasilkan kolom/header yang secara percaya diri salah (baris kosong/sedikit lebih baik daripada baris penuh tapi salah).

## Risiko & Batasan yang Diketahui

- Deteksi "baris berjenjang" (komponen 5) di-tuning berdasar SATU contoh nyata (Panasonic Pump). Pola merged-cell di vendor lain bisa berbeda bentuk (misal label di baris PERTAMA grup, bukan di tengah) — aturan arah-agnostik di desain ini seharusnya tetap menangani itu, tapi belum diuji ke dokumen dengan pola berbeda karena belum ada contoh lain di data yang tersedia.
- `detectColumnBoundaries` dan `wordsToRow` di-reuse apa adanya dari jalur OCR — keduanya sudah diverifikasi generik (tidak bergantung pada asumsi spesifik-OCR di dalam badan fungsinya), tapi belum pernah dijalankan dengan input dari sumber non-OCR sampai implementasi ini.
