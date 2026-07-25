"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ChevronRight,
  ChevronDown,
  Plus,
  FileText,
  ClipboardCheck,
  Megaphone,
  Users,
  LayoutDashboard,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface Page {
  id: string;
  title: string;
  parentId: string | null;
  order: number;
}

interface SidebarProps {
  workspaceId: string;
  pages: Page[];
  onAddPage: (parentId?: string) => void;
  collapsed: boolean;
  WorkspaceSwitcher: React.ReactNode;
}

/** Static shortcuts to the app's non-Notion tools — not sourced from `pages`, since these are
 *  fixed app routes rather than user-created Notion-like pages.
 *  NOTE: Marketing and Sales Dashboard both currently point at /project as a placeholder —
 *  swap in the real sub-route/query param once that page exposes distinct views. */
const TOOL_LINKS = [
  { href: "/price-audit", label: "Audit Price", icon: ClipboardCheck },
  { href: "/transform/marketing", label: "Marketing", icon: Megaphone },
  { href: "/salesman", label: "Salesman", icon: Users },
  { href: "/transform", label: "Sales Dashboard", icon: LayoutDashboard },
];

export function Sidebar({ workspaceId, pages, onAddPage, collapsed, WorkspaceSwitcher }: SidebarProps) {
  const pathname = usePathname();
  // Favorites mock — you could add an isFavorite field to Page later
  const favorites = pages.slice(0, 1);

  if (collapsed) {
    return (
      <div className="flex flex-col gap-3 py-3 items-center">
        {WorkspaceSwitcher}
        <button
          onClick={() => onAddPage()}
          className="flex h-8 w-8 items-center justify-center rounded-lg text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground cursor-pointer"
        >
          <Plus className="h-4 w-4" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-sidebar">
      <div className="px-2 py-2">
        {WorkspaceSwitcher}
      </div>

      <div className="flex-1 overflow-y-auto thin-scroll pb-4">
        {favorites.length > 0 && (
          <div className="mt-2">
            <div className="group flex items-center justify-between px-3 py-1 text-[11px] font-semibold text-sidebar-foreground/45 hover:text-sidebar-foreground/70 cursor-pointer">
              <span>Favorites</span>
            </div>
            <PageTree pages={favorites} allPages={pages} level={0} pathname={pathname} onAddPage={onAddPage} forceExpand />
          </div>
        )}

        <div className="mt-4">
          <div className="group flex items-center justify-between px-3 py-1 text-[11px] font-semibold text-sidebar-foreground/45 hover:text-sidebar-foreground/70 cursor-pointer">
            <span>Private</span>
            <button
              onClick={(e) => { e.stopPropagation(); onAddPage(); }}
              className="opacity-0 group-hover:opacity-100 hover:bg-sidebar-accent rounded p-0.5 cursor-pointer text-sidebar-foreground/60 hover:text-sidebar-foreground"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
          <PageTree pages={pages.filter((p) => p.parentId === null && p.order !== -1)} allPages={pages} level={0} pathname={pathname} onAddPage={onAddPage} />
        </div>

        <div className="mt-4">
          <div className="px-3 py-1 text-[11px] font-semibold text-sidebar-foreground/45">
            <span>Tools</span>
          </div>
          <div className="flex flex-col gap-0.5">
            {TOOL_LINKS.map((tool) => {
              const isActive = pathname === tool.href;
              return (
                <Link
                  key={tool.label}
                  href={tool.href}
                  className={cn(
                    "flex items-center gap-2 rounded text-sm transition-colors min-h-[28px] py-1",
                    isActive
                      ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
                      : "text-sidebar-foreground hover:bg-sidebar-accent/50"
                  )}
                  style={{ paddingLeft: "8px" }}
                >
                  <tool.icon className="h-4 w-4 shrink-0 text-sidebar-foreground/50" />
                  <span className="truncate text-[13px]">{tool.label}</span>
                </Link>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function PageTree({
  pages,
  allPages,
  level,
  pathname,
  onAddPage,
  forceExpand
}: {
  pages: Page[];
  allPages: Page[];
  level: number;
  pathname: string;
  onAddPage: (parentId?: string) => void;
  forceExpand?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      {pages.map((page) => (
        <PageItem key={page.id} page={page} allPages={allPages} level={level} pathname={pathname} onAddPage={onAddPage} forceExpand={forceExpand} />
      ))}
    </div>
  );
}

function PageItem({
  page,
  allPages,
  level,
  pathname,
  onAddPage,
  forceExpand
}: {
  page: Page;
  allPages: Page[];
  level: number;
  pathname: string;
  onAddPage: (parentId?: string) => void;
  forceExpand?: boolean;
}) {
  const [expanded, setExpanded] = React.useState(!!forceExpand);
  const children = allPages.filter((p) => p.parentId === page.id);
  const hasChildren = children.length > 0;

  const isActive = typeof window !== "undefined" && new URLSearchParams(window.location.search).get("id") === page.id;

  return (
    <div className="flex flex-col">
      <div
        className={cn(
          "group flex items-center min-h-[28px] py-1 pr-2 rounded text-sm transition-colors cursor-pointer",
          isActive ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium" : "text-sidebar-foreground hover:bg-sidebar-accent/50"
        )}
        style={{ paddingLeft: `${(level * 16) + 8}px` }}
      >
        <div
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded-sm hover:bg-sidebar-border cursor-pointer mr-1 text-sidebar-foreground/40 hover:text-sidebar-foreground/80 transition-colors"
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpanded(!expanded); }}
        >
          {hasChildren ? (
            expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />
          ) : (
            <span className="h-3.5 w-3.5" />
          )}
        </div>

        <Link href={`/notes?id=${page.id}`} className="flex flex-1 items-center gap-2 truncate text-[13px]">
          <FileText className="h-4 w-4 shrink-0 text-sidebar-foreground/50" />
          <span className="truncate">{page.title || "Untitled"}</span>
        </Link>

        <button
          onClick={(e) => { e.preventDefault(); e.stopPropagation(); setExpanded(true); onAddPage(page.id); }}
          className="opacity-0 group-hover:opacity-100 h-5 w-5 flex shrink-0 items-center justify-center rounded hover:bg-sidebar-border cursor-pointer text-sidebar-foreground/50 hover:text-sidebar-foreground transition-colors"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      </div>

      {expanded && hasChildren && (
        <PageTree pages={children} allPages={allPages} level={level + 1} pathname={pathname} onAddPage={onAddPage} />
      )}
    </div>
  );
}