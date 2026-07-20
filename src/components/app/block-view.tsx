"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, GripVertical, Heading as HeadingIcon, Image as ImageIcon, ListChecks, Plus, Table2, Trash2, Upload } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { TableEditor } from "@/components/app/table-editor";
import { cn, generateUUID } from "@/lib/utils";
import type {
  BlockContent,
  BlockDto,
  BlockType,
  BulletBlockContent,
  ImageBlockContent,
  SubTableDef,
  TableBlockContent,
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
  isFirst,
  isLast,
}: {
  block: BlockDto;
  onChange: (content: BlockContent) => void;
  onConvert?: (type: BlockType) => void;
  onDelete: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
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
          <TextBlockView content={block.content as TextBlockContent} onChange={onChange} onConvert={onConvert} />
        )}
        {block.type === "heading" && (
          <HeadingBlockView content={block.content as TextBlockContent} onChange={onChange} />
        )}
        {block.type === "bullet" && (
          <BulletBlockView content={block.content as BulletBlockContent} onChange={onChange} />
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
}: {
  content: TextBlockContent;
  onChange: (c: BlockContent) => void;
  onConvert?: (type: BlockType) => void;
}) {
  const [menuIndex, setMenuIndex] = React.useState(0);
  // "/" at the start of the line opens the menu; text after it filters the options, Notion-style
  const slashQuery = content.text.startsWith("/") ? content.text.slice(1) : null;
  const options =
    slashQuery === null
      ? []
      : SLASH_OPTIONS.filter((o) => o.label.toLowerCase().includes(slashQuery.toLowerCase()));
  const showMenu = !!onConvert && slashQuery !== null && options.length > 0;

  React.useEffect(() => setMenuIndex(0), [slashQuery]);

  const select = (type: BlockType) => {
    // no need to clear the text first — onConvert replaces the whole block's content,
    // and doing both would race the debounced save from onChange against the immediate convert
    onConvert?.(type);
  };

  return (
    <div className="relative">
      <Textarea
        value={content.text}
        onChange={(e) => onChange({ text: e.target.value })}
        onKeyDown={(e) => {
          if (!showMenu) return;
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

export function HeadingBlockView({ content, onChange }: { content: TextBlockContent; onChange: (c: BlockContent) => void }) {
  return (
    <Input
      value={content.text}
      onChange={(e) => onChange({ text: e.target.value })}
      placeholder="Heading"
      className="h-auto border-0 bg-transparent px-1 py-1 font-display text-lg font-semibold shadow-none focus-visible:ring-1"
    />
  );
}

export function BulletBlockView({ content, onChange }: { content: BulletBlockContent; onChange: (c: BlockContent) => void }) {
  const items = content.items;
  const setItems = (next: typeof items) => onChange({ items: next });
  return (
    <div className="space-y-1">
      {items.map((item) => (
        <div key={item.id} className="group/item flex items-center gap-2">
          <Checkbox
            checked={item.checked}
            onCheckedChange={(v) => setItems(items.map((i) => (i.id === item.id ? { ...i, checked: v === true } : i)))}
          />
          <Input
            value={item.text}
            onChange={(e) => setItems(items.map((i) => (i.id === item.id ? { ...i, text: e.target.value } : i)))}
            placeholder="List item"
            className={cn(
              "h-7 flex-1 border-0 bg-transparent px-1 shadow-none focus-visible:ring-1",
              item.checked && "text-muted-foreground line-through"
            )}
          />
          <button
            onClick={() => setItems(items.filter((i) => i.id !== item.id))}
            className="shrink-0 text-muted-foreground opacity-0 hover:text-status-bad group-hover/item:opacity-100 cursor-pointer"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      <button
        onClick={() => setItems([...items, { id: generateUUID(), text: "", checked: false }])}
        className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground hover:text-primary cursor-pointer"
      >
        <Plus className="h-3.5 w-3.5" /> Add item
      </button>
    </div>
  );
}

export function TableBlockView({ content, onChange }: { content: TableBlockContent; onChange: (c: BlockContent) => void }) {
  // Initialize multi-table structure if not present
  const tables: SubTableDef[] = React.useMemo(() => {
    if (content.tables && content.tables.length > 0) {
      return content.tables;
    }
    return [
      {
        id: "default",
        name: "Table 1",
        columns: content.columns || [{ id: generateUUID(), name: "Column 1" }],
        rows: content.rows || [],
      },
    ];
  }, [content.tables, content.columns, content.rows]);

  const activeId = content.activeTableId || tables[0].id;
  const activeTable = tables.find((t) => t.id === activeId) || tables[0];

  const updateTables = (newTables: SubTableDef[], newActiveId = activeId) => {
    onChange({
      activeTableId: newActiveId,
      tables: newTables,
      columns: [],
      rows: [],
    });
  };

  const handleAddTable = () => {
    const newId = generateUUID();
    const newTable = {
      id: newId,
      name: `Table ${tables.length + 1}`,
      columns: [{ id: generateUUID(), name: "Column 1" }],
      rows: [],
    };
    updateTables([...tables, newTable], newId);
  };

  const handleRenameTable = (id: string, name: string) => {
    const updated = tables.map((t) => (t.id === id ? { ...t, name } : t));
    updateTables(updated);
  };

  const handleDeleteTable = (id: string) => {
    if (tables.length <= 1) return;
    const remaining = tables.filter((t) => t.id !== id);
    updateTables(remaining, remaining[0].id);
  };

  return (
    <div className="space-y-2 border rounded-lg p-3 bg-card shadow-sm">
      <div className="flex items-center justify-between border-b pb-2 gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          {/* Dropdown selector for tables */}
          <select
            value={activeId}
            onChange={(e) => updateTables(tables, e.target.value)}
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
      <TableEditor
        columns={activeTable.columns}
        rows={activeTable.rows}
        onChangeColumns={(cols) => {
          const updated = tables.map((t) => (t.id === activeTable.id ? { ...t, columns: cols } : t));
          updateTables(updated);
        }}
        onChangeRows={(rows) => {
          const updated = tables.map((t) => (t.id === activeTable.id ? { ...t, rows } : t));
          updateTables(updated);
        }}
      />
    </div>
  );
}

export function ImageBlockView({ content, onChange }: { content: ImageBlockContent; onChange: (c: BlockContent) => void }) {
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
