"use client";

import * as React from "react";
import {
  Type,
  Heading1,
  Heading2,
  Heading3,
  Heading4,
  List,
  ListOrdered,
  CheckSquare,
  ListCollapse,
  FileText,
  MessageSquareQuote,
  Minus,
  Link,
  Image as ImageIcon,
  Video,
  File,
  Code,
  Table,
  Kanban,
  LayoutGrid,
  ListTodo,
  LayoutDashboard,
  Calendar,
  Clock,
  Database,
  BarChart,
  ListTree,
  Columns2,
  Columns3,
  Columns4,
  AtSign,
  FileSearch,
  Bell
} from "lucide-react";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";

export type SlashMenuItem = {
  id: string;
  label: string;
  icon: React.ElementType;
  description?: string;
  type: string;
};

export type SlashMenuGroup = {
  name: string;
  items: SlashMenuItem[];
};

export const SLASH_MENU_GROUPS: SlashMenuGroup[] = [
  {
    name: "Basic",
    items: [
      { id: "text", label: "Text", type: "text", icon: Type, description: "Just start typing with plain text." },
      { id: "h1", label: "Heading 1", type: "heading_1", icon: Heading1, description: "Big section heading." },
      { id: "h2", label: "Heading 2", type: "heading_2", icon: Heading2, description: "Medium section heading." },
      { id: "h3", label: "Heading 3", type: "heading_3", icon: Heading3, description: "Small section heading." },
      { id: "h4", label: "Heading 4", type: "heading_4", icon: Heading4, description: "Extra small section heading." },
      { id: "bullet", label: "Bullet List", type: "bullet", icon: List, description: "Create a simple bulleted list." },
      { id: "number", label: "Number List", type: "number", icon: ListOrdered, description: "Create a numbered list." },
      { id: "todo", label: "To-Do List", type: "todo", icon: CheckSquare, description: "Track tasks with a to-do list." },
      { id: "toggle", label: "Toggle List", type: "toggle", icon: ListCollapse, description: "Toggles can hide and show content inside." },
      { id: "page", label: "Page", type: "page", icon: FileText, description: "Embed a sub-page inside this page." },
      { id: "callout", label: "Callout", type: "callout", icon: Bell, description: "Make writing stand out." },
      { id: "quote", label: "Quote", type: "quote", icon: MessageSquareQuote, description: "Capture a quote." },
      { id: "divider", label: "Divider", type: "divider", icon: Minus, description: "Visually divide blocks." },
      { id: "link_page", label: "Link to Page", type: "link_page", icon: Link, description: "Link to an existing page." },
    ],
  },
  {
    name: "Media & Embeds",
    items: [
      { id: "image", label: "Image", type: "image", icon: ImageIcon, description: "Upload or embed with a link." },
      { id: "video", label: "Video", type: "video", icon: Video, description: "Embed from YouTube, Vimeo, etc." },
      { id: "file", label: "File", type: "file", icon: File, description: "Upload a PDF, Excel, Word, etc." },
      { id: "code", label: "Code", type: "code", icon: Code, description: "Capture a code snippet." },
    ],
  },
  {
    name: "Database Views",
    items: [
      { id: "db_table", label: "Table view", type: "database_view", icon: Table, description: "Display a database as a table." },
      { id: "db_board", label: "Board view", type: "database_view", icon: Kanban, description: "Display a database as a Kanban board." },
      { id: "db_gallery", label: "Gallery view", type: "database_view", icon: LayoutGrid, description: "Display a database as a visual gallery." },
      { id: "db_list", label: "List view", type: "database_view", icon: ListTodo, description: "Display a database as a compact list." },
      { id: "db_dashboard", label: "Dashboard view", type: "database_view", icon: LayoutDashboard, description: "Display a database as a metric dashboard." },
      { id: "db_calendar", label: "Calendar view", type: "database_view", icon: Calendar, description: "Display a database as a calendar." },
      { id: "db_timeline", label: "Timeline view", type: "database_view", icon: Clock, description: "Display a database as a Gantt chart." },
      { id: "db_full", label: "Database Full Page", type: "database_full", icon: Database, description: "Create a full page database." },
    ],
  },
  {
    name: "Advanced & Layout",
    items: [
      { id: "chart", label: "Chart Data", type: "chart", icon: BarChart, description: "Visualize data with a chart." },
      { id: "toc", label: "Table of Content", type: "toc", icon: ListTree, description: "Show an outline of this page." },
      { id: "toggle_h1", label: "Toggle Heading 1", type: "toggle_h1", icon: Heading1, description: "Hide content inside a large heading." },
      { id: "toggle_h2", label: "Toggle Heading 2", type: "toggle_h2", icon: Heading2, description: "Hide content inside a medium heading." },
      { id: "toggle_h3", label: "Toggle Heading 3", type: "toggle_h3", icon: Heading3, description: "Hide content inside a small heading." },
      { id: "col_2", label: "2 Columns", type: "column_2", icon: Columns2, description: "Create 2 columns of blocks." },
      { id: "col_3", label: "3 Columns", type: "column_3", icon: Columns3, description: "Create 3 columns of blocks." },
      { id: "col_4", label: "4 Columns", type: "column_4", icon: Columns4, description: "Create 4 columns of blocks." },
    ],
  },
  {
    name: "Mentions",
    items: [
      { id: "mention_person", label: "Mention Person", type: "mention_person", icon: AtSign, description: "Notify a teammate." },
      { id: "mention_page", label: "Mention Page", type: "mention_page", icon: FileSearch, description: "Link to another page here." },
    ],
  },
];

interface SlashMenuProps {
  onSelect: (type: string, id: string) => void;
  query?: string;
}

export function SlashMenu({ onSelect, query = "" }: SlashMenuProps) {
  // If we had a floating popover, this would be wrapped in a Popover/Dialog
  // But for the block editor, it usually renders directly anchored to the block cursor
  
  return (
    <div className="w-80 rounded-lg border bg-popover text-popover-foreground shadow-lg overflow-hidden animate-in fade-in zoom-in-95">
      <Command shouldFilter={true} className="border-none max-h-96">
        <CommandInput placeholder="Type to filter..." value={query} className="hidden" />
        <CommandList className="max-h-[350px] overflow-y-auto thin-scroll">
          <CommandEmpty>No matching blocks.</CommandEmpty>
          
          {SLASH_MENU_GROUPS.map((group) => (
            <CommandGroup key={group.name} heading={group.name} className="px-1 py-2 text-muted-foreground">
              {group.items.map((item) => (
                <CommandItem
                  key={item.id}
                  value={item.label}
                  onSelect={() => onSelect(item.type, item.id)}
                  className="flex items-center gap-3 rounded-md px-2 py-1.5 cursor-pointer aria-selected:bg-accent aria-selected:text-accent-foreground"
                >
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded border bg-background text-foreground/70 shadow-sm">
                    <item.icon className="h-5 w-5" />
                  </div>
                  <div className="flex flex-col">
                    <span className="text-sm font-medium leading-none text-foreground">{item.label}</span>
                    {item.description && (
                      <span className="text-[11px] text-muted-foreground mt-1 line-clamp-1">{item.description}</span>
                    )}
                  </div>
                </CommandItem>
              ))}
            </CommandGroup>
          ))}
        </CommandList>
      </Command>
    </div>
  );
}
