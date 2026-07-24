"use client";

import * as React from "react";
import { Heading as HeadingIcon, Image as ImageIcon, ListChecks, Loader2, Plus, Table2, Trash2, Type } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { BlockView } from "@/components/app/block-view";
import { useDebouncedCallback } from "@/lib/use-debounced-callback";
import type { BlockContent, BlockDto, BlockType, NoteDto } from "@/lib/types";

const ADD_MENU: { type: BlockType; label: string; icon: typeof Type }[] = [
  { type: "text", label: "Text", icon: Type },
  { type: "heading", label: "Heading", icon: HeadingIcon },
  { type: "bullet", label: "Bullet list", icon: ListChecks },
  { type: "table", label: "Table", icon: Table2 },
  { type: "image", label: "Photo / Image", icon: ImageIcon },
];

/**
 * Shared block-editor body for any Note — the per-workspace Home landing page and every page
 * under /notes render the exact same editor, just pointed at a different noteId. Typing here
 * needs no "+" click to get going: a brand-new (block-less) note is auto-seeded with one empty
 * text block the instant it loads, and pressing Enter inside a text/heading block creates and
 * focuses the next block immediately, Notion-style, instead of requiring "Add block" every time.
 */
export function NoteEditor({
  noteId,
  note,
  onTitleChange,
  onDeleteNote,
  showChrome = true,
}: {
  noteId: string;
  note: NoteDto | null;
  onTitleChange?: (title: string) => void;
  onDeleteNote?: () => void;
  showChrome?: boolean;
}) {
  const [title, setTitle] = React.useState(note?.title ?? "");
  const [blocks, setBlocks] = React.useState<BlockDto[]>([]);
  const [blocksLoading, setBlocksLoading] = React.useState(true);
  const seededFor = React.useRef<string | null>(null);
  const focusRegistry = React.useRef<Record<string, { focus: () => void } | null>>({});
  const [pendingFocusId, setPendingFocusId] = React.useState<string | null>(null);

  React.useEffect(() => setTitle(note?.title ?? ""), [note?.id, note?.title]);

  React.useEffect(() => {
    setBlocksLoading(true);
    fetch(`/api/blocks?ws=${noteId}`)
      .then((r) => r.json())
      .then((d) => setBlocks(d.blocks ?? []))
      .catch(() => {})
      .finally(() => setBlocksLoading(false));
  }, [noteId]);

  // brand-new / emptied-out page: seed one text block so there's always a cursor ready to type
  React.useEffect(() => {
    if (blocksLoading || blocks.length > 0 || seededFor.current === noteId) return;
    seededFor.current = noteId;
    fetch("/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: noteId, type: "text" }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.block) {
          setBlocks([d.block]);
          setPendingFocusId(d.block.id);
        }
      });
  }, [blocksLoading, blocks.length, noteId]);

  React.useLayoutEffect(() => {
    if (pendingFocusId && focusRegistry.current[pendingFocusId]) {
      focusRegistry.current[pendingFocusId]!.focus();
      setPendingFocusId(null);
    }
  }, [pendingFocusId, blocks]);

  const saveTitle = useDebouncedCallback((t: string) => onTitleChange?.(t), 500);
  const changeTitle = (t: string) => {
    setTitle(t);
    saveTitle(t);
  };

  const saveContent = useDebouncedCallback((id: string, content: BlockContent) => {
    fetch(`/api/blocks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content }),
    });
  }, 500);

  // Accepts a plain value OR an updater function. The updater form resolves against the block's
  // truly-latest content inside the setBlocks callback — needed because a single interaction can
  // fire two changeContent calls back to back in the same tick (e.g. a table cell creating a new
  // tag option, then setting the cell to it): with a plain-value contract, both calls would
  // compute their "next content" from the same pre-update snapshot, and the second call would
  // silently discard the first's change. Chaining functional updates makes React apply them in
  // order against progressively updated state instead, so neither one is lost.
  const changeContent = (id: string, content: BlockContent | ((prev: BlockContent) => BlockContent)) => {
    setBlocks((prev) =>
      prev.map((b) => {
        if (b.id !== id) return b;
        const next = typeof content === "function" ? content(b.content) : content;
        saveContent(id, next);
        return { ...b, content: next };
      })
    );
  };

  const convertBlock = (id: string, type: BlockType) => {
    fetch(`/api/blocks/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.block) setBlocks((prev) => prev.map((b) => (b.id === id ? d.block : b)));
      });
  };

  const addBlock = async (type: BlockType) => {
    const res = await fetch("/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: noteId, type }),
    });
    if (res.ok) {
      const d = await res.json();
      setBlocks((prev) => [...prev, d.block]);
      setPendingFocusId(d.block.id);
    }
  };

  /** Enter inside a text/heading block: split off a new text block right after it and focus it. */
  const insertBlockAfter = async (index: number) => {
    const res = await fetch("/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: noteId, type: "text" }),
    });
    if (!res.ok) return;
    const d = await res.json();
    setBlocks((prev) => {
      const next = [...prev];
      next.splice(index + 1, 0, d.block);
      fetch("/api/blocks/reorder", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: next.map((b) => b.id) }),
      });
      return next;
    });
    setPendingFocusId(d.block.id);
  };

  /** Backspace on an empty text/heading block: remove it and hand focus back to the previous block. */
  const mergeIntoPrevious = (index: number) => {
    if (index === 0) return; // always keep at least one block
    const target = blocks[index];
    const prev = blocks[index - 1];
    setBlocks((b) => b.filter((x) => x.id !== target.id));
    fetch(`/api/blocks/${target.id}`, { method: "DELETE" });
    if (prev) setPendingFocusId(prev.id);
  };

  const deleteBlock = async (id: string) => {
    setBlocks((prev) => prev.filter((b) => b.id !== id));
    await fetch(`/api/blocks/${id}`, { method: "DELETE" });
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

  return (
    <div className="mx-auto max-w-screen-2xl w-full px-10 py-10">
      {showChrome && (
        <div className="mb-8 flex items-start justify-between gap-4">
          <Input
            value={title}
            onChange={(e) => changeTitle(e.target.value)}
            placeholder="Untitled"
            className="h-auto flex-1 border-0 bg-transparent px-1 py-1 font-display text-3xl font-bold tracking-tight shadow-none focus-visible:ring-0 placeholder:text-muted-foreground/30"
          />
          {onDeleteNote && (
            <button
              onClick={onDeleteNote}
              className="mt-2 flex shrink-0 items-center gap-1 text-xs text-muted-foreground/60 transition-colors hover:text-status-bad cursor-pointer"
              title="Delete this page"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Delete
            </button>
          )}
        </div>
      )}

      {blocksLoading ? (
        <div className="space-y-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="skeleton" style={{ height: 32, opacity: 1 - i * 0.2 }} />
          ))}
        </div>
      ) : (
        <>
          <div className="space-y-1">
            {blocks.map((b, i) => (
              <BlockView
                key={b.id}
                block={b}
                onChange={(content) => changeContent(b.id, content)}
                onConvert={(type) => convertBlock(b.id, type)}
                onDelete={() => deleteBlock(b.id)}
                onMoveUp={() => moveBlock(i, -1)}
                onMoveDown={() => moveBlock(i, 1)}
                onEnter={() => insertBlockAfter(i)}
                onBackspaceEmpty={() => mergeIntoPrevious(i)}
                registerFocus={(el) => {
                  focusRegistry.current[b.id] = el;
                }}
                isFirst={i === 0}
                isLast={i === blocks.length - 1}
              />
            ))}
          </div>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="sm" className="mt-2 text-muted-foreground hover:text-foreground">
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

export function NoteEditorSkeleton() {
  return (
    <div className="flex h-screen items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground/40" />
    </div>
  );
}
