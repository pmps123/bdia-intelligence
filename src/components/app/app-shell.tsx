"use client";

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  ShieldCheck,
  LayoutDashboard,
  Megaphone,
  ChevronsUpDown,
  Check,
  CircleOff,
  Users,
  LogOut,
  ChevronRight,
  Plus,
  FileText,
  Menu,
  PanelLeftClose,
  PanelLeft,
  Sparkles,
  Home as HomeIcon,
} from "lucide-react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Command, CommandEmpty, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { ChatPanel } from "@/components/app/chat-panel";
import { cn } from "@/lib/utils";
import { WORKSPACES, DEFAULT_WORKSPACE, getWorkspace, hasTool, type ToolId } from "@/lib/workspaces";

/* ---------- workspace state (persisted per browser) ---------- */

const WorkspaceContext = React.createContext<{
  workspaceId: string;
  setWorkspaceId: (id: string) => void;
  signOut: () => void;
  notes: any[];
  refreshNotes: () => void;
}>({
  workspaceId: DEFAULT_WORKSPACE,
  setWorkspaceId: () => {},
  signOut: () => {},
  notes: [],
  refreshNotes: () => {},
});

export function useWorkspace() {
  const { workspaceId, setWorkspaceId, signOut, notes, refreshNotes } = React.useContext(WorkspaceContext);
  return { workspaceId, setWorkspaceId, signOut, workspace: getWorkspace(workspaceId), notes, refreshNotes };
}

/** Renders children only when the active workspace has the tool assigned. */
export function ToolGate({ tool, children }: { tool: ToolId; children: React.ReactNode }) {
  const { workspace } = useWorkspace();
  if (!workspace.tools.includes(tool)) {
    return (
      <div className="mx-auto max-w-xl px-6 py-24 text-center">
        <CircleOff className="mx-auto mb-4 h-10 w-10 text-muted-foreground/30" />
        <h1 className="text-lg font-semibold">Not available in {workspace.name}</h1>
        <p className="mt-2 text-sm text-muted-foreground max-w-xs mx-auto">
          This tool isn&apos;t assigned to the current workspace. Switch workspace from the sidebar.
        </p>
      </div>
    );
  }
  return <>{children}</>;
}

/* ---------- nav config ---------- */
// WORKSPACE_NAV is now dynamically generated from notes list.

const TOOL_NAV: { tool: ToolId; href: string; label: string; icon: typeof ShieldCheck; match: (p: string) => boolean }[] = [
  { tool: "priceAudit", href: "/price-audit", label: "Price Audit", icon: ShieldCheck, match: (p) => p.startsWith("/price-audit") || p.startsWith("/project") },
  { tool: "salesDashboard", href: "/transform", label: "Sales Dashboard", icon: LayoutDashboard, match: (p) => p.startsWith("/transform") && p !== "/transform/marketing" },
  { tool: "marketing", href: "/transform/marketing", label: "Marketing", icon: Megaphone, match: (p) => p === "/transform/marketing" },
  { tool: "salesman", href: "/salesman", label: "Salesman", icon: Users, match: (p) => p === "/salesman" },
];

/* ---------- workspace switcher ---------- */

const WorkspaceSwitcher = React.memo(function WorkspaceSwitcher({
  workspaceId,
  onChange,
  collapsed,
}: {
  workspaceId: string;
  onChange: (id: string) => void;
  collapsed?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const current = getWorkspace(workspaceId);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        title={collapsed ? current.name : undefined}
        className={cn(
          "flex w-full items-center rounded-lg text-left transition-colors hover:bg-sidebar-accent cursor-pointer group",
          collapsed ? "justify-center p-1.5" : "gap-2.5 px-2 py-1.5"
        )}
      >
        <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-sidebar-accent font-display text-[12px] font-bold tracking-tight text-sidebar-accent-foreground ring-1 ring-inset ring-white/10">
          {current.name.slice(0, 1)}
        </div>
        {!collapsed && (
          <>
            <div className="min-w-0 flex-1 leading-tight">
              <div className="truncate text-[13px] font-semibold text-sidebar-accent-foreground">{current.name}</div>
              <div className="truncate text-[11px] text-sidebar-foreground/60">Workspace</div>
            </div>
            <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-sidebar-foreground/50 group-hover:text-sidebar-foreground/80 transition-colors" />
          </>
        )}
      </PopoverTrigger>
      <PopoverContent align="start" className="w-60 p-0 shadow-lg">
        <Command>
          <CommandInput placeholder="Find workspace..." className="text-sm" />
          <CommandList>
            <CommandEmpty>No workspace found.</CommandEmpty>
            {WORKSPACES.map((w) => (
              <CommandItem
                key={w.id}
                value={w.name}
                onSelect={() => {
                  onChange(w.id);
                  setOpen(false);
                }}
                className="gap-2.5"
              >
                <span className="flex h-6 w-6 items-center justify-center rounded bg-primary/12 font-display text-[11px] font-bold text-primary">
                  {w.name.slice(0, 1)}
                </span>
                <span className="flex-1 truncate text-sm">{w.name}</span>
                {w.id === workspaceId && <Check className="h-4 w-4 text-primary" />}
              </CommandItem>
            ))}
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
});

/* ---------- full-screen workspace picker ---------- */

function WhoAmI({ onPick }: { onPick: (id: string) => void }) {
  return (
    <div className="flex min-h-screen items-center justify-center px-6 py-16 bg-background">
      <div className="w-full max-w-sm">
        {/* brand mark */}
        <div className="mb-10 text-center">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src="/bdia-mark.png"
            alt="BDIA"
            className="mx-auto mb-4 h-16 w-16 rounded-2xl object-cover shadow-(--shadow-elevated) ring-1 ring-border"
          />
          <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.2em] text-primary">BDIA Intelligence</div>
          <h1 className="font-display text-2xl font-semibold tracking-tight">Choose your workspace</h1>
          <p className="mt-2 text-sm text-muted-foreground">Pick the workspace you work in to continue.</p>
        </div>

        <div className="grid gap-2">
          {WORKSPACES.map((w) => (
            <button
              key={w.id}
              onClick={() => onPick(w.id)}
              className="group flex items-center gap-3 rounded-xl border bg-card px-4 py-3.5 text-left text-sm transition-all hover:border-primary/50 hover:bg-accent hover:shadow-(--shadow-card) cursor-pointer"
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary font-display text-[15px] font-bold text-primary-foreground shadow-sm transition-transform group-hover:scale-105">
                {w.name.slice(0, 1)}
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-semibold truncate">{w.name}</div>
                <div className="text-xs text-muted-foreground truncate">
                  {(w as { tools?: string[] }).tools?.length ?? 0} tools assigned
                </div>
              </div>
              <ChevronRight className="h-4 w-4 text-muted-foreground/40 group-hover:text-primary/60 transition-colors" />
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

/* ---------- sidebar nav item ---------- */

function NavItem({
  href,
  label,
  icon: Icon,
  active,
  collapsed,
}: {
  href: string;
  label: string;
  icon: React.ElementType;
  active: boolean;
  collapsed?: boolean;
}) {
  return (
    <Link
      href={href}
      title={collapsed ? label : undefined}
      className={cn(
        "group/nav flex items-center rounded-lg text-[13px] font-medium transition-colors duration-150",
        collapsed ? "justify-center px-0 py-2" : "gap-2.5 px-2.5 py-1.5",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-sidebar-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-accent-foreground"
      )}
    >
      <Icon
        className={cn(
          "h-3.75 w-3.75 shrink-0 transition-colors",
          active ? "text-(--brand-red)" : "text-sidebar-foreground/60 group-hover/nav:text-sidebar-foreground/90"
        )}
      />
      {!collapsed && <span className="truncate">{label}</span>}
    </Link>
  );
}

function NavSection({ label, children, collapsed }: { label: string; children: React.ReactNode; collapsed?: boolean }) {
  return (
    <div className="flex flex-col gap-0.5">
      {collapsed ? (
        <div className="mx-2 mb-0.5 h-px bg-sidebar-border" />
      ) : (
        <div className="px-2.5 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-sidebar-foreground/45">
          {label}
        </div>
      )}
      {children}
    </div>
  );
}

const STORAGE_KEY = "bdia.workspace";

const COLLAPSE_KEY = "bdia.sidebar.collapsed";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [workspaceId, setWorkspaceIdState] = React.useState<string | null>(null);
  const [ready, setReady] = React.useState(false);
  const [chatOpen, setChatOpen] = React.useState(false);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const [collapsed, setCollapsed] = React.useState(false);
  const [notes, setNotes] = React.useState<any[]>([]);

  React.useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

  React.useEffect(() => {
    setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1");
  }, []);
  const toggleCollapsed = React.useCallback(() => {
    setCollapsed((c) => {
      const next = !c;
      localStorage.setItem(COLLAPSE_KEY, next ? "1" : "0");
      return next;
    });
  }, []);

  const refreshNotes = React.useCallback(() => {
    const saved = localStorage.getItem(STORAGE_KEY) || DEFAULT_WORKSPACE;
    fetch(`/api/notes?ws=${saved}`)
      .then((r) => r.json())
      .then((d) => setNotes(d.notes ?? []))
      .catch(() => {});
  }, []);

  React.useEffect(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved && WORKSPACES.some((w) => w.id === saved)) {
      setWorkspaceIdState(saved);
    } else {
      setWorkspaceIdState(DEFAULT_WORKSPACE);
    }
    setReady(true);
  }, []);

  React.useEffect(() => {
    if (workspaceId) {
      refreshNotes();
    }
  }, [workspaceId, refreshNotes]);

  const setWorkspaceId = React.useCallback((id: string) => {
    setWorkspaceIdState(id);
    localStorage.setItem(STORAGE_KEY, id);
  }, []);

  const signOut = React.useCallback(() => {
    localStorage.removeItem(STORAGE_KEY);
    setWorkspaceIdState(null);
  }, []);

  const handleAddNote = async () => {
    if (!workspaceId) return;
    const res = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: workspaceId, type: "text" }),
    });
    if (res.ok) {
      const d = await res.json();
      refreshNotes();
      window.location.href = `/notes?id=${d.note.id}`;
    }
  };

  if (!ready) return null;
  if (!workspaceId) return <WhoAmI onPick={setWorkspaceId} />;

  const workspace = getWorkspace(workspaceId);
  const toolNav = TOOL_NAV.filter((t) => hasTool(workspaceId, t.tool));

  // Determine active note from query params if on /notes
  const getActiveNoteId = () => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      return params.get("id");
    }
    return null;
  };
  const activeNoteId = getActiveNoteId();
  const activeNote = pathname === "/notes" ? notes.find((n) => n.id === activeNoteId) : null;
  const currentTitle = toolNav.find((t) => t.match(pathname))?.label ?? activeNote?.title ?? workspace.name;

  const renderSidebar = (sbCollapsed: boolean) => (
    <>
      {/* brand */}
      <div className={cn("flex pt-3 pb-2", sbCollapsed ? "flex-col items-center gap-2 px-2" : "items-center gap-2 px-2.5")}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/bdia-mark.png" alt="BDIA" className="h-8 w-8 shrink-0 rounded-lg object-cover ring-1 ring-white/10" />
        {!sbCollapsed && (
          <div className="min-w-0 flex-1 leading-none">
            <div className="font-display text-sm font-bold tracking-tight text-sidebar-accent-foreground">BDIA</div>
            <div className="mt-0.5 text-[9.5px] font-medium uppercase tracking-[0.18em] text-sidebar-foreground/50">Intelligence</div>
          </div>
        )}
        <button
          onClick={toggleCollapsed}
          title={sbCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="hidden md:inline-flex h-6 w-6 items-center justify-center rounded-md text-sidebar-foreground/50 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground cursor-pointer"
          data-testid="sidebar-collapse-toggle"
        >
          {sbCollapsed ? <PanelLeft className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </button>
      </div>

      {/* workspace switcher */}
      <div className="px-2 pb-2">
        <WorkspaceSwitcher workspaceId={workspaceId} onChange={setWorkspaceId} collapsed={sbCollapsed} />
      </div>

      <div className="mx-3 border-t border-sidebar-border" />

      {/* nav */}
      <nav className="flex flex-1 flex-col gap-3 overflow-y-auto px-2 py-3 thin-scroll">
        <NavItem href="/" label="Home" icon={HomeIcon} active={pathname === "/"} collapsed={sbCollapsed} />

        <div className="flex flex-col gap-0.5">
          {sbCollapsed ? (
            <button
              onClick={handleAddNote}
              title="Add page"
              data-testid="sidebar-new-page-btn"
              className="mx-auto flex h-8 w-8 items-center justify-center rounded-lg text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground cursor-pointer"
            >
              <Plus className="h-4 w-4" />
            </button>
          ) : (
            <div className="group flex items-center justify-between px-2.5 pb-1 pt-0.5">
              <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-sidebar-foreground/45">Pages</span>
              <button
                onClick={handleAddNote}
                title="Add page"
                data-testid="sidebar-new-page-btn"
                className="rounded p-0.5 text-sidebar-foreground/60 opacity-0 transition-all hover:bg-sidebar-accent hover:text-sidebar-accent-foreground group-hover:opacity-100 cursor-pointer"
              >
                <Plus className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
          {/* the order:-1 note is the workspace Home page — already pinned above, not listed twice */}
          {notes.filter((n) => n.order !== -1).map((n) => (
            <NavItem
              key={n.id}
              href={`/notes?id=${n.id}`}
              label={n.title || "Untitled"}
              icon={FileText}
              active={pathname === "/notes" && activeNoteId === n.id}
              collapsed={sbCollapsed}
            />
          ))}
          {notes.filter((n) => n.order !== -1).length === 0 && !sbCollapsed && (
            <p className="px-2.5 py-1.5 text-xs italic text-sidebar-foreground/40">No pages yet.</p>
          )}
        </div>

        <NavSection label="Tools" collapsed={sbCollapsed}>
          {toolNav.map(({ href, label, icon: Icon, match }) => (
            <NavItem key={href} href={href} label={label} icon={Icon} active={match(pathname)} collapsed={sbCollapsed} />
          ))}
          {toolNav.length === 0 && !sbCollapsed && (
            <p className="px-2.5 py-1.5 text-xs text-sidebar-foreground/50">No tools assigned yet.</p>
          )}
        </NavSection>
      </nav>

      {/* footer */}
      <div className="border-t border-sidebar-border px-2 py-3">
        <button
          onClick={signOut}
          title="Sign out"
          className={cn(
            "group flex items-center rounded-lg text-[12px] text-sidebar-foreground/60 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground cursor-pointer",
            sbCollapsed ? "mx-auto h-8 w-8 justify-center" : "w-full gap-2 px-2.5 py-1.5"
          )}
        >
          <LogOut className="h-3.5 w-3.5 shrink-0" />
          {!sbCollapsed && <span className="truncate">Sign out of {workspace.name}</span>}
        </button>
      </div>
    </>
  );

  return (
    <WorkspaceContext.Provider value={{ workspaceId, setWorkspaceId, signOut, notes, refreshNotes }}>
      <div className="flex min-h-screen bg-background text-foreground">
        {/* desktop sidebar */}
        <aside
          className="sticky top-0 hidden h-screen shrink-0 flex-col overflow-hidden border-r border-sidebar-border bg-sidebar md:flex"
          style={{ width: collapsed ? 64 : 244, transition: "width 300ms var(--ease-out-quint)" }}
          data-testid="app-sidebar"
        >
          {renderSidebar(collapsed)}
        </aside>

        {/* mobile top bar — a menu button opens the full sidebar as a drawer */}
        <div className="fixed inset-x-0 top-0 z-40 flex items-center gap-2 border-b border-sidebar-border bg-sidebar px-3 py-2.5 md:hidden">
          <button
            onClick={() => setMobileNavOpen(true)}
            className="shrink-0 rounded-md p-1 text-sidebar-foreground hover:bg-sidebar-accent cursor-pointer"
            title="Menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/bdia-mark.png" alt="" className="h-6 w-6 rounded-md object-cover ring-1 ring-white/10" />
          <span className="truncate text-sm font-semibold text-sidebar-accent-foreground">{currentTitle}</span>
          <button
            onClick={() => setChatOpen(true)}
            title="Ask AI"
            className="ml-auto shrink-0 rounded-md p-1.5 text-sidebar-foreground hover:bg-sidebar-accent hover:text-sidebar-accent-foreground cursor-pointer"
          >
            <Sparkles className="h-4.5 w-4.5" />
          </button>
        </div>

        <DialogPrimitive.Root open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
          <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40 md:hidden data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
            <DialogPrimitive.Content
              className="fixed left-0 top-0 z-50 flex h-screen w-72 max-w-[85vw] flex-col bg-sidebar shadow-2xl md:hidden data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left duration-200"
            >
              <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
              <DialogPrimitive.Description className="sr-only">Workspace and tool navigation</DialogPrimitive.Description>
              {renderSidebar(false)}
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        </DialogPrimitive.Root>

        {/* main content */}
        <main className="flex min-w-0 flex-1 flex-col pt-14 md:pt-0">
          {/* desktop top bar — breadcrumb + AI */}
          <header className="sticky top-0 z-30 hidden h-12 items-center gap-3 border-b border-border bg-background/85 px-5 backdrop-blur md:flex">
            <nav className="flex min-w-0 items-center gap-1.5 text-[13px]" aria-label="Breadcrumb">
              <span className="shrink-0 text-muted-foreground">{workspace.name}</span>
              {currentTitle && currentTitle !== workspace.name && (
                <>
                  <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground/40" />
                  <span className="truncate font-medium text-foreground">{currentTitle}</span>
                </>
              )}
            </nav>
            <button
              onClick={() => setChatOpen(true)}
              data-testid="ask-ai-btn"
              className="ml-auto inline-flex shrink-0 items-center gap-1.5 rounded-lg border border-border px-2.5 py-1.5 text-[13px] font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-accent cursor-pointer"
            >
              <Sparkles className="h-3.5 w-3.5 text-primary" /> Ask AI
            </button>
          </header>

          <div key={pathname} className="motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300">
            {children}
          </div>
        </main>

        <ChatPanel workspaceId={workspaceId} open={chatOpen} onOpenChange={setChatOpen} />
      </div>
    </WorkspaceContext.Provider>
  );
}
