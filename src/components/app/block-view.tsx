"use client";

import * as React from "react";
import {
  ArrowDown,
  ArrowUp,
  CalendarRange,
  GripVertical,
  Heading as HeadingIcon,
  Image as ImageIcon,
  ListChecks,
  Plus,
  Table2,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { TableEditor } from "@/components/app/table-editor";
import { TimelineView } from "@/components/app/timeline-view";
import { cn, generateUUID } from "@/lib/utils";
import type {
  BlockContent,
  BlockContentUpdater,
  BlockDto,
  BlockType,
  BulletBlockContent,
  ImageBlockContent,
  SubTableDef,
  TableBlockContent,
  TableViewDef,
  TextBlockContent,
} from "@/lib/types";

/** Notion-like "/" menu — offered from a text block, since it's already the block you're typing into. */
const SLASH_OPTIONS: { type: BlockType; label: string; icon: typeof Table2 }[] = [
  { type: "table", label: "Table", icon: Table2 },
  { type: "bullet", label: "Bullet List", icon: ListChecks },
  { type: "heading", label: "Heading", icon: HeadingIcon },
  { type: "image", label: "Photo / Image", icon: ImageIcon },
];

export function BlockView({
  block,
  onChange,
  onConvert,
  onDelete,
  onMoveUp,
  onMoveDown,
  onEnter,
  onBackspaceEmpty,
  registerFocus,
  isFirst,
  isLast,
}: {
  block: BlockDto;
  onChange: (content: BlockContentUpdater) => void;
  onConvert?: (type: BlockType) => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  /** Enter inside a text/heading block: caller splits off a new block right after this one. */
  onEnter?: () => void;
  /** Backspace on an already-empty text/heading block: caller removes this block. */
  onBackspaceEmpty?: () => void;
  /** Hands the caller a focus() handle for this block, so a newly-created sibling can be focused. */
  registerFocus?: (handle: { focus: () => void } | null) => void;
  isFirst: boolean;
  isLast: boolean;
}) {
  return (
    <div className="group relative flex gap-1.5">
      <div className="flex shrink-0 items-start gap-0.5 pt-1.5 opacity-0 transition-opacity group-hover:opacity-100">
        <GripVertical className="h-4 w-4 text-muted-foreground/40" />
        <div className="flex flex-col">
          <button
            disabled={isFirst}
            onClick={onMoveUp}
            className="text-muted-foreground hover:text-primary disabled:opacity-20 cursor-pointer disabled:cursor-default"
          >
            <ArrowUp className="h-3.5 w-3.5" />
          </button>
          <button
            disabled={isLast}
            onClick={onMoveDown}
            className="text-muted-foreground hover:text-primary disabled:opacity-20 cursor-pointer disabled:cursor-default"
          >
            <ArrowDown className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <div className="min-w-0 flex-1 py-1">
        {block.type === "text" && (
          <TextBlockView
            content={block.content as TextBlockContent}
            onChange={onChange}
            onConvert={onConvert}
            onEnter={onEnter}
            onBackspaceEmpty={onBackspaceEmpty}
            registerFocus={registerFocus}
          />
        )}
        {block.type === "heading" && (
          <HeadingBlockView
            content={block.content as TextBlockContent}
            onChange={onChange}
            onEnter={onEnter}
            onBackspaceEmpty={onBackspaceEmpty}
            registerFocus={registerFocus}
          />
        )}
        {block.type === "bullet" && (
          <BulletBlockView content={block.content as BulletBlockContent} onChange={onChange} onEmptyBackspaceOnly={onBackspaceEmpty} />
        )}
        {block.type === "table" && (
          <TableBlockView content={block.content as TableBlockContent} onChange={onChange} />
        )}
        {block.type === "image" && (
          <ImageBlockView content={block.content as ImageBlockContent} onChange={onChange} />
        )}
      </div>

      <button
        onClick={onDelete}
        title={`Delete ${block.type} block`}
        className="mt-1.5 h-fit shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-status-bad group-hover:opacity-100 cursor-pointer"
      >
        <Trash2 className="h-4 w-4" />
      </button>
    </div>
  );
}

export function TextBlockView({
  content,
  onChange,
  onConvert,
  onEnter,
  onBackspaceEmpty,
  registerFocus,
}: {
  content: TextBlockContent;
  onChange: (c: BlockContentUpdater) => void;
  onConvert?: (type: BlockType) => void;
  onEnter?: () => void;
  onBackspaceEmpty?: () => void;
  registerFocus?: (handle: { focus: () => void } | null) => void;
}) {
  const [menuIndex, setMenuIndex] = React.useState(0);
  const ref = React.useRef<HTMLTextAreaElement>(null);
  // "/" at the start of the line opens the menu; text after it filters the options, Notion-style
  const slashQuery = content.text.startsWith("/") ? content.text.slice(1) : null;
  const options =
    slashQuery === null
      ? []
      : SLASH_OPTIONS.filter((o) => o.label.toLowerCase().includes(slashQuery.toLowerCase()));
  const showMenu = !!onConvert && slashQuery !== null && options.length > 0;

  React.useEffect(() => setMenuIndex(0), [slashQuery]);
  // layout effect, not a passive one: the parent's own layout effect re-focuses a just-created
  // sibling block synchronously during the same commit, so this registration must land first —
  // a passive useEffect here would still be pending when the parent tries to read it.
  React.useLayoutEffect(() => {
    registerFocus?.({ focus: () => ref.current?.focus() });
    return () => registerFocus?.(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const select = (type: BlockType) => {
    // no need to clear the text first — onConvert replaces the whole block's content,
    // and doing both would race the debounced save from onChange against the immediate convert
    onConvert?.(type);
  };

  return (
    <div className="relative">
      <Textarea
        ref={ref}
        value={content.text}
        onChange={(e) => onChange({ text: e.target.value })}
        onKeyDown={(e) => {
          if (showMenu) {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setMenuIndex((i) => (i + 1) % options.length);
            } else if (e.key === "ArrowUp") {
              e.preventDefault();
              setMenuIndex((i) => (i - 1 + options.length) % options.length);
            } else if (e.key === "Enter") {
              e.preventDefault();
              select(options[menuIndex].type);
            } else if (e.key === "Escape") {
              e.preventDefault();
              onChange({ text: "" });
            }
            return;
          }
          // plain Enter: continue typing into a fresh block below, Notion-style — Shift+Enter
          // still inserts a literal line break within this same block, for an actual paragraph.
          if (e.key === "Enter" && !e.shiftKey && onEnter) {
            e.preventDefault();
            onEnter();
          } else if (e.key === "Backspace" && content.text === "" && onBackspaceEmpty) {
            e.preventDefault();
            onBackspaceEmpty();
          }
        }}
        placeholder="Type something, or '/' for commands…"
        rows={1}
        className="min-h-0 resize-none border-0 bg-transparent px-1 py-1 text-sm shadow-none focus-visible:ring-1"
      />
      {showMenu && (
        <div className="absolute left-0 top-full z-20 mt-1 w-56 overflow-hidden rounded-lg border bg-popover py-1 shadow-lg">
          {options.map((opt, i) => (
            <button
              key={opt.type}
              // mousedown (not click) fires before the textarea blurs, so the menu doesn't vanish first
              onMouseDown={(e) => {
                e.preventDefault();
                select(opt.type);
              }}
              className={cn(
                "flex w-full cursor-pointer items-center gap-2 px-3 py-1.5 text-left text-sm",
                i === menuIndex ? "bg-accent text-foreground" : "text-muted-foreground hover:bg-accent/50"
              )}
            >
              <opt.icon className="h-3.5 w-3.5" /> {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function HeadingBlockView({
  content,
  onChange,
  onEnter,
  onBackspaceEmpty,
  registerFocus,
}: {
  content: TextBlockContent;
  onChange: (c: BlockContentUpdater) => void;
  onEnter?: () => void;
  onBackspaceEmpty?: () => void;
  registerFocus?: (handle: { focus: () => void } | null) => void;
}) {
  const ref = React.useRef<HTMLInputElement>(null);
  // see TextBlockView: must be a layout effect so registration wins the race against the
  // parent's own layout effect trying to focus this block right after it mounts.
  React.useLayoutEffect(() => {
    registerFocus?.({ focus: () => ref.current?.focus() });
    return () => registerFocus?.(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <Input
      ref={ref}
      value={content.text}
      onChange={(e) => onChange({ text: e.target.value })}
      onKeyDown={(e) => {
        if (e.key === "Enter" && onEnter) {
          e.preventDefault();
          onEnter();
        } else if (e.key === "Backspace" && content.text === "" && onBackspaceEmpty) {
          e.preventDefault();
          onBackspaceEmpty();
        }
      }}
      placeholder="Heading"
      className="h-auto border-0 bg-transparent px-1 py-1 font-display text-lg font-semibold shadow-none focus-visible:ring-1"
    />
  );
}

export function BulletBlockView({
  content,
  onChange,
  onEmptyBackspaceOnly,
}: {
  content: BulletBlockContent;
  onChange: (c: BlockContentUpdater) => void;
  /** Backspace on the sole, already-empty item: caller removes the whole bullet block. */
  onEmptyBackspaceOnly?: () => void;
}) {
  const items = content.items;
  const setItems = (next: typeof items) => onChange({ items: next });
  const refs = React.useRef<Record<string, HTMLInputElement | null>>({});
  const pendingFocusId = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (pendingFocusId.current && refs.current[pendingFocusId.current]) {
      refs.current[pendingFocusId.current]!.focus();
      pendingFocusId.current = null;
    }
  }, [items]);

  const addItemAfter = (index: number) => {
    const id = generateUUID();
    const next = [...items];
    next.splice(index + 1, 0, { id, text: "", checked: false });
    pendingFocusId.current = id;
    setItems(next);
  };

  const removeItemAndFocusPrev = (index: number) => {
    if (items.length <= 1) {
      onEmptyBackspaceOnly?.();
      return;
    }
    const prev = items[index - 1];
    setItems(items.filter((_, i) => i !== index));
    if (prev) pendingFocusId.current = prev.id;
  };

  return (
    <div className="space-y-1">
      {items.length === 0 && (
        <button
          onClick={() => setItems([{ id: generateUUID(), text: "", checked: false }])}
          className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground hover:text-primary cursor-pointer"
        >
          <Plus className="h-3.5 w-3.5" /> Add item
        </button>
      )}
      {items.map((item, i) => (
        <div key={item.id} className="group/item flex items-center gap-2">
          <Checkbox
            checked={item.checked}
            onCheckedChange={(v) => setItems(items.map((x) => (x.id === item.id ? { ...x, checked: v === true } : x)))}
          />
          <Input
            ref={(el) => {
              refs.current[item.id] = el;
            }}
            value={item.text}
            onChange={(e) => setItems(items.map((x) => (x.id === item.id ? { ...x, text: e.target.value } : x)))}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addItemAfter(i);
              } else if (e.key === "Backspace" && item.text === "") {
                e.preventDefault();
                removeItemAndFocusPrev(i);
              }
            }}
            placeholder="List item"
            className={cn(
              "h-7 flex-1 border-0 bg-transparent px-1 shadow-none focus-visible:ring-1",
              item.checked && "text-muted-foreground line-through"
            )}
          />
          <button
            onClick={() => setItems(items.filter((x) => x.id !== item.id))}
            className="shrink-0 text-muted-foreground opacity-0 hover:text-status-bad group-hover/item:opacity-100 cursor-pointer"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      {items.length > 0 && (
        <button
          onClick={() => addItemAfter(items.length - 1)}
          className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground hover:text-primary cursor-pointer"
        >
          <Plus className="h-3.5 w-3.5" /> Add item
        </button>
      )}
    </div>
  );
}

const DEFAULT_VIEW: TableViewDef = { id: "table-view", name: "Table View", type: "table" };

/** "+ Add view" — Table is one click; Timeline needs to know which Date columns are start/end, so
 *  picking those is a second step in the same popover rather than a whole separate dialog. */
function AddViewMenu({
  dateColumns,
  onAdd,
}: {
  dateColumns: { id: string; name: string }[];
  onAdd: (view: TableViewDef) => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [pickingTimeline, setPickingTimeline] = React.useState(false);
  const [startId, setStartId] = React.useState("");
  const [endId, setEndId] = React.useState("");

  const openTimelinePicker = () => {
    setStartId(dateColumns[0]?.id ?? "");
    setEndId(dateColumns[1]?.id ?? dateColumns[0]?.id ?? "");
    setPickingTimeline(true);
  };

  const reset = () => {
    setPickingTimeline(false);
    setOpen(false);
  };

  return (
    <Popover open={open} onOpenChange={(o) => { setOpen(o); if (!o) setPickingTimeline(false); }}>
      <PopoverTrigger asChild>
        <button className="flex h-7 w-7 items-center justify-center rounded text-muted-foreground hover:bg-accent hover:text-primary cursor-pointer" title="Add view">
          <Plus className="h-3.5 w-3.5" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-60 p-1.5">
        {!pickingTimeline ? (
          <div className="space-y-0.5">
            <button
              onClick={() => {
                onAdd({ id: generateUUID(), name: "Table View", type: "table" });
                reset();
              }}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
            >
              <Table2 className="h-4 w-4" /> Table
            </button>
            <button
              onClick={openTimelinePicker}
              disabled={dateColumns.length === 0}
              title={dateColumns.length === 0 ? "Add a Date column first" : undefined}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer"
            >
              <CalendarRange className="h-4 w-4" /> Timeline
            </button>
          </div>
        ) : (
          <div className="space-y-2 p-1">
            <p className="text-xs font-medium text-muted-foreground">Which Date columns define each bar?</p>
            <label className="block text-xs">
              Start
              <select value={startId} onChange={(e) => setStartId(e.target.value)} className="mt-0.5 h-7 w-full rounded border bg-transparent px-1.5 text-sm">
                {dateColumns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-xs">
              End
              <select value={endId} onChange={(e) => setEndId(e.target.value)} className="mt-0.5 h-7 w-full rounded border bg-transparent px-1.5 text-sm">
                {dateColumns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <Button
              size="sm"
              className="h-7 w-full text-xs"
              onClick={() => {
                onAdd({ id: generateUUID(), name: "Timeline", type: "timeline", startColumnId: startId, endColumnId: endId });
                reset();
              }}
            >
              Create timeline view
            </Button>
          </div>
        )}
      </PopoverContent>
    </Popover>
  );
}

/** Same normalization the component's useMemo does, as a pure function — reusable inside a
 *  functional onChange updater, which always resolves against the truly-latest content rather
 *  than whatever content this component instance last rendered with. */
function tablesFromContent(c: TableBlockContent): SubTableDef[] {
  if (c.tables && c.tables.length > 0) return c.tables;
  return [{ id: "default", name: "Table 1", columns: c.columns?.length ? c.columns : [{ id: generateUUID(), name: "Column 1" }], rows: c.rows ?? [] }];
}

export function TableBlockView({ content, onChange }: { content: TableBlockContent; onChange: (c: BlockContentUpdater) => void }) {
  const tables: SubTableDef[] = React.useMemo(() => tablesFromContent(content), [content]);

  const activeId = content.activeTableId || tables[0].id;
  const activeTable = tables.find((t) => t.id === activeId) || tables[0];
  const views = activeTable.views && activeTable.views.length > 0 ? activeTable.views : [DEFAULT_VIEW];
  const activeView = views.find((v) => v.id === activeTable.activeViewId) ?? views[0];
  const dateColumns = activeTable.columns.filter((c) => c.type === "date").map((c) => ({ id: c.id, name: c.name }));

  // Resolves against the latest content at apply-time (not this render's closure) so that two
  // edits fired back to back in one interaction (e.g. TagCellEditor creating a new option, then
  // setting the cell to it — two separate onChangeColumns/onChangeRows calls) compose instead of
  // the second one silently overwriting the first.
  const updateTables = (compute: (prevTables: SubTableDef[], prevActiveId: string) => { tables: SubTableDef[]; activeId: string }) => {
    onChange((prevContent) => {
      const prevTables = tablesFromContent(prevContent as TableBlockContent);
      const prevActiveId = (prevContent as TableBlockContent).activeTableId || prevTables[0].id;
      const result = compute(prevTables, prevActiveId);
      return { activeTableId: result.activeId, tables: result.tables, columns: [], rows: [] };
    });
  };
  const patchActiveTable = (patch: Partial<SubTableDef>) =>
    updateTables((prevTables, prevActiveId) => {
      const targetId = prevTables.some((t) => t.id === activeTable.id) ? activeTable.id : prevActiveId;
      return { tables: prevTables.map((t) => (t.id === targetId ? { ...t, ...patch } : t)), activeId: targetId };
    });

  const handleAddTable = () => {
    const newId = generateUUID();
    updateTables((prevTables) => ({
      tables: [...prevTables, { id: newId, name: `Table ${prevTables.length + 1}`, columns: [{ id: generateUUID(), name: "Column 1" }], rows: [] }],
      activeId: newId,
    }));
  };

  const handleRenameTable = (id: string, name: string) => {
    updateTables((prevTables, prevActiveId) => ({ tables: prevTables.map((t) => (t.id === id ? { ...t, name } : t)), activeId: prevActiveId }));
  };

  const handleDeleteTable = (id: string) => {
    updateTables((prevTables, prevActiveId) => {
      if (prevTables.length <= 1) return { tables: prevTables, activeId: prevActiveId };
      const remaining = prevTables.filter((t) => t.id !== id);
      return { tables: remaining, activeId: remaining[0].id };
    });
  };

  const addView = (view: TableViewDef) => patchActiveTable({ views: [...views, view], activeViewId: view.id });
  const removeView = (id: string) => {
    if (views.length <= 1) return;
    const remaining = views.filter((v) => v.id !== id);
    patchActiveTable({ views: remaining, activeViewId: remaining[0].id });
  };

  return (
    <div className="space-y-2 border rounded-lg p-3 bg-card shadow-sm">
      <div className="flex items-center justify-between border-b pb-2 gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          {/* Dropdown selector for tables */}
          <select
            value={activeId}
            onChange={(e) => {
              const newId = e.target.value;
              updateTables((prevTables) => ({ tables: prevTables, activeId: newId }));
            }}
            className="text-xs font-semibold bg-transparent border rounded px-2 py-1 focus:ring-1 cursor-pointer font-display text-foreground"
          >
            {tables.map((t) => (
              <option key={t.id} value={t.id} className="bg-popover text-foreground">
                {t.name}
              </option>
            ))}
          </select>
          <input
            type="text"
            value={activeTable.name}
            onChange={(e) => handleRenameTable(activeTable.id, e.target.value)}
            className="text-xs px-2 py-1 border rounded w-32 bg-background font-display"
            placeholder="Rename Table"
          />
        </div>
        <div className="flex items-center gap-1">
          <Button variant="outline" size="sm" onClick={handleAddTable} className="h-7 text-[11px] px-2">
            <Plus className="h-3 w-3 mr-1" /> Add Table
          </Button>
          {tables.length > 1 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => handleDeleteTable(activeTable.id)}
              className="h-7 text-[11px] px-2 text-status-bad hover:bg-status-bad/10"
            >
              Delete
            </Button>
          )}
        </div>
      </div>

      {/* view tabs — same rows/columns, a different way of looking at them (Notion-style) */}
      <div className="flex items-center gap-1 pb-1">
        {views.map((v) => (
          <div key={v.id} className={cn("group/view flex items-center gap-1 rounded-md", v.id === activeView.id ? "bg-accent" : "hover:bg-accent/50")}>
            <button
              onClick={() => patchActiveTable({ activeViewId: v.id })}
              className={cn(
                "flex items-center gap-1.5 rounded-md px-2 py-1 text-xs font-medium cursor-pointer",
                v.id === activeView.id ? "text-accent-foreground" : "text-muted-foreground"
              )}
            >
              {v.type === "timeline" ? <CalendarRange className="h-3.5 w-3.5" /> : <Table2 className="h-3.5 w-3.5" />}
              {v.name}
            </button>
            {views.length > 1 && (
              <button
                onClick={() => removeView(v.id)}
                className="mr-1 shrink-0 text-muted-foreground opacity-0 hover:text-status-bad group-hover/view:opacity-100 cursor-pointer"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>
        ))}
        <AddViewMenu dateColumns={dateColumns} onAdd={addView} />
      </div>

      {activeView.type === "timeline" && activeView.startColumnId && activeView.endColumnId ? (
        <TimelineView
          columns={activeTable.columns}
          rows={activeTable.rows}
          startColumnId={activeView.startColumnId}
          endColumnId={activeView.endColumnId}
          onChangeRows={(rows) => patchActiveTable({ rows })}
        />
      ) : (
        <TableEditor
          columns={activeTable.columns}
          rows={activeTable.rows}
          onChangeColumns={(cols) => patchActiveTable({ columns: cols })}
          onChangeRows={(rows) => patchActiveTable({ rows })}
        />
      )}
    </div>
  );
}

export function ImageBlockView({ content, onChange }: { content: ImageBlockContent; onChange: (c: BlockContentUpdater) => void }) {
  const fileRef = React.useRef<HTMLInputElement>(null);

  const onFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => onChange({ ...content, url: String(reader.result) });
    reader.readAsDataURL(file);
  };

  return (
    <div className="space-y-2">
      {content.url ? (
        // eslint-disable-next-line @next/next/no-img-element -- content.url may be a pasted link or a data: URI, both unsuitable for next/image
        <img src={content.url} alt={content.caption || ""} className="max-h-80 rounded-lg border object-contain" />
      ) : (
        <div className="flex h-28 items-center justify-center rounded-lg border-2 border-dashed border-border/60 text-sm text-muted-foreground">
          No image yet
        </div>
      )}
      <div className="flex items-center gap-2">
        <Input
          value={content.url.startsWith("data:") ? "" : content.url}
          onChange={(e) => onChange({ ...content, url: e.target.value })}
          placeholder="Paste image URL…"
          className="h-8 flex-1 text-xs"
        />
        <Button type="button" variant="outline" size="sm" className="h-8 gap-1.5" onClick={() => fileRef.current?.click()}>
          <Upload className="h-3.5 w-3.5" /> Upload
        </Button>
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onFile(f);
            e.target.value = "";
          }}
        />
      </div>
      <Input
        value={content.caption ?? ""}
        onChange={(e) => onChange({ ...content, caption: e.target.value })}
        placeholder="Caption (optional)"
        className="h-7 border-0 bg-transparent px-1 text-xs text-muted-foreground shadow-none focus-visible:ring-1"
      />
    </div>
  );
}
