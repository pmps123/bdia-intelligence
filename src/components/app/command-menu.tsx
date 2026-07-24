"use client";

import * as React from "react";
import { Search, FileText, CheckSquare, Layout, Sparkles } from "lucide-react";
import { CommandDialog, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";

export function CommandMenu() {
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((open) => !open);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, []);

  return (
    <CommandDialog open={open} onOpenChange={setOpen}>
      <CommandInput placeholder="Type a command or search workspace..." />
      <CommandList>
        <CommandEmpty>No results found.</CommandEmpty>
        <CommandGroup heading="Quick Actions">
          <CommandItem onSelect={() => setOpen(false)}>
            <FileText className="mr-2 h-4 w-4" />
            <span>Create New Note</span>
          </CommandItem>
          <CommandItem onSelect={() => setOpen(false)}>
            <CheckSquare className="mr-2 h-4 w-4" />
            <span>Add Project Task</span>
          </CommandItem>
          <CommandItem onSelect={() => setOpen(false)}>
            <Layout className="mr-2 h-4 w-4" />
            <span>Switch Workspace</span>
          </CommandItem>
        </CommandGroup>
      </CommandList>
    </CommandDialog>
  );
}
