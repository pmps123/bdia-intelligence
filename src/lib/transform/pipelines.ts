/**
 * Data Transform pipeline registry.
 * A pipeline = one existing Python script + the input roles it needs.
 * Only the leading keyword of each role is declared here (per spec) —
 * full filenames, dates and numeric IDs are never matched against.
 */

export interface PipelineRole {
  key: string; // maps 1:1 to the script's --<key> argument
  label: string;
  keywords: string[]; // leading keyword(s) used to auto-detect the uploaded file's purpose
  exclude?: string[]; // filename words that rule the file OUT for this role (e.g. plain "Invoice" vs "Invoice Summary")
}

export interface PipelineDef {
  id: string;
  title: string;
  description: string;
  script: string; // file inside scripts/
  roles: PipelineRole[];
}

export const PIPELINES: Record<string, PipelineDef> = {
  "daily-sales-performance": {
    id: "daily-sales-performance",
    title: "Daily Sales Performance",
    description: "Invoice + Target + Active Brand List → sales dashboards in BigQuery",
    script: "daily_sales_performance.py",
    roles: [
      { key: "invoice", label: "Invoice", keywords: ["invoice"], exclude: ["summary"] },
      { key: "target", label: "Target", keywords: ["target"] },
      { key: "brand", label: "Active Brand List", keywords: ["brand", "list brand name active"] },
    ],
  },
  // Same inputs as daily-sales-performance, but builds the executive PDF report instead of
  // uploading to BigQuery. Deliberately left out of SALES_DASHBOARD_SECTIONS — it's a companion
  // action inside that section's UI, not its own dashboard section or part of "Run all".
  "daily-sales-report": {
    id: "daily-sales-report",
    title: "Executive Report",
    description: "Invoice + Target + Active Brand List → executive PDF report (journalism.py)",
    script: "journalism.py",
    roles: [
      { key: "invoice", label: "Invoice", keywords: ["invoice"], exclude: ["summary"] },
      { key: "target", label: "Target", keywords: ["target"] },
      { key: "brand", label: "Active Brand List", keywords: ["brand", "list brand name active"] },
    ],
  },
  "monitoring-sales": {
    id: "monitoring-sales",
    title: "Monitoring Sales",
    description: "SO Summary + Invoice Summary → sales monitoring tables in BigQuery",
    script: "monitoring_sales.py",
    roles: [
      { key: "so", label: "SO Summary", keywords: ["so summary", "so"] },
      { key: "invoice", label: "Invoice Summary", keywords: ["invoice summary", "invoice"] },
    ],
  },
  "business-flow": {
    id: "business-flow",
    title: "Business Flow",
    description: "SO + Packing + Invoice Summary → order-to-cash flow tables in BigQuery",
    script: "business_flow.py",
    roles: [
      { key: "so", label: "SO Summary", keywords: ["so summary", "so"] },
      { key: "packing", label: "Packing Summary", keywords: ["packing summary", "packing"] },
      { key: "invoice", label: "Invoice Summary", keywords: ["invoice summary", "invoice"] },
    ],
  },
  tracker: {
    id: "tracker",
    title: "Tracker",
    description: "Visit Plan Report → visit tracker tables in BigQuery",
    script: "visit_plan_tracker.py",
    roles: [{ key: "visitplan", label: "Visit Plan Report", keywords: ["visit plan", "visit"] }],
  },
  marketing: {
    id: "marketing",
    title: "Data Transform Marketing",
    description: "Sales Order + Target + Active Brand List → marketing dashboards in BigQuery",
    script: "marketing_dashboard.py",
    roles: [
      { key: "so", label: "Sales Order (SO)", keywords: ["so"], exclude: ["summary"] },
      { key: "target", label: "Target", keywords: ["target"] },
      { key: "brand", label: "Active Brand List", keywords: ["brand", "list brand name active"] },
    ],
  },
};

/** The three sales pipelines + Tracker live together in ONE combined dashboard. */
export const SALES_DASHBOARD_SECTIONS = ["daily-sales-performance", "monitoring-sales", "business-flow", "tracker"] as const;

/**
 * Score how well an uploaded file fits a role. Filename keyword position is
 * the primary signal (spec: leading keyword), worksheet/header content the
 * secondary one. Dates and numeric IDs in the filename are ignored.
 */
export function scoreRole(role: PipelineRole, fileName: string, sheetText: string): number {
  const name = fileName.toLowerCase().replace(/\.[a-z0-9]+$/i, "");
  const content = sheetText.toLowerCase();
  const wordRe = (kw: string) =>
    new RegExp(`(^|[^\\p{L}\\p{N}])${kw.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}($|[^\\p{L}\\p{N}])`, "iu");
  // exclusion words rule the file out entirely (plain "Invoice" role must not grab "Invoice Summary")
  for (const ex of role.exclude ?? []) {
    if (wordRe(ex).test(name)) return 0;
  }
  let score = 0;
  for (const kw of role.keywords) {
    // longer (more specific) keywords outrank shorter ones on the same file
    const bonus = kw.trim().split(/\s+/).length - 1;
    if (name.startsWith(kw)) score = Math.max(score, 5 + bonus);
    else if (wordRe(kw).test(name)) score = Math.max(score, 3 + bonus);
    if (wordRe(kw).test(content)) score += 1;
  }
  return score;
}

/** Detect the most likely role of a single uploaded file within a pipeline. */
export function detectRole(pipeline: PipelineDef, fileName: string, sheetText: string): { role: string | null; score: number } {
  let best: string | null = null;
  let bestScore = 0;
  for (const role of pipeline.roles) {
    const s = scoreRole(role, fileName, sheetText);
    if (s > bestScore) {
      bestScore = s;
      best = role.key;
    }
  }
  return { role: bestScore > 0 ? best : null, score: bestScore };
}

/** Metadata only — shown to the user for confirmation, never used for matching. */
export function extractFileDate(fileName: string): string | null {
  const m = fileName.match(/(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})/);
  return m ? m[1] : null;
}
