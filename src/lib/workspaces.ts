/**
 * Workspaces: one per user, fully isolated — a tool only appears in a
 * workspace it is explicitly assigned to. Empty workspaces get tools later.
 */

export type ToolId = "priceAudit" | "salesDashboard" | "marketing" | "salesman";

export const TOOL_LABELS: Record<ToolId, string> = {
  priceAudit: "Price Audit",
  salesDashboard: "Sales Dashboard",
  marketing: "Marketing",
  salesman: "Salesman",
};

export interface Workspace {
  id: string;
  name: string;
  tools: ToolId[];
}

export const WORKSPACES: Workspace[] = [
  { id: "rafli", name: "Rafli Workspace", tools: ["priceAudit", "salesDashboard", "marketing", "salesman"] },
  { id: "wijaya", name: "Wijaya Workspace", tools: ["priceAudit", "salesman"] },
  { id: "stevina", name: "Stevina Workspace", tools: ["priceAudit"] },
  { id: "juan", name: "Juan Workspace", tools: [] },
  { id: "vincent", name: "Vincent Workspace", tools: [] },
  { id: "niki", name: "Niki Workspace", tools: [] },
];

export const DEFAULT_WORKSPACE = WORKSPACES[0].id;

export function getWorkspace(id: string | null | undefined): Workspace {
  return WORKSPACES.find((w) => w.id === id) ?? WORKSPACES[0];
}

export function hasTool(workspaceId: string, tool: ToolId): boolean {
  return getWorkspace(workspaceId).tools.includes(tool);
}
