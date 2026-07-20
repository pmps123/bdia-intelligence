# BDIA Intelligence

Alat produktivitas internal untuk **Business Development Internal Auditor (BDIA)**. Dua modul utama, semuanya wizard-based tanpa konfigurasi teknis:

1. **Price Audit** — product matching & price validation (pengganti kerja manual Excel).
2. **Data Transform** — menjalankan pipeline Python yang sudah ada (upload file → Run → lihat log → data masuk BigQuery).

## Workspaces

Enam workspace terisolasi (switcher di pojok kiri atas sidebar): **Rafli** (Price Audit, Sales
Dashboard, Marketing), **Wijaya** (Price Audit), **Stevina** (Price Audit), **Juan / Vincent /
Niki** (kosong — diisi menyusul). Tool hanya tampil di workspace yang di-assign; audit Price Audit
juga terpisah per workspace. Mapping-nya ada di `src/lib/workspaces.ts`.

## Menjalankan

```bash
npm install          # sekaligus prisma generate
npx prisma db push   # buat/upgrade database SQLite
npm run dev          # http://localhost:3000
# produksi: npm run build && npm start
```

## Modul 1 — Price Audit (± 5 menit)

1. **Home** — pilih sumber harga internal (**Price List by Product / Basic Price / Customized Price**), lalu buat project.
2. **Upload internal file** → 3. **Upload vendor file** (Excel/CSV/PDF).
4. **Automatic detection** — worksheet & kolom (produk, kode, harga, kategori, qty — plus Qty Rule/From/To untuk Customized Price) disarankan otomatis dari statistik data. User tinggal konfirmasi.
5. **Matching otomatis** — normalisasi + tokenisasi + fuzzy similarity + deteksi kode + confidence dengan threshold dinamis (Otsu). Nama produk dengan varian slash (mis. `EU 309 W/K`) otomatis dipecah menjadi satu baris per varian dan di-match sendiri-sendiri.
6. **Review** — hanya record yang tidak pasti: Accept / Replace / Skip.
7. **Price validation** — kolom mengikuti sumber harga yang dipilih: Internal Product/Price *(sumber)*, Updated Price (= Vendor Price), Price Difference, % Increase, % Decrease, Matching Status, Confidence. Untuk **Customized Price**, aturan kuantitas (`>= 1`, `between 5 and 9`, dst.) dibaca dinamis dari file — baris referensi dipilih sesuai qty vendor.
8. **Export** — Excel / PDF / CSV, pilih kolom & rename judul.

## Modul 2 — Data Transform

**Sales Dashboard** (`/transform`) menggabungkan empat section dengan satu "file tray" bersama
dan **satu tombol Run all**: semua section yang inputnya lengkap dijalankan berurutan dalam satu
proses (yang belum lengkap ditandai *skipped*), dengan status per sub-proses (queued / running /
done / failed) di satu strip progres:

| Section | Input yang di-upload | Script | Destinasi BigQuery |
|---|---|---|---|
| Daily Sales Performance | Invoice, Target, Active Brand List | `daily_sales_performance.py` | **pipamas-v2.data** |
| Monitoring Sales | SO Summary, Invoice Summary | `monitoring_sales.py` | **pipamas-v2.data** |
| Business Flow | SO Summary, Packing Summary, Invoice Summary | `business_flow.py` | **pipamas-v3.data** |
| Tracker | Visit Plan Report | `visit_plan_tracker.py` | **pipamas-v3.data** |

**Data Transform Marketing** tetap menjadi halaman terpisah (`/transform/marketing`):
SO + Target + Active Brand List → `marketing_dashboard.py` → **pipamas-v3.data**.

- Peran setiap file dideteksi otomatis dari **keyword awal nama file + isi worksheet/header** — tanggal & ID numerik pada nama file hanya metadata tampilan, tidak pernah dipakai untuk matching.
- Tidak ada file hasil yang disimpan di server: output-nya adalah **checklist log live di UI** + **upload ke Google BigQuery**.
- Business logic 100% tetap di script Python; website hanya orkestrasi (upload, run, progress, log, notifikasi).
- KPI **"Persentase Pembayaran"** (Sales Monitoring → Tracking Payment) harus memakai kolom
  cohort di `sales_monitoring`/`sales_customer_monitoring`:
  `DIVIDE(SUM(payment_matched_to_invoice_date), SUM(invoice_value_on_invoice_date))` —
  payment diatribusikan ke tanggal invoice induknya, bukan tanggal uang diterima. `DIVIDE`
  otomatis BLANK ("-") saat tidak ada invoice terbit di periode filter; beri tooltip
  "Tidak ada invoice baru di periode ini". Jangan lagi memakai
  `SUM(total_payment)/(SUM(total_payment)+SUM(total_sales_balance))`.
- Autentikasi BigQuery: setiap script memuat **service account key** secara eksplisit dari satu
  tempat — env `BQ_KEY_FILE`; default per script mengikuti destinasinya
  (`pipamas-v2-f9e3e0625182.json` untuk script ber-destinasi pipamas-v2,
  `pipamas-v3-f08db75e6c67.json` untuk pipamas-v3). Tidak ada gcloud/ADC.
  ⚠ Jangan set `BQ_PROJECT_ID`/`BQ_KEY_FILE` global di `.env` — destinasi tiap script berbeda;
  env tersebut hanya untuk override sadar per eksekusi.

### Prasyarat menjalankan pipeline dari web app

1. Python 3 terpasang (per-user, tanpa admin) beserta dependensi:
   ```bash
   pip install pandas numpy polars fastexcel openpyxl pyarrow db-dtypes google-cloud-bigquery pandas-gbq
   ```
   Jika interpreter bukan `python` di PATH, set env `PYTHON_BIN`.
2. Service account key ada di root project (❗ jangan pernah di-commit — sudah di-`.gitignore`):
   - `pipamas-v3-f08db75e6c67.json` → project **pipamas-v3** (default)
   - `pipamas-v2-f9e3e0625182.json` → project pipamas-v2 (hanya jika target diganti;
     set `BQ_KEY_FILE` + `BQ_PROJECT_ID`)
3. Konfigurasi target via env (tidak pernah hardcode): `BQ_PROJECT_ID` (default `pipamas-v3`),
   `BQ_DATASET_ID` (default `data`), `BQ_LOCATION` (default `asia-southeast2`),
   `BQ_KEY_FILE` (default `pipamas-v3-f08db75e6c67.json`).

### Alternatif: menjalankan pipeline di Google Colab

Bila mesin lokal tidak bisa dipakai, pipeline bisa dijalankan di Colab:
<https://colab.research.google.com/drive/1qb1LEHezZpBYOML7lcCKruSEZPvtwW3R?usp=sharing>

**Yang di-upload ke Colab (panel Files / `/content`) per sesi:**
1. Script pipeline dari folder `scripts/` (mis. `business_flow.py`).
2. Key `pipamas-v3-f08db75e6c67.json` — script otomatis menemukannya di folder kerja
   (nama default sudah cocok; tidak perlu set env apa pun).
3. File input Excel pipeline tersebut (nama bebas — cukup diawali keyword-nya: `Invoice ...`,
   `SO ...`, `Packing ...`, `Target ...`, `List Brand ...`, `Visit ...`).

**Cell 1 — install library (sekali per runtime):**
```python
%pip install -q pandas numpy polars fastexcel openpyxl pyarrow db-dtypes google-cloud-bigquery pandas-gbq
```

**Cell 2 — helper cari file input berdasarkan keyword awal (tanggal/ID di nama file diabaikan):**
```python
import glob, os
def find(prefix):
    hits = sorted(glob.glob(f"/content/{prefix}*.xls*"), key=os.path.getmtime)
    assert hits, f"Upload dulu file yang namanya diawali '{prefix}'"
    return hits[-1]  # file terbaru bila ada beberapa
```

**Cell 3 — jalankan pipeline yang diinginkan (pilih salah satu):**
```python
!python "daily_sales_performance.py" --invoice "{find('Invoice')}" --target "{find('Target')}" --brand "{find('List Brand')}"

!python "monitoring_sales.py" --so "{find('SO')}" --invoice "{find('Invoice')}"

!python "business_flow.py" --so "{find('SO')}" --packing "{find('Packing')}" --invoice "{find('Invoice')}"

!python "visit_plan_tracker.py" --visitplan "{find('Visit')}"

!python "marketing_dashboard.py" --so "{find('SO')}" --target "{find('Target')}" --brand "{find('List Brand')}"
```
Catatan: upload hanya file input milik pipeline yang sedang dijalankan agar keyword `SO`/`Invoice`
tidak tertukar antara "SO - ..." dan "SO Summary - ..." (atau tulis path lengkapnya manual).
Untuk mengganti target project: `os.environ["BQ_PROJECT_ID"] = "pipamas-v2"` dan
`os.environ["BQ_KEY_FILE"] = "/content/pipamas-v2-f9e3e0625182.json"` sebelum cell 3.

Log berjalan tampil langsung di output cell; satu-satunya output persisten adalah tabel BigQuery.

## Desain

Identitas visual "ledger": basis hitam-putih (`#0A0A0A` / `#FAFAFA`) dengan satu aksen amber
gelap `#B8894F` — dipakai hanya untuk CTA utama, item aktif, angka penting, dan elemen signature
**ledger rule/tick** (garis amber pendek ala coretan pena auditor; utility `.ledger-rule` /
`.ledger-tick` di `globals.css`). Warna status dibuat muted (`--status-good #4C7A5C`,
`--status-bad #A8524C`) agar tidak bersaing dengan identitas utama — jangan pakai kelas warna
Tailwind jenuh (emerald/red/blue) langsung. Tipografi: Inter (body) + Space Grotesk (display),
angka selalu `tabular-nums`. Komponen UI: shadcn/ui (`components.json`, `src/components/ui/`).

## Teknologi

Next.js 15 · React 19 · TypeScript · TailwindCSS 4 + Shadcn UI · Prisma + Supabase (Postgres) · SheetJS · pdf-parse · ExcelJS + jsPDF (export) · Python (pipeline Data Transform)

## Struktur

```
src/app/page.tsx            Home (Price Audit + Data Transform)
src/app/project/[id]/       Wizard Price Audit 6 langkah
src/app/transform/[pipeline]/  Wizard Data Transform (upload → confirm → run → live log)
src/app/api/projects/       CRUD project, upload, process (deteksi+matching), validate
src/app/api/matching/       hasil sesi, keputusan review, pencarian produk
src/app/api/transform/      upload + deteksi peran file, run pipeline, poll log
src/app/api/export/         export Excel/CSV/PDF
src/lib/parse/              parser file + deteksi header dinamis
src/lib/engine/             suggest, cleaning, tokens (slash-split), qty-rules, matching, price
src/lib/transform/          registry pipeline + deteksi peran file + runner Python
src/lib/export/             exporter + sumber data dinamis
scripts/                    script Python per pipeline (business logic asli, path input via argumen)
test/engine-check.ts        self-check logika slash-split / qty-rule / deteksi peran
```

Tidak ada nama sheet, kolom, produk, vendor, filename, aturan kuantitas, atau GCP project ID yang di-hardcode — semuanya dideteksi dari file yang di-upload atau dikonfigurasi via env.
