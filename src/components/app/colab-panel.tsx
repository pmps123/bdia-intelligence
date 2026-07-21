"use client";

import * as React from "react";
import { Copy, ExternalLink } from "lucide-react";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import type { ColabInstructions } from "@/lib/transform/colab";

/** No Python on Vercel — this hands the run off to Google Colab instead of a live log. */
export function ColabPanel({ instructions }: { instructions: ColabInstructions }) {
  const copy = () => {
    navigator.clipboard.writeText(instructions.command);
    toast.success("Command copied");
  };

  return (
    <div className="rounded-lg border bg-card p-4 text-sm space-y-3">
      <p className="font-medium">
        {instructions.pipelineTitle} butuh Python — website ini tidak bisa menjalankannya langsung di production. Jalankan di Google Colab:
      </p>
      <ol className="list-decimal space-y-1 pl-5 text-muted-foreground">
        <li>
          Buka{" "}
          <a href={instructions.notebookUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-primary underline">
            notebook Colab <ExternalLink className="h-3 w-3" />
          </a>
        </li>
        <li>
          Upload <code className="rounded bg-muted px-1">scripts/{instructions.script}</code> dan key BigQuery ke Colab (lihat README bagian &quot;Alternatif: menjalankan pipeline di Google Colab&quot;)
        </li>
        <li>Paste &amp; jalankan cell di bawah — link file berlaku 30 menit dari sekarang</li>
      </ol>
      <div className="relative">
        <pre className="thin-scroll max-h-56 overflow-auto rounded-md bg-muted px-3 py-2 pr-16 font-mono text-[11px] leading-relaxed whitespace-pre-wrap">
          {instructions.command}
        </pre>
        <Button size="sm" variant="outline" className="absolute right-2 top-2 h-7" onClick={copy}>
          <Copy className="h-3 w-3" /> Copy
        </Button>
      </div>
    </div>
  );
}
