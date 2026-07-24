# Design: Nested Pages for the Notes Module

## Context

The Notes module (`src/app/notes`, `Note` model) already works like a lightweight Notion clone: each `Note` is a page with a title and an ordered list of blocks (text/heading/bullet/table/image), scoped per workspace. Pages are currently flat — the sidebar renders them as a single unordered list, with one special pinned page (`order: -1`) acting as the workspace's Home page.

This feature adds page hierarchy: any page can have sub-pages, rendered as an expandable tree in the sidebar, matching the core navigation model of Notion/ClickUp-style knowledge bases.

**Scope note:** this is a documentation/knowledge-base improvement to the existing Notes module — not a broader "project management" system (tasks, boards, assignees). That was explicitly descoped during brainstorming; if task/board features are wanted later, they get their own spec.

## Data model

Add a self-relation to `Note`:

```prisma
model Note {
  id        String   @id @default(cuid())
  workspace String
  title     String   @default("Untitled")
  type      String
  content   String
  order     Int      @default(0)
  parentId  String?
  parent    Note?    @relation("NoteHierarchy", fields: [parentId], references: [id], onDelete: Cascade)
  children  Note[]   @relation("NoteHierarchy")
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt

  @@index([workspace])
  @@index([parentId])
}
```

- `parentId` null = root-level page (includes the pinned Home page, which never has a parent and is excluded from the tree UI as today).
- `onDelete: Cascade` means deleting a page deletes its entire sub-tree at the database level — no manual recursive-delete logic needed.
- `order` is now interpreted as "order among siblings sharing the same `parentId`" rather than a single global sequence. Existing rows (all `parentId = null` after migration) keep working unchanged since they're all siblings at the root.

## API changes

- `POST /api/notes` — accept optional `parentId` in the body. When creating, compute `last` (for the new `order` value) scoped to `{ workspace, parentId }` instead of just `{ workspace }`.
- `PATCH /api/notes/[id]` — accept optional `parentId` (including explicit `null` to move back to root) to support "Move to...". No other change to this route.
- `DELETE /api/notes/[id]` — unchanged; cascade is handled by the DB via the schema relation.
- `GET /api/notes` — unchanged response shape (already returns full rows, so `parentId` comes along for free). Tree construction happens client-side from the flat list, same as the current flat rendering does today.

## UI changes

**Sidebar tree** (`app-shell.tsx`, where `notes.filter(...).map(...)` currently renders a flat list):
- Replace the flat map with a recursive tree component that groups notes by `parentId`, starting from `null`.
- Each node shows an expand/collapse chevron if it has children. Expanded/collapsed state persists in `localStorage`, keyed per workspace, so it survives navigation (the sidebar re-renders on every route change).
- Indentation reflects depth.
- Hover reveals a "+" button per node (in addition to the existing top-level "Add page" button) that creates a new child page under that node and navigates to it.

**Breadcrumb** (`note-editor.tsx` / its header): show the ancestor chain resolved from the flat `notes` list already available via `useWorkspace()` (walk `parentId` up to root). Each ancestor is a clickable link to `/notes?id=<id>`.

**Move to...** (page's existing three-dot menu): new menu item opens a searchable list of all pages in the workspace, excluding the page itself and all of its descendants (computed client-side by walking `children` from the flat list) to prevent creating a cycle. Includes a "No parent (root)" option to move a page back to the top level. Selecting an option calls `PATCH /api/notes/[id]` with the new `parentId`.

**Delete confirmation**: before calling `DELETE`, compute the descendant count client-side (same tree walk as above) and adjust the existing `confirm()` message to state how many sub-pages will be deleted along with it when that count is greater than zero.

## Out of scope (deliberately deferred)

- Drag-and-drop reparenting — "Move to..." covers the need for v1; drag-drop can be added later if it turns out to be worth the added complexity (drop-zone indicators, cross-parent drag reordering).
- Reordering across different parents via drag — sibling order still uses the existing up/down controls, now scoped to siblings sharing a `parentId`.
- The pinned Home page (`order: -1`) participating in the hierarchy — it stays a special, parent-less, tree-excluded page exactly as it behaves today.
- Any task/board/assignee functionality — explicitly out of scope for this spec (see Context).

## Testing

- Prisma migration applied cleanly against the Supabase Postgres instance (session-mode port, per existing project convention — see `project_memory.md`).
- Manual verification in the browser: create a sub-page, expand/collapse persists across navigation, breadcrumb renders and links correctly, "Move to..." excludes descendants and successfully reparents, deleting a parent with children removes the whole subtree and the sidebar updates.
