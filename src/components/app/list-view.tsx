"use client";

import * as React from "react";
import { Plus, Calendar, User, Tag as TagIcon, CheckSquare, Square, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { TAG_COLOR_STYLES, type TagColorKey } from "@/lib/tag-colors";
import type { EditableColumn, EditableRow } from "@/components/app/table-editor";

interface ListViewProps {
  columns: EditableColumn[];
  rows: EditableRow[];
  onChangeRows: (rows: EditableRow[]) => void;
  onCellChange?: (rowId: string, colId: string, value: string) => void;
  onRowClick?: (row: EditableRow) => void;
  onAddRow?: () => void;
  onRemoveRow?: (id: string) => void;
}

export function ListView({
  columns,
  rows,
  onChangeRows,
  onCellChange,
  onRowClick,
  onAddRow,
  onRemoveRow,
}: ListViewProps) {
  const titleCol = columns.find((c) => c.type === "text") ?? columns[0];
  const statusCol = columns.find((c) => c.type === "status" || c.type === "select");
  const dateCol = columns.find((c) => c.type === "date");
  const personCol = columns.find((c) => c.type === "person");
  const checkboxCol = columns.find((c) => c.type === "checkbox");

  const toggleCheckbox = (e: React.MouseEvent, rowId: string) => {
    e.stopPropagation();
    if (!checkboxCol) return;
    const current = rows.find((r) => r.id === rowId)?.cells[checkboxCol.id] === "true";
    const nextVal = current ? "false" : "true";
    
    onChangeRows(
      rows.map((r) => (r.id === rowId ? { ...r, cells: { ...r.cells, [checkboxCol.id]: nextVal } } : r))
    );
    onCellChange?.(rowId, checkboxCol.id, nextVal);
  };

  return (
    <div className="rounded-xl border bg-card p-2 shadow-xs">
      <div className="flex flex-col divide-y divide-border/50">
        {rows.map((row) => {
          const title = row.cells[titleCol.id] || "Untitled Task";
          const statusVal = statusCol ? row.cells[statusCol.id] : "";
          const dateVal = dateCol ? row.cells[dateCol.id] : "";
          const personVal = personCol ? row.cells[personCol.id] : "";
          const isChecked = checkboxCol ? row.cells[checkboxCol.id] === "true" : false;

          const statusColorKey = (statusCol?.optionColors?.[statusVal] as TagColorKey) || "slate";
          const statusStyle = TAG_COLOR_STYLES[statusColorKey] ?? TAG_COLOR_STYLES.slate;

          return (
            <div
              key={row.id}
              onClick={() => onRowClick?.(row)}
              className="group flex cursor-pointer items-center justify-between gap-3 px-3 py-2.5 transition-colors hover:bg-muted/50 rounded-lg"
            >
              {/* Left Title & Checkbox */}
              <div className="flex min-w-0 items-center gap-3">
                {checkboxCol && (
                  <button
                    type="button"
                    onClick={(e) => toggleCheckbox(e, row.id)}
                    className="text-muted-foreground hover:text-primary transition-colors cursor-pointer"
                  >
                    {isChecked ? (
                      <CheckSquare className="h-4 w-4 text-primary" />
                    ) : (
                      <Square className="h-4 w-4" />
                    )}
                  </button>
                )}

                <span
                  className={`truncate text-sm font-medium ${
                    isChecked ? "line-through text-muted-foreground" : "text-foreground"
                  }`}
                >
                  {title}
                </span>
              </div>

              {/* Right Properties */}
              <div className="flex items-center gap-2.5 shrink-0 text-xs">
                {statusVal && (
                  <span
                    className="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium"
                    style={{ background: statusStyle.bg, color: statusStyle.text }}
                  >
                    {statusVal}
                  </span>
                )}

                {dateVal && (
                  <span className="inline-flex items-center gap-1 text-muted-foreground bg-muted/80 px-2 py-0.5 rounded">
                    <Calendar className="h-3 w-3" />
                    {dateVal}
                  </span>
                )}

                {personVal && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 font-medium text-primary">
                    <User className="h-3 w-3" />
                    {personVal}
                  </span>
                )}

                {onRemoveRow && (
                  <Button
                    size="icon"
                    variant="ghost"
                    className="h-7 w-7 text-muted-foreground opacity-0 hover:text-destructive group-hover:opacity-100 transition-opacity"
                    onClick={(e) => {
                      e.stopPropagation();
                      onRemoveRow(row.id);
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </Button>
                )}
              </div>
            </div>
          );
        })}

        {rows.length === 0 && (
          <div className="py-8 text-center text-sm text-muted-foreground">
            No items in list view.
          </div>
        )}
      </div>

      <div className="pt-2 px-1">
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start gap-2 text-xs text-muted-foreground hover:text-foreground"
          onClick={onAddRow}
        >
          <Plus className="h-3.5 w-3.5" /> Add Task
        </Button>
      </div>
    </div>
  );
}
