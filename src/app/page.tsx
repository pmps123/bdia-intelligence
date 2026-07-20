"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Plus, FolderOpen, Trash2, Loader2, ArrowRight, LayoutDashboard } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { toast } from "sonner";
import { cn, formatDate } from "@/lib/utils";
import { PRICE_SOURCES, priceSourceLabel, type PriceSource } from "@/lib/types";
import { ToolGate, useWorkspace } from "@/components/app/app-shell";
import { hasTool } from "@/lib/workspaces";

interface ProjectDto {
  id: string;
  name: string;
  step: string;
  priceSource: string;
  createdAt: string;
  updatedAt: string;
}

const STEP_LABEL: Record<string, string> = {
  internal: "Upload internal file",
  vendor: "Upload vendor file",
  detect: "Automatic detection",
  review: "Review matching",
  price: "Price validation",
  export: "Export",
};

/* ── skeleton rows while loading ─────────────────────────────────────────── */
function ProjectSkeleton() {
  return (
    <>
      {Array.from({ length: 3 }).map((_, i) => (
        <TableRow key={i} className="pointer-events-none">
          <TableCell>
            <div className="flex items-center gap-2">
              <div className="skeleton skeleton-text h-4 w-4 rounded-full" />
              <div className="skeleton skeleton-text w-40" />
            </div>
          </TableCell>
          <TableCell className="hidden sm:table-cell"><div className="skeleton skeleton-text w-28" /></TableCell>
          <TableCell className="hidden sm:table-cell"><div className="skeleton skeleton-text w-20" /></TableCell>
          <TableCell><div className="skeleton skeleton-text w-24 rounded-full" /></TableCell>
          <TableCell />
        </TableRow>
      ))}
    </>
  );
}

export default function HomePage() {
  return (
    <ToolGate tool="priceAudit">
      <PriceAuditHome />
    </ToolGate>
  );
}

function PriceAuditHome() {
  const router = useRouter();
  const { workspaceId } = useWorkspace();
  const [projects, setProjects] = React.useState<ProjectDto[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [name, setName] = React.useState("");
  const [priceSource, setPriceSource] = React.useState<PriceSource | null>(null);
  const [creating, setCreating] = React.useState(false);

  const load = React.useCallback(() => {
    setLoading(true);
    fetch(`/api/projects?ws=${workspaceId}`)
      .then((r) => r.json())
      .then((d) => setProjects(d.projects ?? []))
      .finally(() => setLoading(false));
  }, [workspaceId]);
  React.useEffect(load, [load]);

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim() || !priceSource) return;
    setCreating(true);
    const res = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, priceSource, workspace: workspaceId }),
    });
    setCreating(false);
    if (res.ok) {
      const d = await res.json();
      router.push(`/project/${d.project.id}`);
    } else toast.error("Could not create project");
  };

  const remove = async (p: ProjectDto) => {
    if (!confirm(`Delete project "${p.name}"?`)) return;
    await fetch(`/api/projects/${p.id}`, { method: "DELETE" });
    load();
  };

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      {/* page header */}
      <div className="mb-8">
        <div className="mb-1.5 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-widest text-primary">
          <span>Price Audit</span>
        </div>
        <h1 className="ledger-tick text-2xl font-semibold tracking-tight">Vendor price audits</h1>
        <p className="mt-2 max-w-xl text-sm text-muted-foreground">
          Match vendor products against your internal price source and validate every price change — upload two files,
          the rest is automatic.
        </p>
      </div>

      {/* new audit card */}
      <Card className="mb-8 module-card">
        <CardContent className="p-5">
          <form onSubmit={create} className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="text-sm font-semibold">Start a new audit</div>
              {!priceSource && (
                <span className="text-[11px] text-muted-foreground">Choose a price source to begin</span>
              )}
            </div>

            <RadioGroup
              value={priceSource ?? ""}
              onValueChange={(v) => setPriceSource(v as PriceSource)}
              className="grid gap-2 sm:grid-cols-3"
            >
              {(Object.keys(PRICE_SOURCES) as PriceSource[]).map((key) => (
                <label
                  key={key}
                  className={cn(
                    "flex items-start gap-2.5 rounded-lg border p-3 text-left text-sm transition-all cursor-pointer",
                    priceSource === key
                      ? "border-primary bg-accent shadow-sm"
                      : "hover:border-border/80 hover:bg-muted/60"
                  )}
                >
                  <RadioGroupItem value={key} className="mt-0.5 shrink-0" />
                  <div className="leading-snug">
                    <div className={cn("font-medium", priceSource !== key && "font-normal")}>
                      {PRICE_SOURCES[key]}
                    </div>
                  </div>
                </label>
              ))}
            </RadioGroup>

            <div className="flex gap-2">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder='e.g. "Panasonic July 2026"'
                className="h-10 flex-1"
                disabled={!priceSource}
              />
              <Button type="submit" disabled={creating || !name.trim() || !priceSource} className="h-10 shrink-0">
                {creating ? <Loader2 className="animate-spin" /> : <Plus />}
                New audit
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* recent projects */}
      <div className="mb-10">
        <div className="mb-3 flex items-center justify-between">
          <div className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
            Recent audits
          </div>
          {!loading && projects.length > 0 && (
            <span className="text-[11px] text-muted-foreground">{projects.length} project{projects.length !== 1 ? "s" : ""}</span>
          )}
        </div>
        <div className="overflow-hidden rounded-xl border bg-card module-card">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/40">
                <TableHead className="font-semibold text-foreground/70">Audit</TableHead>
                <TableHead className="hidden sm:table-cell font-semibold text-foreground/70">Price source</TableHead>
                <TableHead className="hidden sm:table-cell font-semibold text-foreground/70">Updated</TableHead>
                <TableHead className="font-semibold text-foreground/70">Status</TableHead>
                <TableHead className="w-10" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <ProjectSkeleton />
              ) : (
                <>
                  {projects.map((p) => (
                    <TableRow
                      key={p.id}
                      className="group cursor-pointer hover:bg-accent/40 transition-colors"
                      onClick={() => router.push(`/project/${p.id}`)}
                    >
                      <TableCell className="max-w-64">
                        <div className="flex items-center gap-2">
                          <FolderOpen className="h-4 w-4 shrink-0 text-primary" />
                          <span className="truncate font-medium">{p.name}</span>
                        </div>
                      </TableCell>
                      <TableCell className="hidden text-muted-foreground sm:table-cell">
                        {priceSourceLabel(p.priceSource)}
                      </TableCell>
                      <TableCell className="hidden text-muted-foreground sm:table-cell">
                        {formatDate(p.updatedAt)}
                      </TableCell>
                      <TableCell>
                        <Badge variant={p.step === "export" ? "success" : "info"}>
                          {STEP_LABEL[p.step] ?? p.step}
                        </Badge>
                      </TableCell>
                      <TableCell>
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-7 w-7 text-muted-foreground opacity-0 transition-opacity hover:text-status-bad group-hover:opacity-100"
                          onClick={(e) => {
                            e.stopPropagation();
                            remove(p);
                          }}
                        >
                          <Trash2 />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {projects.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={5} className="py-10 text-center text-muted-foreground">
                        <div className="flex flex-col items-center gap-2">
                          <FolderOpen className="h-6 w-6 text-muted-foreground/30" />
                          <span className="text-sm">No audits yet — start one above.</span>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </>
              )}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* cross-module banner */}
      {hasTool(workspaceId, "salesDashboard") && (
        <div className="rounded-xl border bg-card module-card">
          <Link
            href="/transform"
            className="flex items-center gap-3 px-5 py-4 transition-colors hover:bg-accent/40 rounded-xl"
          >
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10">
              <LayoutDashboard className="h-4.5 w-4.5 text-primary" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="font-semibold text-sm">Sales Dashboard</div>
              <div className="text-xs text-muted-foreground">
                Daily Sales · Monitoring · Business Flow · Tracker
              </div>
            </div>
            <ArrowRight className="h-4 w-4 text-muted-foreground/50 shrink-0" />
          </Link>
        </div>
      )}
    </div>
  );
}
