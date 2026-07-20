# PROJECT MEMORY — BDIA Intelligence

Catatan keputusan & histori yang **tidak** bisa disimpulkan dari membaca kode saja. Untuk kebutuhan produk lihat [PRD.md](PRD.md), untuk spesifikasi teknis lihat [SRS.md](SRS.md), untuk cara jalan lihat [README.md](README.md). File ini di-update tiap ada keputusan baru — tambahkan entri baru, jangan hapus histori lama kecuali sudah benar-benar tidak relevan.

---

## Keputusan arsitektur & alasan

- **gcloud/ADC ditinggalkan (2026-07-11)** — sempat pakai Application Default Credentials, tapi `bigquery.Client()` polos melempar `DefaultCredentialsError` di mesin user. Solusi: tiap script Python memuat service-account key JSON secara eksplisit dan pass `credentials=` ke tiap `bigquery.Client()`. Jangan kembali ke pola ADC tanpa alasan kuat.
- **Dua GCP project berbeda per script (fixed 2026-07-12, per spec user)** — bukan preferensi teknis, ini keputusan bisnis: `daily_sales_performance.py` & `monitoring_sales.py` → `pipamas-v2`; `business_flow.py`, `marketing_dashboard.py`, `visit_plan_tracker.py`, `journalism.py` → `pipamas-v3`. **Jangan** set `BQ_PROJECT_ID`/`BQ_KEY_FILE` global di `.env` — itu akan menimpa destinasi semua script jadi satu project, merusak split yang disengaja ini.
- **KPI "Persentase Pembayaran" pakai atribusi cohort**, bukan `SUM(total_payment)/(SUM(total_payment)+SUM(total_sales_balance))`. Formula lama dianggap salah karena tidak mengaitkan pembayaran ke invoice induknya. Formula benar: `DIVIDE(SUM(payment_matched_to_invoice_date), SUM(invoice_value_on_invoice_date))`, BLANK ("-") kalau tak ada invoice baru di periode filter. Ini pernah salah diimplementasikan sekali — jangan ulangi.
- **Workspace bukan sistem keamanan** — hanya switcher UI untuk memisahkan noise data antar auditor (6 orang: Rafli, Wijaya, Stevina, Juan, Vincent, Niki). Tidak ada login/password. Jangan asumsikan ini access control saat menambah fitur baru.
- **Tidak ada hardcoding nama sheet/kolom/vendor/produk/filename/GCP project ID** — ini instruksi eksplisit user, berlaku untuk seluruh kode aplikasi (web maupun Python). Semua dideteksi dari isi file upload atau dikonfigurasi via env var.
- **`journalism.py` sengaja dipisah dari "Run all"** — ini companion action di dalam section Daily Sales Performance (tombol/aksi sendiri), bukan pipeline dashboard kelima. Kalau ada permintaan "tambah ke Run all", cek dulu apakah itu benar-benar dimaksudkan atau salah paham scope.

## Histori fitur (urutan tambah, bukan urutan penting)

1. Price Audit (matching engine, wizard 8 langkah) — modul inti pertama.
2. Data Transform: Sales Dashboard 4 pipeline + Marketing Dashboard terpisah.
3. Salesman Mapping (import + table editor + autosync).
4. Notes per workspace (`Block`/`Note`, block-based editor).
5. Chat AI per workspace via OpenRouter (`ChatMessage`, `src/lib/chat/`) — system prompt disuntik konteks workspace (`buildWorkspaceContext`), fallback ke pesan error tersimpan kalau semua model AI gagal (tidak pernah 500 polos ke user).
6. `journalism.py` (Executive Report) — generate PDF/HTML + ringkasan WhatsApp dari data Daily Sales Performance, disajikan lewat `/api/reports/[filename]` dari folder `reports/`. Butuh `weasyprint` (auto pip-install kalau belum ada, lihat isi script).

## Desain visual — identitas "ledger" (confirmed 2026-07-12)

Hitam-putih (`#0A0A0A`/`#FAFAFA`) + satu aksen amber gelap `#B8894F`, dipakai eksklusif untuk CTA utama, item aktif, dan elemen signature `.ledger-rule`/`.ledger-tick` (globals.css). Warna status muted (`--status-good #4C7A5C`, `--status-bad #A8524C`) — **jangan** pakai kelas Tailwind jenuh (emerald/red/blue) langsung, itu sudah pernah ditegur user. Font: Inter (body) + Space Grotesk (display), angka finansial selalu `tabular-nums`. shadcn/ui diformalkan lewat `components.json`.

## Database: migrasi SQLite → Supabase (2026-07-20)

- Datasource (`prisma/schema.prisma`) pindah dari `sqlite` ke `postgresql`. `DATABASE_URL` di `.env` sekarang menunjuk ke Supabase pooler (`aws-0-ap-southeast-1.pooler.supabase.com:6543`, `?pgbouncer=true`) — dipakai untuk runtime app.
- **Port pooler beda fungsi**: 6543 = transaction mode (buat runtime app, `DATABASE_URL`), 5432 di host pooler yang sama = session mode (wajib dipakai untuk `prisma db push`/`migrate` — 6543 hang/gagal untuk operasi skema karena pgbouncer transaction mode tidak mendukung advisory lock). Kalau perlu `db push` lagi, override sementara: `DATABASE_URL=postgresql://postgres.cxhhimuxzuzbyizppnjo:...@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres npx prisma db push`.
- Semua data lama (Project, Upload, DataRow, SalesmanRow dst. — total ±1450 baris) sudah dipindahkan 1:1 dari `prisma/dev.db` ke Supabase, diverifikasi row-count cocok persis di setiap tabel.
- `prisma/dev.db` (dan backup `dev.db.backup-20260720223545`) **tidak dihapus** — tetap jadi fallback/rollback kalau Supabase bermasalah: kembalikan `provider = "sqlite"` + `DATABASE_URL="file:./dev.db"`, lalu `npx prisma generate`.
- `DATABASE_URL_2` di `.env` (nilai sama dengan `DATABASE_URL` tapi tanpa `pgbouncer=true`) adalah entri yang sudah dimasukkan user sendiri sebelum migrasi — dibiarkan, bukan dipakai oleh app.

## Lingkungan kerja mesin lokal user

- Windows, tanpa admin rights. Python 3.14 + semua dependensi terinstal per-user (~2026-07-12), sudah diverifikasi end-to-end lewat web runner.
- `npm start` di port 3000. `next build` gagal EPERM di `.next\trace` selama server itu jalan — harus stop server dulu sebelum build/rebuild. `prisma generate` juga butuh server dihentikan dulu (Windows file lock).
- Alternatif kalau mesin lokal tak bisa dipakai: jalankan pipeline manual di Google Colab (link & cara di README.md).
- Kunci service-account (`pipamas-v2-*.json`, `pipamas-v3-*.json`) ada di root project, di-gitignore — jangan pernah commit.

## Hal yang perlu diverifikasi ulang sebelum dipercaya (memory bisa basi)

- Daftar tool per workspace di §3 PRD — cek `src/lib/workspaces.ts` untuk state terkini sebelum menjawab pertanyaan soal akses fitur.
- Skema Prisma — cek `prisma/schema.prisma` langsung, jangan andalkan ringkasan di PRD/SRS kalau ada perubahan model terbaru.
- Daftar pipeline & destinasi BigQuery — cek `src/lib/transform/pipelines.ts` untuk konfirmasi role/script/keyword terbaru.
