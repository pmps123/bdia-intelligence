"use client";

import * as React from "react";
import {
  Calendar,
  CheckSquare,
  Hash,
  Link as LinkIcon,
  ListFilter,
  Plus,
  SquareUser,
  Tag as TagIcon,
  Trash2,
  Type as TypeIcon,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, generateUUID } from "@/lib/utils";
import { TAG_COLOR_STYLES, nextTagColor, type TagColorKey } from "@/lib/tag-colors";
import type { ColumnType } from "@/lib/types";

export interface EditableColumn {
  id: string;
  name: string;
  type?: ColumnType; // default "text"
  options?: string[]; // "select" | "status" | "person"
  /** option label -> TagColorKey. Present only on columns created through the typed-column picker
   *  (below) — a "select" column that predates it (e.g. Salesman's fixed schema) has none, and
   *  keeps rendering as the original plain native <select>, unchanged. */
  optionColors?: Record<string, string>;
  width?: number; // px, user-resized — falls back to auto width when unset
}

const MIN_COL_WIDTH = 80;
const DEFAULT_COL_WIDTH = 140; // columns without a saved width still get a legible minimum instead of being squeezed to fit the viewport
const ACTION_COL_WIDTH = 36;

const TYPE_META: Record<ColumnType, { label: string; icon: typeof TypeIcon }> = {
  text: { label: "Text", icon: TypeIcon },
  number: { label: "Number", icon: Hash },
  select: { label: "Select", icon: TagIcon },
  status: { label: "Status", icon: ListFilter },
  date: { label: "Date", icon: Calendar },
  person: { label: "Person", icon: SquareUser },
  checkbox: { label: "Checkbox", icon: CheckSquare },
  url: { label: "URL", icon: LinkIcon },
};
const TYPE_ORDER: ColumnType[] = ["text", "number", "select", "status", "date", "person", "checkbox", "url"];

/** Colored pill (Select/Status) or avatar chip (Person) for one option value. */
function Tag({ label, color, avatar }: { label: string; color?: string; avatar?: boolean }) {
  const style = TAG_COLOR_STYLES[(color as TagColorKey) ?? "slate"] ?? TAG_COLOR_STYLES.slate;
  if (avatar) {
    return (
      <span className="flex min-w-0 items-center gap-1.5">
        <span
          className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold"
          style={{ background: style.bg, color: style.text }}
        >
          {label.trim().slice(0, 1).toUpperCase() || "?"}
        </span>
        <span className="truncate text-sm">{label}</span>
      </span>
    );
  }
  return (
    <span
      className="inline-flex max-w-full items-center truncate rounded px-1.5 py-0.5 text-xs font-medium"
      style={{ background: style.bg, color: style.text }}
    >
      {label}
    </span>
  );
}

/** Click-to-open tag picker for Select/Status/Person cells: pick an existing colored option, or type to create a new one (auto-colored), Notion-style. */
function TagCellEditor({
  value,
  options,
  optionColors,
  onChange,
  onCreateOption,
  avatar,
}: {
  value: string;
  options: string[];
  optionColors: Record<string, string>;
  onChange: (value: string) => void;
  onCreateOption: (label: string) => void;
  avatar?: boolean;
}) {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const filtered = query ? options.filter((o) => o.toLowerCase().includes(query.toLowerCase())) : options;
  const exact = options.some((o) => o.toLowerCase() === query.trim().toLowerCase());

  const pick = (label: string) => {
    if (!options.some((o) => o === label)) onCreateOption(label);
    onChange(label);
    setOpen(false);
  };

  return (
    <Popover
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        if (!o) setQuery("");
      }}
    >
      <PopoverTrigger asChild>
        <button className="flex h-8 w-full items-center rounded px-1 text-left cursor-pointer hover:bg-accent/40">
          {value ? <Tag label={value} color={optionColors[value]} avatar={avatar} /> : <span className="px-1 text-sm text-muted-foreground/40">Empty</span>}
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-56 p-1.5" align="start">
        <input
          autoFocus
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && query.trim() && !exact) pick(query.trim());
          }}
          placeholder={avatar ? "Search or add a name…" : "Search or create…"}
          className="mb-1.5 h-7 w-full rounded border bg-transparent px-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        <div className="max-h-48 space-y-0.5 overflow-y-auto">
          {value && (
            <button
              onClick={() => {
                onChange("");
                setOpen(false);
              }}
              className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent cursor-pointer"
            >
              <X className="h-3 w-3" /> Clear
            </button>
          )}
          {filtered.map((opt) => (
            <button key={opt} onClick={() => pick(opt)} className="flex w-full items-center rounded px-1.5 py-1 hover:bg-accent cursor-pointer">
              <Tag label={opt} color={optionColors[opt]} avatar={avatar} />
            </button>
          ))}
          {query.trim() && !exact && (
            <button
              onClick={() => pick(query.trim())}
              className="flex w-full items-center gap-1.5 rounded px-2 py-1 text-xs text-primary hover:bg-accent cursor-pointer"
            >
              <Plus className="h-3 w-3" /> Create &ldquo;{query.trim()}&rdquo;
            </button>
          )}
          {filtered.length === 0 && !query && <p className="px-2 py-1 text-xs text-muted-foreground/60">No options yet — type to add one.</p>}
        </div>
      </PopoverContent>
    </Popover>
  );
}

/** Drag handle on a column's right edge — reports the new width as the pointer moves. */
function ColumnResizeHandle({ onResize }: { onResize: (width: number) => void }) {
  const onMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    const th = e.currentTarget.closest("th");
    const startWidth = th?.getBoundingClientRect().width ?? 160;
    const startX = e.clientX;
    const onMove = (ev: MouseEvent) => onResize(Math.max(MIN_COL_WIDTH, startWidth + (ev.clientX - startX)));
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };
  return (
    <div
      onMouseDown={onMouseDown}
      className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize select-none hover:bg-primary/40 active:bg-primary/50"
    />
  );
}

export interface EditableRow {
  id: string;
  cells: Record<string, string>;
}

/**
 * Generic editable grid — shared by the workspace page's table block, Notes tables, and (with
 * fixed columns + a plain "select" type) the Salesman table. Omit `onChangeColumns` to lock the
 * column set (rows still editable).
 */
export function TableEditor({
  columns,
  rows,
  onChangeColumns,
  onChangeRows,
  newRow,
  onAddRow,
  onRemoveRow,
  onCellChange,
}: {
  columns: EditableColumn[];
  rows: EditableRow[];
  onChangeColumns?: (columns: EditableColumn[]) => void;
  onChangeRows: (rows: EditableRow[]) => void;
  newRow?: () => EditableRow;
  /** Override the "Add row" button — use when rows are individual DB records that must be created server-side first. */
  onAddRow?: () => void;
  /** Fired (in addition to the local removal) when a row is deleted — use to delete the server-side record. */
  onRemoveRow?: (id: string) => void;
  /** Fired (in addition to onChangeRows) with the precise field that changed — use for per-field autosave instead of diffing. */
  onCellChange?: (rowId: string, colId: string, value: string) => void;
}) {
  const addRow = () => (onAddRow ? onAddRow() : onChangeRows([...rows, newRow ? newRow() : { id: generateUUID(), cells: {} }]));
  const removeRow = (id: string) => {
    onChangeRows(rows.filter((r) => r.id !== id));
    onRemoveRow?.(id);
  };
  const setCell = (rowId: string, colId: string, value: string) => {
    onChangeRows(rows.map((r) => (r.id === rowId ? { ...r, cells: { ...r.cells, [colId]: value } } : r)));
    onCellChange?.(rowId, colId, value);
  };

  const addColumn = (type: ColumnType) =>
    onChangeColumns?.([...columns, { id: generateUUID(), name: TYPE_META[type].label, type }]);
  const renameColumn = (id: string, name: string) => onChangeColumns?.(columns.map((c) => (c.id === id ? { ...c, name } : c)));
  const removeColumn = (id: string) => onChangeColumns?.(columns.filter((c) => c.id !== id));
  const resizeColumn = (id: string, width: number) => onChangeColumns?.(columns.map((c) => (c.id === id ? { ...c, width } : c)));
  const createOption = (colId: string, label: string) => {
    const col = columns.find((c) => c.id === colId);
    if (!col || (col.options ?? []).includes(label)) return;
    const existing = col.options ?? [];
    onChangeColumns?.(
      columns.map((c) =>
        c.id === colId
          ? { ...c, options: [...existing, label], optionColors: { ...(c.optionColors ?? {}), [label]: nextTagColor(existing.length) } }
          : c
      )
    );
  };

  // explicit total width (never just "100% of viewport") — narrow screens scroll horizontally
  // instead of squeezing every column down to an illegible sliver
  const tableWidth =
    columns.reduce((sum, c) => sum + (c.width ?? DEFAULT_COL_WIDTH), 0) + (onChangeColumns ? ACTION_COL_WIDTH : 0) + ACTION_COL_WIDTH;

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      <div className="overflow-x-auto">
        <Table style={{ tableLayout: "fixed", width: tableWidth, minWidth: tableWidth }}>
          <colgroup>
            {columns.map((col) => (
              <col key={col.id} style={{ width: col.width ?? DEFAULT_COL_WIDTH }} />
            ))}
            {onChangeColumns && <col style={{ width: ACTION_COL_WIDTH }} />}
            <col style={{ width: ACTION_COL_WIDTH }} />
          </colgroup>
          <TableHeader>
            <TableRow>
              {columns.map((col) => {
                const Icon = TYPE_META[col.type ?? "text"].icon;
                return (
                  <TableHead key={col.id} className="group/col relative overflow-hidden">
                    {onChangeColumns ? (
                      <div className="flex items-center gap-1">
                        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
                        <Input
                          value={col.name}
                          onChange={(e) => renameColumn(col.id, e.target.value)}
                          className="h-7 border-0 bg-transparent px-1 font-medium shadow-none focus-visible:ring-1"
                        />
                        {columns.length > 1 && (
                          <button
                            onClick={() => removeColumn(col.id)}
                            className="shrink-0 text-muted-foreground opacity-0 hover:text-status-bad group-hover/col:opacity-100 cursor-pointer"
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        )}
                      </div>
                    ) : (
                      <span className="flex items-center gap-1.5 truncate">
                        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground/60" />
                        {col.name}
                      </span>
                    )}
                    {onChangeColumns && <ColumnResizeHandle onResize={(w) => resizeColumn(col.id, w)} />}
                  </TableHead>
                );
              })}
              {onChangeColumns && (
                <TableHead className="w-9">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button className="text-muted-foreground hover:text-primary cursor-pointer" title="Add column">
                        <Plus className="h-3.5 w-3.5" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start">
                      {TYPE_ORDER.map((type) => {
                        const meta = TYPE_META[type];
                        return (
                          <DropdownMenuItem key={type} onSelect={() => addColumn(type)}>
                            <meta.icon className="h-4 w-4" /> {meta.label}
                          </DropdownMenuItem>
                        );
                      })}
                    </DropdownMenuContent>
                  </DropdownMenu>
                </TableHead>
              )}
              <TableHead className="w-9" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id} className="group">
                {columns.map((col) => {
                  const value = row.cells[col.id] ?? "";
                  const type = col.type ?? "text";

                  // colored tag picker: any "status"/"person" column, or a "select" column that
                  // was created with color assignments — a plain options-only "select" (e.g.
                  // Salesman's fixed schema) falls through to the original native <select> below,
                  // completely unchanged.
                  if (type === "status" || type === "person" || (type === "select" && col.optionColors)) {
                    return (
                      <TableCell key={col.id}>
                        <TagCellEditor
                          value={value}
                          options={col.options ?? []}
                          optionColors={col.optionColors ?? {}}
                          onChange={(v) => setCell(row.id, col.id, v)}
                          onCreateOption={(label) => createOption(col.id, label)}
                          avatar={type === "person"}
                        />
                      </TableCell>
                    );
                  }

                  if (type === "select") {
                    return (
                      <TableCell key={col.id}>
                        <select
                          value={value}
                          onChange={(e) => setCell(row.id, col.id, e.target.value)}
                          className="h-8 w-full rounded-md border bg-transparent px-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        >
                          <option value="" disabled>
                            —
                          </option>
                          {(col.options ?? []).map((opt) => (
                            <option key={opt} value={opt}>
                              {opt}
                            </option>
                          ))}
                        </select>
                      </TableCell>
                    );
                  }

                  if (type === "checkbox") {
                    return (
                      <TableCell key={col.id} className="text-center">
                        <Checkbox checked={value === "true"} onCheckedChange={(v) => setCell(row.id, col.id, v === true ? "true" : "false")} />
                      </TableCell>
                    );
                  }

                  if (type === "date") {
                    return (
                      <TableCell key={col.id}>
                        <Input
                          type="date"
                          value={value}
                          onChange={(e) => setCell(row.id, col.id, e.target.value)}
                          className="h-8 border-0 bg-transparent px-1 shadow-none focus-visible:ring-1"
                        />
                      </TableCell>
                    );
                  }

                  if (type === "number") {
                    return (
                      <TableCell key={col.id}>
                        <Input
                          type="number"
                          value={value}
                          onChange={(e) => setCell(row.id, col.id, e.target.value)}
                          className="h-8 border-0 bg-transparent px-1 text-right tabular-nums shadow-none focus-visible:ring-1"
                        />
                      </TableCell>
                    );
                  }

                  if (type === "url") {
                    return (
                      <TableCell key={col.id}>
                        <div className="flex items-center gap-1">
                          <Input
                            value={value}
                            onChange={(e) => setCell(row.id, col.id, e.target.value)}
                            placeholder="https://…"
                            className="h-8 border-0 bg-transparent px-1 shadow-none focus-visible:ring-1"
                          />
                          {value && (
                            <a
                              href={value}
                              target="_blank"
                              rel="noreferrer"
                              className="shrink-0 text-muted-foreground hover:text-primary"
                              title="Open link"
                            >
                              <LinkIcon className="h-3.5 w-3.5" />
                            </a>
                          )}
                        </div>
                      </TableCell>
                    );
                  }

                  return (
                    <TableCell key={col.id}>
                      <Input
                        value={value}
                        onChange={(e) => setCell(row.id, col.id, e.target.value)}
                        className="h-8 border-0 bg-transparent px-1 shadow-none focus-visible:ring-1"
                      />
                    </TableCell>
                  );
                })}
                {onChangeColumns && <TableCell />}
                <TableCell>
                  <Button
                    size="icon"
                    variant="ghost"
                    onClick={() => removeRow(row.id)}
                    className="h-7 w-7 text-muted-foreground opacity-0 hover:text-status-bad group-hover:opacity-100"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {rows.length === 0 && (
              <TableRow>
                <TableCell colSpan={columns.length + (onChangeColumns ? 2 : 1)} className="p-4 text-center text-muted-foreground">
                  No rows yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <button
        onClick={addRow}
        className="flex w-full items-center gap-1.5 border-t px-3 py-2 text-xs text-muted-foreground transition-colors hover:bg-accent/50 hover:text-primary cursor-pointer"
      >
        <Plus className="h-3.5 w-3.5" /> Add row
      </button>
    </div>
  );
}
