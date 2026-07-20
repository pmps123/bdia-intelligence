"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowDown, ArrowUp, Heading as HeadingIcon, Image as ImageIcon, ListChecks, Loader2, Plus, Table2, Trash2, Type, FileText } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { BlockView } from "@/components/app/block-view";
import { useDebouncedCallback } from "@/lib/use-debounced-callback";
import { useWorkspace } from "@/components/app/app-shell";
import { emptyBlockContent, type BlockContent, type BlockDto, type BlockType, type NoteDto } from "@/lib/types";

const ADD_MENU: { type: BlockType; label: string; icon: typeof Type }[] = [
  { type: "text", label: "Text", icon: Type },
  { type: "heading", label: "Heading", icon: HeadingIcon },
  { type: "bullet", label: "Bullet list", icon: ListChecks },
  { type: "table", label: "Table", icon: Table2 },
  { type: "image", label: "Image", icon: ImageIcon },
];

export default function NotesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeNoteId = searchParams.get("id");
  const { workspaceId, notes, refreshNotes } = useWorkspace();

  const [activeNote, setActiveNote] = React.useState<NoteDto | null>(null);
  const [blocks, setBlocks] = React.useState<BlockDto[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [blocksLoading, setBlocksLoading] = React.useState(false);

  // 1. Auto-redirect or load notes list
  React.useEffect(() => {
    if (!activeNoteId && notes.length > 0) {
      router.replace(`/notes?id=${notes[0].id}`);
    } else if (notes.length === 0) {
      setLoading(false);
    }
  }, [activeNoteId, notes, router]);

  // 2. Fetch active note and its blocks
  React.useEffect(() => {
    if (!activeNoteId) {
      setActiveNote(null);
      setBlocks([]);
      return;
    }

    setLoading(true);
    setBlocksLoading(true);

    // Find the note from the already fetched list
    const found = notes.find((n) => n.id === activeNoteId);
    if (found) {
      setActiveNote(found);
    }

    // Load blocks belonging to this note (repuposing ws parameter to noteId)
    fetch(`/api/blocks?ws=${activeNoteId}`)
      .then((r) => r.json())
      .then((d) => setBlocks(d.blocks ?? []))
      .catch(() => {})
      .finally(() => {
        setLoading(false);
        setBlocksLoading(false);
      });
  }, [activeNoteId, notes]);

  const saveTitle = useDebouncedCallback((id: string, title: string) => {
    fetch(`/api/notes/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }).then(() => refreshNotes());
  }, 500);

  const changeTitle = (title: string) => {
    if (!activeNote) return;
    setActiveNote({ ...activeNote, title });
    saveTitle(activeNote.id, title);
  };

  const saveContent = useDebouncedCallback((id: string, content: BlockContent) => {
    fetch(`/api/blocks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
  }, 500);

  const changeContent = (id: string, content: BlockContent) => {
    setBlocks((prev) => prev.map((b) => (b.id === id ? { ...b, content } : b)));
    saveContent(id, content);
  };

  const convertBlock = (id: string, type: BlockType) => {
    const content = emptyBlockContent(type);
    setBlocks((prev) => prev.map((b) => (b.id === id ? { ...b, type, content } : b)));
    fetch(`/api/blocks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, content }),
    });
  };

  const addBlock = async (type: BlockType) => {
    if (!activeNoteId) return;
    const res = await fetch("/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: activeNoteId, type }),
    });
    if (res.ok) {
      const d = await res.json();
      setBlocks((prev) => [...prev, d.block]);
    }
  };

  const deleteBlock = async (id: string) => {
    setBlocks((prev) => prev.filter((b) => b.id !== id));
    await fetch(`/api/blocks/${id}`, { method: "DELETE" });
  };

  const deleteActiveNote = async () => {
    if (!activeNote) return;
    if (!confirm("Are you sure you want to delete this page?")) return;
    await fetch(`/api/notes/${activeNote.id}`, { method: "DELETE" });
    refreshNotes();
    router.replace("/notes");
  };

  const addFirstPage = async () => {
    const res = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: workspaceId, type: "text" }),
    });
    if (res.ok) {
      const d = await res.json();
      refreshNotes();
      router.push(`/notes?id=${d.note.id}`);
    }
  };

  const moveBlock = (index: number, dir: -1 | 1) => {
    const next = [...blocks];
    const target = index + dir;
    if (target < 0 || target >= next.length) return;
    [next[index], next[target]] = [next[target], next[index]];
    setBlocks(next);
    fetch("/api/blocks/reorder", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ids: next.map((b) => b.id) }),
    });
  };

  if (loading && notes.length > 0) {
    return (
      <div className="flex h-screen items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground/40" />
      </div>
    );
  }

  if (notes.length === 0) {
    return (
      <div className="mx-auto max-w-xl px-6 py-32 text-center">
        <FileText className="mx-auto mb-4 h-12 w-12 text-muted-foreground/30" />
        <h2 className="text-xl font-semibold tracking-tight font-display">No pages created</h2>
        <p className="mt-2 text-sm text-muted-foreground max-w-sm mx-auto">
          Create pages to take notes, compile checklist, and organize audits in your workspace.
        </p>
        <Button onClick={addFirstPage} className="mt-6 gap-2">
          <Plus className="h-4 w-4" /> Create your first page
        </Button>
      </div>
    );
  }

  if (!activeNote) return null;

  return (
    <div className="mx-auto max-w-3xl px-6 py-10">
      {/* breadcrumbs & Actions */}
      <div className="mb-4 flex items-center justify-between text-[11px] font-medium text-muted-foreground">
        <div className="flex items-center gap-1.5">
          <span className="text-primary font-semibold uppercase tracking-widest font-display">BDIA</span>
          <span>/</span>
          <span>{notes.find((n) => n.id === activeNoteId)?.title || "Untitled"}</span>
        </div>
        <button
          onClick={deleteActiveNote}
          className="flex items-center gap-1 text-muted-foreground/60 hover:text-status-bad transition-colors cursor-pointer"
          title="Delete this page"
        >
          <Trash2 className="h-3.5 w-3.5" />
          <span>Delete page</span>
        </button>
      </div>

      {/* editable page title */}
      <div className="mb-8">
        <Input
          value={activeNote.title}
          onChange={(e) => changeTitle(e.target.value)}
          placeholder="Untitled Page"
          className="h-auto border-0 bg-transparent px-1 py-1 text-3xl font-bold tracking-tight font-display shadow-none focus-visible:ring-0 placeholder:text-muted-foreground/30"
        />
      </div>

      {/* blocks rendering */}
      {blocksLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 48, opacity: 1 - i * 0.2 }} />
          ))}
        </div>
      ) : (
        <>
          <div className="space-y-2">
            {blocks.map((b, i) => (
              <BlockView
                key={b.id}
                block={b}
                onChange={(content) => changeContent(b.id, content)}
                onConvert={(type) => convertBlock(b.id, type)}
                onDelete={() => deleteBlock(b.id)}
                onMoveUp={() => moveBlock(i, -1)}
                onMoveDown={() => moveBlock(i, 1)}
                isFirst={i === 0}
                isLast={i === blocks.length - 1}
              />
            ))}
            {blocks.length === 0 && (
              <div className="rounded-xl border border-dashed px-6 py-10 text-center bg-muted/10">
                <p className="text-sm text-muted-foreground">Empty page. Type `/` in a text block or add a block below to start.</p>
              </div>
            )}
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="mt-6 text-muted-foreground hover:text-foreground">
                <Plus className="h-3.5 w-3.5" /> Add block
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {ADD_MENU.map(({ type, label, icon: Icon }) => (
                <DropdownMenuItem key={type} onSelect={() => addBlock(type)}>
                  <Icon className="h-4 w-4" /> {label}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </>
      )}
    </div>
  );
}
