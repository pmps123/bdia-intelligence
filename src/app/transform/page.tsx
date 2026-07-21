"use client";

import * as React from "react";
import {
  CheckCircle2,
  Circle,
  FileSpreadsheet,
  Loader2,
  MinusCircle,
  Play,
  UploadCloud,
  XCircle,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { cn, formatBytes } from "@/lib/utils";
import { PIPELINES, SALES_DASHBOARD_SECTIONS, detectRole } from "@/lib/transform/pipelines";
import { TransformLog } from "@/components/app/transform-log";
import { ColabPanel } from "@/components/app/colab-panel";
import { ReportPreview } from "@/components/app/report-preview";
import { ToolGate } from "@/components/app/app-shell";
import type { ColabInstructions } from "@/lib/transform/colab";

interface PoolFile {
  id: string;
  fileName: string;
  fileSize: number;
  dateLabel: string | null;
  sheetText: string;
}

interface RunState {
  runId: string;
  status: string;
  log: string;
}

type Assignments = Record<string, Record<string, string>>;

const SECTIONS = SALES_DASHBOARD_SECTIONS.map((id) => PIPELINES[id]);

type SectionStatus = "idle" | "ready" | "pending" | "running" | "done" | "failed" | "skipped";

export default function SalesDashboardPage() {
  return (
    <ToolGate tool="salesDashboard">
      <SalesDashboard />
    </ToolGate>
  );
}

function SalesDashboard() {
  const [files, setFiles] = React.useState<PoolFile[]>([]);
  const [assignments, setAssignments] = React.useState<Assignments>({});
  const [runs, setRuns] = React.useState<Record<string, RunState>>({});
  const [colabs, setColabs] = React.useState<Record<string, ColabInstructions>>({});
  const [skipped, setSkipped] = React.useState<Set<string>>(new Set());
  const [reportRun, setReportRun] = React.useState<RunState | null>(null);
  const [reportColab, setReportColab] = React.useState<ColabInstructions | null>(null);
  const reportPollRef = React.useRef<ReturnType<typeof setInterval> | null>(null);
  const [active, setActive] = React.useState(SECTIONS[0].id);
  const [uploading, setUploading] = React.useState(false);
  const [dragOver, setDragOver] = React.useState(false);
  const [trayOpen, setTrayOpen] = React.useState(true);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const pollRef = React.useRef<ReturnType<typeof setInterval> | null>(null);

  const anyActive = Object.values(runs).some((r) => r.status === "RUNNING" || r.status === "PENDING");

  const autoAssign = React.useCallback((pool: PoolFile[]) => {
    setAssignments((prev) => {
      const next: Assignments = { ...prev };
      for (const sec of SECTIONS) {
        const cur = { ...(next[sec.id] ?? {}) };
        for (const role of sec.roles) {
          if (cur[role.key] && pool.some((f) => f.id === cur[role.key])) continue;
          const used = new Set(Object.values(cur));
          let best: PoolFile | null = null;
          let bestScore = 0;
          for (const f of pool) {
            if (used.has(f.id)) continue;
            const { role: detected, score } = detectRole(sec, f.fileName, f.sheetText);
            if (detected === role.key && score > bestScore) {
              best = f;
              bestScore = score;
            }
          }
          if (best) cur[role.key] = best.id;
        }
        next[sec.id] = cur;
      }
      return next;
    });
  }, []);

  const uploadFiles = async (list: FileList | File[]) => {
    setUploading(true);
    const added: PoolFile[] = [];
    for (const file of Array.from(list)) {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/transform/upload", { method: "POST", body: form });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        toast.error(d.error || `Upload failed: ${file.name}`);
        continue;
      }
      const up = await res.json();
      added.push({ id: up.id, fileName: up.fileName, fileSize: up.fileSize, dateLabel: up.dateLabel, sheetText: up.sheetText ?? "" });
      toast.success(`Added ${up.fileName}${up.dateLabel ? ` — ${up.dateLabel}` : ""}`);
    }
    setUploading(false);
    if (added.length > 0) {
      setFiles((fs) => {
        const pool = [...fs, ...added];
        autoAssign(pool);
        return pool;
      });
    }
  };

  const removeFile = (id: string) => {
    setFiles((fs) => fs.filter((f) => f.id !== id));
    setAssignments((prev) => {
      const next: Assignments = {};
      for (const [sec, roles] of Object.entries(prev)) {
        next[sec] = Object.fromEntries(Object.entries(roles).filter(([, v]) => v !== id));
      }
      return next;
    });
  };

  const readySections = SECTIONS.filter((sec) => sec.roles.every((r) => assignments[sec.id]?.[r.key]));

  const runAll = async () => {
    const res = await fetch("/api/transform/run-all", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sections: assignments }),
    });
    if (!res.ok) {
      toast.error((await res.json().catch(() => ({}))).error || "Could not start");
      return;
    }
    const d: { runs?: Record<string, string>; colab?: Record<string, ColabInstructions>; skipped: string[] } = await res.json();
    setSkipped(new Set(d.skipped));
    if (d.colab) {
      setColabs(d.colab);
      setRuns({});
      const first = SECTIONS.find((s) => d.colab![s.id]);
      if (first) setActive(first.id);
    } else {
      const runsMap = d.runs ?? {};
      setColabs({});
      setRuns(Object.fromEntries(Object.entries(runsMap).map(([sec, runId]) => [sec, { runId, status: "PENDING", log: "" }])));
      const first = SECTIONS.find((s) => runsMap[s.id]);
      if (first) setActive(first.id);
    }
    if (d.skipped.length > 0) {
      toast.info(`Skipped: ${d.skipped.map((s) => PIPELINES[s].title).join(", ")}`);
    }
  };

  // Companion action for the Daily Sales Performance section: same assigned files,
  // builds the executive PDF report (journalism.py) instead of uploading to BigQuery.
  const generateReport = async () => {
    const files = assignments["daily-sales-performance"] ?? {};
    setReportRun(null);
    setReportColab(null);
    const res = await fetch("/api/transform/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pipeline: "daily-sales-report", files }),
    });
    if (!res.ok) {
      toast.error((await res.json().catch(() => ({}))).error || "Could not start");
      return;
    }
    const d: { runId?: string; colab?: ColabInstructions } = await res.json();
    if (d.colab) setReportColab(d.colab);
    else if (d.runId) setReportRun({ runId: d.runId, status: "PENDING", log: "" });
  };

  React.useEffect(() => {
    const pending = reportRun && (reportRun.status === "RUNNING" || reportRun.status === "PENDING");
    if (!pending) {
      if (reportPollRef.current) { clearInterval(reportPollRef.current); reportPollRef.current = null; }
      return;
    }
    if (reportPollRef.current) return;
    reportPollRef.current = setInterval(async () => {
      if (!reportRun) return;
      try {
        const res = await fetch(`/api/transform/runs/${reportRun.runId}`);
        if (!res.ok) return;
        const d = await res.json();
        setReportRun((prev) => (prev ? { ...prev, status: d.run.status, log: d.run.log } : prev));
        if (d.run.status === "COMPLETED") toast.success("Executive report selesai");
        if (d.run.status === "FAILED") toast.error("Executive report gagal");
      } catch { /* retry */ }
    }, 1200);
    return () => { if (reportPollRef.current) { clearInterval(reportPollRef.current); reportPollRef.current = null; } };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reportRun?.status]);

  /* ── polling — stable interval using ref ─────────────────────────────────
   * Using a ref avoids recreating the interval every time `runs` changes,
   * which was causing excessive re-renders and janky progress updates.
   */
  const runsRef = React.useRef(runs);
  runsRef.current = runs;

  React.useEffect(() => {
    const hasPending = Object.values(runs).some((r) => r.status === "RUNNING" || r.status === "PENDING");
    if (!hasPending) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }
    if (pollRef.current) return; // already polling
    pollRef.current = setInterval(async () => {
      const current = runsRef.current;
      const pending = Object.entries(current).filter(([, r]) => r.status === "RUNNING" || r.status === "PENDING");
      if (pending.length === 0) { clearInterval(pollRef.current!); pollRef.current = null; return; }
      for (const [sectionId, r] of pending) {
        try {
          const res = await fetch(`/api/transform/runs/${r.runId}`);
          if (!res.ok) continue;
          const d = await res.json();
          if (d.run.status !== r.status || d.run.log !== r.log) {
            setRuns((prev) => ({ ...prev, [sectionId]: { runId: r.runId, status: d.run.status, log: d.run.log } }));
            if (d.run.status === "RUNNING" && r.status === "PENDING") setActive(sectionId);
            if (d.run.status === "COMPLETED") toast.success(`${PIPELINES[sectionId].title} selesai`);
            if (d.run.status === "FAILED") toast.error(`${PIPELINES[sectionId].title} gagal`);
          }
        } catch { /* retry */ }
      }
    }, 1200);
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyActive]);

  const sectionStatus = (id: string): SectionStatus => {
    const r = runs[id];
    if (r?.status === "PENDING") return "pending";
    if (r?.status === "RUNNING") return "running";
    if (r?.status === "COMPLETED") return "done";
    if (r?.status === "FAILED") return "failed";
    if (skipped.has(id)) return "skipped";
    return PIPELINES[id].roles.every((role) => assignments[id]?.[role.key]) ? "ready" : "idle";
  };

  const STATUS_ICON: Record<SectionStatus, React.ReactNode> = {
    idle: <Circle className="h-3.5 w-3.5 text-muted-foreground/40" />,
    ready: <Circle className="h-3.5 w-3.5 text-primary" />,
    pending: <Circle className="h-3.5 w-3.5 text-muted-foreground" />,
    running: <Loader2 className="h-3.5 w-3.5 animate-spin text-primary" />,
    done: <CheckCircle2 className="h-3.5 w-3.5 text-status-good" />,
    failed: <XCircle className="h-3.5 w-3.5 text-status-bad" />,
    skipped: <MinusCircle className="h-3.5 w-3.5 text-muted-foreground/40" />,
  };

  const STATUS_LABEL: Record<SectionStatus, string> = {
    idle: "Waiting for files",
    ready: "Ready",
    pending: "Queued",
    running: "Running…",
    done: "Done",
    failed: "Failed",
    skipped: "Skipped",
  };

  const STATUS_BADGE: Record<SectionStatus, "muted" | "info" | "success" | "destructive"> = {
    idle: "muted",
    ready: "info",
    pending: "muted",
    running: "info",
    done: "success",
    failed: "destructive",
    skipped: "muted",
  };

  return (
    <div className="flex flex-col h-full min-h-screen">
      {/* ── top header ────────────────────────────────────────────────────── */}
      <div className="border-b bg-card px-6 py-4 flex flex-wrap items-center gap-4">
        <div className="flex-1 min-w-0">
          <div className="mb-0.5 text-[11px] font-semibold uppercase tracking-widest text-primary">Data Transform</div>
          <h1 className="font-display text-xl font-semibold tracking-tight leading-tight">Sales Dashboard</h1>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            size="sm"
            variant="outline"
            onClick={() => fileRef.current?.click()}
            disabled={uploading || anyActive}
            className="h-9"
          >
            {uploading ? <Loader2 className="animate-spin" /> : <UploadCloud />}
            Add files
          </Button>
          <Button
            size="sm"
            onClick={runAll}
            disabled={readySections.length === 0 || uploading || anyActive}
            className="h-9"
          >
            {anyActive ? <Loader2 className="animate-spin" /> : <Play />}
            Run all
            {readySections.length > 0 && !anyActive && (
              <span className="ml-1 rounded bg-primary-foreground/20 px-1.5 py-0.5 text-[11px] font-bold">
                {readySections.length}
              </span>
            )}
          </Button>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept=".xlsx,.xls,.xlsm,.xlsb,.csv"
            className="hidden"
            onChange={(e) => { if (e.target.files?.length) uploadFiles(e.target.files); e.target.value = ""; }}
          />
        </div>
      </div>

      {/* ── file tray (collapsible) ────────────────────────────────────────── */}
      <div
        className={cn(
          "border-b bg-card transition-colors",
          dragOver && "bg-accent border-primary"
        )}
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files?.length) uploadFiles(e.dataTransfer.files); }}
      >
        <button
          className="flex w-full items-center gap-2 px-6 py-2.5 text-left hover:bg-muted/40 transition-colors cursor-pointer"
          onClick={() => setTrayOpen((v) => !v)}
        >
          <span className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            Files ({files.length})
          </span>
          {files.length > 0 && (
            <span className="ml-1 flex gap-1 overflow-hidden">
              {files.slice(0, 3).map((f) => (
                <span key={f.id} className="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5 text-[11px] font-medium">
                  <FileSpreadsheet className="h-3 w-3 text-primary/70" />
                  {f.fileName.length > 20 ? f.fileName.slice(0, 20) + "…" : f.fileName}
                </span>
              ))}
              {files.length > 3 && (
                <span className="text-[11px] text-muted-foreground self-center">+{files.length - 3} more</span>
              )}
            </span>
          )}
          <span className="ml-auto text-muted-foreground/50">
            {trayOpen ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
          </span>
        </button>

        {trayOpen && (
          <div className="px-6 pb-3">
            {files.length > 0 ? (
              <div className="flex flex-wrap gap-2">
                {files.map((f) => (
                  <span key={f.id} className="group inline-flex items-center gap-1.5 rounded-lg border bg-muted px-2.5 py-1.5 text-xs">
                    <FileSpreadsheet className="h-3.5 w-3.5 text-primary" />
                    <span className="max-w-48 truncate font-medium">{f.fileName}</span>
                    {f.dateLabel && <span className="text-muted-foreground">· {f.dateLabel}</span>}
                    <span className="text-muted-foreground">· {formatBytes(f.fileSize)}</span>
                    <button
                      className="ml-0.5 hidden text-muted-foreground hover:text-destructive group-hover:inline cursor-pointer"
                      onClick={() => removeFile(f.id)}
                      aria-label={`Remove ${f.fileName}`}
                      disabled={anyActive}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground py-1">
                Drop or add files — Invoice, SO Summary, Packing Summary, Target, Brand List, Visit Plan.
              </p>
            )}
          </div>
        )}
      </div>

      {/* ── main layout: section sidebar + content panel ───────────────────── */}
      <div className="flex flex-1 min-h-0">
        {/* section sidebar */}
        <aside className="hidden w-56 shrink-0 border-r bg-muted/30 md:flex flex-col py-3 gap-0.5 overflow-y-auto thin-scroll">
          {SECTIONS.map((sec) => {
            const st = sectionStatus(sec.id);
            const isActive = active === sec.id;
            return (
              <button
                key={sec.id}
                onClick={() => setActive(sec.id)}
                className={cn(
                  "section-sidebar-item mx-2 flex items-center gap-2.5 px-3 py-2.5 text-left text-[13px] transition-all cursor-pointer",
                  isActive ? "active text-foreground font-medium" : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
                )}
              >
                <span className="shrink-0">{STATUS_ICON[st]}</span>
                <div className="flex-1 min-w-0">
                  <div className="truncate leading-snug">{sec.title}</div>
                  <div className={cn("text-[11px] leading-none mt-0.5",
                    st === "done" ? "text-status-good" :
                    st === "failed" ? "text-status-bad" :
                    st === "running" ? "text-primary" :
                    "text-muted-foreground/60"
                  )}>
                    {STATUS_LABEL[st]}
                  </div>
                </div>
              </button>
            );
          })}
        </aside>

        {/* content panel */}
        <div className="flex-1 min-w-0 overflow-y-auto px-6 py-6 thin-scroll">
          {SECTIONS.map((sec) => {
            if (sec.id !== active) return null;
            const assign = assignments[sec.id] ?? {};
            const run = runs[sec.id];
            const st = sectionStatus(sec.id);

            return (
              <div key={sec.id} className="max-w-2xl">
                {/* section header */}
                <div className="mb-5">
                  <div className="flex items-center gap-2.5 mb-1">
                    <h2 className="font-display text-lg font-semibold">{sec.title}</h2>
                    <Badge variant={STATUS_BADGE[st]} className="gap-1 text-[11px]">
                      {STATUS_ICON[st]}
                      {STATUS_LABEL[st]}
                    </Badge>
                  </div>
                  <p className="text-sm text-muted-foreground">{sec.description}</p>
                </div>

                {/* file assignments */}
                <Card className="mb-5 module-card">
                  <CardContent className="p-5 space-y-3">
                    <div className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3">
                      File assignments
                    </div>
                    {sec.roles.map((role) => {
                      const chosen = files.find((f) => f.id === assign[role.key]);
                      return (
                        <div key={role.key} className="flex items-center gap-3">
                          <Label className="w-32 shrink-0 text-sm text-muted-foreground">{role.label}</Label>
                          <Select
                            value={assign[role.key] ?? "none"}
                            onValueChange={(v) =>
                              setAssignments((prev) => {
                                const cur = { ...(prev[sec.id] ?? {}) };
                                if (v === "none") delete cur[role.key];
                                else cur[role.key] = v;
                                return { ...prev, [sec.id]: cur };
                              })
                            }
                            disabled={anyActive}
                          >
                            <SelectTrigger className="h-9 flex-1 text-sm">
                              <SelectValue placeholder="— choose a file —" />
                            </SelectTrigger>
                            <SelectContent>
                              <SelectItem value="none">— choose a file —</SelectItem>
                              {files.map((f) => (
                                <SelectItem key={f.id} value={f.id}>
                                  {f.fileName}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          {chosen?.dateLabel && (
                            <Badge variant="info" className="hidden sm:inline-flex shrink-0 text-[11px]">
                              {chosen.dateLabel}
                            </Badge>
                          )}
                        </div>
                      );
                    })}
                    {files.length === 0 && (
                      <p className="text-xs text-muted-foreground pt-1">
                        Add files using the tray above — file purpose is detected automatically.
                      </p>
                    )}
                    {files.length > 0 && (
                      <p className="text-xs text-muted-foreground pt-1">
                        {st === "skipped"
                          ? "Section was skipped — assign all inputs and run again."
                          : st === "idle"
                          ? "Assign each input; complete sections are included in the run."
                          : "This section is included in the dashboard run."}
                      </p>
                    )}
                  </CardContent>
                </Card>

                {/* run output */}
                {colabs[sec.id] && <ColabPanel instructions={colabs[sec.id]} />}
                {run && run.status !== "PENDING" && <TransformLog log={run.log} status={run.status} />}
                {run?.status === "PENDING" && (
                  <div className="flex items-center gap-2.5 rounded-xl border bg-card p-4 text-sm text-muted-foreground module-card">
                    <Circle className="h-4 w-4 shrink-0" />
                    <span>Queued — starts after the preceding section finishes.</span>
                  </div>
                )}

                <p className="mt-5 text-xs text-muted-foreground">
                  No result file is stored — the checklist above is the output, and the data goes straight to Google BigQuery.
                </p>

                {/* companion action: same files, builds the executive PDF report */}
                {sec.id === "daily-sales-performance" && (
                  <div className="mt-6 border-t pt-5">
                    <div className="mb-3 flex items-center justify-between gap-3">
                      <div>
                        <div className="text-sm font-semibold">Executive Report</div>
                        <p className="text-xs text-muted-foreground">
                          Same files — builds the executive PDF report (journalism.py) instead of uploading to BigQuery.
                        </p>
                      </div>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={generateReport}
                        disabled={
                          (st !== "ready" && st !== "done") ||
                          reportRun?.status === "RUNNING" ||
                          reportRun?.status === "PENDING"
                        }
                        className="h-9 shrink-0"
                      >
                        {reportRun?.status === "RUNNING" || reportRun?.status === "PENDING" ? (
                          <Loader2 className="animate-spin" />
                        ) : (
                          <Play />
                        )}
                        Generate report
                      </Button>
                    </div>
                    {reportColab && <ColabPanel instructions={reportColab} />}
                    {reportRun && <TransformLog log={reportRun.log} status={reportRun.status} />}
                    {reportRun?.status === "COMPLETED" && (
                      <div className="mt-3">
                        <ReportPreview log={reportRun.log} />
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* mobile section tabs — shown below md */}
      <div className="flex overflow-x-auto border-t bg-card md:hidden thin-scroll">
        {SECTIONS.map((sec) => {
          const st = sectionStatus(sec.id);
          const isActive = active === sec.id;
          return (
            <button
              key={sec.id}
              onClick={() => setActive(sec.id)}
              className={cn(
                "flex shrink-0 items-center gap-1.5 border-b-2 px-4 py-2.5 text-[12px] transition-colors cursor-pointer",
                isActive
                  ? "border-primary text-foreground font-medium"
                  : "border-transparent text-muted-foreground"
              )}
            >
              {STATUS_ICON[st]}
              {sec.title}
            </button>
          );
        })}
      </div>
    </div>
  );
}
