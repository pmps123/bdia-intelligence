# Design: Complete the Notion/ClickUp Clone (Notes/Blocks Module)

## Context

`implementation_plan.md` describes building a Notion/ClickUp-style Notes module: Supabase-backed `Page`/`Block` schema, a wide app shell, a recursive sidebar, and a categorized slash menu with ~30 block types.

Reading the actual codebase (as of commit `19e70be`, "mulai fokus project management") shows most of the surface-level UI already exists: `Page`/`Block` schema, `/api/notes` + `/api/blocks` CRUD, the wide `app-shell.tsx` layout, the recursive `sidebar.tsx`, and a fully categorized `slash-menu.tsx` component. But three things are broken or disconnected, and one thing is a bigger decision than the plan doc accounts for:

1. **DB provider mismatch**: `schema.prisma` declares `postgresql` but `.env`'s `DATABASE_URL` still points at local `prisma/dev.db` (sqlite) — this breaks `prisma generate`/any query as-is.
2. **`slash-menu.tsx` is decorative**: it offers ~30 block types, but `api/blocks/route.ts` only accepts 5 (`text/heading/bullet/table/image`), and `block-view.tsx` only renders those same 5. Typing `/` in an actual block uses a smaller, separate hardcoded list inside `TextBlockView`, not this component.
3. **No Supabase Storage code exists** (`grep -r supabase src/` = no matches). Image blocks currently store a base64 data URI directly in the block's JSON `content`.
4. **Prior history**: this exact SQLite → Supabase migration was already tried and reverted 2026-07-20 → 2026-07-21, for a since-abandoned Vercel deployment, due to Vercel's 4.5MB function body cap (real uploads run 14-100MB), no Python runtime on Vercel (blocks the pipeline "Run" button), and Supabase Storage's 50MB/file free-tier cap. Confirmed with the user this migration is wanted again — **scoped to the database only, not a Vercel redeploy** — so the Python-runtime blocker doesn't apply, and file-size limits are avoided by keeping Price Audit's large exports on local disk storage (unchanged) and only routing new, small Notes attachments through Supabase Storage.

**Decisions confirmed with the user:**
- Migrate **all** Prisma models to Supabase Postgres (not just `Page`/`Block`), preserving existing local data. App keeps running locally (`npm start`/`npm run dev`) — no Vercel redeploy in this scope.
- Price Audit/Sales Dashboard/Salesman keep their current local-disk file storage and SQLite-CRUD-shaped access patterns; only Notes/Blocks attachments move to Supabase Storage.
- `BQ_KEY_FILE` maps to the new `pipamas-83893e7fd607.json` key, scoped to Notes' database-view blocks querying pipeline data — independent of the existing v2/v3 keys the Python scripts already use (per `[[bdia-app-context]]` memory, do not set `BQ_PROJECT_ID`/`BQ_KEY_FILE` globally in a way that overrides those).
- Build real support for the full ~30 slash-menu block types, not a trimmed subset.
- Project-management (Kanban/List/TaskDetailDrawer, already partially wired into table-block views) resumes only after the above is done.

## Stage 1 — Database migration to Supabase

- `prisma/schema.prisma`: datasource `provider` stays `postgresql` (already changed). No model changes needed for this stage — same schema, new host.
- `.env`: uncomment and activate the existing Supabase pooler URL as `DATABASE_URL` (session-mode port 5432 for `prisma db push`, matching prior working config from the 2026-07-20 attempt). Keep `SUPABASE_URL`/keys uncommented for Stage 2's Storage client.
- Data preservation: before switching, export all rows from the current `prisma/dev.db` (a script using the existing `@prisma/client` against the sqlite datasource) and re-insert against the new Postgres datasource after `prisma db push` creates the tables. This covers every model, not just Notes — Price Audit projects, uploads, datasets, match sessions, salesman rows, chat history, jobs.
- `prisma/dev.db*` stays on disk (untouched, not deleted) as a rollback fallback, consistent with how the prior migration kept it around.
- Verification: stop the local Next.js server (Windows file-lock issue, per existing project convention), run `npx prisma db push` against Supabase, run the data-migration script, `npm run build && npm start`, confirm Price Audit/Sales Dashboard/Salesman/Notes all read and write correctly against Supabase.

## Stage 2 — Supabase Storage for Notes attachments

- Add a small Supabase client helper (`src/lib/supabase.ts`) using `SUPABASE_SERVICE_ROLE_KEY` server-side only — uploads go through an API route, not directly from the browser, so the service key never reaches the client.
- New route `src/app/api/blocks/upload/route.ts`: accepts a file, uploads to a Supabase Storage bucket (e.g. `note-attachments`), returns the public/signed URL.
- `ImageBlockView`'s existing "Upload" button switches from `FileReader`→base64 to calling this route. Same pattern extends to the new `video` and `file` block types (Stage 4).
- No change to Price Audit's upload path (`storage/uploads` on local disk) — deliberately out of scope per the user's decision to keep that on local disk.

## Stage 3 — BigQuery env mapping

- `.env`: add `BQ_KEY_FILE="Z:\Rafli\bdia app\pipamas-83893e7fd607.json"`, scoped for use only by the Notes database-view block's query path (Stage 4) — not set as a project-wide override, so it doesn't affect the existing v2/v3-keyed Python pipeline scripts.
- No BigQuery client code needs building beyond what a `database_view` block's "connect to a pipeline dataset" option requires (Stage 4) — this stage is just the credential plumbing so that feature has something to point at.

## Stage 4 — Full slash-menu block-type buildout

Currently `BlockType = "text" | "heading" | "bullet" | "table" | "image"`. Target: every group in `SLASH_MENU_GROUPS` produces a real, rendering, persistable block. Design choice: **collapse variants that differ only by a parameter into one `BlockType` with a content field**, rather than one `BlockType` string per slash-menu item — matches the existing pattern (`TableBlockContent.tables[].views[]` already does this for Table/Board/List/Timeline) and avoids 30 near-duplicate React components.

| Slash items | `BlockType` | Content shape sketch | Notes |
|---|---|---|---|
| Text | `text` | `{ text }` | exists |
| Heading 1-4 | `heading` | `{ text, level: 1\|2\|3\|4 }` | extends existing `heading` with a `level` field; 4 menu entries write different `level` |
| Bullet List | `bullet` | `{ items: BulletItem[] }` | exists |
| Number List | `numbered` | `{ items: { id, text }[] }` | new, same shape as bullet minus `checked` |
| To-Do List | `todo` | `{ items: BulletItem[] }` | reuses `BulletItem` (already has `checked`) — effectively `bullet` with a checkbox-first render; can literally alias to `bullet`'s content type |
| Toggle List | `toggle` | `{ text, children: BlockDto[] }` | collapsible; children stored inline in the block's own content (small nesting, not separate `Block` rows) |
| Page | `page` | `{ pageId }` | creates a new child `Page` (via existing `/api/notes` with `parentId`) and embeds a link/preview |
| Callout | `callout` | `{ text, icon }` | |
| Quote | `quote` | `{ text }` | |
| Divider | `divider` | `{}` | pure visual separator |
| Link to Page | `link_page` | `{ pageId }` | links an *existing* page, vs. `page` which creates a new one |
| Image | `image` | `{ url, caption }` | exists; upload path moves to Stage 2's route |
| Video | `video` | `{ url, caption }` | embed URL (YouTube/Vimeo) or Storage-uploaded file |
| File | `file` | `{ url, name, size }` | uploaded via Stage 2's route |
| Code | `code` | `{ code, language }` | |
| Table/Board/Gallery/List/Dashboard/Calendar/Timeline views | `database_view` | same `TableBlockContent` shape already used by `table` blocks | reuses `TableBlockView` entirely; the menu item just seeds a different initial `TableViewDef.type`. Adds three new `TableViewDef.type` values: `gallery`, `dashboard`, `calendar` (alongside existing `table`/`timeline`/`board`/`list`) |
| Database Full Page | — | n/a | not a block: creates a new child `Page` whose sole block is one full-width `database_view` |
| Chart Data | `chart` | `{ sourceColumnId, chartType }` referencing a sibling `database_view` block, or `{ data: {label,value}[] }` for standalone data | |
| Table of Content | `toc` | `{}` | computed at render time from the page's own heading blocks, nothing persisted |
| Toggle Heading 1-3 | `toggle` | `{ text, level: 1\|2\|3, children }` | same block type as plain Toggle List, with an optional `level` field distinguishing a heading-styled toggle |
| Columns 2/3/4 | `columns` | `{ columnCount: 2\|3\|4, columns: BlockDto[][] }` | each column holds nested blocks inline, same nesting approach as Toggle |
| Mention Person | `mention_person` | `{ personId, label }` | small inline-style block (compact chip), not a full-width block — this block architecture is block-per-row, not rich inline text, so a "mention" reads as a minimal block rather than an inline span |
| Mention Page | `mention_page` | `{ pageId, label }` | same inline-chip treatment as Mention Person |

- `BLOCK_TYPES` in `api/blocks/route.ts` (and the matching list in `emptyBlockContent`, `lib/types.ts`) expands to all of the above.
- `block-view.tsx` gains one render branch per new `BlockType` (several are thin — `divider`, `quote`, `callout` are near-identical to existing text-ish blocks).
- `TextBlockView`'s own hardcoded `SLASH_OPTIONS` list is deleted; `/` inside a text block now opens the real `slash-menu.tsx` component (already built, just needs to be the one thing actually invoked), filtered by whatever's typed after `/`.
- Nested-content types (`toggle`, `columns`) store their children inline in the parent block's JSON `content` rather than as separate `Block` rows with a `parentBlockId` — avoids a second self-relation on top of `Page`'s existing one, keeps ordering/reordering logic scoped to a single block's local array instead of a second recursive tree. Reasonable for the shallow nesting these types need (a toggle's contents, a column's contents) — would need revisiting only if columns-within-columns or multi-level toggle nesting shows up as a real requirement.

## Stage 5 — Project-management thread (deferred, not designed here)

`KanbanView`/`ListView`/`TaskDetailDrawer` already exist and are wired as views inside `TableBlockView` (Board/List view types, row-click opens the drawer). This appears to already satisfy the immediate task-tracking need through the `database_view` block from Stage 4 — no separate "Project" data model exists or is proposed. Whether this needs to grow into something more (assignees, due-date notifications, cross-page rollups) is explicitly **not** designed here; the earlier approved spec (`nested-notes-pages-design.md`) descoped it once already, and per the user's sequencing decision this only gets picked up, and re-scoped if needed, after Stages 1-4 ship.

## Out of scope (deliberately deferred)

- Vercel redeployment — this migration targets the database only; the app keeps running locally.
- Migrating Price Audit/Sales Dashboard/Salesman's file storage off local disk.
- Rich inline text formatting (bold/italic/inline links within a single text block) — every block type above is still block-level content, matching the current editor's model.
- Multi-level nesting for `toggle`/`columns` beyond one level deep.
- Any new BigQuery client/query-builder work beyond credential plumbing — the actual "query a pipeline dataset from a database_view block" UI is real scope but its detailed design (which pipelines, what query surface) needs its own follow-up pass once Stage 4's block plumbing exists to hang it on.

## Testing

- Stage 1: data-migration script is a one-shot, run-once operation — verify row counts match between sqlite source and Postgres destination per table before switching `DATABASE_URL` over for good.
- Stage 2: manual upload of an image/file/video block, confirm the Storage URL persists and reloads correctly.
- Stage 4: manual pass creating one block of every new type, confirming persistence (reload the page) and that reordering/deleting still works for the expanded type list. Table/Board/Gallery/List/Dashboard/Calendar/Timeline all verified through the same `database_view` block by switching view tabs, consistent with how Table/Board/List/Timeline already work today.
