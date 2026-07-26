"use client";

import * as React from "react";
// Tambahkan Maximize2 untuk ikon "Open"
import { Clock, AlignLeft, Maximize2 } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import type { EditableColumn, EditableRow } from "@/components/app/table-editor";

interface TaskDetailDrawerProps {
  row: EditableRow | null;
  columns: EditableColumn[];
  onClose: () => void;
  onCellChange: (rowId: string, colId: string, value: string) => void;
  // Prop baru untuk menangani aksi Buka sebagai Halaman Penuh
  onOpenAsPage?: (rowId: string) => void;
}

export function TaskDetailDrawer({
  row,
  columns,
  onClose,
  onCellChange,
  onOpenAsPage, // Ekstrak prop di sini
}: TaskDetailDrawerProps) {
  if (!row) return null;

  const titleCol = columns.find((c) => c.type === "text") ?? columns[0];
  const titleVal = row.cells[titleCol.id] || "";

  return (
    <Dialog open={!!row} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl sm:max-w-2xl overflow-y-auto max-h-[85vh] p-6">
        <DialogHeader className="flex flex-row items-center justify-between border-b pb-4 gap-4">
          <DialogTitle className="text-xl font-semibold flex items-center gap-2 flex-1">
            <Input
              value={titleVal}
              placeholder="Task Title..."
              onChange={(e) => onCellChange(row.id, titleCol.id, e.target.value)}
              className="text-lg font-semibold border-0 bg-transparent px-1 focus-visible:ring-1"
            />
          </DialogTitle>
          {/* Tombol Open as Page persis seperti Notion */}
          {onOpenAsPage && (
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                onOpenAsPage(row.id);
                onClose(); // Tutup drawer modal saat beralih ke halaman penuh
              }}
              className="flex items-center gap-1.5 h-8 text-xs shrink-0"
            >
              <Maximize2 className="h-3.5 w-3.5" />
              Open
            </Button>
          )}
        </DialogHeader>

        {/* Property Grid */}
        <div className="grid grid-cols-2 gap-4 py-4 border-b text-sm">
          {columns.map((col) => {
            if (col.id === titleCol.id) return null;
            const val = row.cells[col.id] || "";

            return (
              <div key={col.id} className="flex items-center gap-3">
                <span className="w-28 font-medium text-muted-foreground truncate">{col.name}</span>
                <div className="flex-1 min-w-0">
                  {col.type === "select" || col.type === "status" ? (
                    <select
                      value={val}
                      onChange={(e) => onCellChange(row.id, col.id, e.target.value)}
                      className="w-full rounded border bg-background px-2 py-1 text-xs"
                    >
                      <option value="">— Select —</option>
                      {(col.options || []).map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  ) : col.type === "date" ? (
                    <Input
                      type="date"
                      value={val}
                      onChange={(e) => onCellChange(row.id, col.id, e.target.value)}
                      className="h-7 text-xs border-muted"
                    />
                  ) : (
                    <Input
                      value={val}
                      onChange={(e) => onCellChange(row.id, col.id, e.target.value)}
                      className="h-7 text-xs border-muted"
                    />
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Description & Notes */}
        <div className="space-y-2 py-4">
          <div className="flex items-center gap-2 font-medium text-sm text-foreground">
            <AlignLeft className="h-4 w-4 text-muted-foreground" />
            <span>Description & Notes</span>
          </div>
          <Textarea
            placeholder="Add detailed task notes, instructions, or acceptance criteria..."
            rows={5}
            value={row.cells["_description"] || ""}
            onChange={(e) => onCellChange(row.id, "_description", e.target.value)}
            className="w-full text-sm resize-y focus-visible:ring-1"
          />
        </div>

        {/* Activity Footer */}
        <div className="pt-2 border-t flex items-center justify-between text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            <Clock className="h-3.5 w-3.5" /> ID: {row.id.slice(0, 8)}
          </span>
          <Button size="sm" onClick={onClose}>
            Done
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}