"use client";

import * as React from "react";
import { Plus, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn, generateUUID } from "@/lib/utils";

export interface EditableColumn {
  id: string;
  name: string;
  type?: "text" | "select"; // default text
  options?: string[]; // for type "select"
  width?: number; // px, user-resized — falls back to auto width when unset
}

const MIN_COL_WIDTH = 80;
const DEFAULT_COL_WIDTH = 140; // columns without a saved width still get a legible minimum instead of being squeezed to fit the viewport
const ACTION_COL_WIDTH = 36;

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
 * Generic editable grid — shared by the workspace page's table block, Notes
 * tables, and (with fixed columns + a select type) the Salesman table.
 * Omit `onChangeColumns` to lock the column set (rows still editable).
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

  const addColumn = () =>
    onChangeColumns?.([...columns, { id: generateUUID(), name: `Column ${columns.length + 1}` }]);
  const renameColumn = (id: string, name: string) => onChangeColumns?.(columns.map((c) => (c.id === id ? { ...c, name } : c)));
  const removeColumn = (id: string) => onChangeColumns?.(columns.filter((c) => c.id !== id));
  const resizeColumn = (id: string, width: number) => onChangeColumns?.(columns.map((c) => (c.id === id ? { ...c, width } : c)));

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
              {columns.map((col) => (
                <TableHead key={col.id} className="group/col relative overflow-hidden">
                  {onChangeColumns ? (
                    <div className="flex items-center gap-1">
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
                    <span className="block truncate">{col.name}</span>
                  )}
                  {onChangeColumns && <ColumnResizeHandle onResize={(w) => resizeColumn(col.id, w)} />}
                </TableHead>
              ))}
              {onChangeColumns && (
                <TableHead className="w-9">
                  <button onClick={addColumn} className="text-muted-foreground hover:text-primary cursor-pointer">
                    <Plus className="h-3.5 w-3.5" />
                  </button>
                </TableHead>
              )}
              <TableHead className="w-9" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((row) => (
              <TableRow key={row.id} className="group">
                {columns.map((col) =>
                  col.type === "select" ? (
                    <TableCell key={col.id}>
                      <select
                        value={row.cells[col.id] ?? ""}
                        onChange={(e) => setCell(row.id, col.id, e.target.value)}
                        className={cn(
                          "h-8 w-full rounded-md border bg-transparent px-2 text-sm outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        )}
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
                  ) : (
                    <TableCell key={col.id}>
                      <Input
                        value={row.cells[col.id] ?? ""}
                        onChange={(e) => setCell(row.id, col.id, e.target.value)}
                        className="h-8 border-0 bg-transparent px-1 shadow-none focus-visible:ring-1"
                      />
                    </TableCell>
                  )
                )}
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
