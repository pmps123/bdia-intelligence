"use client";

import * as React from "react";
import { Progress } from "@/components/ui/progress";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";

export interface JobState {
  id: string;
  status: string;
  progress: number;
  message: string;
  result?: string | null;
}

/** Polls a job until it completes and renders live progress. */
export function useJob(jobId: string | null, onDone?: (job: JobState) => void) {
  const [job, setJob] = React.useState<JobState | null>(null);
  const onDoneRef = React.useRef(onDone);
  onDoneRef.current = onDone;

  React.useEffect(() => {
    if (!jobId) {
      setJob(null);
      return;
    }
    let stop = false;
    const tick = async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}`);
        if (!res.ok) return;
        const d = await res.json();
        if (stop) return;
        setJob(d.job);
        if (d.job.status === "RUNNING") {
          setTimeout(tick, 700);
        } else {
          onDoneRef.current?.(d.job);
        }
      } catch {
        if (!stop) setTimeout(tick, 1500);
      }
    };
    tick();
    return () => {
      stop = true;
    };
  }, [jobId]);

  return job;
}

export function JobProgress({ job }: { job: JobState | null }) {
  if (!job) return null;
  return (
    <div className="space-y-2 rounded-lg border bg-card p-4">
      <div className="flex items-center gap-2 text-sm">
        {job.status === "RUNNING" && <Loader2 className="h-4 w-4 animate-spin text-primary" />}
        {job.status === "COMPLETED" && <CheckCircle2 className="h-4 w-4 text-status-good" />}
        {job.status === "FAILED" && <XCircle className="h-4 w-4 text-destructive" />}
        <span className="font-medium">{job.message || job.status}</span>
        <span className="ml-auto text-muted-foreground">{Math.round(job.progress)}%</span>
      </div>
      <Progress value={job.progress} />
    </div>
  );
}
