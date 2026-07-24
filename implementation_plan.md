# Implementation Plan — Notion/ClickUp Clone Module

This plan details the steps to fulfill your 3 requested tasks sequentially to build the Notion/ClickUp clone features, focusing on database schema, layout/sidebar UI, and the slash command popover.

## Proposed Changes

### TUGAS 1: Skema Database (Prisma SQLite)
We will introduce `Page` and `Block` models that support hierarchy and block-based editing.

#### [MODIFY] [schema.prisma](file:///c:/Pipamas/bdia-intelligence/prisma/schema.prisma)
- Replace the legacy `Note` model with a new `Page` model.
- Add self-referencing fields (`parentId`, `parent`, `children`) to `Page` to support Notion-style tree hierarchy in the sidebar.
- Link `Page` to a `workspace`.
- Update the `Block` model to relate to a `Page` via `pageId` (Cascade delete).
- Ensure `Block.type` remains a `String` to support the wide variety of slash menu options.

### TUGAS 2: Komponen Frontend - Sidebar Notion-Style & Pelebaran Layout
We will create a new sidebar component and widen the main layout.

#### [NEW] [sidebar.tsx](file:///c:/Pipamas/bdia-intelligence/src/components/app/sidebar.tsx)
- Create a `Sidebar` component that exactly mimics Notion's structure:
  - **Workspace Switcher** at the top.
  - **Favorites** section.
  - **Private / Shared** sections with a recursive Tree view for `Page` hierarchy (collapsible/expandable).
  - **+ New Page** button at the bottom of sections.

#### [MODIFY] [app-shell.tsx](file:///c:/Pipamas/bdia-intelligence/src/components/app/app-shell.tsx)
- Integrate the new `Sidebar` component, replacing the existing static `NavItem` lists.
- Widen the main content area layout. Remove max-width constraints like `max-w-2xl` or `prose`. Apply `max-w-screen-2xl`, `w-full`, and `px-10` so tables and boards span across the screen.

### TUGAS 3: Komponen Frontend - Slash Menu Popover ('/')
We will build the robust configuration and UI for the Slash Menu.

#### [NEW] [slash-menu.tsx](file:///c:/Pipamas/bdia-intelligence/src/components/app/slash-menu.tsx)
- Create a `SlashMenu` popover component triggered by typing `/` in the editor.
- Define a comprehensive array of grouped options:
  - **Basic**: Text, Headings (1-4), Lists (Bullet, Number, To-Do, Toggle), Page, Callout, Quote, Divider, Link to Page.
  - **Media & Embeds**: Image, Video, File, Code.
  - **Database Views**: Table, Board, Gallery, List, Dashboard, Calendar, Timeline, Database Full Page.
  - **Advanced & Layout**: Chart Data, Table of Content, Toggle Headings, Columns (2, 3, 4).
  - **Mentions**: Person, Page.
- Implement the UI for this popover using standard `cmdk` or custom Radix Popover with a sleek, categorized look similar to Notion.

## Strategy for Rendering 'Database Views' (Board/Kanban, Table, etc.)
*This addresses your request for an explanation in Task 3.*
In a block-based architecture, a "Database View" (like a Kanban Board) is fundamentally just a **Block** where `type = "database_view"`. The `content` JSON of this block will store a reference to the actual Database ID (e.g., a `TableBlock` or a dedicated `Database` entity) and the view configuration (e.g., `viewType: "board"`, `groupBy: "status"`).
When the editor encounters this block type, it hands off rendering to a specialized component (like our newly built `KanbanView` or `TableEditor`). These components fetch/manage their own rows independently, but they are positioned and treated as just another block in the document stream. A "Database Full Page" is simply a Page where its *only* block is a Database View, hiding the standard text editor canvas.

## Verification Plan
1. Run `npx prisma db push` to verify and apply the schema changes safely.
2. Run `npm run dev` to ensure the layout widens correctly and the sidebar renders the new recursive `Page` structure without TypeScript errors.
3. Verify the `/` command triggers the extensive categorized menu.
