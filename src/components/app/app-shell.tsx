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
  NotebookText,
  StickyNote,
  Users,
  LogOut,
  ChevronRight,
  MessageCircle,
  Plus,
  FileText,
  Menu,
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
  { tool: "priceAudit", href: "/", label: "Price Audit", icon: ShieldCheck, match: (p) => p === "/" || p.startsWith("/project") },
  { tool: "salesDashboard", href: "/transform", label: "Sales Dashboard", icon: LayoutDashboard, match: (p) => p.startsWith("/transform") && p !== "/transform/marketing" },
  { tool: "marketing", href: "/transform/marketing", label: "Marketing", icon: Megaphone, match: (p) => p === "/transform/marketing" },
  { tool: "salesman", href: "/salesman", label: "Salesman", icon: Users, match: (p) => p === "/salesman" },
];

/* ---------- workspace switcher ---------- */

const WorkspaceSwitcher = React.memo(function WorkspaceSwitcher({
  workspaceId,
  onChange,
}: {
  workspaceId: string;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const current = getWorkspace(workspaceId);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger className="flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-sidebar-accent cursor-pointer group">
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary font-display text-[13px] font-bold tracking-tight text-primary-foreground shadow-sm">
          {current.name.slice(0, 1)}
        </div>
        <div className="min-w-0 flex-1 leading-tight">
          <div className="truncate font-display text-[13px] font-semibold text-sidebar-accent-foreground">
            {current.name}
          </div>
          <div className="truncate text-[11px] text-sidebar-foreground/70">BDIA Intelligence</div>
        </div>
        <ChevronsUpDown className="h-3.5 w-3.5 shrink-0 text-sidebar-foreground/50 group-hover:text-sidebar-foreground/80 transition-colors" />
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
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary shadow-md">
            <span className="font-display text-2xl font-bold text-primary-foreground">B</span>
          </div>
          <div className="text-[11px] font-semibold uppercase tracking-widest text-primary mb-1">BDIA Intelligence</div>
          <h1 className="text-2xl font-semibold tracking-tight font-display">Choose your workspace</h1>
          <p className="mt-2 text-sm text-muted-foreground">Pick the workspace you work in to continue.</p>
        </div>

        <div className="grid gap-2">
          {WORKSPACES.map((w) => (
            <button
              key={w.id}
              onClick={() => onPick(w.id)}
              className="flex items-center gap-3 rounded-xl border bg-card px-4 py-3.5 text-left text-sm transition-all hover:border-primary/60 hover:bg-accent hover:shadow-sm cursor-pointer group"
            >
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary font-display text-[15px] font-bold text-primary-foreground shadow-sm group-hover:scale-105 transition-transform">
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
}: {
  href: string;
  label: string;
  icon: React.ElementType;
  active: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "relative flex items-center gap-2.5 rounded-md px-3 py-1.5 text-[13px] font-medium transition-colors",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground border-l-2 border-primary pl-[calc(0.75rem-2px)]"
          : "text-sidebar-foreground hover:bg-sidebar-accent/70 hover:text-sidebar-accent-foreground border-l-2 border-transparent pl-[calc(0.75rem-2px)]"
      )}
    >
      <Icon className={cn("h-[15px] w-[15px] shrink-0", active ? "text-primary" : "text-sidebar-foreground/60")} />
      <span className="truncate">{label}</span>
    </Link>
  );
}

function NavSection({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="px-3 pb-1 pt-0.5 text-[10px] font-semibold uppercase tracking-widest text-sidebar-foreground/40">
        {label}
      </div>
      {children}
    </div>
  );
}

const STORAGE_KEY = "bdia.workspace";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [workspaceId, setWorkspaceIdState] = React.useState<string | null>(null);
  const [ready, setReady] = React.useState(false);
  const [chatOpen, setChatOpen] = React.useState(false);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const [notes, setNotes] = React.useState<any[]>([]);

  React.useEffect(() => {
    setMobileNavOpen(false);
  }, [pathname]);

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
  const mobileTitle = toolNav.find((t) => t.match(pathname))?.label ?? activeNote?.title ?? workspace.name;

  const sidebar = (
    <>
      {/* workspace switcher */}
      <div className="px-2 pt-1 pb-2">
        <WorkspaceSwitcher workspaceId={workspaceId} onChange={setWorkspaceId} />
      </div>

      {/* divider */}
      <div className="mx-3 border-t border-sidebar-border" />

      {/* nav */}
      <nav className="flex flex-1 flex-col gap-4 overflow-y-auto py-3 px-2 thin-scroll">
        <div className="flex flex-col gap-0.5">
          <div className="px-3 pb-1 pt-0.5 flex items-center justify-between group">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-sidebar-foreground/40">
              Pages
            </span>
            <button
              onClick={handleAddNote}
              className="opacity-0 group-hover:opacity-100 p-0.5 hover:bg-sidebar-accent rounded transition-all cursor-pointer text-sidebar-foreground/60"
              title="Add page"
            >
              <Plus className="h-3 w-3" />
            </button>
          </div>
          {notes.map((n) => {
            const isNoteActive = pathname === "/notes" && activeNoteId === n.id;
            return (
              <NavItem
                key={n.id}
                href={`/notes?id=${n.id}`}
                label={n.title || "Untitled"}
                icon={FileText}
                active={isNoteActive}
              />
            );
          })}
          {notes.length === 0 && (
            <p className="px-3 py-1.5 text-xs text-sidebar-foreground/40 italic">No pages yet.</p>
          )}
        </div>

        <NavSection label="Tools">
          {toolNav.map(({ href, label, icon: Icon, match }) => (
            <NavItem key={href} href={href} label={label} icon={Icon} active={match(pathname)} />
          ))}
          {toolNav.length === 0 && (
            <p className="px-3 py-1.5 text-xs text-sidebar-foreground/50">No tools assigned yet.</p>
          )}
        </NavSection>
      </nav>

      {/* footer */}
      <div className="border-t border-sidebar-border px-3 py-3 space-y-1">
        <button
          onClick={signOut}
          className="flex w-full items-center gap-2 rounded-md px-1 py-1 text-[12px] text-sidebar-foreground/60 hover:text-primary transition-colors cursor-pointer group"
        >
          <LogOut className="h-3.5 w-3.5 group-hover:text-primary" />
          <span>Not {workspace.name.replace(" Workspace", "")}? Sign out</span>
        </button>
        <p className="text-[11px] leading-relaxed text-sidebar-foreground/40 px-1">
          Upload · Run · BigQuery
        </p>
      </div>
    </>
  );

  return (
    <WorkspaceContext.Provider value={{ workspaceId, setWorkspaceId, signOut, notes, refreshNotes }}>
      <div className="flex min-h-screen bg-background text-foreground">
        {/* desktop sidebar */}
        <aside
          className="sticky top-0 hidden h-screen shrink-0 flex-col border-r border-sidebar-border bg-sidebar md:flex overflow-hidden transition-all duration-300"
          style={{ width: "var(--sidebar-width, 240px)" }}
        >
          {sidebar}
        </aside>

        {/* mobile top bar — a menu button opens the full sidebar as a drawer, instead of cramming nav inline */}
        <div className="fixed inset-x-0 top-0 z-40 flex items-center gap-2 border-b border-sidebar-border bg-sidebar px-3 py-2.5 md:hidden">
          <button
            onClick={() => setMobileNavOpen(true)}
            className="shrink-0 rounded-md p-1 text-sidebar-foreground hover:bg-sidebar-accent cursor-pointer"
            title="Menu"
          >
            <Menu className="h-5 w-5" />
          </button>
          <span className="truncate font-display text-sm font-semibold text-sidebar-accent-foreground">{mobileTitle}</span>
        </div>

        <DialogPrimitive.Root open={mobileNavOpen} onOpenChange={setMobileNavOpen}>
          <DialogPrimitive.Portal>
            <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40 md:hidden data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
            <DialogPrimitive.Content
              className="fixed left-0 top-0 z-50 flex h-screen w-72 max-w-[85vw] flex-col bg-sidebar shadow-2xl md:hidden data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-left data-[state=open]:slide-in-from-left duration-200"
            >
              <DialogPrimitive.Title className="sr-only">Navigation</DialogPrimitive.Title>
              <DialogPrimitive.Description className="sr-only">Workspace and tool navigation</DialogPrimitive.Description>
              {sidebar}
            </DialogPrimitive.Content>
          </DialogPrimitive.Portal>
        </DialogPrimitive.Root>

        {/* main content */}
        <main className="min-w-0 flex-1 pt-14 md:pt-0">
          <div key={pathname} className="motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-1 motion-safe:duration-300">
            {children}
          </div>
        </main>

        {/* chat AI — floating trigger + slide-over panel, available on every page */}
        <button
          onClick={() => setChatOpen(true)}
          title="Chat AI"
          className="fixed bottom-5 right-5 z-40 flex h-12 w-12 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105 cursor-pointer"
        >
          <MessageCircle className="h-5 w-5" />
        </button>
        <ChatPanel workspaceId={workspaceId} open={chatOpen} onOpenChange={setChatOpen} />
      </div>
    </WorkspaceContext.Provider>
  );
}
