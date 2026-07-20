"use client";

import * as React from "react";
import { AlertCircle, Check, ChevronDown, ChevronRight, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * Renders a raw pipeline log as an audit checklist that ticks itself:
 * every "[n/m] ..." line becomes a step with a live status icon, detail
 * lines fold underneath, and new steps slide in as the script prints them.
 */

interface Step {
  key: string;
  title: string;
  lines: string[];
  hasError: boolean;
}

const STEP_RE = /^\[(\d+)\s*\/\s*(\d+)\]\s*(.*)$/;
const ERROR_RE = /\b(error|traceback|failed|exception)\b/i;
const OK_RE = /^(\[OK\]|✓)/;

function parseSteps(log: string): { steps: Step[]; sawError: boolean } {
  const steps: Step[] = [];
  let current: Step | null = null;
  let sawError = false;
  for (const raw of log.split("\n")) {
    const line = raw.replace(/\r$/, "");
    if (line.trim() === "" || /^[=─-]{6,}$/.test(line.trim())) continue;
    const m = line.match(STEP_RE);
    if (m) {
      current = { key: `${m[1]}/${m[2]}`, title: m[3] || `Step ${m[1]}`, lines: [], hasError: false };
      steps.push(current);
      continue;
    }
    if (!current) {
      current = { key: "prep", title: "Preparing", lines: [], hasError: false };
      steps.push(current);
    }
    current.lines.push(line);
    if (ERROR_RE.test(line) && !OK_RE.test(line.trim())) {
      current.hasError = true;
      sawError = true;
    }
  }
  return { steps, sawError };
}

function StepRow({ step, state, isLast }: { step: Step; state: "done" | "running" | "error"; isLast: boolean }) {
  const [open, setOpen] = React.useState(false);
  const opened = open || state === "error" || (state === "running" && step.lines.length > 0);
  const shownLines = state === "running" && !open ? step.lines.slice(-6) : step.lines;

  return (
    <div className="log-step relative pl-8">
      {/* rail */}
      {!isLast && <span className="absolute left-[11px] top-6 h-[calc(100%-1.25rem)] w-px bg-border" aria-hidden />}
      <span
        className={cn(
          "absolute left-0 top-0.5 flex h-[22px] w-[22px] items-center justify-center rounded-full border",
          state === "done" && "border-primary/30 bg-primary/10 text-primary",
          state === "running" && "border-primary/40 bg-primary text-primary-foreground",
          state === "error" && "border-destructive/40 bg-destructive/10 text-destructive"
        )}
      >
        {state === "done" && <Check className="h-3.5 w-3.5" />}
        {state === "running" && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
        {state === "error" && <AlertCircle className="h-3.5 w-3.5" />}
      </span>

      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="group flex w-full items-center gap-2 py-0.5 text-left cursor-pointer"
      >
        <span className={cn("text-sm", state === "running" ? "font-medium text-foreground" : "text-foreground/90")}>
          {step.title}
        </span>
        {step.lines.length > 0 && (
          <span className="flex items-center gap-0.5 text-[11px] text-muted-foreground opacity-70 group-hover:opacity-100">
            {opened ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {step.lines.length}
          </span>
        )}
      </button>

      {opened && shownLines.length > 0 && (
        <pre className="thin-scroll mb-2 mt-1 max-h-56 overflow-auto whitespace-pre-wrap rounded-md bg-muted px-3 py-2 font-mono text-[11px] leading-relaxed text-muted-foreground">
          {shownLines.join("\n")}
        </pre>
      )}
      {!opened && <div className="pb-2" />}
    </div>
  );
}

export function TransformLog({ log, status }: { log: string; status: string }) {
  const { steps, sawError } = React.useMemo(() => parseSteps(log), [log]);
  const endRef = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    endRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [steps.length, status]);

  if (steps.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-lg border bg-card p-4 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin text-primary" /> Waiting for the first output...
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-4">
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1;
        const state: "done" | "running" | "error" =
          step.hasError || (isLast && status === "FAILED")
            ? "error"
            : isLast && status === "RUNNING"
              ? "running"
              : "done";
        return <StepRow key={`${step.key}-${i}`} step={step} state={state} isLast={isLast} />;
      })}
      {status === "FAILED" && !sawError && (
        <p className="mt-2 pl-8 text-xs text-destructive">The run stopped before finishing — open the last step for details.</p>
      )}
      <div ref={endRef} />
    </div>
  );
}
