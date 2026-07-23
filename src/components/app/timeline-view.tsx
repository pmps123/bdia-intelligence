"use client";

import * as React from "react";
import { cn } from "@/lib/utils";
import { TAG_COLOR_STYLES, type TagColorKey } from "@/lib/tag-colors";
import type { EditableColumn, EditableRow } from "@/components/app/table-editor";

const DAY_MS = 86_400_000;
const DAY_PX = 36; // fixed day width — no zoom control in this first pass (see note below)
const ROW_H = 40;
const LABEL_W = 220;

function parseDate(s: string): Date | null {
  if (!s) return null;
  const d = new Date(s + "T00:00:00");
  return Number.isNaN(d.getTime()) ? null : d;
}
const toISO = (d: Date) => d.toISOString().slice(0, 10);
const addDays = (d: Date, n: number) => new Date(d.getTime() + n * DAY_MS);
const dayDiff = (a: Date, b: Date) => Math.round((b.getTime() - a.getTime()) / DAY_MS);

/**
 * Gantt-lite: a horizontal date ruler with one draggable bar per row. Deliberately scoped to what
 * the audit/PM workflow actually needs for a first pass — drag the bar to reschedule, drag an edge
 * to resize, a "today" marker, colored by a Status/Select column when the view has one.
 *
 * ponytail: fixed day-width (no zoom levels) and no dependency arrows — both real Gantt features,
 * left for a later pass since neither was needed to make this genuinely usable day-to-day yet.
 */
export function TimelineView({
  columns,
  rows,
  startColumnId,
  endColumnId,
  onChangeRows,
  onCellChange,
}: {
  columns: EditableColumn[];
  rows: EditableRow[];
  startColumnId: string;
  endColumnId: string;
  onChangeRows: (rows: EditableRow[]) => void;
  onCellChange?: (rowId: string, colId: string, value: string) => void;
}) {
  const titleCol = columns.find((c) => c.id !== startColumnId && c.id !== endColumnId) ?? columns[0];
  const colorCol = columns.find((c) => c.id !== startColumnId && c.id !== endColumnId && (c.type === "status" || c.type === "select") && c.optionColors);

  const items = rows
    .map((r) => {
      const start = parseDate(r.cells[startColumnId]);
      const end = parseDate(r.cells[endColumnId]) ?? start;
      return start && end ? { row: r, start: start <= end ? start : end, end: start <= end ? end : start } : null;
    })
    .filter((x): x is { row: EditableRow; start: Date; end: Date } => x !== null);

  const missingCount = rows.length - items.length;

  const [rangeStart, totalDays] = React.useMemo(() => {
    const today = new Date(new Date().toDateString());
    if (items.length === 0) return [addDays(today, -3), 14] as const;
    const min = items.reduce((m, it) => (it.start < m ? it.start : m), items[0].start);
    const max = items.reduce((m, it) => (it.end > m ? it.end : m), items[0].end);
    const withToday = today < min ? today : max < today ? today : null;
    const rs = addDays(withToday && withToday < min ? withToday : min, -2);
    const re = addDays(withToday && withToday > max ? withToday : max, 2);
    return [rs, Math.max(dayDiff(rs, re), 7)] as const;
  }, [items]);

  const trackWidth = totalDays * DAY_PX;
  const todayOffset = dayDiff(rangeStart, new Date(new Date().toDateString()));
  const dayTicks = Array.from({ length: totalDays + 1 }, (_, i) => addDays(rangeStart, i));

  const commit = (rowId: string, colId: string, iso: string) => {
    onChangeRows(rows.map((r) => (r.id === rowId ? { ...r, cells: { ...r.cells, [colId]: iso } } : r)));
    onCellChange?.(rowId, colId, iso);
  };

  const startDrag = (e: React.MouseEvent, rowId: string, start: Date, end: Date, mode: "move" | "start" | "end") => {
    e.preventDefault();
    const startX = e.clientX;
    const onMove = (ev: MouseEvent) => {
      const deltaDays = Math.round((ev.clientX - startX) / DAY_PX);
      if (deltaDays === 0) return;
      let ns = start;
      let ne = end;
      if (mode === "move") {
        ns = addDays(start, deltaDays);
        ne = addDays(end, deltaDays);
      } else if (mode === "start") {
        ns = addDays(start, Math.min(deltaDays, dayDiff(start, end)));
      } else {
        ne = addDays(end, Math.max(deltaDays, -dayDiff(start, end)));
      }
      commit(rowId, startColumnId, toISO(ns));
      commit(rowId, endColumnId, toISO(ne));
    };
    const onUp = () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  if (!titleCol) return null;

  return (
    <div className="overflow-hidden rounded-lg border bg-card">
      {missingCount > 0 && (
        <div className="border-b bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
          {missingCount} row{missingCount !== 1 ? "s" : ""} without a valid date aren&apos;t shown here — set both date fields to see them on the timeline.
        </div>
      )}
      {items.length === 0 ? (
        <div className="px-6 py-10 text-center text-sm text-muted-foreground">Add a date to a row to see it on the timeline.</div>
      ) : (
        <div className="flex overflow-x-auto thin-scroll">
          {/* fixed row-label rail */}
          <div className="sticky left-0 z-10 shrink-0 border-r bg-card" style={{ width: LABEL_W }}>
            <div className="flex items-center border-b px-3 text-xs font-semibold uppercase tracking-wide text-muted-foreground" style={{ height: 32 }}>
              {titleCol.name}
            </div>
            {items.map(({ row }) => (
              <div key={row.id} className="flex items-center truncate border-b px-3 text-sm" style={{ height: ROW_H }} title={row.cells[titleCol.id]}>
                {row.cells[titleCol.id] || <span className="text-muted-foreground/40">Untitled</span>}
              </div>
            ))}
          </div>

          {/* scrollable date track */}
          <div className="relative shrink-0" style={{ width: trackWidth }}>
            <div className="relative flex border-b" style={{ height: 32 }}>
              {dayTicks.slice(0, -1).map((d, i) => (
                <div
                  key={i}
                  className={cn(
                    "shrink-0 border-r px-1 pt-1 text-[10px] text-muted-foreground",
                    (d.getDay() === 0 || d.getDay() === 6) && "bg-muted/30"
                  )}
                  style={{ width: DAY_PX }}
                >
                  {d.getDate() === 1 || i === 0 ? d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) : d.getDate()}
                </div>
              ))}
            </div>

            {todayOffset >= 0 && todayOffset <= totalDays && (
              <div
                className="pointer-events-none absolute top-0 z-10 w-px bg-(--brand-red)"
                style={{ left: todayOffset * DAY_PX, height: 32 + items.length * ROW_H }}
              >
                <span className="absolute -left-4 top-0 rounded-b bg-(--brand-red) px-1 text-[9px] font-medium text-white">Today</span>
              </div>
            )}

            {items.map(({ row, start, end }, i) => {
              const left = dayDiff(rangeStart, start) * DAY_PX;
              const width = Math.max(DAY_PX, (dayDiff(start, end) + 1) * DAY_PX);
              const statusVal = colorCol ? row.cells[colorCol.id] : "";
              const colorKey = (colorCol?.optionColors?.[statusVal] as TagColorKey) ?? "navy";
              const style = TAG_COLOR_STYLES[colorKey] ?? TAG_COLOR_STYLES.navy;
              return (
                <div key={row.id} className="relative border-b" style={{ height: ROW_H }}>
                  {/* weekend shading continues down the row body for visual continuity */}
                  {dayTicks.slice(0, -1).map(
                    (d, di) =>
                      (d.getDay() === 0 || d.getDay() === 6) && (
                        <div key={di} className="absolute top-0 h-full bg-muted/20" style={{ left: di * DAY_PX, width: DAY_PX }} />
                      )
                  )}
                  <div
                    className="group absolute top-1.5 flex h-7 items-center overflow-hidden rounded-md px-2 text-xs font-medium shadow-sm"
                    style={{ left, width, background: style.bg, color: style.text }}
                  >
                    <div
                      onMouseDown={(e) => startDrag(e, row.id, start, end, "move")}
                      className="absolute inset-0 cursor-grab active:cursor-grabbing"
                      title={`${toISO(start)} → ${toISO(end)}`}
                    />
                    <div onMouseDown={(e) => startDrag(e, row.id, start, end, "start")} className="absolute left-0 top-0 h-full w-2 cursor-w-resize" />
                    <div onMouseDown={(e) => startDrag(e, row.id, start, end, "end")} className="absolute right-0 top-0 h-full w-2 cursor-e-resize" />
                    <span className="pointer-events-none truncate">{row.cells[titleCol.id] || "Untitled"}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
