"use client";

import * as React from "react";
import { Download, Eye } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/** journalism.py prints "[OK] PDF selesai: <path>" once the report is written. */
function extractReportFileName(log: string): string | null {
  const m = log.match(/PDF selesai:\s*(.+\.pdf)\s*$/im);
  if (!m) return null;
  const fullPath = m[1].trim();
  return fullPath.split(/[\\/]/).pop() ?? null;
}

/** Preview + download for the Executive Report PDF, read straight from the run log. */
export function ReportPreview({ log }: { log: string }) {
  const [open, setOpen] = React.useState(false);
  const fileName = React.useMemo(() => extractReportFileName(log), [log]);
  if (!fileName) return null;
  const url = `/api/reports/${encodeURIComponent(fileName)}`;

  return (
    <>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="outline" className="h-8 gap-1.5" onClick={() => setOpen(true)}>
          <Eye className="h-3.5 w-3.5" /> Preview
        </Button>
        <Button size="sm" variant="outline" className="h-8 gap-1.5" asChild>
          <a href={url} download={fileName}>
            <Download className="h-3.5 w-3.5" /> Download PDF
          </a>
        </Button>
      </div>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-4xl h-[85vh] p-0 overflow-hidden flex flex-col">
          <DialogHeader className="p-4 pb-0">
            <DialogTitle className="text-sm">{fileName}</DialogTitle>
          </DialogHeader>
          <iframe src={url} title={fileName} className="min-h-0 flex-1 w-full" />
        </DialogContent>
      </Dialog>
    </>
  );
}
