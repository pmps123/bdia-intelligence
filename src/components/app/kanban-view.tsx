"use client";

import * as React from "react";
import { Plus, MoreHorizontal, Calendar, User, Tag as TagIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { TAG_COLOR_STYLES, type TagColorKey } from "@/lib/tag-colors";
import type { EditableColumn, EditableRow } from "@/components/app/table-editor";

interface KanbanViewProps {
  columns: EditableColumn[];
  rows: EditableRow[];
  groupByColumnId?: string;
  onChangeRows: (rows: EditableRow[]) => void;
  onCellChange?: (rowId: string, colId: string, value: string) => void;
  onCardClick?: (row: EditableRow) => void;
  onAddCard?: (statusValue: string) => void;
}

export function KanbanView({
  columns,
  rows,
  groupByColumnId,
  onChangeRows,
  onCellChange,
  onCardClick,
  onAddCard,
}: KanbanViewProps) {
  // Find group-by column (default to first status/select column, or first column)
  const groupCol =
    columns.find((c) => c.id === groupByColumnId) ??
    columns.find((c) => (c.type === "status" || c.type === "select") && c.options && c.options.length > 0) ??
    columns[0];

  const titleCol = columns.find((c) => c.type === "text" || c.id !== groupCol?.id) ?? columns[0];
  const dateCol = columns.find((c) => c.type === "date");
  const personCol = columns.find((c) => c.type === "person");
  const tagCol = columns.find((c) => c.type === "select" && c.id !== groupCol?.id);

  const statuses = groupCol?.options && groupCol.options.length > 0 ? groupCol.options : ["To Do", "In Progress", "Done"];

  // Group rows by status value
  const groupedRows = React.useMemo(() => {
    const map: Record<string, EditableRow[]> = {};
    statuses.forEach((s) => (map[s] = []));
    map["Unassigned"] = [];

    rows.forEach((row) => {
      const val = row.cells[groupCol.id]?.trim();
      if (val && map[val]) {
        map[val].push(row);
      } else {
        map["Unassigned"].push(row);
      }
    });

    return map;
  }, [rows, groupCol, statuses]);

  const [draggedRowId, setDraggedRowId] = React.useState<string | null>(null);

  const handleDragStart = (e: React.DragEvent, rowId: string) => {
    setDraggedRowId(rowId);
    e.dataTransfer.setData("text/plain", rowId);
  };

  const handleDrop = (e: React.DragEvent, targetStatus: string) => {
    e.preventDefault();
    if (!draggedRowId || !groupCol) return;

    const updatedRows = rows.map((r) =>
      r.id === draggedRowId ? { ...r, cells: { ...r.cells, [groupCol.id]: targetStatus } } : r
    );
    onChangeRows(updatedRows);
    onCellChange?.(draggedRowId, groupCol.id, targetStatus);
    setDraggedRowId(null);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  return (
    <div className="flex gap-4 overflow-x-auto pb-4 pt-1">
      {statuses.map((status) => {
        const cards = groupedRows[status] || [];
        const colorKey = (groupCol.optionColors?.[status] as TagColorKey) || "slate";
        const colorStyle = TAG_COLOR_STYLES[colorKey] ?? TAG_COLOR_STYLES.slate;

        return (
          <div
            key={status}
            onDragOver={handleDragOver}
            onDrop={(e) => handleDrop(e, status)}
            className="flex w-72 shrink-0 flex-col rounded-xl border bg-muted/30 p-3 shadow-xs transition-colors hover:bg-muted/50"
          >
            {/* Column Header */}
            <div className="mb-3 flex items-center justify-between px-1">
              <div className="flex items-center gap-2">
                <span
                  className="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-semibold"
                  style={{ background: colorStyle.bg, color: colorStyle.text }}
                >
                  {status}
                </span>
                <span className="text-xs font-medium text-muted-foreground">{cards.length}</span>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="h-6 w-6 text-muted-foreground hover:text-foreground"
                onClick={() => onAddCard?.(status)}
              >
                <Plus className="h-4 w-4" />
              </Button>
            </div>

            {/* Cards Area */}
            <div className="flex min-h-[150px] flex-col gap-2.5">
              {cards.map((row) => {
                const title = row.cells[titleCol.id] || "Untitled";
                const dateVal = dateCol ? row.cells[dateCol.id] : "";
                const personVal = personCol ? row.cells[personCol.id] : "";
                const tagVal = tagCol ? row.cells[tagCol.id] : "";

                return (
                  <div
                    key={row.id}
                    draggable
                    onDragStart={(e) => handleDragStart(e, row.id)}
                    onClick={() => onCardClick?.(row)}
                    className={cn(
                      "group relative cursor-grab rounded-lg border bg-card p-3 shadow-2xs transition-all hover:border-primary/40 hover:shadow-md active:cursor-grabbing",
                      draggedRowId === row.id && "opacity-40 border-dashed"
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <h4 className="line-clamp-2 text-sm font-medium leading-snug text-foreground">
                        {title}
                      </h4>
                    </div>

                    {/* Metadata chips */}
                    <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                      {tagVal && (
                        <span className="inline-flex items-center gap-1 rounded bg-secondary/80 px-1.5 py-0.5 text-[11px] font-medium text-secondary-foreground">
                          <TagIcon className="h-3 w-3" />
                          {tagVal}
                        </span>
                      )}

                      {dateVal && (
                        <span className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 text-[11px]">
                          <Calendar className="h-3 w-3" />
                          {dateVal}
                        </span>
                      )}

                      {personVal && (
                        <span className="ml-auto inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                          <User className="h-3 w-3" />
                          {personVal}
                        </span>
                      )}
                    </div>
                  </div>
                );
              })}

              {cards.length === 0 && (
                <div className="flex h-24 items-center justify-center rounded-lg border border-dashed border-muted-foreground/20 text-xs text-muted-foreground">
                  Drop cards here
                </div>
              )}
            </div>

            {/* Quick add button at bottom */}
            <Button
              variant="ghost"
              className="mt-2 w-full justify-start gap-1.5 text-xs text-muted-foreground hover:text-foreground"
              onClick={() => onAddCard?.(status)}
            >
              <Plus className="h-3.5 w-3.5" /> Add card
            </Button>
          </div>
        );
      })}
    </div>
  );
}
