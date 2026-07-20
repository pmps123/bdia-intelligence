# PRODUCT REQUIREMENT DOCUMENT (PRD)
## BDIA Intelligence

| Informasi Dokumen | Detail |
|---|---|
| **Nama Proyek** | BDIA Intelligence |
| **Deskripsi** | Alat produktivitas internal untuk Business Development Internal Auditor (BDIA) |
| **Teknologi Utama** | Next.js 15, React 19, Prisma, SQLite, TailwindCSS 4, Shadcn/UI, Python |
| **Status Dokumen** | Final |
| **Lokasi Penyimpanan** | Workspace Root |

---

## 1. PENDAHULUAN & LATAR BELAKANG
**BDIA Intelligence** dikembangkan sebagai aplikasi internal khusus bagi tim **Business Development Internal Auditor (BDIA)**. Sebelum adanya aplikasi ini, tim BDIA melakukan audit harga, rekonsiliasi data produk, dan eksekusi pipeline data secara manual menggunakan spreadsheet Excel. Proses manual tersebut memakan waktu yang lama, rentan terhadap kesalahan manusia (*human error*), serta membutuhkan keahlian teknis untuk menjalankan script Python lokal.

Aplikasi ini hadir dengan pendekatan **wizard-based** tanpa memerlukan konfigurasi teknis yang rumit dari sisi pengguna. BDIA Intelligence memfasilitasi audit harga (*Price Audit*), otomatisasi eksekusi pipeline data ke BigQuery (*Data Transform*), dan manajemen pemetaan salesman (*Salesman Mapping*).

---

## 2. TUJUAN PRODUK
* **Mengurangi Waktu Audit**: Mengotomatisasi pencocokan produk (*product matching*) dan validasi harga dari hitungan jam/hari menjadi hitungan menit.
* **Standardisasi Proses**: Menyediakan satu platform terpadu dengan standar aturan kalkulasi dan kecocokan yang konsisten.
* **Kemudahan Operasional**: Menghilangkan kebutuhan menjalankan script Python lewat terminal bagi auditor non-teknis dengan menyediakan GUI orkestrasi berbasis web.
* **Isolasi Data**: Memastikan setiap auditor memiliki ruang kerja (*workspace*) sendiri yang terisolasi untuk mengelola datanya masing-masing.

---

## 3. TARGET PENGGUNA & ISOLASI WORKSPACE
Aplikasi menggunakan sistem pembagian ruang kerja terisolasi (*workspace switcher*) yang dapat diakses di bagian pojok kiri atas sidebar. Pembagian akses fitur diatur sebagai berikut (didefinisikan di `src/lib/workspaces.ts`):

| Workspace | Nama Pengguna | Fitur yang Diaktifkan |
|---|---|---|
| `rafli` | Rafli Workspace | Price Audit, Sales Dashboard, Marketing, Salesman |
| `wijaya` | Wijaya Workspace | Price Audit, Salesman |
| `stevina` | Stevina Workspace | Price Audit |
| `juan` | Juan Workspace | *Kosong (Akan ditentukan kemudian)* |
| `vincent` | Vincent Workspace | *Kosong (Akan ditentukan kemudian)* |
| `niki` | Niki Workspace | *Kosong (Akan ditentukan kemudian)* |

---

## 4. FITUR DAN MODUL UTAMA

### 4.1 Modul 1: Price Audit (Audit Harga)
Modul ini digunakan untuk membandingkan daftar harga internal perusahaan dengan file harga yang diberikan oleh vendor/supplier, mendeteksi perbedaan harga secara otomatis, dan mengekspor hasilnya.

#### Alur Penggunaan (Wizard-Based 8 Langkah):
1. **Home (Inisialisasi Proyek)**: Pengguna memilih salah satu sumber harga internal:
   * **Price List by Product**: Daftar harga standar per produk.
   * **Basic Price**: Harga dasar sebelum penyesuaian khusus.
   * **Customized Price**: Harga khusus yang memiliki struktur aturan kuantitas pembelian (*Quantity Rules*).
2. **Upload Internal File**: Mengunggah file internal resmi perusahaan (format Excel/CSV).
3. **Upload Vendor File**: Mengunggah file penawaran/tagihan dari vendor (format Excel/CSV/PDF).
4. **Automatic Detection**: Sistem mendeteksi worksheet dan memetakan kolom secara otomatis berdasarkan statistik nama kolom (seperti mendeteksi kolom Produk, Kode, Harga, Kategori, Qty, dsb). User hanya perlu meninjau dan mengonfirmasi.
5. **Matching Otomatis (Mesin Pencocokan)**:
   * **Tokenisasi & Normalisasi**: Membersihkan teks dari karakter non-alfanumerik standar.
   * **Slash-Split Varian**: Jika terdapat nama produk dengan varian slash (misal: `EU 309 W/K`), sistem otomatis memecahnya menjadi entitas terpisah untuk dicocokkan secara individual.
   * **Fuzzy Similarity**: Menggunakan algoritma kecocokan teks berbasis kemiripan.
   * **Dynamic Thresholding**: Memakai algoritma Otsu secara dinamis untuk menentukan ambang batas keputusan *confidence score*.
6. **Review Manual**: Menyaring hasil pencocokan dengan tingkat kepercayaan sedang (*Need Review*). Pengguna dapat memilih aksi **Accept** (terima saran), **Replace** (cari kecocokan manual), atau **Skip** (abaikan).
7. **Price Validation (Validasi Harga)**:
   * Melakukan komparasi harga internal vs harga vendor yang diperbarui.
   * Menampilkan kolom hasil: *Internal Price*, *Updated Price* (Vendor Price), *Price Difference*, *% Increase*, *% Decrease*, *Matching Status*, dan *Confidence*.
   * **Quantity Rules**: Khusus untuk *Customized Price*, sistem mengevaluasi aturan gradasi kuantitas (misal: `>= 1` atau `between 5 and 9`) secara dinamis sesuai kuantitas yang diajukan vendor.
8. **Export**: Mengekspor laporan hasil audit ke Excel, CSV, atau PDF dengan kebebasan menentukan kolom mana saja yang ingin disertakan dan mengubah penamaan judul kolom.

---

### 4.2 Modul 2: Data Transform (Integrasi BigQuery)
Modul ini bertindak sebagai GUI orkestrasi untuk menjalankan script Python pemrosesan data (ETL) lokal yang kemudian mengunggah hasilnya langsung ke Google BigQuery.

#### Pembagian Halaman dan Section:
1. **Sales Dashboard (`/transform`)**: Menggabungkan 4 (empat) pipeline dengan satu "File Tray" bersama dan tombol **Run All**. Pipeline dijalankan berurutan; jika input suatu pipeline belum lengkap, pipeline tersebut otomatis dilewati (*skipped*).

| Nama Pipeline | Input yang Diperlukan | Script Python Utama | Destinasi Tabel BigQuery |
|---|---|---|---|
| **Daily Sales Performance** | Invoice, Target, Active Brand List | `daily_sales_performance.py` | `pipamas-v2.data` |
| **Monitoring Sales** | SO Summary, Invoice Summary | `monitoring_sales.py` | `pipamas-v2.data` |
| **Business Flow** | SO Summary, Packing Summary, Invoice Summary | `business_flow.py` | `pipamas-v3.data` |
| **Tracker** | Visit Plan Report | `visit_plan_tracker.py` | `pipamas-v3.data` |

2. **Marketing Dashboard (`/transform/marketing`)**: Halaman terpisah yang menjalankan script `marketing_dashboard.py` dengan input SO Summary, Target, dan Active Brand List menuju dataset `pipamas-v3.data`.

#### Ketentuan Khusus Modul Transform:
* **Deteksi Otomatis Peran File**: Peran file dideteksi otomatis berdasarkan kata kunci awal nama file dan struktur header kolom (misal: file diawali `Invoice...` akan dideteksi sebagai input Invoice). Tanggal dan ID numerik pada nama file diabaikan.
* **Tanpa Penyimpanan Permanen di Server**: Aplikasi web tidak menyimpan file hasil akhir. Hasil pemrosesan langsung dikirim oleh script Python ke Google BigQuery, sementara log progres dan status eksekusi dikirim secara live ke antarmuka web.
* **Autentikasi BigQuery**: Kredensial BigQuery diambil secara eksplisit menggunakan Service Account JSON yang didefinisikan melalui variabel lingkungan `BQ_KEY_FILE`. Default file kunci:
  * `pipamas-v3-f08db75e6c67.json` untuk proyek `pipamas-v3`.
  * `pipamas-v2-f9e3e0625182.json` untuk proyek `pipamas-v2`.
* **Executive Report (`journalism.py`)**: Aksi companion di dalam section Daily Sales Performance (bukan bagian dari "Run all" dan bukan section dashboard tersendiri). Mengolah data Invoice/Target/Active Brand List menjadi laporan eksekutif PDF + HTML beserta ringkasan WhatsApp, disimpan ke folder `reports/` dan disajikan lewat `/api/reports/[filename]`.
* **Formula Persentase Pembayaran (Cohort-based)**:
  Dalam KPI Tracking Payment, persentase pembayaran dihitung menggunakan atribusi cohort tanggal invoice induk:
  $$\text{Persentase Pembayaran} = \frac{\sum(\text{payment\_matched\_to\_invoice\_date})}{\sum(\text{invoice\_value\_on\_invoice\_date})}$$
  Jika pada periode tersebut tidak ada invoice baru, tampilkan tanda minus/kosong (`-`) dengan tooltip: *"Tidak ada invoice baru di periode ini"*.

---

### 4.3 Modul 3: Salesman Mapping (Pemetaan Salesman)
Modul untuk mengelola data master penugasan salesman, memetakan kode lama (*Legacy Code*) ke kode baru (*New Code*), serta memperbarui data NIK dan status aktif per cabang/divisi.
* **Fitur Utama**:
  * Mengunggah daftar pemetaan salesman dari Excel.
  * Tabel interaktif (*Table Editor*) untuk mengedit data secara langsung di UI.
  * Sinkronisasi data dinamis dan penyimpanan otomatis menggunakan debounced callback.
  * Penyaringan data (*filtering*) berdasarkan bulan kerja.
  * Penandaan baris yang membutuhkan perhatian (*needsReview*) apabila terdapat duplikasi kode lama yang tidak dapat diselesaikan otomatis saat impor.

---

### 4.4 Modul 4: Notes
Halaman catatan berbasis blok (text, heading, bullet, table, image) per workspace, dapat di-reorder, tersimpan sebagai `Block`/`Note`.

### 4.5 Modul 5: Chat AI
Asisten chat per workspace (halaman `workspace`) yang terhubung ke model AI via OpenRouter (`src/lib/chat/`). System prompt disuntik konteks ringkas workspace (`buildWorkspaceContext`) agar jawaban relevan dengan data auditor tersebut. Riwayat percakapan (`ChatMessage`) tersimpan per workspace dan bisa dihapus penuh oleh user. Jika seluruh model AI gagal merespons, sistem tetap menyimpan pesan error sebagai balasan assistant (tidak silent-fail).

---

## 5. SPESIFIKASI TEKNOLOGI & ARSITEKTUR

### Frontend & Backend Framework
* **Framework**: Next.js 15 (App Router)
* **Library UI**: React 19, Shadcn/UI, Lucide React (ikon)
* **Styling**: TailwindCSS 4, CSS Variables untuk desain ledger
* **Database Client**: Prisma ORM

### File Processing & Exporter
* **Excel Parsing**: SheetJS (`xlsx`)
* **PDF Parsing**: `pdf-parse`
* **Excel Export**: `exceljs`
* **PDF Export**: `jspdf`, `jspdf-autotable`

### Runtime Python & Data Science
* **Interpreter**: Python 3 (dapat dikustomisasi via env `PYTHON_BIN`)
* **Library Python**: `pandas`, `numpy`, `polars`, `fastexcel`, `openpyxl`, `pyarrow`, `db-dtypes`, `google-cloud-bigquery`, `pandas-gbq`

---

## 6. DETAIL SKEMA BASIS DATA (Prisma Schema)
Database yang digunakan adalah **SQLite**. Berikut penjelasan model data utama:

* **Project**: Menyimpan metadata audit harga per workspace beserta status langkah aktif wizard (`step`).
* **Upload**: Menyimpan informasi metadata file yang diunggah oleh user (nama file, tipe, ukuran, jalur penyimpanan).
* **Worksheet**: Representasi dari tab lembar kerja di dalam file Excel yang diunggah.
* **Dataset**: Kumpulan baris data hasil ekstraksi dari file upload, terbagi menjadi jenis `VENDOR` atau `INTERNAL`.
* **DataRow**: Representasi baris individual dari dataset, lengkap dengan hasil normalisasi nama, token kata, kode produk, dan rentang kuantitas (`qtyMin`, `qtyMax`).
* **MatchSession**: Menyimpan sesi proses pencocokan harga antara dataset internal dan dataset vendor.
* **MatchResult**: Menyimpan hasil pemetaan baris demi baris beserta nilai kecocokan (*score* dan *confidence*) dan status pencocokan (`MATCHED`, `PARTIAL`, `NEED_REVIEW`, `UNMATCHED`).
* **MasterMapping**: Tabel referensi belajar sistem untuk merekam pencocokan manual yang pernah disetujui agar dapat otomatis diterapkan pada proyek berikutnya.
* **PriceValidationRun & PriceValidationItem**: Merekam hasil evaluasi perbandingan harga akhir, selisih persentase kenaikan/penurunan harga, dan status deviasi harga.
* **TransformRun**: Melacak eksekusi pipeline data transform Python beserta rekaman log live yang dihasilkan.
* **SalesmanRow**: Menyimpan data pemetaan kode salesman dan status keaktifan per cabang dan bulan.
* **Block & Note**: Struktur data pendukung untuk membuat catatan berbasis blok teks atau tabel di dalam workspace.
* **ChatMessage**: Riwayat percakapan Chat AI per workspace, termasuk model AI (OpenRouter) yang menghasilkan tiap balasan.
* **Job**: Pelacakan generik untuk proses async berdurasi panjang di luar `TransformRun` (status, progress, result).

---

## 7. IDENTITAS VISUAL & DESIGN SYSTEM
Desain visual mengusung tema **"Ledger"** yang merepresentasikan antarmuka bersih khas kertas kerja auditor keuangan.
* **Warna Dasar**: Monokrom hitam dan putih (`#0A0A0A` / `#FAFAFA`).
* **Warna Aksen**: Amber gelap (`#B8894F`) yang digunakan secara minimalis dan eksklusif hanya untuk tombol aksi utama (CTA), indikator aktif, dan elemen visual khas *ledger rule / ledger tick* (garis dekoratif pena emas).
* **Warna Status**: Dibuat tenang dan tidak jenuh (*muted*):
  * Sukses/Baik: `--status-good` (`#4C7A5C`)
  * Gagal/Peringatan: `--status-bad` (`#A8524C`)
* **Tipografi**: Inter sebagai font utama pembacaan teks (*body font*) dan Space Grotesk sebagai font penampang judul (*display font*). Tampilan angka finansial wajib menggunakan font berfitur `tabular-nums` agar presisi saat disejajarkan ke bawah.

---

## 8. KEBUTUHAN NON-FUNGSIONAL (NFR)
1. **Keamanan**: Kunci Service Account Google Cloud Platform tidak boleh disimpan atau dikomit ke repositori git. Kredensial wajib diletakkan di environment lokal atau file JSON eksternal yang diabaikan oleh `.gitignore`.
2. **Kinerja Engine**: Pengolahan data berbasis Python menggunakan library berkinerja tinggi seperti `polars` dan `pyarrow` guna meminimalkan penggunaan memori server ketika memproses data transaksi bervolume besar.
3. **Responsivitas**: Eksekusi pipeline Python dijalankan secara asinkron di latar belakang menggunakan child-process sehingga server web Next.js tetap responsif melayani permintaan pengguna lain ketika pipeline berjalan.
4. **Validitas Data**: Persentase toleransi perbedaan harga harus dapat diatur secara dinamis per sesi validasi untuk mengakomodasi fluktuasi nilai tukar atau margin toleransi audit yang disetujui.
