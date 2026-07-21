"use client";

import * as React from "react";
import { useParams, useRouter } from "next/navigation";
import { CheckCircle2, ChevronLeft, FileSpreadsheet, Loader2, Play, UploadCloud, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { toast } from "sonner";
import { cn, formatBytes } from "@/lib/utils";
import { PIPELINES, SALES_DASHBOARD_SECTIONS } from "@/lib/transform/pipelines";
import { TransformLog } from "@/components/app/transform-log";
import { ColabPanel } from "@/components/app/colab-panel";
import { ToolGate } from "@/components/app/app-shell";
import type { ColabInstructions } from "@/lib/transform/colab";
import { uploadTransformFile } from "@/lib/transform/upload-client";

interface UploadedFile {
  id: string;
  fileName: string;
  fileSize: number;
  detectedRole: string | null;
  dateLabel: string | null;
}

interface RunState {
  id: string;
  status: string;
  log: string;
}

export default function TransformPage() {
  return (
    <ToolGate tool="marketing">
      <PipelinePage />
    </ToolGate>
  );
}

function PipelinePage() {
  const { pipeline: pipelineId } = useParams<{ pipeline: string }>();
  const router = useRouter();
  const pipeline = PIPELINES[pipelineId];

  // the sales pipelines merged into the combined dashboard — old links follow along
  const merged = (SALES_DASHBOARD_SECTIONS as readonly string[]).includes(pipelineId);
  React.useEffect(() => {
    if (merged) router.replace("/transform");
  }, [merged, router]);

  const [files, setFiles] = React.useState<UploadedFile[]>([]);
  const [assignments, setAssignments] = React.useState<Record<string, string>>({}); // roleKey -> uploadId
  const [uploading, setUploading] = React.useState(false);
  const [runId, setRunId] = React.useState<string | null>(null);
  const [run, setRun] = React.useState<RunState | null>(null);
  const [colab, setColab] = React.useState<ColabInstructions | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = React.useState(false);

  // poll the run while it's active; the log streams in as the script prints
  React.useEffect(() => {
    if (!runId) return;
    let stop = false;
    const tick = async () => {
      try {
        const res = await fetch(`/api/transform/runs/${runId}`);
        if (res.ok) {
          const d = await res.json();
          if (stop) return;
          setRun(d.run);
          if (d.run.status !== "RUNNING") {
            if (d.run.status === "COMPLETED") toast.success("Transform completed — data uploaded to BigQuery");
            else toast.error("Transform failed — check the log below");
            return;
          }
        }
      } catch {
        /* retry on next tick */
      }
      if (!stop) setTimeout(tick, 1000);
    };
    tick();
    return () => {
      stop = true;
    };
  }, [runId]);

  if (!pipeline || merged) {
    return <div className="p-10 text-center text-muted-foreground">{merged ? "Opening the Sales Dashboard..." : "Unknown pipeline."}</div>;
  }

  const uploadFiles = async (list: FileList | File[]) => {
    setUploading(true);
    for (const file of Array.from(list)) {
      let up: UploadedFile;
      try {
        up = await uploadTransformFile(file, pipeline.id);
      } catch (e) {
        toast.error(e instanceof Error ? e.message : `Upload failed: ${file.name}`);
        continue;
      }
      setFiles((fs) => [...fs.filter((f) => f.id !== up.id), up]);
      if (up.detectedRole) {
        // auto-assign when the slot is still free; the user can always change it
        setAssignments((a) => (a[up.detectedRole!] ? a : { ...a, [up.detectedRole!]: up.id }));
        const label = pipeline.roles.find((r) => r.key === up.detectedRole)?.label ?? up.detectedRole;
        toast.success(`Detected: ${label} file${up.dateLabel ? ` dated ${up.dateLabel}` : ""}`);
      } else {
        toast.info(`Could not detect the purpose of ${up.fileName} — assign it below`);
      }
    }
    setUploading(false);
  };

  const allAssigned = pipeline.roles.every((r) => assignments[r.key]);
  const running = run?.status === "RUNNING" || (!!runId && !run);

  const start = async () => {
    setRun(null);
    setRunId(null);
    setColab(null);
    const res = await fetch("/api/transform/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pipeline: pipeline.id, files: assignments }),
    });
    if (!res.ok) {
      toast.error((await res.json().catch(() => ({}))).error || "Could not start");
      return;
    }
    const d = await res.json();
    if (d.colab) setColab(d.colab);
    else setRunId(d.runId);
  };

  return (
    <div className="mx-auto max-w-4xl px-6 py-10">
      <div className="mb-8 flex items-start gap-3">
        <Button variant="ghost" size="icon" onClick={() => router.push("/")}>
          <ChevronLeft />
        </Button>
        <div>
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-primary">Data Transform</div>
          <h1 className="ledger-tick text-2xl font-semibold tracking-tight">{pipeline.title}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{pipeline.description}</p>
        </div>
      </div>

      {/* step 1: upload */}
      <Card className="mb-4">
        <CardContent className="p-5">
          <div
            className={cn(
              "flex flex-col items-center gap-2 rounded-xl border-2 border-dashed p-8 text-center transition-colors",
              dragOver ? "border-primary bg-primary/5" : "border-border"
            )}
            onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => { e.preventDefault(); setDragOver(false); if (e.dataTransfer.files?.length) uploadFiles(e.dataTransfer.files); }}
          >
            <UploadCloud className="h-8 w-8 text-primary" />
            <div className="font-semibold">Upload the input files</div>
            <div className="text-sm text-muted-foreground">
              Needed: {pipeline.roles.map((r) => r.label).join(" · ")} — each file&apos;s purpose is detected automatically
            </div>
            <Button onClick={() => fileRef.current?.click()} disabled={uploading || running}>
              {uploading ? <Loader2 className="animate-spin" /> : <UploadCloud />} Choose files
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
        </CardContent>
      </Card>

      {/* step 2: confirm role assignment */}
      {files.length > 0 && (
        <Card className="mb-4">
          <CardContent className="space-y-3 p-5">
            <div className="text-sm font-semibold">Confirm which file is which</div>
            {pipeline.roles.map((role) => {
              const chosen = files.find((f) => f.id === assignments[role.key]);
              return (
                <div key={role.key} className="flex items-center gap-3">
                  <Label className="w-40 shrink-0 text-sm">{role.label}</Label>
                  <Select
                    value={assignments[role.key] ?? "none"}
                    onValueChange={(v) => setAssignments((a) => ({ ...a, [role.key]: v === "none" ? "" : v }))}
                    disabled={running}
                  >
                    <SelectTrigger className="h-9 flex-1">
                      <SelectValue />
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
                  {chosen?.dateLabel && <Badge variant="info">dated {chosen.dateLabel}</Badge>}
                </div>
              );
            })}
            <div className="flex flex-wrap gap-2 pt-1">
              {files.map((f) => (
                <Badge key={f.id} variant="muted" className="gap-1">
                  <FileSpreadsheet className="h-3 w-3" /> {f.fileName} ({formatBytes(f.fileSize)})
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* step 3: run + live log */}
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm">
          {run?.status === "RUNNING" && (
            <Badge variant="info" className="gap-1"><Loader2 className="h-3 w-3 animate-spin" /> Running</Badge>
          )}
          {run?.status === "COMPLETED" && (
            <Badge variant="success" className="gap-1"><CheckCircle2 className="h-3 w-3" /> Completed — uploaded to BigQuery</Badge>
          )}
          {run?.status === "FAILED" && (
            <Badge variant="destructive" className="gap-1"><XCircle className="h-3 w-3" /> Failed</Badge>
          )}
        </div>
        <Button size="lg" onClick={start} disabled={!allAssigned || running || uploading}>
          {running ? <Loader2 className="animate-spin" /> : <Play />} Run transform
        </Button>
      </div>

      {colab && <ColabPanel instructions={colab} />}
      {(run || runId) && <TransformLog log={run?.log ?? ""} status={run?.status ?? "RUNNING"} />}

      <p className="mt-3 text-xs text-muted-foreground">
        The checklist above is the output of this transform — no result file is stored. The processed data goes straight to Google BigQuery.
      </p>
    </div>
  );
}
