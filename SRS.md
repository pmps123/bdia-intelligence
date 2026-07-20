# SOFTWARE REQUIREMENTS SPECIFICATION (SRS)
## BDIA Intelligence

| Info | Detail |
|---|---|
| **Versi Dokumen** | 1.0 |
| **Berlaku untuk** | Codebase per 2026-07-20 |
| **Dokumen terkait** | [PRD.md](PRD.md) (kebutuhan produk), [README.md](README.md) (cara jalan), [project_memory.md](project_memory.md) (keputusan & histori) |

---

## 1. RUANG LINGKUP
BDIA Intelligence adalah aplikasi web internal (Next.js, single-instance, tanpa multi-tenant auth) yang mengorkestrasi dua kelas pekerjaan yang sebelumnya manual:
1. **Price Audit** — pencocokan & validasi harga internal vs vendor.
2. **Data Transform** — eksekusi pipeline Python lokal (ETL) yang menulis ke BigQuery, plus pembuatan laporan eksekutif (PDF/WhatsApp) dan asisten chat AI per workspace.

Di luar cakupan: autentikasi multi-user (workspace bukan akun berpassword — hanya switcher), deployment cloud/container, mobile app.

---

## 2. ARSITEKTUR SISTEM

```
Browser (React 19 / Next.js App Router)
   │
   ├─ Price Audit wizard  → /api/projects, /api/matching, /api/export  → SQLite (Prisma)
   ├─ Data Transform      → /api/transform/*  → child_process spawn python scripts/*.py → BigQuery
   ├─ Notes               → /api/notes, /api/blocks → SQLite
   ├─ Chat AI              → /api/chat → OpenRouter API → SQLite (ChatMessage)
   └─ Reports              → /api/reports/[filename] → serves reports/*.pdf|html|txt (filesystem)
```

- **Web app**: tidak menjalankan business logic data — hanya upload, deteksi, orkestrasi proses, dan tampilan hasil/log.
- **Python scripts** (`scripts/*.py`): sumber kebenaran business logic ETL & reporting. Menerima path file via argumen CLI, menulis progres ke stdout (di-poll/stream ke UI), menulis hasil ke BigQuery, dan (untuk `journalism.py`) file laporan ke `reports/`.
- **Database**: SQLite lokal via Prisma (`prisma/schema.prisma`), file DB tidak untuk multi-instance/concurrent write tinggi — cukup untuk pemakaian internal 6 workspace.
- **BigQuery**: dua GCP project berbeda (`pipamas-v2`, `pipamas-v3`) tergantung script, tiap script memuat service-account key eksplisit (tidak pakai ADC/gcloud).

---

## 3. MODUL & REQUIREMENT FUNGSIONAL

### 3.1 Price Audit
| ID | Requirement |
|---|---|
| FR-PA-01 | Sistem harus mendukung 3 sumber harga internal: Price List by Product, Basic Price, Customized Price (dengan Quantity Rules). |
| FR-PA-02 | Sistem harus menerima upload file internal & vendor dalam format Excel (.xlsx/.xls), CSV, dan PDF (vendor only). |
| FR-PA-03 | Sistem harus mendeteksi worksheet & mapping kolom (Produk, Kode, Harga, Kategori, Qty, Qty Rule/From/To) secara otomatis dari statistik konten, dengan opsi user mengonfirmasi/mengoreksi. |
| FR-PA-04 | Engine matching harus melakukan: normalisasi teks, tokenisasi, slash-split varian (mis. `EU 309 W/K` → 2 entitas), fuzzy similarity, dan thresholding dinamis (Otsu) untuk confidence. |
| FR-PA-05 | Hasil match dengan confidence menengah harus difilter ke tahap Review Manual dengan aksi Accept / Replace / Skip. |
| FR-PA-06 | Master mapping (`MasterMapping`) yang disetujui manual harus disimpan agar otomatis diterapkan pada project berikutnya (per vendor). |
| FR-PA-07 | Price validation harus menghitung Price Difference, %Increase, %Decrease, Matching Status, Confidence, dengan toleransi persentase yang dapat diatur per sesi (`tolerancePct`). |
| FR-PA-08 | Untuk Customized Price, validasi harus memilih baris referensi berdasarkan qty vendor terhadap rentang `qtyMin`/`qtyMax` yang di-parse dinamis dari file. |
| FR-PA-09 | Export hasil ke Excel, CSV, PDF dengan pemilihan kolom & rename judul kolom oleh user. |
| FR-PA-10 | Setiap Project terisolasi per `workspace` — user di satu workspace tidak melihat project workspace lain. |

### 3.2 Data Transform
| ID | Requirement |
|---|---|
| FR-DT-01 | Sales Dashboard (`/transform`) harus menjalankan 4 pipeline (Daily Sales Performance, Monitoring Sales, Business Flow, Tracker) via satu file tray & tombol "Run all", berurutan, dengan section yang input-nya belum lengkap ditandai *skipped* otomatis. |
| FR-DT-02 | Peran tiap file upload harus dideteksi otomatis dari keyword awal nama file + struktur header, mengabaikan tanggal/ID numerik di nama file. |
| FR-DT-03 | Tiap pipeline dijalankan sebagai child-process Python terpisah; status per section harus salah satu dari PENDING/RUNNING/COMPLETED/FAILED/SKIPPED, dengan log live yang di-stream/poll ke UI (`TransformRun.log`). |
| FR-DT-04 | Marketing Dashboard (`/transform/marketing`) berjalan sebagai halaman & section terpisah dari Sales Dashboard. |
| FR-DT-05 | Executive Report (`journalism.py`) adalah aksi companion di dalam section Daily Sales Performance (bukan bagian dari "Run all"), menghasilkan PDF + HTML + ringkasan WhatsApp ke folder `reports/`, disajikan lewat `/api/reports/[filename]`. |
| FR-DT-06 | Tidak ada file hasil pipeline yang disimpan permanen oleh web app selain artefak laporan `journalism.py`; data tabular hasil ETL hanya berakhir di BigQuery. |
| FR-DT-07 | Destinasi BigQuery per script tetap (lihat §5) dan kredensial harus dimuat eksplisit via `BQ_KEY_FILE`/`BQ_PROJECT_ID` per proses, tidak pernah di-hardcode di source maupun di-set global di `.env`. |
| FR-DT-08 | KPI "Persentase Pembayaran" wajib pakai atribusi cohort tanggal invoice induk (lihat formula di PRD §4.2), bukan rasio total_payment sederhana. |

### 3.3 Salesman Mapping
| ID | Requirement |
|---|---|
| FR-SM-01 | Import mapping salesman dari Excel dengan pemetaan Legacy Code → New Code, per cabang/divisi/bulan. |
| FR-SM-02 | Re-import tidak boleh menimpa baris existing (`source: IMPORT` vs `MANUAL`); duplikasi Legacy Code yang tak terselesaikan otomatis ditandai `needsReview`. |
| FR-SM-03 | Tabel harus dapat diedit langsung di UI dengan autosave (debounced) dan filter per bulan kerja. |

### 3.4 Notes & Workspace Pages
| ID | Requirement |
|---|---|
| FR-NT-01 | Tiap workspace punya halaman Notes (`Block`/`Note` model) berbasis blok: text, heading, bullet, table, image — dapat di-reorder. |
| FR-NT-02 | Konten note tersimpan sebagai JSON per tipe blok dan terisolasi per `workspace`. |

### 3.5 Chat AI
| ID | Requirement |
|---|---|
| FR-CH-01 | Tiap workspace punya riwayat chat sendiri (`ChatMessage`), dikirim ke model AI via OpenRouter dengan system prompt + konteks workspace (`buildWorkspaceContext`) + hingga 30 pesan riwayat terakhir. |
| FR-CH-02 | Kegagalan semua model AI harus menghasilkan pesan error yang tetap tersimpan sebagai balasan assistant (bukan silent failure / 500 ke user). |
| FR-CH-03 | User dapat menghapus seluruh riwayat chat per workspace. |

---

## 4. KEBUTUHAN NON-FUNGSIONAL

| ID | Kategori | Requirement |
|---|---|---|
| NFR-01 | Keamanan | Service-account JSON & API key (OpenRouter, dsb.) tidak boleh dikomit; wajib di `.gitignore`. Tidak ada auth per-user — batas akses hanya isolasi workspace via `workspace` param, bukan kontrol keamanan sebenarnya (asumsi: jaringan internal tepercaya). |
| NFR-02 | Kinerja | Pemrosesan data besar memakai `polars`/`pyarrow`, bukan pandas murni, untuk menekan memori. Pipeline berjalan sebagai proses async (child_process) agar server Next.js tetap responsif. |
| NFR-03 | Reliabilitas | Section yang gagal (FAILED) tidak menghentikan section lain dalam "Run all"; tiap section independen. |
| NFR-04 | Portabilitas | Tidak ada nama sheet/kolom/vendor/produk/filename/GCP project ID yang di-hardcode di kode aplikasi — semua dideteksi dari file atau env var. |
| NFR-05 | Skalabilitas data | SQLite cukup untuk skala pemakaian internal (6 workspace, single-instance); bukan untuk concurrent write tinggi atau multi-server. |
| NFR-06 | Ketertelusuran | Setiap `TransformRun` menyimpan log lengkap eksekusi untuk audit/debug ulang. |

---

## 5. INTERFACE EKSTERNAL

| Sistem | Arah | Detail |
|---|---|---|
| Google BigQuery `pipamas-v2` | Tulis | `daily_sales_performance.py`, `monitoring_sales.py` → dataset `data`, key `pipamas-v2-f9e3e0625182.json` |
| Google BigQuery `pipamas-v3` | Tulis | `business_flow.py`, `marketing_dashboard.py`, `visit_plan_tracker.py`, `journalism.py` (baca) → dataset `data`, key `pipamas-v3-f08db75e6c67.json` |
| OpenRouter API | Baca/Tulis | Chat completion untuk fitur Chat AI (`src/lib/chat/openrouter.ts`) |
| Filesystem lokal `reports/` | Tulis/Baca | Artefak `journalism.py`: `*.pdf`, `*.html`, `WhatsApp_Executive_Summary_*.txt`, disajikan via `/api/reports/[filename]` |
| Python interpreter | Proses | Dipanggil via `child_process`, path dikustomisasi lewat env `PYTHON_BIN` |

---

## 6. MODEL DATA
Lihat `prisma/schema.prisma` sebagai sumber kebenaran. Ringkasan model & tujuan ada di PRD §6. Model tambahan di luar PRD saat ini: `Block`, `Note` (halaman Notes per workspace), `ChatMessage` (riwayat Chat AI), `Job` (job generik async — status/progress/result, dipakai untuk proses panjang di luar TransformRun, mis. journalism report).

---

## 7. KONSTRAIN & ASUMSI
- Aplikasi berjalan single-instance di mesin lokal/internal; tidak didesain untuk deployment multi-region atau horizontal scaling.
- Python 3 dan seluruh dependensi (`pandas`, `numpy`, `polars`, `fastexcel`, `openpyxl`, `pyarrow`, `db-dtypes`, `google-cloud-bigquery`, `pandas-gbq`, `weasyprint` untuk journalism) harus terpasang di mesin yang menjalankan `npm start`.
- Workspace bukan mekanisme keamanan — siapa pun yang mengakses URL app bisa switch workspace. Isolasi hanya untuk mengurangi noise antar auditor, bukan access control.
- Perubahan skema BigQuery/kolom sumber harus dikoordinasikan manual antara script Python dan dashboard hilir (Data Studio) — tidak ada contract test otomatis antara keduanya.
