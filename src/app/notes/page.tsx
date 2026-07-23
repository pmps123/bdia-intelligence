"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { FileText, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { NoteEditor, NoteEditorSkeleton } from "@/components/app/note-editor";
import { useWorkspace } from "@/components/app/app-shell";

export default function NotesPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeNoteId = searchParams.get("id");
  const { workspaceId, notes, refreshNotes } = useWorkspace();

  React.useEffect(() => {
    if (!activeNoteId && notes.length > 0) router.replace(`/notes?id=${notes[0].id}`);
  }, [activeNoteId, notes, router]);

  const saveTitle = (title: string) => {
    if (!activeNoteId) return;
    fetch(`/api/notes/${activeNoteId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }).then(() => refreshNotes());
  };

  const deleteActiveNote = async () => {
    if (!activeNoteId) return;
    if (!confirm("Are you sure you want to delete this page?")) return;
    await fetch(`/api/notes/${activeNoteId}`, { method: "DELETE" });
    refreshNotes();
    router.replace("/notes");
  };

  const addFirstPage = async () => {
    const res = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: workspaceId, type: "text" }),
    });
    if (res.ok) {
      const d = await res.json();
      refreshNotes();
      router.push(`/notes?id=${d.note.id}`);
    }
  };

  if (notes.length === 0) {
    return (
      <div className="mx-auto max-w-xl px-6 py-32 text-center">
        <FileText className="mx-auto mb-4 h-12 w-12 text-muted-foreground/30" />
        <h2 className="font-display text-xl font-semibold tracking-tight">No pages created</h2>
        <p className="mx-auto mt-2 max-w-sm text-sm text-muted-foreground">
          Create pages to take notes, compile checklists, and organize audits in your workspace.
        </p>
        <Button onClick={addFirstPage} className="mt-6 gap-2">
          <Plus className="h-4 w-4" /> Create your first page
        </Button>
      </div>
    );
  }

  if (!activeNoteId) return <NoteEditorSkeleton />;
  const activeNote = notes.find((n) => n.id === activeNoteId) ?? null;

  return (
    <NoteEditor key={activeNoteId} noteId={activeNoteId} note={activeNote} onTitleChange={saveTitle} onDeleteNote={deleteActiveNote} />
  );
}
