Implementation Plan — Notion/ClickUp Clone Module (BDIA Intelligence)
This comprehensive implementation plan outlines the sequential stages to build the custom Notion/ClickUp clone features within the BDIA Intelligence project, integrating Supabase (Database & Storage), local BigQuery credentials, and fluid, desktop-grade frontend interactions.

Stage 1: Database Architecture & Environment Configuration
Focus: Supabase PostgreSQL schema migration, hierarchical page relations, and local BigQuery credential mapping.

1.1 Update Prisma Schema (prisma/schema.prisma)
Configure the datasource provider to postgresql pointing to Supabase (using session mode port 5432 for schema pushes if utilizing pgbouncer pooler).

Deprecate/replace the legacy Note model with the new Page model.

Add self-referencing fields (parentId, parent, children) to Page to construct a recursive tree hierarchy for the Notion-style sidebar.

Bind every Page to a specific workspace string (consistent with project architecture).

Define the Block model relating to Page via pageId with cascading deletes. Keep Block.type as a flexible String to support custom slash menu components, database views, and media references.

1.2 Environment & Storage Integration (.env)
Uncomment and configure Supabase variables (DATABASE_URL, SUPABASE_URL, SUPABASE_ANON_KEY, SUPABASE_SERVICE_ROLE_KEY).

Explicitly map the local BigQuery credential path:
BQ_KEY_FILE="Z:\Rafli\bdia app\pipamas-83893e7fd607.json".

Set up Supabase Storage client initialization to handle secure uploads for files (PDF, Excel, images, videos) referenced inside blocks.

Stage 2: Backend API & Data Handlers
Focus: Endpoints for recursive page trees, block manipulation, and database view states.

2.1 Workspace Pages & Tree Endpoint (src/app/api/notes/route.ts & related)
Build GET/POST handlers to fetch and create pages filtered by workspace.

Implement recursive query logic or tree-building helpers to organize parent-child page relationships for the sidebar navigation.

2.2 Block-based CRUD Handlers (src/app/api/blocks/...)
Implement endpoints for updating, reordering, and deleting individual blocks within a page canvas.

Ensure auto-saving behavior with debounce mechanisms.

Stage 3: Frontend Layout & Notion-Style Sidebar
Focus: Responsive workspace shell, wide layout container, and animated recursive sidebar.

3.1 Wide Layout Shell (src/components/app/app-shell.tsx)
Remove restrictive layout constraints like max-w-2xl or typography prose classes.

Implement a fluid container (max-w-screen-2xl, w-full, px-10) so data tables, kanban boards, and documents span across the screen cleanly.

Maintain the monochrome Ledger visual identity (#0A0A0A / #FAFAFA with #B8894F amber accent highlights).

3.2 Notion-Exact Sidebar (src/components/app/sidebar.tsx)
Workspace Switcher at the top.

Favorites & Quick Links sections.

Recursive Tree View for Pages supporting collapse/expand animations.

Quick Actions on Hover: Inline buttons for adding sub-pages (+) and option menus (⋮⋮).

Stage 4: Advanced Editor & Slash Menu (/)
Focus: Block rendering, inline editing, and a robust categorized slash command popover with motion.

4.1 Slash Menu Popover (src/components/app/slash-menu.tsx)
Triggered dynamically when typing / on an empty block canvas.

Organized into categorized, searchable groups:

Basic: Text, Headings (1-4), Lists (Bullet, Number, To-Do, Toggle), Page, Callout, Quote, Divider, Link to Page.

Media & Embeds: Image, Video, File (Supabase Storage upload), Code.

Database Views: Table, Board (Kanban), Gallery, List, Dashboard, Calendar, Timeline, Database Full Page.

Advanced & Layout: Chart Data, Table of Content, Toggle Headings, Columns (2, 3, 4).

Mentions: Person, Page.

Motion & Accessibility: Smooth scale-in transition, keyboard navigation (ArrowUp, ArrowDown, Enter), and clear muted-foreground category headers.

4.2 Database Views & Storage Handling
Database Views (Board/Table): Implemented as block types (type = "database_view") pointing to structured data or querying local datasets/BigQuery pipelines when applicable.

File Attachments: Uploaded seamlessly to Supabase Storage buckets, saving secure URL strings in block metadata.

Verification & Deployment Plan
Stop Local Server: Terminate active Next.js processes to clear file locks on Windows.

Database Push: Run npx prisma db push targeting Supabase (using session mode port 5432) to establish Page and Block tables safely.

Boot & Test (npm run dev): Verify layout width expansion, recursive sidebar tree interaction, and slash command keyboard response.