"use client";

import * as React from "react";
import { ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Loader2, Upload, Users, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { TableEditor, type EditableColumn, type EditableRow } from "@/components/app/table-editor";
import { useDebouncedCallback } from "@/lib/use-debounced-callback";
import { ToolGate, useWorkspace } from "@/components/app/app-shell";

interface SalesmanRowDto {
  id: string;
  bulan: string;
  branch: string;
  division: string;
  legacyCode: string;
  newCode: string | null;
  salesName: string | null;
  nik: string | null;
  tanggalMasuk: string | null;
  tanggalKeluar: string | null;
  aktif: string;
  needsReview: boolean;
}

const COLUMNS: EditableColumn[] = [
  { id: "bulan", name: "Bulan" },
  { id: "branch", name: "Branch" },
  { id: "division", name: "Division" },
  { id: "legacyCode", name: "Legacy Code" },
  { id: "newCode", name: "New Code" },
  { id: "salesName", name: "Sales Name" },
  { id: "nik", name: "NIK" },
  { id: "tanggalMasuk", name: "Tanggal Masuk" },
  { id: "tanggalKeluar", name: "Tanggal Keluar" },
  { id: "aktif", name: "Aktif", type: "select", options: ["Aktif", "Tidak Aktif"] },
];

const toEditableRow = (r: SalesmanRowDto): EditableRow => ({
  id: r.id,
  cells: {
    bulan: r.bulan,
    branch: r.branch,
    division: r.division,
    legacyCode: r.legacyCode,
    newCode: r.newCode ?? "",
    salesName: r.salesName ?? "",
    nik: r.nik ?? "",
    tanggalMasuk: r.tanggalMasuk ?? "",
    tanggalKeluar: r.tanggalKeluar ?? "",
    aktif: r.aktif,
  },
});

export default function SalesmanPage() {
  return (
    <ToolGate tool="salesman">
      <SalesmanTable />
    </ToolGate>
  );
}

/* ── skeleton loading ────────────────────────────────────────────────────── */
function TableSkeleton() {
  return (
    <div className="space-y-1.5 mt-2">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex gap-3 px-3 py-2">
          {Array.from({ length: 7 }).map((_, j) => (
            <div key={j} className="skeleton skeleton-text flex-1" style={{ opacity: 1 - i * 0.1 }} />
          ))}
        </div>
      ))}
    </div>
  );
}

const PAGE_SIZE = 50;

function SalesmanTable() {
  const { workspaceId } = useWorkspace();
  const [rows, setRows] = React.useState<SalesmanRowDto[]>([]);
  const [total, setTotal] = React.useState(0);
  const [bulanOptions, setBulanOptions] = React.useState<string[]>([]);
  const [bulanFilter, setBulanFilterState] = React.useState<string>("__all__");
  const [page, setPage] = React.useState(1);
  const [loading, setLoading] = React.useState(true);
  const [importing, setImporting] = React.useState(false);
  const [importOpen, setImportOpen] = React.useState(false);
  const [syncing, setSyncing] = React.useState(false);

  const handleAutoSync = async () => {
    setSyncing(true);
    try {
      const res = await fetch("/api/salesman/autosync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ workspace: workspaceId }),
      });
      const d = await res.json();
      if (!res.ok) {
        toast.error(d.error ?? "Gagal menyinkronkan data.");
      } else {
        toast.success(`Berhasil menyinkronkan data! ${d.inserted} entri baru ditambahkan.`);
        load();
      }
    } catch {
      toast.error("Gagal melakukan sinkronisasi data.");
    } finally {
      setSyncing(false);
    }
  };

  const setBulanFilter = (v: string) => {
    setBulanFilterState(v);
    setPage(1);
  };

  const load = React.useCallback(() => {
    setLoading(true);
    const qs = new URLSearchParams({ ws: workspaceId, page: String(page), limit: String(PAGE_SIZE) });
    if (bulanFilter !== "__all__") qs.set("bulan", bulanFilter);
    fetch(`/api/salesman?${qs}`)
      .then((r) => r.json())
      .then((d) => {
        setRows(d.rows ?? []);
        setTotal(d.total ?? 0);
        setBulanOptions(d.bulanOptions ?? []);
      })
      .finally(() => setLoading(false));
  }, [workspaceId, bulanFilter, page]);
  React.useEffect(load, [load]);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const saveField = useDebouncedCallback((id: string, field: string, value: string) => {
    fetch(`/api/salesman/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: value }),
    });
  }, 500);

  const editable: EditableRow[] = rows.map(toEditableRow);

  const onChangeRows = (next: EditableRow[]) => {
    setRows((prev) =>
      next.map((e) => {
        const base = prev.find((r) => r.id === e.id);
        return {
          id: e.id,
          bulan: e.cells.bulan ?? "",
          branch: e.cells.branch ?? "",
          division: e.cells.division ?? "",
          legacyCode: e.cells.legacyCode ?? "",
          newCode: e.cells.newCode || null,
          salesName: e.cells.salesName || null,
          nik: e.cells.nik || null,
          tanggalMasuk: e.cells.tanggalMasuk || null,
          tanggalKeluar: e.cells.tanggalKeluar || null,
          aktif: e.cells.aktif || "Aktif",
          needsReview: base?.needsReview ?? false,
        };
      })
    );
  };

  const onCellChange = (rowId: string, colId: string, value: string) => saveField(rowId, colId, value);

  const onAddRow = async () => {
    await fetch("/api/salesman", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workspace: workspaceId,
        bulan: bulanFilter === "__all__" ? "" : bulanFilter,
      }),
    });
    load(); // re-fetch: pagination/sort means the new row's page position isn't known locally
  };

  const onRemoveRow = async (id: string) => {
    await fetch(`/api/salesman/${id}`, { method: "DELETE" });
    load();
  };

  const doImport = async (files: { karyawan: File; hierarchy: File; berjalan: File }) => {
    setImporting(true);
    const form = new FormData();
    form.set("workspace", workspaceId);
    form.set("karyawan", files.karyawan);
    form.set("hierarchy", files.hierarchy);
    form.set("berjalan", files.berjalan);
    const res = await fetch("/api/salesman/import", { method: "POST", body: form });
    const d = await res.json();
    setImporting(false);
    if (!res.ok) {
      toast.error(d.error ?? "Import gagal");
      return;
    }
    toast.success(
      `${d.inserted} baris baru ditambahkan` +
        (d.skippedExisting ? `, ${d.skippedExisting} sudah ada (dilewati)` : "") +
        (d.needsReview ? `, ${d.needsReview} perlu direview` : "")
    );
    setImportOpen(false);
    load();
  };

  const hasData = !loading && total > 0;
  const isEmpty = !loading && total === 0;

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      {/* page header */}
      <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-widest text-primary">Salesman</div>
          <h1 className="ledger-tick text-2xl font-semibold tracking-tight">Sales code mapping</h1>
          {hasData && (
            <p className="mt-1 text-sm text-muted-foreground">
              {total} entri{bulanFilter !== "__all__" ? ` · ${bulanFilter}` : ""}
            </p>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* month filter */}
          {bulanOptions.length > 0 && (
            <Select value={bulanFilter} onValueChange={setBulanFilter}>
              <SelectTrigger className="h-9 w-44 text-sm">
                <SelectValue placeholder="Semua bulan" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="__all__">Semua bulan</SelectItem>
                {bulanOptions.map((b) => (
                  <SelectItem key={b} value={b}>
                    {b}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}

          {/* sync button */}
          <Button
            variant="outline"
            size="sm"
            className="h-9 gap-1.5 border-primary/40 text-primary hover:bg-primary/5"
            onClick={handleAutoSync}
            disabled={syncing}
          >
            {syncing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Sync Local Files
          </Button>

          {/* import toggle — compact in header when data exists */}
          <Button
            variant={importOpen ? "default" : "outline"}
            size="sm"
            className="h-9 gap-1.5"
            onClick={() => setImportOpen((v) => !v)}
          >
            <Upload className="h-3.5 w-3.5" />
            Import
            {importOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </Button>
        </div>
      </div>

      {/* collapsible import panel — shown at top only when explicitly opened or table is empty */}
      {(importOpen || isEmpty) && (
        <div
          className={cn(
            "mb-6 rounded-xl border bg-card p-5 module-card transition-all",
            isEmpty && "border-primary/30 bg-accent/30"
          )}
        >
          {isEmpty && (
            <div className="flex flex-col gap-4">
              <div className="flex items-center gap-3">
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10">
                  <Users className="h-5 w-5 text-primary" />
                </div>
                <div>
                  <div className="font-semibold text-sm">Belum ada data salesman</div>
                  <div className="text-xs text-muted-foreground">
                    Mulai dengan menyinkronkan berkas Excel lokal di folder root (Mapping Salesman Berjalan & Data Karyawan) secara otomatis, atau unggah manual di bawah.
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-2">
                <Button onClick={handleAutoSync} disabled={syncing} size="sm" className="gap-1.5 h-8">
                  {syncing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                  Sync dari File Lokal (Jan-Mar)
                </Button>
              </div>
            </div>
          )}

          {!isEmpty && (
            <div className="mb-4 text-sm font-semibold">Import data salesman</div>
          )}

          <ImportPanel importing={importing} onImport={doImport} />
        </div>
      )}

      {/* table area */}
      {loading ? (
        <TableSkeleton />
      ) : hasData ? (
        <div>
          <TableEditor
            columns={COLUMNS}
            rows={editable}
            onChangeRows={onChangeRows}
            onAddRow={onAddRow}
            onRemoveRow={onRemoveRow}
            onCellChange={onCellChange}
          />
          {rows.some((r) => r.needsReview) && (
            <p className="mt-2 text-xs text-status-bad">
              {rows.filter((r) => r.needsReview).length} baris punya Legacy Code ganda di NEW Data Karyawan — New
              Code/NIK dikosongkan, isi manual.
            </p>
          )}
          {pageCount > 1 && (
            <div className="mt-3 flex items-center justify-between text-sm">
              <span className="text-muted-foreground">
                Halaman {page} dari {pageCount}
              </span>
              <div className="flex gap-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-1"
                  disabled={page <= 1}
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                >
                  <ChevronLeft className="h-3.5 w-3.5" /> Prev
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-1"
                  disabled={page >= pageCount}
                  onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
                >
                  Next <ChevronRight className="h-3.5 w-3.5" />
                </Button>
              </div>
            </div>
          )}
        </div>
      ) : null}
    </div>
  );
}

/* ── import panel ─────────────────────────────────────────────────────────── */

function ImportPanel({
  importing,
  onImport,
}: {
  importing: boolean;
  onImport: (files: { karyawan: File; hierarchy: File; berjalan: File }) => void;
}) {
  const [karyawan, setKaryawan] = React.useState<File | null>(null);
  const [hierarchy, setHierarchy] = React.useState<File | null>(null);
  const [berjalan, setBerjalan] = React.useState<File | null>(null);
  const ready = karyawan && hierarchy && berjalan;

  return (
    <div className="flex flex-wrap items-end gap-3">
      <FilePicker label="NEW Data Karyawan" file={karyawan} onPick={setKaryawan} />
      <FilePicker label="Mapping Sales Co SPV BM" file={hierarchy} onPick={setHierarchy} />
      <FilePicker label="Mapping Salesman Berjalan" file={berjalan} onPick={setBerjalan} />
      <Button
        disabled={!ready || importing}
        onClick={() => ready && onImport({ karyawan, hierarchy, berjalan })}
        className="ml-auto"
      >
        {importing ? <Loader2 className="animate-spin" /> : <Upload />}
        {importing ? "Importing…" : "Run import"}
      </Button>
    </div>
  );
}

function FilePicker({
  label,
  file,
  onPick,
}: {
  label: string;
  file: File | null;
  onPick: (f: File) => void;
}) {
  const ref = React.useRef<HTMLInputElement>(null);
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-medium text-muted-foreground">{label}</span>
      <Button
        variant="outline"
        size="sm"
        className={cn("h-9 max-w-56 truncate text-left justify-start", file && "border-primary/60 bg-accent text-foreground")}
        onClick={() => ref.current?.click()}
      >
        <span className="truncate">{file ? file.name : "Choose file…"}</span>
      </Button>
      <input
        ref={ref}
        type="file"
        accept=".xlsx,.xls"
        className="hidden"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onPick(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}
