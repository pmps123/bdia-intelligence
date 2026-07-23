"use client";

import * as React from "react";
import { NoteEditor, NoteEditorSkeleton } from "@/components/app/note-editor";
import { useWorkspace } from "@/components/app/app-shell";
import type { NoteDto } from "@/lib/types";

/**
 * Workspace landing: a blank, freely-editable page — not a tool dashboard. Every workspace gets
 * its own "Home" note (found or lazily created server-side), so this is exactly the same block
 * editor as any /notes page, just always at the root URL.
 */
export default function HomePage() {
  const { workspaceId } = useWorkspace();
  const [home, setHome] = React.useState<NoteDto | null>(null);

  React.useEffect(() => {
    setHome(null);
    fetch(`/api/notes/home?ws=${workspaceId}`)
      .then((r) => r.json())
      .then((d) => setHome(d.note ?? null))
      .catch(() => {});
  }, [workspaceId]);

  const saveTitle = (title: string) => {
    if (!home) return;
    fetch(`/api/notes/${home.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
  };

  if (!home) return <NoteEditorSkeleton />;

  return <NoteEditor key={home.id} noteId={home.id} note={home} onTitleChange={saveTitle} />;
}
