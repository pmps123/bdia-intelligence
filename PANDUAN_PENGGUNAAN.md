# Panduan Penggunaan — BDIA Intelligence

Panduan ini untuk **pengguna** (auditor/tim internal), bukan developer — untuk detail teknis/setup lihat [README.md](README.md). Istilah tombol/label ditulis persis seperti di layar (dalam bahasa Inggris, karena UI aplikasi berbahasa Inggris), penjelasannya dalam bahasa Indonesia.

Aplikasi punya dua modul, keduanya wizard tanpa perlu konfigurasi teknis:

1. **Price Audit** — cocokkan produk vendor dengan data internal & validasi perubahan harga.
2. **Data Transform** (Sales Dashboard + Marketing) — jalankan pipeline pelaporan yang sudah ada.

Tool mana yang tampil tergantung **workspace** yang dipilih di pojok kiri atas sidebar (switcher workspace) — tidak semua workspace punya semua tool.

---

## Modul 1 — Price Audit

Alur kerja: **Home → Upload internal file → Upload vendor file → Automatic detection → Review matching → Price validation → Export**. Progres tersimpan otomatis; kembali ke halaman project kapan saja untuk melanjutkan dari step terakhir (stepper di atas menandai step mana yang sudah dilewati — klik untuk kembali ke step itu).

### 1. Mulai audit baru (Home)

Di halaman utama:
- Pilih **sumber harga internal**: `Price List by Product`, `Basic Price`, atau `Customized Price`. Pilihan ini menentukan kolom harga mana yang jadi acuan pembanding sepanjang audit.
- Isi nama audit (mis. `"Panasonic July 2026"`), lalu klik **New audit**.
- Daftar **Recent audits** menampilkan semua audit yang pernah dibuat di workspace ini, dengan status step terakhirnya — klik baris mana pun untuk melanjutkan. Ikon tempat sampah (muncul saat hover) untuk menghapus audit.

### 2–3. Upload internal file & vendor file

Dua step upload terpisah, formatnya sama:
- Drag-and-drop file atau klik **Choose file** (atau **Replace file** kalau sudah pernah upload). Format yang didukung: **Excel (.xlsx/.xls), CSV, atau PDF**.
- File PDF (misalnya price list vendor yang di-scan atau di-export sebagai PDF) diproses lewat ekstraksi tabel otomatis — termasuk OCR kalau PDF-nya hasil scan tanpa lapisan teks. Sistem membuang teks di luar tabel (judul, footnote) dan menyatukan tabel yang terpotong jadi beberapa bagian di halaman yang sama (pola umum di price list vendor: satu daftar dipecah jadi 2 kolom cetak karena keterbatasan panjang halaman).
- Tidak perlu menyusun ulang kolom sebelum upload — worksheet & kolom apa pun akan dideteksi otomatis di step berikutnya.

### 4. Automatic detection

Sistem mendeteksi otomatis (berdasarkan **statistik isi data**, bukan nama kolom — jadi berlaku untuk sheet apa pun):
- **Worksheet** mana yang paling relevan (kalau file punya beberapa sheet) — ditandai "— suggested".
- Kolom mana yang berperan sebagai **Product** (wajib, ditandai `*`), **Price**, **Code**, **Category**, **Qty** — dan untuk sumber `Customized Price`, tambahan **Qty Rule / Qty From / Qty To** (aturan gradasi kuantitas, dibaca dinamis dari isi file, bukan aturan tetap).
- Kalau deteksi otomatis salah, ganti manual lewat dropdown masing-masing kolom (isi "— not present —" kalau kolom itu memang tidak ada di file).
- Setelah kedua sisi (internal & vendor) dikonfirmasi, klik **Match products automatically** untuk menjalankan proses matching (ada progress bar).

### 5. Review matching

Hanya baris yang **tidak pasti** yang perlu ditinjau manual — baris yang otomatis MATCHED dengan confidence tinggi tidak ditampilkan di sini (ditandai badge "✓ N matched automatically" di atas).

Untuk tiap baris yang perlu ditinjau, ada 3 aksi:
- **Accept** — setujui saran produk internal yang ditampilkan.
- **Replace** — buka dialog pencarian untuk memilih produk internal yang benar secara manual (bisa cari nama produk langsung).
- **Skip** — sembunyikan sementara dari daftar "perlu ditinjau" di sesi ini (hanya di layar, tidak tersimpan) — kalau halaman di-refresh, baris itu akan muncul lagi di daftar review.

Bar hijau/kuning/merah di samping tiap baris menunjukkan confidence skor matching (hijau ≥70%, kuning ≥40%, merah di bawah itu).

**Penting:** setiap kali Anda **Accept**/**Replace** manual, pasangan vendor↔internal itu otomatis "diingat" (Master Mapping) dan akan dipakai langsung di audit berikutnya untuk vendor yang sama — bahkan kalau kode produknya cocok tapi tulisan namanya sedikit berbeda dari sebelumnya (reformatting spasi, tambahan suffix, dsb). Jadi semakin sering dipakai untuk satu vendor, semakin sedikit yang perlu ditinjau manual dari waktu ke waktu.

Klik **Validate prices** untuk lanjut setelah semua baris penting sudah diputuskan (baris yang di-Skip tetap boleh dilanjutkan).

### 6. Price validation

Tabel penuh berisi **setiap** baris — hasil gabungan penuh (*full outer join*) antara data vendor dan data internal, bukan cuma yang ter-match:

| Kolom | Arti |
|---|---|
| Vendor Product / Internal Product | Nama produk masing-masing sisi |
| Vendor Price / Internal Price | Harga masing-masing sisi (Internal Price mengikuti sumber harga yang dipilih di awal) |
| Updated Price | Selalu sama dengan Vendor Price (harga yang diusulkan menggantikan Internal Price) |
| Price Difference | Vendor Price − Internal Price |
| % Increase / % Decrease | Persentase kenaikan/penurunan (hanya salah satu yang terisi per baris) |
| Status | `Same` / `Higher` / `Lower` / `Missing` (kalau salah satu sisi harganya kosong) / `Tidak ada di internal` (vendor punya produk ini tapi internal tidak) / `Tidak ada kenaikan harga` (internal punya produk ini tapi vendor tidak menawarkannya di price list ini) |
| Matching | Status pencocokan produk (`MATCHED`/`PARTIAL`/`MANUAL`/dst.) |
| Confidence | Skor keyakinan pencocokan produk |

Gunakan kolom pencarian di kanan atas untuk memfilter, atau **Re-validate** kalau ada perubahan matching setelah tabel ini pertama kali dibuat. Klik **Continue to export** untuk lanjut.

### 7. Export

- Pilih format: **Excel (.xlsx)**, **CSV**, atau **PDF**.
- Centang/hilangkan kolom yang mau disertakan, dan ubah judul kolomnya kalau perlu (mis. judul kolom harga otomatis menyertakan nama sumber harga yang dipilih, misal "Internal Price (Basic Price)").
- Klik **Export XLSX/CSV/PDF** untuk mengunduh file hasil akhirnya.

#### Yang perlu diketahui soal file Excel hasil export

Beberapa hal ini dibuat khusus supaya auditor bisa langsung bekerja dari file yang diunduh, tanpa perlu menyusun ulang:

- **Kolom "Vendor Product" selalu merah** (background merah) di setiap baris — supaya gampang di-scan visual, sesuai kode + nama produk internal yang benar-benar match (bukan nama generik yang sama untuk semua baris).
- **Baris jadi merah semua** kalau: (a) kode produk vendor mengandung tanda `*` atau `**` — banyak vendor menandai baris kenaikan harga sendiri dengan cara ini di price list mereka, atau (b) sistem menghitung sendiri perubahan harga baris itu **ekstrem** (lebih dari ±80%) — ini ditandai di kolom **"Price Alert"** dengan teks "Cek Manual - Perubahan Ekstrem", terlepas dari seberapa yakin sistem pada pencocokan produknya. Kombinasi keduanya membantu auditor langsung fokus ke baris yang paling berisiko salah atau paling perlu divalidasi manual.
- **Kolom kode internal otomatis** (mis. "Prod. Variant Code", "Alias Code", "SKU" — apa pun namanya di file internal Anda) ikut disertakan di export, diisi sesuai baris internal yang benar-benar match — jadi tidak perlu buka file internal lagi untuk cek kode resminya.
- **"Match Source"** menunjukkan asal keputusan pencocokan: `MASTER` (diingat dari koreksi manual Anda di audit sebelumnya), `AI` (divalidasi AI karena skor fuzzy-nya ambigu), `ENGINE` (murni skor kemiripan otomatis), `MANUAL` (Anda putuskan sendiri di step Review).
- **"Match Note"** — saat AI yang memutuskan (kasus ambigu), kolom ini berisi alasan singkatnya (mis. "variant suffix differs"), jadi tidak perlu menebak kenapa suatu baris di-flag.
- Header tabel di baris atas **dibekukan** (freeze pane, tetap terlihat saat scroll) dan sudah aktif **autofilter**-nya.

---

## Modul 2 — Data Transform

Untuk workspace yang punya tool ini (link "Sales Dashboard" muncul di bawah tabel audit di Home). Ringkasnya (detail lengkap ada di [README.md](README.md)):

- **Sales Dashboard** (`/transform`) — upload beberapa file sekaligus ke satu "file tray" bersama, perannya (Invoice/Target/SO/dst.) dideteksi otomatis dari nama file & isi worksheet. Section yang datanya lengkap otomatis bisa dijalankan; klik **Run all** untuk menjalankan semua section berurutan dalam satu proses, dengan log live per section.
- **Marketing** (`/transform/marketing`) — pipeline terpisah dengan alur upload → run → log yang sama.
- Tidak ada file hasil yang disimpan di server — hasil akhirnya masuk ke Google BigQuery, log prosesnya tampil live di layar.

---

## Tips penggunaan untuk auditor

1. **Cek baris merah dulu** di file Excel hasil export — itu prioritas tertinggi (tanda `*` vendor atau perubahan harga ekstrem).
2. **Kalau ragu di step Review, pakai Replace** daripada Accept sembarangan — begitu dikoreksi manual sekali, sistem akan mengingatnya untuk vendor yang sama di audit-audit berikutnya (Master Mapping), jadi koreksi Anda hari ini mengurangi pekerjaan Anda ke depan.
3. **Kolom "Match Note" adalah tempat pertama untuk cek "kenapa"** kalau suatu pencocokan terlihat aneh tapi statusnya MATCHED — kalau kosong, berarti itu bukan hasil validasi AI (murni skor otomatis atau data dari Master Mapping).
4. Untuk vendor yang datanya berupa **PDF hasil scan**, kualitas ekstraksi bergantung pada ketajaman scan aslinya — kalau ada kode/angka yang terbaca aneh, itu biasanya batasan resolusi scan, bukan bug logika; bandingkan langsung ke PDF asli untuk baris yang mencurigakan.
