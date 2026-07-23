"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ArrowLeft,
  ArrowRight,
  Ban,
  Check,
  ChevronLeft,
  Equal,
  FileSpreadsheet,
  FileDown,
  HelpCircle,
  Loader2,
  Replace,
  Search,
  Sparkles,
  UploadCloud,
  ArrowUp,
  ArrowDown,
  CircleOff,
  SkipForward,
  AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { toast } from "sonner";
import { cn, formatNumber, formatBytes } from "@/lib/utils";
import { JobProgress, useJob } from "@/components/app/job-progress";
import type { SheetSuggestion, ColumnRole } from "@/lib/engine/suggest";
import { priceSourceLabel, priceStatusLabel, type MatchCandidate } from "@/lib/types";
import { analyzeAnomalies } from "@/lib/engine/anomaly";

/* ---------- types mirrored from the API ---------- */

interface UploadInfo {
  id: string;
  fileName: string;
  fileSize: number;
  suggestions: SheetSuggestion[];
  sheets: { name: string; rowCount: number; headers: string[]; preview: string[][] }[];
}
interface ProjectState {
  project: {
    id: string;
    name: string;
    step: string;
    priceSource: string;
    sessionId: string | null;
    internalDatasetId: string | null;
    vendorDatasetId: string | null;
    validationRunId: string | null;
  };
  internal: UploadInfo | null;
  vendor: UploadInfo | null;
  session: { id: string; status: string; stats: Record<string, number> | null } | null;
}
interface ResultDto {
  id: string;
  status: string;
  source: string;
  confidence: number;
  internalRowId: string | null;
  vendorLabel: string;
  internalLabel: string;
  candidates: MatchCandidate[];
}
interface PriceItem {
  id: string;
  vendorLabel: string;
  internalLabel: string;
  vendorPrice: number | null;
  internalPrice: number | null;
  diff: number | null;
  diffPct: number | null;
  status: string;
  matchStatus: string;
  confidence: number | null;
}
interface Roles {
  product: number | null;
  code: number | null;
  price: number | null;
  category: number | null;
  qty: number | null;
  qtyRule: number | null;
  qtyFrom: number | null;
  qtyTo: number | null;
}

const EMPTY_ROLES: Roles = { product: null, code: null, price: null, category: null, qty: null, qtyRule: null, qtyFrom: null, qtyTo: null };

const STEPS = ["Internal File", "Vendor File", "Detection", "Review", "Prices", "Export"] as const;
const stepIndex = (step: string) => ({ internal: 0, vendor: 1, detect: 2, review: 3, price: 4, export: 5 }[step] ?? 0);

// any internal-data header that reads as a product code, whatever the vendor calls it
// (Prod. Variant Code, Alias Code, SKU, ...) - discovered from the sheet's own headers, never a fixed list
const CODE_HEADER_RE = /code|kode|sku|part\s*no|artikel|item\s*no/i;

function codeColumnsFor(headers: string[] | undefined): { key: string; title: string }[] {
  const seen = new Set<string>();
  const out: { key: string; title: string }[] = [];
  for (const h of headers ?? []) {
    if (CODE_HEADER_RE.test(h) && !seen.has(h)) {
      seen.add(h);
      out.push({ key: h, title: h });
    }
  }
  return out;
}

/** Export columns adapt to the selected internal price source, plus whatever code columns the internal sheet has. */
const exportColumns = (sourceLabel: string, internalHeaders?: string[]) => [
  { key: "Vendor Product", title: "Vendor Product" },
  { key: "Internal Product", title: `Internal Product (${sourceLabel})` },
  ...codeColumnsFor(internalHeaders),
  { key: "Vendor Price", title: "Vendor Price" },
  { key: "Internal Price", title: `Internal Price (${sourceLabel})` },
  { key: "Updated Price", title: "Updated Price" },
  { key: "Price Difference", title: "Price Difference" },
  { key: "% Increase", title: "% Increase" },
  { key: "% Decrease", title: "% Decrease" },
  { key: "Price Status", title: "Price Status" },
  { key: "Matching Status", title: "Matching Status" },
  { key: "Confidence", title: "Confidence" },
  { key: "Match Source", title: "Match Source" },
  { key: "Match Note", title: "Match Note" },
  { key: "Price Alert", title: "Price Alert" },
];

function rolesFromSuggestion(sheet: SheetSuggestion | undefined): Roles {
  const find = (role: ColumnRole) => sheet?.columns.find((c) => c.suggestedRole === role)?.index ?? null;
  return {
    product: find("product"),
    code: find("code"),
    price: find("price"),
    category: find("category"),
    qty: find("qty"),
    qtyRule: find("qtyRule"),
    qtyFrom: find("qtyFrom"),
    qtyTo: find("qtyTo"),
  };
}

/* ---------- page ---------- */

export default function ProjectPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [state, setState] = React.useState<ProjectState | null>(null);
  const [view, setView] = React.useState<number | null>(null); // manual navigation override
  const [uploading, setUploading] = React.useState(false);

  // detection step
  const [internalSheet, setInternalSheet] = React.useState("");
  const [vendorSheet, setVendorSheet] = React.useState("");
  const [internalRoles, setInternalRoles] = React.useState<Roles>(EMPTY_ROLES);
  const [vendorRoles, setVendorRoles] = React.useState<Roles>(EMPTY_ROLES);
  const [jobId, setJobId] = React.useState<string | null>(null);

  // review step
  const [results, setResults] = React.useState<ResultDto[]>([]);
  const [skipped, setSkipped] = React.useState<Set<string>>(new Set());
  const [replaceFor, setReplaceFor] = React.useState<ResultDto | null>(null);
  const [searchQ, setSearchQ] = React.useState("");
  const [searchRows, setSearchRows] = React.useState<{ id: string; label: string; code: string | null }[]>([]);

  // price step
  const [items, setItems] = React.useState<PriceItem[]>([]);
  const [priceStats, setPriceStats] = React.useState<Record<string, number> | null>(null);
  const [priceFilter, setPriceFilter] = React.useState("");
  const [validating, setValidating] = React.useState(false);

  // export step
  const [format, setFormat] = React.useState<"xlsx" | "csv" | "pdf">("xlsx");
  const [cols, setCols] = React.useState<{ key: string; title: string; include: boolean }[]>([]);
  const [exporting, setExporting] = React.useState(false);
  // load() can (and normally does) fire before the internal file's sheet/header details exist yet
  // (e.g. on the very first page visit, before any file is even uploaded) - this tracks whether
  // code columns have actually been incorporated, so they can be retrofitted the moment real
  // internal headers show up, instead of being silently skipped forever because `cols` already
  // had *some* entries by then.
  const codeColsAppliedRef = React.useRef(false);

  const load = React.useCallback(async () => {
    const res = await fetch(`/api/projects/${id}`);
    if (!res.ok) {
      toast.error("Project not found");
      router.push("/price-audit");
      return null;
    }
    const d: ProjectState = await res.json();
    setState(d);
    // export column titles follow the selected internal price source, plus whatever code
    // columns the (auto-suggested) internal sheet has
    setCols((c) => {
      const bestName = d.internal?.suggestions[0]?.name;
      const internalHeaders = d.internal?.sheets.find((s) => s.name === bestName)?.headers;
      if (c.length === 0) {
        codeColsAppliedRef.current = !!internalHeaders?.length;
        return exportColumns(priceSourceLabel(d.project.priceSource), internalHeaders).map((x) => ({ ...x, include: true }));
      }
      if (codeColsAppliedRef.current || !internalHeaders?.length) return c;
      codeColsAppliedRef.current = true;
      const toAdd = codeColumnsFor(internalHeaders).filter((cc) => !c.some((x) => x.key === cc.key));
      if (toAdd.length === 0) return c;
      const insertAt = c.findIndex((x) => x.key === "Internal Product") + 1 || c.length;
      return [...c.slice(0, insertAt), ...toAdd.map((x) => ({ ...x, include: true })), ...c.slice(insertAt)];
    });
    // preselect detection suggestions
    if (d.internal) {
      const best = d.internal.suggestions[0];
      setInternalSheet((s) => s || best?.name || "");
      setInternalRoles((r) => (r.product === null ? rolesFromSuggestion(best) : r));
    }
    if (d.vendor) {
      const best = d.vendor.suggestions[0];
      setVendorSheet((s) => s || best?.name || "");
      setVendorRoles((r) => (r.product === null ? rolesFromSuggestion(best) : r));
    }
    return d;
  }, [id, router]);
  React.useEffect(() => {
    load();
  }, [load]);

  const loadResults = React.useCallback(async (sessionId: string) => {
    const res = await fetch(`/api/matching/sessions/${sessionId}`);
    if (res.ok) setResults((await res.json()).results ?? []);
  }, []);
  React.useEffect(() => {
    if (state?.project.sessionId && stepIndex(state.project.step) >= 3) loadResults(state.project.sessionId);
  }, [state?.project.sessionId, state?.project.step, loadResults]);

  const job = useJob(jobId, async (j) => {
    setJobId(null);
    if (j.status === "COMPLETED") {
      toast.success("Automatic matching completed");
      setView(null);
      await load();
    } else toast.error(j.message || "Processing failed");
  });

  /* ---------- actions ---------- */

  const uploadFile = async (side: "internal" | "vendor", file: File) => {
    setUploading(true);
    const form = new FormData();
    form.append("file", file);
    form.append("side", side);
    const res = await fetch(`/api/projects/${id}/upload`, { method: "POST", body: form });
    setUploading(false);
    if (res.ok) {
      setView(null);
      // force re-suggestion for the replaced side
      if (side === "internal") setInternalRoles(EMPTY_ROLES);
      else setVendorRoles(EMPTY_ROLES);
      if (side === "internal") setInternalSheet("");
      else setVendorSheet("");
      await load();
    } else {
      const d = await res.json().catch(() => ({}));
      toast.error(d.error || "Upload failed");
    }
  };

  const runProcess = async () => {
    if (!state?.internal || !state?.vendor) return;
    if (internalRoles.product === null || vendorRoles.product === null) {
      toast.error("A product column is required on both files");
      return;
    }
    const sideCfg = (info: UploadInfo, sheetName: string, roles: Roles) => ({
      sheetName,
      headers: info.sheets.find((s) => s.name === sheetName)?.headers ?? [],
      roles,
    });
    const res = await fetch(`/api/projects/${id}/process`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        internal: sideCfg(state.internal, internalSheet, internalRoles),
        vendor: sideCfg(state.vendor, vendorSheet, vendorRoles),
      }),
    });
    if (res.ok) setJobId((await res.json()).jobId);
    else toast.error((await res.json().catch(() => ({}))).error || "Could not start");
  };

  const decide = async (r: ResultDto, action: "accept" | "replace", internalRowId?: string) => {
    const res = await fetch(`/api/matching/results/${r.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, internalRowId }),
    });
    if (res.ok) {
      setReplaceFor(null);
      if (state?.project.sessionId) loadResults(state.project.sessionId);
    } else toast.error("Action failed");
  };

  const doSearch = React.useCallback(async () => {
    if (!state?.project.internalDatasetId) return;
    const res = await fetch(`/api/matching/search?datasetId=${state.project.internalDatasetId}&q=${encodeURIComponent(searchQ)}`);
    if (res.ok) setSearchRows((await res.json()).rows ?? []);
  }, [state?.project.internalDatasetId, searchQ]);
  React.useEffect(() => {
    if (replaceFor) {
      const t = setTimeout(doSearch, 300);
      return () => clearTimeout(t);
    }
  }, [replaceFor, searchQ, doSearch]);

  const validatePrices = async () => {
    setValidating(true);
    const res = await fetch(`/api/projects/${id}/validate`, { method: "POST" });
    setValidating(false);
    if (res.ok) {
      const d = await res.json();
      setItems(d.items ?? []);
      setPriceStats(d.stats ?? null);
      setView(null);
      await load();
    } else toast.error((await res.json().catch(() => ({}))).error || "Validation failed");
  };

  const goExport = async () => {
    await fetch(`/api/projects/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ step: "export" }) });
    setView(null);
    await load();
  };

  const doExport = async () => {
    if (!state?.project.validationRunId) return;
    setExporting(true);
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: { type: "validation", id: state.project.validationRunId },
        config: {
          format,
          columns: cols.map((c) => ({ ...c, width: 24 })),
          groupBy: null,
          sortBy: null,
          sortDir: "asc",
          filterColumn: null,
          filterValue: "",
          summaryRow: false,
          includeLogo: false,
          orientation: "landscape",
          paperSize: "a4",
          header: "",
          footer: "",
          title: state.project.name,
          // vendors commonly mark their own price-increase rows with "*"/"**" in the product
          // code, and "Cek Manual" is the computed extreme-price-swing flag - both make a row red
          highlightIfContains: ["*", "Cek Manual"],
          // a genuine matched pair (both sides of the comparison actually present, not a
          // one-sided vendor-only or internal-only row) stands out red for quick visual scanning
          highlightIfBothPresent: ["Vendor Product", "Internal Product"],
        },
      }),
    });
    setExporting(false);
    if (!res.ok) {
      toast.error("Export failed");
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${state.project.name}.${format}`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  /* ---------- render ---------- */

  if (!state) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  const current = view ?? stepIndex(state.project.step);
  const reviewList = results.filter((r) => r.status !== "MATCHED");
  const autoApproved = results.filter((r) => r.status === "MATCHED").length;
  const pendingReview = reviewList.filter((r) => r.status === "NEED_REVIEW" || r.status === "PARTIAL" || r.status === "UNMATCHED").filter((r) => !skipped.has(r.id));

  return (
    <div className="mx-auto max-w-5xl px-4 py-8">
      {/* header */}
      <div className="mb-6 flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => router.push("/price-audit")}>
          <ChevronLeft />
        </Button>
        <div className="min-w-0">
          <h1 className="truncate text-xl font-bold">{state.project.name}</h1>
          <p className="text-xs text-muted-foreground">Guided product matching & price validation</p>
        </div>
        <Badge variant="info" className="ml-auto shrink-0">Based on {priceSourceLabel(state.project.priceSource)}</Badge>
      </div>

      {/* stepper */}
      <div className="mb-8 flex items-center">
        {STEPS.map((label, i) => {
          const reached = stepIndex(state.project.step) >= i;
          const active = current === i;
          return (
            <React.Fragment key={label}>
              {i > 0 && <div className={cn("h-0.5 flex-1", reached ? "bg-primary" : "bg-border")} />}
              <button
                className={cn("flex items-center gap-2 rounded-full px-2 py-1", reached ? "cursor-pointer" : "cursor-default")}
                onClick={() => reached && setView(i)}
              >
                <span
                  className={cn(
                    "flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold",
                    active ? "bg-primary text-primary-foreground" : reached ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground"
                  )}
                >
                  {reached && !active ? <Check className="h-4 w-4" /> : i + 1}
                </span>
                <span className={cn("hidden text-xs font-medium sm:block", active ? "text-foreground" : "text-muted-foreground")}>{label}</span>
              </button>
            </React.Fragment>
          );
        })}
      </div>

      {/* step 1 & 2: uploads */}
      {(current === 0 || current === 1) && (
        <UploadStep
          side={current === 0 ? "internal" : "vendor"}
          sourceLabel={priceSourceLabel(state.project.priceSource)}
          existing={current === 0 ? state.internal : state.vendor}
          uploading={uploading}
          onUpload={(f) => uploadFile(current === 0 ? "internal" : "vendor", f)}
        />
      )}

      {/* step 3: detection */}
      {current === 2 && state.internal && state.vendor && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 rounded-lg border border-primary/30 bg-primary/5 p-3 text-sm">
            <Sparkles className="h-4 w-4 shrink-0 text-primary" />
            Worksheets and columns were detected automatically. Confirm or adjust the suggestions, then run matching.
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            <DetectCard title={`Internal file (${priceSourceLabel(state.project.priceSource)})`} info={state.internal} sheetName={internalSheet} onSheet={(s) => { setInternalSheet(s); setInternalRoles(rolesFromSuggestion(state.internal!.suggestions.find((x) => x.name === s))); }} roles={internalRoles} onRoles={setInternalRoles} showQtyRules={state.project.priceSource === "CUSTOM"} />
            <DetectCard title="Vendor file" info={state.vendor} sheetName={vendorSheet} onSheet={(s) => { setVendorSheet(s); setVendorRoles(rolesFromSuggestion(state.vendor!.suggestions.find((x) => x.name === s))); }} roles={vendorRoles} onRoles={setVendorRoles} showQtyRules={false} />
          </div>
          <JobProgress job={job} />
          <div className="flex justify-end">
            <Button size="lg" onClick={runProcess} disabled={!!jobId}>
              {jobId ? <Loader2 className="animate-spin" /> : <Sparkles />} Match products automatically
            </Button>
          </div>
        </div>
      )}

      {/* step 4: review */}
      {current === 3 && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge variant="success" className="gap-1">
              <Check className="h-3 w-3" /> {autoApproved} matched automatically
            </Badge>
            <Badge variant="warning">{pendingReview.length} to review</Badge>
            <span className="text-muted-foreground">Only uncertain matches need your attention.</span>
          </div>

          <div className="space-y-2">
            {reviewList.length === 0 && (
              <Card>
                <CardContent className="p-6 text-center text-sm text-muted-foreground">Everything was matched automatically — nothing to review.</CardContent>
              </Card>
            )}
            {reviewList.map((r) => (
              <Card key={r.id} className={cn(skipped.has(r.id) && "opacity-50")}>
                <CardContent className="flex flex-wrap items-center gap-3 p-4">
                  <div className="min-w-0 flex-1">
                    <div className="truncate font-medium">{r.vendorLabel}</div>
                    <div className="truncate text-sm text-muted-foreground">
                      {r.status === "MANUAL" ? (
                        <span className="text-status-good">→ {r.internalLabel} (manual)</span>
                      ) : r.internalLabel || r.candidates[0]?.label ? (
                        <>Suggested: {r.internalLabel || r.candidates[0]?.label}</>
                      ) : (
                        "No suggestion found"
                      )}
                    </div>
                  </div>
                  <div className="flex w-24 items-center gap-2">
                    <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                      <div className={cn("h-full", r.confidence >= 0.7 ? "bg-status-good" : r.confidence >= 0.4 ? "bg-primary" : "bg-status-bad")} style={{ width: `${r.confidence * 100}%` }} />
                    </div>
                    <span className="text-xs tabular-nums text-muted-foreground">{(r.confidence * 100).toFixed(0)}%</span>
                  </div>
                  <div className="flex gap-1">
                    <Button size="sm" variant="outline" className="text-status-good" disabled={!r.internalRowId && !r.candidates[0]} onClick={() => (r.internalRowId ? decide(r, "accept") : decide(r, "replace", r.candidates[0]?.rowId))}>
                      <Check /> Accept
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => { setReplaceFor(r); setSearchQ(r.vendorLabel.split(" ").slice(0, 2).join(" ")); }}>
                      <Replace /> Replace
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setSkipped((s) => new Set(s).add(r.id))}>
                      <SkipForward /> Skip
                    </Button>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="flex justify-end">
            <Button size="lg" onClick={validatePrices} disabled={validating}>
              {validating ? <Loader2 className="animate-spin" /> : <ArrowRight />} Validate prices
            </Button>
          </div>
        </div>
      )}

      {/* step 5: prices */}
      {current === 4 && <PriceStep items={items} stats={priceStats} filter={priceFilter} setFilter={setPriceFilter} refresh={validatePrices} validating={validating} onNext={goExport} projectId={id} setItems={setItems} setStats={setPriceStats} sourceLabel={priceSourceLabel(state.project.priceSource)} />}

      {/* step 6: export */}
      {current === 5 && (
        <div className="space-y-4">
          <Card>
            <CardContent className="space-y-4 p-5">
              <div className="flex items-center gap-3">
                <Label className="w-24 text-sm">Format</Label>
                <Select value={format} onValueChange={(v) => setFormat(v as typeof format)}>
                  <SelectTrigger className="w-44">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="xlsx">Excel (.xlsx)</SelectItem>
                    <SelectItem value="csv">CSV</SelectItem>
                    <SelectItem value="pdf">PDF</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label className="text-sm">Columns</Label>
                {cols.map((c, i) => (
                  <div key={c.key} className="flex items-center gap-3">
                    <Checkbox checked={c.include} onCheckedChange={(v) => setCols((cs) => cs.map((x, xi) => (xi === i ? { ...x, include: !!v } : x)))} />
                    <span className="w-40 truncate text-sm text-muted-foreground">{c.key}</span>
                    <Input value={c.title} onChange={(e) => setCols((cs) => cs.map((x, xi) => (xi === i ? { ...x, title: e.target.value } : x)))} className="h-8 w-56" disabled={!c.include} />
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
          <div className="flex justify-between">
            <Button variant="outline" onClick={() => setView(4)}>
              <ArrowLeft /> Back to prices
            </Button>
            <Button size="lg" onClick={doExport} disabled={exporting}>
              {exporting ? <Loader2 className="animate-spin" /> : <FileDown />} Export {format.toUpperCase()}
            </Button>
          </div>
        </div>
      )}

      {/* replace dialog */}
      <Dialog open={!!replaceFor} onOpenChange={(o) => !o && setReplaceFor(null)}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>Find the right product</DialogTitle>
            <DialogDescription className="truncate">{replaceFor?.vendorLabel}</DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input value={searchQ} onChange={(e) => setSearchQ(e.target.value)} placeholder="Search internal products..." className="pl-8" />
            </div>
            {replaceFor && replaceFor.candidates.length > 0 && (
              <div className="space-y-1">
                {replaceFor.candidates.map((c) => (
                  <button key={c.rowId} className="flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm hover:bg-accent cursor-pointer" onClick={() => decide(replaceFor, "replace", c.rowId)}>
                    <span className="truncate">{c.label}</span>
                    <Badge variant="info">{(c.score * 100).toFixed(0)}%</Badge>
                  </button>
                ))}
              </div>
            )}
            <div className="max-h-60 space-y-1 overflow-y-auto thin-scroll">
              {searchRows.map((r) => (
                <button key={r.id} className="flex w-full items-center justify-between rounded-md border px-3 py-2 text-left text-sm hover:bg-accent cursor-pointer" onClick={() => replaceFor && decide(replaceFor, "replace", r.id)}>
                  <span className="truncate">{r.label}</span>
                  {r.code && <span className="text-xs text-muted-foreground">{r.code}</span>}
                </button>
              ))}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ---------- sub-components ---------- */

function UploadStep({ side, sourceLabel, existing, uploading, onUpload }: { side: "internal" | "vendor"; sourceLabel: string; existing: UploadInfo | null; uploading: boolean; onUpload: (f: File) => void }) {
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = React.useState(false);
  return (
    <Card>
      <CardContent className="p-6">
        <div
          className={cn(
            "flex flex-col items-center justify-center gap-3 rounded-xl border-2 border-dashed p-12 text-center transition-colors",
            dragOver ? "border-primary bg-primary/5" : "border-border"
          )}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => { e.preventDefault(); setDragOver(false); const f = e.dataTransfer.files?.[0]; if (f) onUpload(f); }}
        >
          <UploadCloud className="h-10 w-10 text-primary" />
          <div className="text-lg font-semibold">{side === "internal" ? `Upload your internal price file — ${sourceLabel}` : "Upload the vendor price file"}</div>
          <div className="text-sm text-muted-foreground">Excel, CSV or PDF — worksheets and columns are detected automatically</div>
          {existing && (
            <Badge variant="info" className="gap-1">
              <FileSpreadsheet className="h-3 w-3" /> current: {existing.fileName} ({formatBytes(existing.fileSize)})
            </Badge>
          )}
          <Button size="lg" onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? <Loader2 className="animate-spin" /> : <UploadCloud />} {existing ? "Replace file" : "Choose file"}
          </Button>
          <input ref={fileRef} type="file" accept=".xlsx,.xls,.csv,.pdf" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ""; }} />
        </div>
      </CardContent>
    </Card>
  );
}

const ROLE_FIELDS: { key: keyof Roles; label: string; required?: boolean }[] = [
  { key: "product", label: "Product", required: true },
  { key: "price", label: "Price" },
  { key: "code", label: "Code" },
  { key: "category", label: "Category" },
  { key: "qty", label: "Qty" },
];

// quantity gradation columns — only relevant for a Customized Price reference
const QTY_RULE_FIELDS: { key: keyof Roles; label: string; required?: boolean }[] = [
  { key: "qtyRule", label: "Qty Rule" },
  { key: "qtyFrom", label: "Qty From" },
  { key: "qtyTo", label: "Qty To" },
];

function DetectCard({ title, info, sheetName, onSheet, roles, onRoles, showQtyRules }: {
  title: string;
  info: UploadInfo;
  sheetName: string;
  onSheet: (s: string) => void;
  roles: Roles;
  onRoles: (r: Roles) => void;
  showQtyRules: boolean;
}) {
  const sheet = info.sheets.find((s) => s.name === sheetName);
  const roleFields = showQtyRules ? [...ROLE_FIELDS, ...QTY_RULE_FIELDS] : ROLE_FIELDS;
  return (
    <Card>
      <CardContent className="space-y-3 p-5">
        <div className="flex items-center gap-2">
          <FileSpreadsheet className="h-4 w-4 text-status-good" />
          <span className="font-semibold">{title}</span>
          <span className="truncate text-xs text-muted-foreground">{info.fileName}</span>
        </div>
        {info.sheets.length > 1 && (
          <div className="flex items-center gap-2">
            <Label className="w-20 shrink-0 text-xs">Worksheet</Label>
            <Select value={sheetName} onValueChange={onSheet}>
              <SelectTrigger className="h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {info.suggestions.map((s, i) => (
                  <SelectItem key={s.name} value={s.name}>
                    {s.name} ({s.rowCount} rows){i === 0 ? " — suggested" : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        {roleFields.map(({ key, label, required }) => (
          <div key={key} className="flex items-center gap-2">
            <Label className="w-20 shrink-0 text-xs">
              {label}
              {required && <span className="text-destructive"> *</span>}
            </Label>
            <Select
              value={roles[key] === null ? "none" : String(roles[key])}
              onValueChange={(v) => onRoles({ ...roles, [key]: v === "none" ? null : Number(v) })}
            >
              <SelectTrigger className="h-8">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">— not present —</SelectItem>
                {(sheet?.headers ?? []).map((h, i) => (
                  <SelectItem key={i} value={String(i)}>
                    {h}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        ))}
        <p className="text-xs text-muted-foreground">{sheet?.rowCount ?? 0} data rows detected · other columns are kept automatically</p>
      </CardContent>
    </Card>
  );
}

function PriceStep({ items, stats, filter, setFilter, refresh, validating, onNext, projectId, setItems, setStats, sourceLabel }: {
  items: PriceItem[];
  stats: Record<string, number> | null;
  filter: string;
  setFilter: (s: string) => void;
  refresh: () => void;
  validating: boolean;
  onNext: () => void;
  projectId: string;
  setItems: (i: PriceItem[]) => void;
  setStats: (s: Record<string, number> | null) => void;
  sourceLabel: string;
}) {
  // restore items when landing on this step after a reload
  React.useEffect(() => {
    if (items.length === 0) {
      fetch(`/api/projects/${projectId}/validate`)
        .then((r) => r.json())
        .then((d) => {
          if (d.run) {
            setItems(d.run.items ?? []);
            setStats(d.run.stats ?? null);
          }
        });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // anomaly analysis runs on the loaded items — same engine the AI summary and export use
  const anomaly = React.useMemo(() => analyzeAnomalies(items.map((it) => ({ id: it.id, diffPct: it.diffPct }))), [items]);
  const [onlyAnomalies, setOnlyAnomalies] = React.useState(false);
  const [aiSummary, setAiSummary] = React.useState<string | null>(null);
  const [aiModel, setAiModel] = React.useState<string | null>(null);
  const [aiLoading, setAiLoading] = React.useState(false);

  const generateSummary = async () => {
    setAiLoading(true);
    try {
      const res = await fetch(`/api/projects/${projectId}/insights`, { method: "POST" });
      const d = await res.json().catch(() => ({}));
      if (res.ok) {
        setAiSummary(d.summary ?? "");
        setAiModel(d.model ?? null);
      } else toast.error(d.error || "Gagal generate ringkasan AI");
    } finally {
      setAiLoading(false);
    }
  };

  const [page, setPage] = React.useState(0);
  const pageSize = 200;
  const filtered = items.filter((i) => {
    if (filter && !(i.vendorLabel + i.internalLabel).toLowerCase().includes(filter.toLowerCase())) return false;
    if (onlyAnomalies && (anomaly.byId.get(i.id)?.severity ?? "none") === "none") return false;
    return true;
  });
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, pageCount - 1);
  const shown = filtered.slice(safePage * pageSize, safePage * pageSize + pageSize);
  React.useEffect(() => setPage(0), [filter, onlyAnomalies]);

  const sevBadge = (id: string) => {
    const a = anomaly.byId.get(id);
    if (!a || a.severity === "none") return <span className="text-muted-foreground">-</span>;
    return (
      <Badge variant={a.severity === "high" ? "destructive" : "warning"} className="gap-1" title={a.reason} data-testid={`anomaly-severity-badge-${a.severity}`}>
        <AlertTriangle className="h-3 w-3" /> {a.severity === "high" ? "Tinggi" : "Sedang"}
      </Badge>
    );
  };
  const badge = (s: string) => {
    const map: Record<string, { v: "success" | "destructive" | "info" | "muted"; icon: React.ReactNode }> = {
      SAME: { v: "success", icon: <Equal className="h-3 w-3" /> },
      HIGHER: { v: "destructive", icon: <ArrowUp className="h-3 w-3" /> },
      LOWER: { v: "info", icon: <ArrowDown className="h-3 w-3" /> },
      MISSING: { v: "muted", icon: <CircleOff className="h-3 w-3" /> },
      // full-join sides: vendor row with nothing in the internal file, and
      // internal row nothing came in from the vendor for
      NOT_IN_INTERNAL: { v: "muted", icon: <Ban className="h-3 w-3" /> },
      NOT_IN_VENDOR: { v: "muted", icon: <HelpCircle className="h-3 w-3" /> },
    };
    const m = map[s] ?? map.MISSING;
    return (
      <Badge variant={m.v} className="gap-1">
        {m.icon} {priceStatusLabel(s)}
      </Badge>
    );
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {stats && (
          <>
            <Badge variant="success">{stats.same ?? 0} same</Badge>
            <Badge variant="destructive">{stats.higher ?? 0} higher</Badge>
            <Badge variant="info">{stats.lower ?? 0} lower</Badge>
            <Badge variant="muted">{stats.missing ?? 0} missing</Badge>
            <Badge variant="muted">{stats.notInInternal ?? 0} not in internal</Badge>
            <Badge variant="muted">{stats.notInVendor ?? 0} not in vendor</Badge>
          </>
        )}
        <div className="relative ml-auto">
          <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
          <Input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search..." className="h-9 w-56 pl-8" />
        </div>
        <Button variant="outline" size="sm" onClick={refresh} disabled={validating}>
          {validating ? <Loader2 className="animate-spin" /> : null} Re-validate
        </Button>
      </div>

      {/* anomaly summary + AI executive summary trigger */}
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-primary/20 bg-primary/3 p-3 text-sm" data-testid="anomaly-banner">
        {anomaly.summary.high + anomaly.summary.medium > 0 ? (
          <>
            <AlertTriangle className="h-4 w-4 shrink-0 text-status-bad" />
            <span className="font-medium">{anomaly.summary.high} anomali tinggi · {anomaly.summary.medium} sedang</span>
            <span className="text-muted-foreground">dari {anomaly.summary.total} baris berharga.</span>
            <Button size="sm" variant={onlyAnomalies ? "default" : "outline"} onClick={() => setOnlyAnomalies((v) => !v)} data-testid="anomaly-filter-toggle">
              {onlyAnomalies ? "Tampilkan semua" : "Hanya anomali"}
            </Button>
          </>
        ) : (
          <span className="text-muted-foreground">Tidak ada anomali harga signifikan terdeteksi.</span>
        )}
        <Button size="sm" variant="outline" className="ml-auto" onClick={generateSummary} disabled={aiLoading} data-testid="ai-insights-generate-btn">
          {aiLoading ? <Loader2 className="animate-spin" /> : <Sparkles />} AI Executive Summary
        </Button>
      </div>

      {aiSummary && (
        <Card data-testid="ai-summary-card">
          <CardContent className="space-y-2 p-4">
            <div className="flex items-center gap-2 text-sm font-semibold">
              <Sparkles className="h-4 w-4 text-primary" /> Ringkasan Eksekutif (AI)
            </div>
            <p className="whitespace-pre-wrap text-sm text-muted-foreground">{aiSummary}</p>
            {aiModel && <p className="text-[11px] text-muted-foreground/70">model: {aiModel}</p>}
          </CardContent>
        </Card>
      )}

      <div className="max-h-[60vh] overflow-auto rounded-lg border bg-card thin-scroll">
        <table className="w-full text-sm">
          <thead className="sticky top-0 bg-muted">
            <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2">Vendor Product</th>
              <th className="px-3 py-2">Internal Product ({sourceLabel})</th>
              <th className="px-3 py-2 text-right">Vendor Price</th>
              <th className="px-3 py-2 text-right">Internal Price ({sourceLabel})</th>
              <th className="px-3 py-2 text-right">Updated Price</th>
              <th className="px-3 py-2 text-right">Price Difference</th>
              <th className="px-3 py-2 text-right">% Increase</th>
              <th className="px-3 py-2 text-right">% Decrease</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Matching</th>
              <th className="px-3 py-2 text-right">Confidence</th>
              <th className="px-3 py-2">Anomali</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={12} className="p-6 text-center text-muted-foreground">
                  {onlyAnomalies ? "Tidak ada anomali pada filter ini." : "No price rows — accept some matches first, then re-validate."}
                </td>
              </tr>
            )}
            {shown.map((it) => (
              <tr key={it.id} className={cn("border-t", anomaly.byId.get(it.id)?.severity === "high" && "bg-status-bad/5")}>
                <td className="max-w-56 truncate px-3 py-2">{it.vendorLabel}</td>
                <td className="max-w-56 truncate px-3 py-2">{it.internalLabel}</td>
                <td className="px-3 py-2 text-right tabular-nums">{formatNumber(it.vendorPrice)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{formatNumber(it.internalPrice)}</td>
                {/* Updated Price always takes the vendor price */}
                <td className="px-3 py-2 text-right font-medium tabular-nums">{formatNumber(it.vendorPrice)}</td>
                <td className={cn("px-3 py-2 text-right tabular-nums", (it.diff ?? 0) > 0 ? "text-status-bad" : (it.diff ?? 0) < 0 ? "text-status-good" : "")}>{formatNumber(it.diff)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-status-bad">
                  {it.diffPct !== null && it.diffPct > 0 ? `+${formatNumber(it.diffPct)}%` : "-"}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-status-good">
                  {it.diffPct !== null && it.diffPct < 0 ? `${formatNumber(Math.abs(it.diffPct))}%` : "-"}
                </td>
                <td className="px-3 py-2">{badge(it.status)}</td>
                <td className="px-3 py-2 text-xs">{it.matchStatus || "-"}</td>
                <td className="px-3 py-2 text-right tabular-nums text-xs">
                  {it.confidence === null ? "-" : `${Math.round(it.confidence * 100)}%`}
                </td>
                <td className="px-3 py-2">{sevBadge(it.id)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        {pageCount > 1 && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Button variant="outline" size="sm" disabled={safePage === 0} onClick={() => setPage(safePage - 1)}>
              Previous
            </Button>
            <span>
              Page {safePage + 1} of {pageCount} ({filtered.length} rows)
            </span>
            <Button variant="outline" size="sm" disabled={safePage >= pageCount - 1} onClick={() => setPage(safePage + 1)}>
              Next
            </Button>
          </div>
        )}
        <Button size="lg" className="ml-auto" onClick={onNext}>
          <ArrowRight /> Continue to export
        </Button>
      </div>
    </div>
  );
}
