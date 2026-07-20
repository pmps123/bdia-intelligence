"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { Bot, Loader2, Send, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

interface ChatMessageDto {
  id: string;
  role: string;
  content: string;
  model?: string | null;
  createdAt: string;
}

export function ChatPanel({
  workspaceId,
  open,
  onOpenChange,
}: {
  workspaceId: string;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const [messages, setMessages] = React.useState<ChatMessageDto[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [sending, setSending] = React.useState(false);
  const [input, setInput] = React.useState("");
  const scrollRef = React.useRef<HTMLDivElement>(null);

  const load = React.useCallback(() => {
    setLoading(true);
    fetch(`/api/chat?ws=${workspaceId}`)
      .then((r) => r.json())
      .then((d) => setMessages(d.messages ?? []))
      .finally(() => setLoading(false));
  }, [workspaceId]);

  React.useEffect(() => {
    if (open) load();
  }, [open, load]);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, sending]);

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    setInput("");
    setMessages((prev) => [...prev, { id: `tmp-${Date.now()}`, role: "user", content: text, createdAt: new Date().toISOString() }]);
    setSending(true);
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: workspaceId, message: text }),
    });
    const d = await res.json().catch(() => ({}));
    setSending(false);
    if (d.message) setMessages((prev) => [...prev, d.message]);
    else load();
  };

  const clearChat = async () => {
    await fetch(`/api/chat?ws=${workspaceId}`, { method: "DELETE" });
    setMessages([]);
  };

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/40 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0" />
        <DialogPrimitive.Content
          className={cn(
            "fixed right-0 top-0 z-50 flex h-screen w-full max-w-sm flex-col border-l bg-card shadow-2xl",
            "duration-200 data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:slide-out-to-right data-[state=open]:slide-in-from-right"
          )}
        >
          <div className="flex items-center justify-between border-b px-4 py-3">
            <div className="flex items-center gap-2">
              <Bot className="h-4 w-4 text-primary" />
              <DialogPrimitive.Title className="text-sm font-semibold">Chat AI</DialogPrimitive.Title>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={clearChat}
                title="Clear chat"
                className="rounded p-1.5 text-muted-foreground hover:bg-muted hover:text-status-bad cursor-pointer"
              >
                <Trash2 className="h-3.5 w-3.5" />
              </button>
              <DialogPrimitive.Close className="rounded p-1.5 text-muted-foreground hover:bg-muted cursor-pointer">
                <X className="h-4 w-4" />
              </DialogPrimitive.Close>
            </div>
          </div>

          <div ref={scrollRef} className="thin-scroll flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {loading ? (
              <p className="text-xs text-muted-foreground">Loading…</p>
            ) : messages.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                Tanya apa saja soal workspace ini — notes, salesman, atau project Price Audit yang aktif.
              </p>
            ) : (
              messages.map((m) => (
                <div key={m.id} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
                  <div
                    className={cn(
                      "max-w-[85%] whitespace-pre-wrap rounded-lg px-3 py-2 text-sm",
                      m.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted text-foreground"
                    )}
                  >
                    {m.content}
                    {m.model && <div className="mt-1 text-[10px] opacity-60">{m.model}</div>}
                  </div>
                </div>
              ))
            )}
            {sending && (
              <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Loader2 className="h-3 w-3 animate-spin" /> Thinking…
              </div>
            )}
          </div>

          <div className="border-t p-3">
            <div className="flex items-end gap-2">
              <Textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    send();
                  }
                }}
                placeholder="Tulis pesan…"
                rows={2}
                className="min-h-0 resize-none text-sm"
              />
              <Button size="sm" className="h-9 shrink-0" onClick={send} disabled={sending || !input.trim()}>
                <Send className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
