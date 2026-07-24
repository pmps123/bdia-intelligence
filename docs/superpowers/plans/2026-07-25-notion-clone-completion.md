# Notion/ClickUp Clone Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Notes/Blocks module (Page/Block schema, sidebar, slash menu) actually work end-to-end on Supabase, with real Storage-backed attachments and full backing for all ~30 slash-menu block types.

**Architecture:** Fix a schema/code mismatch left over from an incomplete refactor (Block records currently can't be created against the real `Page`/`Block` relation), migrate the whole app's data from local SQLite to Supabase Postgres (preserving existing rows, converting the old flat `Note`/workspace-scoped `Block` shape into the new `Page`+`Block` hierarchy), wire real Supabase Storage uploads, then expand the block type system from 5 to ~24 real types so every group in the already-built `slash-menu.tsx` produces a working block.

**Tech Stack:** Next.js 15 / React 19, Prisma 6.7 + `@prisma/client`, Supabase (Postgres + Storage), TypeScript.

## Global Constraints

- No Vercel redeploy in this scope — the app keeps running locally via `npm start`/`npm run dev`. (Spec: Context/Decisions)
- Price Audit/Sales Dashboard/Salesman keep their existing local-disk file storage untouched — only Notes/Blocks attachments move to Supabase Storage. (Spec: Stage 2)
- BigQuery credential mapping is postponed — `database_view` blocks ship as views over the block's own stored rows only, no pipeline-query capability. (Spec: Out of scope)
- Stop the local Next.js dev/prod server before any `prisma generate`/`prisma db push` (Windows file-lock convention already used in this project).
- Preserve every existing row across the migration (Project, Upload, Worksheet, Dataset, DataRow, MatchSession, MatchResult, MasterMapping, PriceValidationRun, PriceValidationItem, TransformRun, SalesmanRow, ChatMessage, Job, plus the old `Note`/`Block` rows converted into the new `Page`/`Block` shape) — nothing gets dropped.
- Every task adds at least one automated Vitest test covering the core logic it introduces (pure functions, API route handlers, content-shape defaults, migration/conversion logic) — **in addition to**, not instead of, the task's manual-verification step. This is a firm requirement per user decision on 2026-07-25 (this codebase had no automated test runner before Task 0 introduces one). Test files live next to the code they test, named `*.test.ts`, matching Vitest's default convention. UI-only rendering with no meaningful branching logic (e.g. a static `<hr>` for Divider) doesn't need a test of its own — test the logic, not the JSX.

---

## Stage 0: Test infrastructure

### Task 0: Set up Vitest

**Context for implementer:** This project has no automated test runner today — only `jiti` for running ad-hoc `.ts` scripts. Every task from here on requires a real automated test (per Global Constraints), so this task exists purely to make `npx vitest run` a working command before Task 1 needs it.

**Files:**
- Modify: `package.json`
- Create: `vitest.config.ts`
- Create: `src/lib/utils.test.ts`

**Interfaces:**
- Produces: `npm test` runs `vitest run` (single pass, CI-style, non-watch) for every later task to use.

- [ ] **Step 1: Install Vitest**

Run: `npm install -D vitest`

- [ ] **Step 2: Add the test script to `package.json`**

In `"scripts"`, add: `"test": "vitest run"`

- [ ] **Step 3: Create `vitest.config.ts`**

```typescript
import { defineConfig } from "vitest/config";
import path from "path";

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  test: {
    environment: "node",
  },
});
```

(matches this project's existing `@/*` -> `src/*` path alias, already used everywhere via `tsconfig.json`'s `paths`)

- [ ] **Step 4: Write a real first test against existing code, to prove the harness works**

```typescript
// src/lib/utils.test.ts
import { describe, it, expect } from "vitest";
import { safeJson, formatBytes } from "@/lib/utils";

describe("safeJson", () => {
  it("parses valid JSON", () => {
    expect(safeJson('{"a":1}', {})).toEqual({ a: 1 });
  });

  it("falls back on invalid JSON", () => {
    expect(safeJson("not json", { fallback: true })).toEqual({ fallback: true });
  });

  it("falls back on null/undefined input", () => {
    expect(safeJson(null, [])).toEqual([]);
    expect(safeJson(undefined, [])).toEqual([]);
  });
});

describe("formatBytes", () => {
  it("formats bytes under 1KB as B", () => {
    expect(formatBytes(500)).toBe("500 B");
  });

  it("formats KB", () => {
    expect(formatBytes(2048)).toBe("2.0 KB");
  });

  it("formats MB", () => {
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});
```

- [ ] **Step 5: Run the tests**

Run: `npm test`
Expected: `Test Files 1 passed (1)`, `Tests 6 passed (6)`, zero failures.

- [ ] **Step 6: Commit**

```bash
git add package.json package-lock.json vitest.config.ts src/lib/utils.test.ts
git commit -m "chore: add Vitest test runner"
```

---

## Stage 1: Fix the Page/Block relation bug, then migrate to Supabase

### Task 1: Fix Block API routes to use the real `pageId` relation

**Context for implementer:** `prisma/schema.prisma` already defines `Block.pageId` (required, relation to `Page`, cascade delete) — but `src/app/api/blocks/route.ts` and `src/components/app/note-editor.tsx` were never updated after that schema change: they still create/query blocks using a `workspace` field holding the *page id* (a leftover from an older, flat, workspace-scoped `Block` model that had no `pageId` at all). The generated Prisma client in `node_modules/.prisma/client` is also stale — it still matches the *old* schema (models `Note`/flat `Block`, no `Page`), which is why this mismatch hasn't shown up as a type error yet. Confirmed by running `npx tsc --noEmit`: `notes/route.ts` etc. already correctly reference `prisma.page` (that model doesn't exist in the stale client at all), while `blocks/route.ts` silently "compiles" only because the stale client's `Block` type doesn't require `pageId`.

This task fixes the application code to match the real schema, then regenerates the client so the mismatch becomes impossible to reintroduce.

**Files:**
- Modify: `src/app/api/blocks/route.ts`
- Modify: `src/components/app/note-editor.tsx`

**Interfaces:**
- Produces: `GET /api/blocks?pageId=<id>` and `POST /api/blocks` body `{ pageId: string, type: string }` — replaces the old `?ws=`/`{ workspace }` contract for these two routes only. `PATCH`/`DELETE /api/blocks/[id]` and `PUT /api/blocks/reorder` are unaffected (already keyed by block id).

- [ ] **Step 1: Rewrite `src/app/api/blocks/route.ts` to require `pageId`**

```typescript
import { NextRequest, NextResponse } from "next/server";
import { prisma } from "@/lib/db";
import { safeJson } from "@/lib/utils";
import { emptyBlockContent, type BlockType } from "@/lib/types";

const BLOCK_TYPES: BlockType[] = ["text", "heading", "bullet", "table", "image"];

export async function GET(req: NextRequest) {
  const pageId = req.nextUrl.searchParams.get("pageId");
  if (!pageId) return NextResponse.json({ error: "pageId is required" }, { status: 400 });
  const blocks = await prisma.block.findMany({ where: { pageId }, orderBy: { order: "asc" } });
  return NextResponse.json({ blocks: blocks.map((b) => ({ ...b, content: safeJson(b.content, {}) })) });
}

export async function POST(req: NextRequest) {
  const { pageId, type } = await req.json().catch(() => ({}));
  if (!pageId) return NextResponse.json({ error: "pageId is required" }, { status: 400 });
  if (!BLOCK_TYPES.includes(type)) return NextResponse.json({ error: "Invalid block type" }, { status: 400 });
  const page = await prisma.page.findUnique({ where: { id: pageId } });
  if (!page) return NextResponse.json({ error: "Page not found" }, { status: 404 });
  const last = await prisma.block.findFirst({ where: { pageId }, orderBy: { order: "desc" } });
  const block = await prisma.block.create({
    data: {
      pageId,
      workspace: page.workspace,
      type,
      order: (last?.order ?? -1) + 1,
      content: JSON.stringify(emptyBlockContent(type)),
    },
  });
  return NextResponse.json({ block: { ...block, content: safeJson(block.content, {}) } });
}
```

- [ ] **Step 2: Update `src/components/app/note-editor.tsx` to use `pageId`**

Three fetch call sites change. In the blocks-loading effect (currently `fetch(\`/api/blocks?ws=${noteId}\`)`):

```typescript
  React.useEffect(() => {
    setBlocksLoading(true);
    fetch(`/api/blocks?pageId=${noteId}`)
      .then((r) => r.json())
      .then((d) => setBlocks(d.blocks ?? []))
      .catch(() => {})
      .finally(() => setBlocksLoading(false));
  }, [noteId]);
```

In the auto-seed effect (currently `body: JSON.stringify({ workspace: noteId, type: "text" })`):

```typescript
    fetch("/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pageId: noteId, type: "text" }),
    })
```

In `addBlock` (currently `body: JSON.stringify({ workspace: noteId, type })`):

```typescript
  const addBlock = async (type: BlockType) => {
    const res = await fetch("/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pageId: noteId, type }),
    });
    if (res.ok) {
      const d = await res.json();
      setBlocks((prev) => [...prev, d.block]);
      setPendingFocusId(d.block.id);
    }
  };
```

In `insertBlockAfter` (currently `body: JSON.stringify({ workspace: noteId, type: "text" })`):

```typescript
  const insertBlockAfter = async (index: number) => {
    const res = await fetch("/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pageId: noteId, type: "text" }),
    });
```

- [ ] **Step 3: Regenerate the Prisma client so the fix is type-checked**

Run: `npx prisma generate`
Expected: `✔ Generated Prisma Client` with no errors (this only reads `prisma/schema.prisma`, no DB connection needed, so it's safe to run before Stage 1's Supabase cutover).

- [ ] **Step 4: Typecheck the whole project**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors referencing `blocks/route.ts`, `note-editor.tsx`, or `prisma.page`/`prisma.block`. (Pre-existing unrelated errors, if any, are out of scope for this task.)

- [ ] **Step 5: Commit**

```bash
git add src/app/api/blocks/route.ts src/components/app/note-editor.tsx
git commit -m "fix: wire Block creation to the real Page relation via pageId"
```

---

### Task 2: Point the app at Supabase and remove SQLite-only code

**Files:**
- Modify: `.env`
- Modify: `src/lib/db.ts`

**Interfaces:**
- Consumes: nothing new
- Produces: `DATABASE_URL` pointing at Supabase Postgres for every subsequent task in this plan.

- [ ] **Step 1: Stop the local server**

Whoever runs this task must stop any running `npm run dev`/`npm start` process first (Windows file-lock convention already used in this project — `prisma generate`/`db push` fail with EPERM otherwise).

- [ ] **Step 2: Activate Supabase env vars in `.env`**

Uncomment and use the existing Supabase block, replacing the SQLite `DATABASE_URL` line. Keep the pooler URL on session-mode port 5432 (matches the working config from the prior 2026-07-20 attempt, needed for `prisma db push` to succeed against pgbouncer):

```
# Supabase Postgres — primary datastore (2026-07-25: re-migrated, DB only, no Vercel redeploy)
DATABASE_URL="postgresql://postgres.cxhhimuxzuzbyizppnjo:BDIA_Soeta409@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres"
SUPABASE_URL="https://cxhhimuxzuzbyizppnjo.supabase.co"
NEXT_PUBLIC_SUPABASE_URL="https://cxhhimuxzuzbyizppnjo.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImN4aGhpbXV4enV6YnlpenBwbmpvIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc4NDU1NDAxMSwiZXhwIjoyMTAwMTMwMDExfQ.EdXlUJQErIgsSMDsU6tuz0KJlpEqBSir87_ocL_QiyM"

# Old local SQLite — retired 2026-07-25, dev.db kept on disk untouched as a rollback fallback
# DATABASE_URL="file:./dev.db"
```

Leave the other previously-commented Supabase lines (`POSTGRES_URL`, `SUPABASE_ANON_KEY`, etc.) as they are — unused, harmless.

- [ ] **Step 3: Remove the SQLite-only PRAGMA calls in `src/lib/db.ts`**

These are silently swallowed by `.catch(() => null)` today, but they're dead/misleading code once the datasource is Postgres (`PRAGMA` is SQLite syntax; Postgres would just error and get swallowed). Replace the whole file:

```typescript
import { PrismaClient } from "@prisma/client";

const globalForPrisma = globalThis as unknown as { prisma?: PrismaClient };

export const prisma = globalForPrisma.prisma ?? new PrismaClient();

if (process.env.NODE_ENV !== "production") globalForPrisma.prisma = prisma;
```

- [ ] **Step 4: Push the schema to Supabase**

Run: `npx prisma db push`
Expected: `Your database is now in sync with your Prisma schema.` — creates every table (`Project`, `Upload`, ..., `Page`, `Block`, `ChatMessage`, `Job`) fresh on the empty Supabase database.

- [ ] **Step 5: Regenerate the client against the live schema**

Run: `npx prisma generate`
Expected: `✔ Generated Prisma Client`

- [ ] **Step 6: Build and smoke-test**

Run: `npm run build && npm start`
Expected: build succeeds; app boots on port 3000. Visiting any page won't show real data yet (Supabase is empty until Task 3 runs) — confirm no crashes, and that creating a brand-new Note/Page/Block works end-to-end against Supabase (this exercises Task 1's fix for real, against a real relational DB with FK constraints — the strictest possible check that `pageId` wiring is correct).

- [ ] **Step 7: Commit**

```bash
git add .env src/lib/db.ts
git commit -m "chore: point DATABASE_URL at Supabase, drop SQLite-only pragmas"
```

---

### Task 3: Migrate existing local data into Supabase

**Context for implementer:** `prisma/dev.db` has real data under the *old* schema: 6 `Project`, 107 `Upload`, 12 `Worksheet`, 12 `Dataset`, 1405 `DataRow`, 6 `MatchSession`, 337 `MatchResult`, 0 `MasterMapping`, 6 `PriceValidationRun`, 1194 `PriceValidationItem`, 42 `TransformRun`, 570 `SalesmanRow`, 8 `ChatMessage`, 20 `Job` — all of these models are byte-identical between the old and new schema, so they copy over 1:1. Two models need real conversion, not a straight copy:

- Old flat `Note` (3 rows: `id, workspace, title, type, content, order`, one row = one whole page with no sub-blocks) → becomes one new `Page` (same `id`/`workspace`/`title`/`order`) **plus** one new `Block` holding that page's `type`/`content` at `order: 0`.
- Old workspace-scoped `Block` (7 rows: `id, workspace, order, type, content`, no `pageId` — this was the shared per-workspace canvas, i.e. what's now the Home page's content) → each row's `workspace` maps to that workspace's Home `Page` (`find-or-create` with `order: -1`, matching the existing logic in `src/app/api/notes/home/route.ts`), and becomes a new `Block` with the same `id`/`order`/`type`/`content`, now carrying `pageId`.

Reading the old data needs a Prisma client generated against the *old* schema (since the main client is now generated against the new Postgres schema and can't read a SQLite file with a different shape). We reuse Prisma itself for this (already a project dependency) rather than adding a new SQLite driver package — generate a second, separately-output client from a temporary schema file that's an exact copy of the old shape.

**Files:**
- Create: `prisma/schema.sqlite-source.prisma`
- Create: `scripts/migrate-to-supabase.ts`

**Interfaces:**
- Consumes: `prisma` (the main, Postgres-pointed client from `src/lib/db.ts`, produced by Task 2)
- Produces: nothing consumed by later tasks — this is a one-shot operational script, not app code.

- [ ] **Step 1: Create the temporary SQLite-source schema**

```prisma
generator client {
  provider = "prisma-client-js"
  output   = "../generated/sqlite-source-client"
}

datasource db {
  provider = "sqlite"
  url      = env("SQLITE_MIGRATION_URL")
}

model Project {
  id                String   @id @default(cuid())
  name              String
  workspace         String   @default("rafli")
  priceSource       String   @default("PRICE_LIST")
  step              String   @default("internal")
  internalUploadId  String?
  vendorUploadId    String?
  internalDatasetId String?
  vendorDatasetId   String?
  sessionId         String?
  validationRunId   String?
  createdAt         DateTime @default(now())
  updatedAt         DateTime @updatedAt
}

model Upload {
  id          String      @id @default(cuid())
  fileName    String
  fileType    String
  fileSize    Int
  storagePath String
  createdAt   DateTime    @default(now())
  worksheets  Worksheet[]
  datasets    Dataset[]
}

model Worksheet {
  id          String @id @default(cuid())
  uploadId    String
  upload      Upload @relation(fields: [uploadId], references: [id], onDelete: Cascade)
  name        String
  sheetIndex  Int
  rowCount    Int
  columnCount Int
  headers     String
  preview     String
}

model Dataset {
  id             String    @id @default(cuid())
  name           String
  kind           String
  vendorName     String?
  uploadId       String
  upload         Upload    @relation(fields: [uploadId], references: [id], onDelete: Cascade)
  worksheetName  String
  mapping        String
  cleaningReport String?
  rowCount       Int       @default(0)
  createdAt      DateTime  @default(now())
  rows           DataRow[]
}

model DataRow {
  id           String  @id @default(cuid())
  datasetId    String
  dataset      Dataset @relation(fields: [datasetId], references: [id], onDelete: Cascade)
  rowIndex     Int
  data         String
  nameRaw      String?
  nameNorm     String?
  code         String?
  variant      String?
  brand        String?
  category     String?
  tokens       String?
  prices       String?
  qty          Float?
  qtyMin       Float?
  qtyMax       Float?
  qtyRuleLabel String?

  @@index([datasetId])
  @@index([nameNorm])
}

model MatchSession {
  id                String               @id @default(cuid())
  name              String
  vendorDatasetId   String
  internalDatasetId String
  status            String               @default("PENDING")
  stats             String?
  createdAt         DateTime             @default(now())
  results           MatchResult[]
  validations       PriceValidationRun[]
}

model MatchResult {
  id            String       @id @default(cuid())
  sessionId     String
  session       MatchSession @relation(fields: [sessionId], references: [id], onDelete: Cascade)
  vendorRowId   String
  internalRowId String?
  score         Float        @default(0)
  confidence    Float        @default(0)
  status        String
  source        String       @default("ENGINE")
  candidates    String?
  detail        String?

  @@index([sessionId])
  @@index([status])
}

model MasterMapping {
  id            String   @id @default(cuid())
  vendorName    String   @default("")
  vendorKey     String
  vendorLabel   String
  vendorCode    String?
  internalKey   String
  internalLabel String
  internalCode  String?
  usageCount    Int      @default(0)
  createdAt     DateTime @default(now())

  @@unique([vendorName, vendorKey])
  @@index([vendorName, vendorCode])
}

model PriceValidationRun {
  id                 String                @id @default(cuid())
  name               String
  sessionId          String
  session            MatchSession          @relation(fields: [sessionId], references: [id], onDelete: Cascade)
  referenceDatasetId String
  vendorPriceField   String
  internalPriceField String
  tolerancePct       Float                 @default(0)
  status             String                @default("COMPLETED")
  stats              String?
  createdAt          DateTime              @default(now())
  items              PriceValidationItem[]
}

model PriceValidationItem {
  id            String             @id @default(cuid())
  runId         String
  run           PriceValidationRun @relation(fields: [runId], references: [id], onDelete: Cascade)
  matchResultId String?
  vendorRowId   String?
  internalRowId String?
  vendorLabel   String
  internalLabel String
  vendorPrice   Float?
  internalPrice Float?
  diff          Float?
  diffPct       Float?
  status        String

  @@index([runId])
}

model TransformRun {
  id        String   @id @default(cuid())
  pipeline  String
  status    String   @default("RUNNING")
  log       String   @default("")
  files     String   @default("{}")
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt
}

model SalesmanRow {
  id            String   @id @default(cuid())
  workspace     String
  bulan         String
  branch        String
  division      String
  legacyCode    String
  newCode       String?
  salesName     String?
  nik           String?
  tanggalMasuk  String?
  tanggalKeluar String?
  aktif         String   @default("Aktif")
  needsReview   Boolean  @default(false)
  source        String   @default("IMPORT")
  createdAt     DateTime @default(now())
  updatedAt     DateTime @updatedAt

  @@unique([workspace, bulan, legacyCode])
  @@index([workspace, bulan])
}

model Note {
  id        String   @id @default(cuid())
  workspace String
  title     String   @default("Untitled")
  type      String
  content   String
  order     Int      @default(0)
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt

  @@index([workspace])
}

model Block {
  id        String   @id @default(cuid())
  workspace String
  order     Int      @default(0)
  type      String
  content   String
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt

  @@index([workspace])
}

model ChatMessage {
  id        String   @id @default(cuid())
  workspace String
  role      String
  content   String
  model     String?
  createdAt DateTime @default(now())

  @@index([workspace, createdAt])
}

model Job {
  id        String   @id @default(cuid())
  type      String
  status    String   @default("RUNNING")
  progress  Float    @default(0)
  message   String   @default("")
  result    String?
  createdAt DateTime @default(now())
  updatedAt DateTime @updatedAt
}
```

- [ ] **Step 2: Generate the source client**

Run (PowerShell, since `.env`'s `DATABASE_URL` is now Supabase and must not leak into this generate/read step): `$env:SQLITE_MIGRATION_URL="file:./prisma/dev.db"; npx prisma generate --schema=prisma/schema.sqlite-source.prisma`
Expected: `✔ Generated Prisma Client` written to `generated/sqlite-source-client`.

- [ ] **Step 3: Write the migration script**

```typescript
// scripts/migrate-to-supabase.ts
// One-shot: copies every row from the old local SQLite dev.db into the live
// Supabase Postgres database. Run once, from a repo root with SQLITE_MIGRATION_URL set.
import { PrismaClient as SqliteClient } from "../generated/sqlite-source-client";
import { prisma as pg } from "../src/lib/db";

const sqlite = new SqliteClient();

const HOME_ORDER = -1;

async function copyDirect(model: string, chunkSize = 500) {
  const rows: any[] = await (sqlite as any)[model].findMany();
  for (let i = 0; i < rows.length; i += chunkSize) {
    await (pg as any)[model].createMany({ data: rows.slice(i, i + chunkSize) });
  }
  console.log(`${model}: migrated ${rows.length} rows`);
}

async function migratePagesAndBlocks() {
  const oldNotes = await sqlite.note.findMany();
  for (const note of oldNotes) {
    await pg.page.create({
      data: {
        id: note.id,
        workspace: note.workspace,
        title: note.title,
        order: note.order,
        createdAt: note.createdAt,
        updatedAt: note.updatedAt,
      },
    });
    await pg.block.create({
      data: {
        pageId: note.id,
        workspace: note.workspace,
        order: 0,
        type: note.type,
        content: note.content,
        createdAt: note.createdAt,
        updatedAt: note.updatedAt,
      },
    });
  }
  console.log(`note -> page+block: migrated ${oldNotes.length} rows`);

  const oldBlocks = await sqlite.block.findMany();
  const homePageIdByWorkspace = new Map<string, string>();
  for (const block of oldBlocks) {
    let homePageId = homePageIdByWorkspace.get(block.workspace);
    if (!homePageId) {
      const existing = await pg.page.findFirst({ where: { workspace: block.workspace, order: HOME_ORDER } });
      const home = existing ?? (await pg.page.create({ data: { workspace: block.workspace, title: "Home", order: HOME_ORDER } }));
      homePageId = home.id;
      homePageIdByWorkspace.set(block.workspace, homePageId);
    }
    await pg.block.create({
      data: {
        id: block.id,
        pageId: homePageId,
        workspace: block.workspace,
        order: block.order,
        type: block.type,
        content: block.content,
        createdAt: block.createdAt,
        updatedAt: block.updatedAt,
      },
    });
  }
  console.log(`block (old, workspace-scoped) -> block (new, pageId-scoped): migrated ${oldBlocks.length} rows`);
}

async function main() {
  await copyDirect("project");
  await copyDirect("upload");
  await copyDirect("worksheet");
  await copyDirect("dataset");
  await copyDirect("dataRow");
  await copyDirect("matchSession");
  await copyDirect("matchResult");
  await copyDirect("masterMapping");
  await copyDirect("priceValidationRun");
  await copyDirect("priceValidationItem");
  await copyDirect("transformRun");
  await copyDirect("salesmanRow");
  await copyDirect("chatMessage");
  await copyDirect("job");
  await migratePagesAndBlocks();
  await sqlite.$disconnect();
  await pg.$disconnect();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
```

- [ ] **Step 4: Run the migration**

Run: `$env:SQLITE_MIGRATION_URL="file:./prisma/dev.db"; npx tsx scripts/migrate-to-supabase.ts` (or `npx jiti scripts/migrate-to-supabase.ts` — this project already depends on `jiti` for running `.ts` scripts directly, per its existing test runner convention)
Expected: one log line per model with a row count, ending in the two conversion summary lines. No errors.

- [ ] **Step 5: Verify row counts match**

Run a quick count check against Supabase (reusing the main `pg` client) for each model and compare to the source counts noted above (6 Project, 107 Upload, 12 Worksheet, 12 Dataset, 1405 DataRow, 6 MatchSession, 337 MatchResult, 0 MasterMapping, 6 PriceValidationRun, 1194 PriceValidationItem, 42 TransformRun, 570 SalesmanRow, 8 ChatMessage, 20 Job, 3 Page from Notes + however many Home pages got created, 3+7 Block). Any mismatch means stop and investigate before deleting anything — `prisma/dev.db` stays on disk untouched either way, per the Global Constraints.

- [ ] **Step 6: Manual smoke test in the browser**

`npm run build && npm start`, open each of Price Audit, Sales Dashboard, Salesman, Notes — confirm real data shows up (not empty states) and basic CRUD (e.g. editing a Note's title, checking a Salesman row) persists across a page reload.

- [ ] **Step 7: Commit**

```bash
git add prisma/schema.sqlite-source.prisma scripts/migrate-to-supabase.ts
git commit -m "feat: migrate local SQLite data into Supabase (Project..Job, Note/Block -> Page/Block)"
```

Note: `generated/sqlite-source-client` is a build artifact — add `generated/` to `.gitignore` if not already covered, rather than committing it.

---

## Stage 2: Supabase Storage for Notes attachments

### Task 4: Supabase client helper and upload API route

**Files:**
- Modify: `package.json` (add `@supabase/supabase-js`)
- Create: `src/lib/supabase.ts`
- Create: `src/app/api/blocks/upload/route.ts`

**Interfaces:**
- Produces: `uploadToSupabase(file: File, bucket?: string): Promise<{ url: string; path: string }>` is NOT exported — the upload route is the only consumer-facing surface. `POST /api/blocks/upload` (multipart form field `file`) → `{ url: string }`.

- [ ] **Step 1: Add the Supabase JS SDK**

Run: `npm install @supabase/supabase-js`

- [ ] **Step 2: Create the server-side Supabase client helper**

```typescript
// src/lib/supabase.ts
import { createClient } from "@supabase/supabase-js";

// Service-role key — server-side only, never sent to the browser. Used exclusively
// by API routes that need to write to Storage on the user's behalf.
export const supabaseAdmin = createClient(
  process.env.SUPABASE_URL!,
  process.env.SUPABASE_SERVICE_ROLE_KEY!
);

export const NOTE_ATTACHMENTS_BUCKET = "note-attachments";
```

- [ ] **Step 3: Create the upload route**

```typescript
// src/app/api/blocks/upload/route.ts
import { NextRequest, NextResponse } from "next/server";
import { supabaseAdmin, NOTE_ATTACHMENTS_BUCKET } from "@/lib/supabase";
import { generateUUID } from "@/lib/utils";

export async function POST(req: NextRequest) {
  const form = await req.formData();
  const file = form.get("file");
  if (!(file instanceof File)) return NextResponse.json({ error: "file is required" }, { status: 400 });

  const ext = file.name.includes(".") ? file.name.slice(file.name.lastIndexOf(".")) : "";
  const path = `${generateUUID()}${ext}`;
  const buffer = Buffer.from(await file.arrayBuffer());

  const { error } = await supabaseAdmin.storage
    .from(NOTE_ATTACHMENTS_BUCKET)
    .upload(path, buffer, { contentType: file.type || "application/octet-stream" });
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });

  const { data } = supabaseAdmin.storage.from(NOTE_ATTACHMENTS_BUCKET).getPublicUrl(path);
  return NextResponse.json({ url: data.publicUrl, name: file.name, size: file.size });
}
```

- [ ] **Step 4: Create the Storage bucket**

In the Supabase dashboard (Storage section) for project `cxhhimuxzuzbyizppnjo`, create a public bucket named `note-attachments`. (No SQL/API step needed — this is a one-time manual setup identical across environments, so it's a dashboard action, not code.)

- [ ] **Step 5: Manual verification**

`npm run build && npm start`, then from a terminal: `curl -F "file=@package.json" http://localhost:3000/api/blocks/upload`
Expected: JSON response with a `url` pointing at `https://cxhhimuxzuzbyizppnjo.supabase.co/storage/v1/object/public/note-attachments/...` — open that URL in a browser and confirm it serves the file.

- [ ] **Step 6: Commit**

```bash
git add package.json package-lock.json src/lib/supabase.ts src/app/api/blocks/upload/route.ts
git commit -m "feat: add Supabase Storage client and block-attachment upload route"
```

---

### Task 5: Wire `ImageBlockView` to real uploads

**Files:**
- Modify: `src/components/app/block-view.tsx`

**Interfaces:**
- Consumes: `POST /api/blocks/upload` (Task 4)

- [ ] **Step 1: Replace the `FileReader`/base64 upload path**

In `ImageBlockView`, replace the `onFile` function:

```typescript
  const onFile = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/blocks/upload", { method: "POST", body: form });
    if (!res.ok) return;
    const d = await res.json();
    onChange({ ...content, url: d.url });
  };
```

(Remove the now-unused `FileReader` code from the old implementation.)

- [ ] **Step 2: Manual verification**

`npm run dev`, open a Note, add an Image block, click Upload, pick a small image file. Expected: the image renders using a `https://cxhhimuxzuzbyizppnjo.supabase.co/...` URL (check via browser devtools Network tab or by inspecting the `<img>` `src`), and it's still there after reloading the page.

- [ ] **Step 3: Commit**

```bash
git add src/components/app/block-view.tsx
git commit -m "feat: upload image blocks to Supabase Storage instead of inlining base64"
```

---

## Stage 3: Full slash-menu block-type buildout

### Task 6: Extend block types, content shapes, and the blocks API type list

**Context for implementer:** This task adds every new `BlockType` string and content interface the rest of Stage 3 depends on, plus wires them into `emptyBlockContent` and the API's allow-list — so `POST /api/blocks` with any new `type` already works and returns sane default content, before any UI renders it. Later tasks only need to add render branches in `block-view.tsx`.

**Files:**
- Modify: `src/lib/types.ts`
- Modify: `src/app/api/blocks/route.ts`

**Interfaces:**
- Produces: the full expanded `BlockType` union and every content interface named in the table below, plus `emptyBlockContent(type)` returning correct defaults for all of them. Every later task in Stage 3 consumes these types by name.

- [ ] **Step 1: Expand `BlockType` and add new content interfaces in `src/lib/types.ts`**

Replace the `BlockType` line and everything from `BlockContentUpdater`/`BlockContent` down to (not including) `emptyBlockContent`:

```typescript
export type BlockType =
  | "text" | "heading" | "bullet" | "table" | "image"
  | "numbered" | "todo" | "toggle"
  | "page" | "callout" | "quote" | "divider" | "link_page"
  | "video" | "file" | "code"
  | "database_view"
  | "chart" | "toc" | "columns"
  | "mention_person" | "mention_page";

export interface HeadingBlockContent {
  text: string;
  level: 1 | 2 | 3 | 4;
}

export interface NumberedItem {
  id: string;
  text: string;
}

export interface NumberedBlockContent {
  items: NumberedItem[];
}

export interface ToggleBlockContent {
  text: string;
  /** Present only for a "Toggle Heading" — plain Toggle List omits it. */
  level?: 1 | 2 | 3;
  children: BlockDto[];
}

export interface PageBlockContent {
  pageId: string;
}

export interface CalloutBlockContent {
  text: string;
  icon: string;
}

export interface QuoteBlockContent {
  text: string;
}

export type DividerBlockContent = Record<string, never>;

export interface LinkPageBlockContent {
  pageId: string;
}

export interface VideoBlockContent {
  url: string;
  caption: string;
}

export interface FileBlockContent {
  url: string;
  name: string;
  size: number;
}

export interface CodeBlockContent {
  code: string;
  language: string;
}

export interface ChartBlockContent {
  chartType: "bar" | "line" | "pie";
  data: { label: string; value: number }[];
}

export type TocBlockContent = Record<string, never>;

export interface ColumnsBlockContent {
  columnCount: 2 | 3 | 4;
  columns: BlockDto[][];
}

export interface MentionPersonBlockContent {
  personId: string;
  label: string;
}

export interface MentionPageBlockContent {
  pageId: string;
  label: string;
}

/** A block's onChange either replaces content outright, or (safer when a single interaction can
 *  fire more than one update in the same tick) resolves against the truly-latest content. */
export type BlockContentUpdater = BlockContent | ((prev: BlockContent) => BlockContent);

export type BlockContent =
  | TextBlockContent
  | HeadingBlockContent
  | BulletBlockContent
  | NumberedBlockContent
  | ToggleBlockContent
  | TableBlockContent
  | ImageBlockContent
  | PageBlockContent
  | CalloutBlockContent
  | QuoteBlockContent
  | DividerBlockContent
  | LinkPageBlockContent
  | VideoBlockContent
  | FileBlockContent
  | CodeBlockContent
  | ChartBlockContent
  | TocBlockContent
  | ColumnsBlockContent
  | MentionPersonBlockContent
  | MentionPageBlockContent;

export interface BlockDto {
  id: string;
  workspace: string;
  order: number;
  type: BlockType;
  content: BlockContent;
}

export const emptyBlockContent = (type: BlockType): BlockContent => {
  switch (type) {
    case "bullet":
    case "todo":
      return { items: [] };
    case "numbered":
      return { items: [] };
    case "toggle":
      return { text: "", children: [] };
    case "table":
    case "database_view":
      return { columns: [{ id: generateUUID(), name: "Column 1" }], rows: [] };
    case "image":
      return { url: "", caption: "" };
    case "video":
      return { url: "", caption: "" };
    case "file":
      return { url: "", name: "", size: 0 };
    case "code":
      return { code: "", language: "text" };
    case "callout":
      return { text: "", icon: "💡" };
    case "quote":
      return { text: "" };
    case "divider":
      return {};
    case "toc":
      return {};
    case "page":
      return { pageId: "" };
    case "link_page":
      return { pageId: "" };
    case "chart":
      return { chartType: "bar", data: [] };
    case "columns":
      return { columnCount: 2, columns: [[], []] };
    case "mention_person":
      return { personId: "", label: "" };
    case "mention_page":
      return { pageId: "", label: "" };
    case "heading":
      return { text: "", level: 1 };
    default:
      return { text: "" };
  }
};
```

(`BulletBlockContent`, `TextBlockContent`, `ImageBlockContent`, `TableBlockContent` and their existing fields/interfaces stay exactly as they are today, above this block — only insert the new interfaces and replace the old `emptyBlockContent`/`BlockContent`/`BlockDto`/`BlockContentUpdater`.)

Note the existing `TextBlockView`/`HeadingBlockView` etc. currently type their `content` prop as `TextBlockContent` for headings too — Task 7 updates `HeadingBlockView`'s prop type to the new `HeadingBlockContent` when it adds the `level` UI, so this step alone leaves `block-view.tsx`'s existing heading branch on the old (still-valid, since `HeadingBlockContent` is a superset shape at the JS level) content type until Task 7 lands.

- [ ] **Step 2: Expand `BLOCK_TYPES` in `src/app/api/blocks/route.ts`**

```typescript
const BLOCK_TYPES: BlockType[] = [
  "text", "heading", "bullet", "table", "image",
  "numbered", "todo", "toggle",
  "page", "callout", "quote", "divider", "link_page",
  "video", "file", "code",
  "database_view",
  "chart", "toc", "columns",
  "mention_person", "mention_page",
];
```

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no new errors (existing `block-view.tsx` render branches only handle 5 types via `block.type === "text"` etc. checks, which remain valid TypeScript even though new union members exist — unhandled types just render nothing until later tasks add branches).

- [ ] **Step 4: Manual verification**

`npm run dev`, in a browser devtools console or via `curl`, hit `POST /api/blocks` with `{"pageId": "<any real page id>", "type": "callout"}`. Expected: `201`-equivalent success JSON with `content: { text: "", icon: "💡" }`.

- [ ] **Step 5: Commit**

```bash
git add src/lib/types.ts src/app/api/blocks/route.ts
git commit -m "feat: expand BlockType to the full slash-menu set (content shapes + API allow-list)"
```

---

### Task 7: Heading levels, Divider, Quote, Callout

**Files:**
- Modify: `src/components/app/block-view.tsx`

**Interfaces:**
- Consumes: `HeadingBlockContent`, `QuoteBlockContent`, `DividerBlockContent`, `CalloutBlockContent` (Task 6)

- [ ] **Step 1: Update `HeadingBlockView` to render by `level`**

Replace its content prop type and add a `<h1>`-`<h4>`-equivalent size mapping:

```typescript
const HEADING_SIZE: Record<1 | 2 | 3 | 4, string> = {
  1: "text-2xl",
  2: "text-xl",
  3: "text-lg",
  4: "text-base",
};

export function HeadingBlockView({
  content,
  onChange,
  onEnter,
  onBackspaceEmpty,
  registerFocus,
}: {
  content: HeadingBlockContent;
  onChange: (c: BlockContentUpdater) => void;
  onEnter?: () => void;
  onBackspaceEmpty?: () => void;
  registerFocus?: (handle: { focus: () => void } | null) => void;
}) {
  const ref = React.useRef<HTMLInputElement>(null);
  React.useLayoutEffect(() => {
    registerFocus?.({ focus: () => ref.current?.focus() });
    return () => registerFocus?.(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  return (
    <Input
      ref={ref}
      value={content.text}
      onChange={(e) => onChange({ ...content, text: e.target.value })}
      onKeyDown={(e) => {
        if (e.key === "Enter" && onEnter) {
          e.preventDefault();
          onEnter();
        } else if (e.key === "Backspace" && content.text === "" && onBackspaceEmpty) {
          e.preventDefault();
          onBackspaceEmpty();
        }
      }}
      placeholder="Heading"
      className={cn("h-auto border-0 bg-transparent px-1 py-1 font-display font-semibold shadow-none focus-visible:ring-1", HEADING_SIZE[content.level ?? 1])}
    />
  );
}
```

(This replaces the existing `HeadingBlockView` in place — same component name, same call site in `BlockView`, just a new content type and a level-driven size class. `block.content as TextBlockContent` at the `BlockView` call site becomes `block.content as HeadingBlockContent`.)

- [ ] **Step 2: Add Divider, Quote, Callout view components**

```typescript
export function DividerBlockView() {
  return <hr className="my-2 border-border" />;
}

export function QuoteBlockView({ content, onChange }: { content: QuoteBlockContent; onChange: (c: BlockContentUpdater) => void }) {
  return (
    <Textarea
      value={content.text}
      onChange={(e) => onChange({ text: e.target.value })}
      placeholder="Quote"
      rows={1}
      className="min-h-0 resize-none border-l-2 border-primary/50 bg-transparent px-3 py-1 text-sm italic shadow-none focus-visible:ring-1"
    />
  );
}

const CALLOUT_ICONS = ["💡", "⚠️", "📌", "✅", "❗"];

export function CalloutBlockView({ content, onChange }: { content: CalloutBlockContent; onChange: (c: BlockContentUpdater) => void }) {
  return (
    <div className="flex items-start gap-2 rounded-lg border bg-accent/40 p-3">
      <Popover>
        <PopoverTrigger className="shrink-0 text-lg cursor-pointer">{content.icon}</PopoverTrigger>
        <PopoverContent className="flex w-auto gap-1 p-1.5">
          {CALLOUT_ICONS.map((icon) => (
            <button key={icon} onClick={() => onChange({ ...content, icon })} className="rounded p-1 text-lg hover:bg-accent cursor-pointer">
              {icon}
            </button>
          ))}
        </PopoverContent>
      </Popover>
      <Textarea
        value={content.text}
        onChange={(e) => onChange({ ...content, text: e.target.value })}
        placeholder="Callout text"
        rows={1}
        className="min-h-0 flex-1 resize-none border-0 bg-transparent px-0 py-0.5 text-sm shadow-none focus-visible:ring-0"
      />
    </div>
  );
}
```

- [ ] **Step 3: Wire the three new branches into `BlockView`**

Add alongside the existing `block.type === "image"` branch:

```typescript
        {block.type === "divider" && <DividerBlockView />}
        {block.type === "quote" && (
          <QuoteBlockView content={block.content as QuoteBlockContent} onChange={onChange} />
        )}
        {block.type === "callout" && (
          <CalloutBlockView content={block.content as CalloutBlockContent} onChange={onChange} />
        )}
```

- [ ] **Step 4: Manual verification**

`npm run dev`, in a Note, use the "Add block" menu (Task 18 will make every type reachable there — until then, verify by directly POSTing via devtools/curl as in Task 6 Step 4, then reloading the page) to create one of each: heading at each of the 4 levels renders at 4 visibly different sizes; divider renders a horizontal rule; quote renders italic with a left border; callout renders with an icon picker and persists the chosen icon after reload.

- [ ] **Step 5: Commit**

```bash
git add src/components/app/block-view.tsx
git commit -m "feat: heading levels, divider, quote, and callout blocks"
```

---

### Task 8: Numbered List and To-Do List

**Files:**
- Modify: `src/components/app/block-view.tsx`

**Interfaces:**
- Consumes: `NumberedBlockContent`, `NumberedItem` (Task 6), existing `BulletBlockContent`/`BulletItem` (To-Do reuses these exactly — same shape, different `BlockType` string, checkbox-first render)

- [ ] **Step 1: Add `NumberedBlockView`**

Same interaction pattern as the existing `BulletBlockView`, minus the checkbox:

```typescript
export function NumberedBlockView({ content, onChange, onEmptyBackspaceOnly }: {
  content: NumberedBlockContent;
  onChange: (c: BlockContentUpdater) => void;
  onEmptyBackspaceOnly?: () => void;
}) {
  const items = content.items;
  const setItems = (next: typeof items) => onChange({ items: next });
  const refs = React.useRef<Record<string, HTMLInputElement | null>>({});
  const pendingFocusId = React.useRef<string | null>(null);

  React.useEffect(() => {
    if (pendingFocusId.current && refs.current[pendingFocusId.current]) {
      refs.current[pendingFocusId.current]!.focus();
      pendingFocusId.current = null;
    }
  }, [items]);

  const addItemAfter = (index: number) => {
    const id = generateUUID();
    const next = [...items];
    next.splice(index + 1, 0, { id, text: "" });
    pendingFocusId.current = id;
    setItems(next);
  };

  const removeItemAndFocusPrev = (index: number) => {
    if (items.length <= 1) {
      onEmptyBackspaceOnly?.();
      return;
    }
    const prev = items[index - 1];
    setItems(items.filter((_, i) => i !== index));
    if (prev) pendingFocusId.current = prev.id;
  };

  return (
    <div className="space-y-1">
      {items.length === 0 && (
        <button onClick={() => setItems([{ id: generateUUID(), text: "" }])} className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground hover:text-primary cursor-pointer">
          <Plus className="h-3.5 w-3.5" /> Add item
        </button>
      )}
      {items.map((item, i) => (
        <div key={item.id} className="group/item flex items-center gap-2">
          <span className="w-4 shrink-0 text-right text-xs text-muted-foreground">{i + 1}.</span>
          <Input
            ref={(el) => { refs.current[item.id] = el; }}
            value={item.text}
            onChange={(e) => setItems(items.map((x) => (x.id === item.id ? { ...x, text: e.target.value } : x)))}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addItemAfter(i);
              } else if (e.key === "Backspace" && item.text === "") {
                e.preventDefault();
                removeItemAndFocusPrev(i);
              }
            }}
            placeholder="List item"
            className="h-7 flex-1 border-0 bg-transparent px-1 shadow-none focus-visible:ring-1"
          />
          <button onClick={() => setItems(items.filter((x) => x.id !== item.id))} className="shrink-0 text-muted-foreground opacity-0 hover:text-status-bad group-hover/item:opacity-100 cursor-pointer">
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ))}
      {items.length > 0 && (
        <button onClick={() => addItemAfter(items.length - 1)} className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground hover:text-primary cursor-pointer">
          <Plus className="h-3.5 w-3.5" /> Add item
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Wire `numbered` and `todo` branches into `BlockView`**

`todo` reuses `BulletBlockView` directly (identical content shape — `BulletItem` already has `checked`):

```typescript
        {block.type === "numbered" && (
          <NumberedBlockView content={block.content as NumberedBlockContent} onChange={onChange} onEmptyBackspaceOnly={onBackspaceEmpty} />
        )}
        {block.type === "todo" && (
          <BulletBlockView content={block.content as BulletBlockContent} onChange={onChange} onEmptyBackspaceOnly={onBackspaceEmpty} />
        )}
```

- [ ] **Step 3: Manual verification**

Create a numbered-list block: type items, confirm the "1. 2. 3." prefix auto-renumbers as items are added/removed/reordered, and persists after reload. Create a to-do block: confirm it behaves exactly like the existing Bullet List block (checkbox + strikethrough) since it's the same component under a different `BlockType`.

- [ ] **Step 4: Commit**

```bash
git add src/components/app/block-view.tsx
git commit -m "feat: numbered list and to-do list blocks"
```

---

### Task 9: Toggle List and Toggle Heading

**Files:**
- Modify: `src/components/app/block-view.tsx`

**Interfaces:**
- Consumes: `ToggleBlockContent` (Task 6)

- [ ] **Step 1: Add `ToggleBlockView`**

Children are nested inline `BlockDto[]` (per the spec's deliberate one-level-nesting design) — reuses `BlockView` recursively for each child, with its own local `onChange` that patches the specific child index inside the parent's `content.children` array.

```typescript
export function ToggleBlockView({ content, onChange }: { content: ToggleBlockContent; onChange: (c: BlockContentUpdater) => void }) {
  const [open, setOpen] = React.useState(false);
  const HeadingTag = content.level ? (["h1", "h2", "h3"][content.level - 1] as "h1" | "h2" | "h3") : null;

  const addChild = () => {
    const child: BlockDto = { id: generateUUID(), workspace: "", order: content.children.length, type: "text", content: { text: "" } };
    onChange({ ...content, children: [...content.children, child] });
  };

  const updateChild = (index: number, next: BlockContentUpdater) => {
    onChange((prev) => {
      const p = prev as ToggleBlockContent;
      const child = p.children[index];
      const resolved = typeof next === "function" ? next(child.content) : next;
      const children = p.children.map((c, i) => (i === index ? { ...c, content: resolved } : c));
      return { ...p, children };
    });
  };

  const removeChild = (index: number) => onChange({ ...content, children: content.children.filter((_, i) => i !== index) });

  return (
    <div>
      <div className="flex items-center gap-1.5">
        <button onClick={() => setOpen((o) => !o)} className="flex h-5 w-5 items-center justify-center rounded text-muted-foreground hover:bg-accent cursor-pointer">
          {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        </button>
        <Input
          value={content.text}
          onChange={(e) => onChange({ ...content, text: e.target.value })}
          placeholder="Toggle"
          className={cn(
            "h-auto flex-1 border-0 bg-transparent px-1 py-1 shadow-none focus-visible:ring-1",
            HeadingTag ? "font-display font-semibold text-lg" : "text-sm"
          )}
        />
      </div>
      {open && (
        <div className="ml-6 mt-1 space-y-1 border-l pl-3">
          {content.children.map((child, i) => (
            <BlockView
              key={child.id}
              block={child}
              onChange={(c) => updateChild(i, c)}
              onDelete={() => removeChild(i)}
              onMoveUp={() => {}}
              onMoveDown={() => {}}
              isFirst
              isLast
            />
          ))}
          <button onClick={addChild} className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground hover:text-primary cursor-pointer">
            <Plus className="h-3.5 w-3.5" /> Add inside toggle
          </button>
        </div>
      )}
    </div>
  );
}
```

Add `ChevronRight, ChevronDown` to the existing `lucide-react` import list at the top of the file.

- [ ] **Step 2: Wire `toggle` branch into `BlockView`**

Both plain Toggle List and Toggle Heading 1-3 use the same block type — `level` being present or absent is what the slash-menu picker sets:

```typescript
        {block.type === "toggle" && (
          <ToggleBlockView content={block.content as ToggleBlockContent} onChange={onChange} />
        )}
```

- [ ] **Step 3: Manual verification**

Create a Toggle List block: confirm it starts collapsed, expand it, add a nested text block inside, type in it, collapse and re-expand — content persists. Create a Toggle Heading (once Task 18 exposes it in the menu with `level: 1`): confirm the toggle's own label renders at heading size.

- [ ] **Step 4: Commit**

```bash
git add src/components/app/block-view.tsx
git commit -m "feat: toggle list and toggle heading blocks with one level of nested children"
```

---

### Task 10: Page and Link to Page blocks

**Files:**
- Modify: `src/components/app/block-view.tsx`

**Interfaces:**
- Consumes: `PageBlockContent`, `LinkPageBlockContent` (Task 6), `GET /api/notes?ws=<workspace>` (existing route, returns `{ notes: Page[] }`) for the page picker
- Produces: `PageBlockView`/`LinkPageBlockView` need the current page's `workspace` to create a child page or list link candidates — `BlockView`'s props gain an optional `workspace?: string`, threaded from `note-editor.tsx`'s `note.workspace`.

- [ ] **Step 1: Thread `workspace` through `BlockView`**

Add `workspace?: string` to `BlockView`'s props type and pass it down to the two new view components (Step 2). In `note-editor.tsx`'s `<BlockView ... />` call site, add `workspace={note?.workspace}`.

- [ ] **Step 2: Add `PageBlockView` (creates + embeds a new child page) and `LinkPageBlockView` (links an existing page)**

```typescript
export function PageBlockView({ content, onChange, workspace }: { content: PageBlockContent; onChange: (c: BlockContentUpdater) => void; workspace?: string }) {
  const [title, setTitle] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!content.pageId || !workspace) return;
    fetch(`/api/notes?ws=${workspace}`).then((r) => r.json()).then((d) => {
      const page = (d.notes ?? []).find((n: { id: string }) => n.id === content.pageId);
      setTitle(page?.title ?? "Untitled");
    });
  }, [content.pageId, workspace]);

  const createSubPage = async () => {
    if (!workspace) return;
    const res = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace }),
    });
    if (!res.ok) return;
    const d = await res.json();
    onChange({ pageId: d.note.id });
  };

  if (!content.pageId) {
    return (
      <button onClick={createSubPage} className="flex items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-sm text-muted-foreground hover:border-primary/50 hover:text-primary cursor-pointer">
        <FileText className="h-4 w-4" /> New sub-page
      </button>
    );
  }
  return (
    <Link href={`/notes?id=${content.pageId}`} className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-accent">
      <FileText className="h-4 w-4 text-muted-foreground" /> {title ?? "Loading…"}
    </Link>
  );
}

export function LinkPageBlockView({ content, onChange, workspace }: { content: LinkPageBlockContent; onChange: (c: BlockContentUpdater) => void; workspace?: string }) {
  const [pages, setPages] = React.useState<{ id: string; title: string }[]>([]);
  const [open, setOpen] = React.useState(false);

  React.useEffect(() => {
    if (!workspace) return;
    fetch(`/api/notes?ws=${workspace}`).then((r) => r.json()).then((d) => setPages(d.notes ?? []));
  }, [workspace]);

  const selected = pages.find((p) => p.id === content.pageId);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-accent cursor-pointer">
        <Link2Icon className="h-4 w-4 text-muted-foreground" /> {selected ? selected.title : "Link to page…"}
      </PopoverTrigger>
      <PopoverContent className="w-64 p-1">
        {pages.map((p) => (
          <button key={p.id} onClick={() => { onChange({ pageId: p.id }); setOpen(false); }} className="block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-accent cursor-pointer">
            {p.title || "Untitled"}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}
```

Add `Link2 as Link2Icon` to the `lucide-react` import list (avoids clashing with `next/link`'s `Link` import already used elsewhere in this file's siblings — confirm `Link` isn't already imported in `block-view.tsx`; if it is, this alias keeps both usable).

- [ ] **Step 3: Wire `page` and `link_page` branches into `BlockView`**

```typescript
        {block.type === "page" && (
          <PageBlockView content={block.content as PageBlockContent} onChange={onChange} workspace={workspace} />
        )}
        {block.type === "link_page" && (
          <LinkPageBlockView content={block.content as LinkPageBlockContent} onChange={onChange} workspace={workspace} />
        )}
```

- [ ] **Step 4: Manual verification**

Create a Page block: click "New sub-page", confirm it creates a real child page (check the sidebar — Task 3's earlier sidebar work already renders the parent/child tree) and the block turns into a working link to it. Create a Link to Page block: confirm the popover lists existing pages, selecting one persists and links correctly after reload.

- [ ] **Step 5: Commit**

```bash
git add src/components/app/block-view.tsx src/components/app/note-editor.tsx
git commit -m "feat: page (create sub-page) and link-to-page blocks"
```

---

### Task 11: Video and File blocks

**Files:**
- Modify: `src/components/app/block-view.tsx`

**Interfaces:**
- Consumes: `VideoBlockContent`, `FileBlockContent` (Task 6), `POST /api/blocks/upload` (Task 4)

- [ ] **Step 1: Add `VideoBlockView` and `FileBlockView`**

```typescript
export function VideoBlockView({ content, onChange }: { content: VideoBlockContent; onChange: (c: BlockContentUpdater) => void }) {
  const fileRef = React.useRef<HTMLInputElement>(null);

  const onFile = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/blocks/upload", { method: "POST", body: form });
    if (!res.ok) return;
    const d = await res.json();
    onChange({ ...content, url: d.url });
  };

  return (
    <div className="space-y-2">
      {content.url ? (
        <video src={content.url} controls className="max-h-80 w-full rounded-lg border" />
      ) : (
        <div className="flex h-28 items-center justify-center rounded-lg border-2 border-dashed border-border/60 text-sm text-muted-foreground">No video yet</div>
      )}
      <div className="flex items-center gap-2">
        <Input value={content.url} onChange={(e) => onChange({ ...content, url: e.target.value })} placeholder="Paste a video URL…" className="h-8 flex-1 text-xs" />
        <Button type="button" variant="outline" size="sm" className="h-8 gap-1.5" onClick={() => fileRef.current?.click()}>
          <Upload className="h-3.5 w-3.5" /> Upload
        </Button>
        <input ref={fileRef} type="file" accept="video/*" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
      </div>
    </div>
  );
}

export function FileBlockView({ content, onChange }: { content: FileBlockContent; onChange: (c: BlockContentUpdater) => void }) {
  const fileRef = React.useRef<HTMLInputElement>(null);

  const onFile = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch("/api/blocks/upload", { method: "POST", body: form });
    if (!res.ok) return;
    const d = await res.json();
    onChange({ url: d.url, name: d.name, size: d.size });
  };

  return content.url ? (
    <a href={content.url} target="_blank" rel="noreferrer" className="flex items-center gap-2 rounded-lg border px-3 py-2 text-sm hover:bg-accent">
      <FileIcon className="h-4 w-4 text-muted-foreground" /> {content.name} <span className="text-xs text-muted-foreground">({formatBytes(content.size)})</span>
    </a>
  ) : (
    <>
      <button onClick={() => fileRef.current?.click()} className="flex items-center gap-2 rounded-lg border border-dashed px-3 py-2 text-sm text-muted-foreground hover:border-primary/50 hover:text-primary cursor-pointer">
        <Upload className="h-4 w-4" /> Upload a file
      </button>
      <input ref={fileRef} type="file" className="hidden" ref2={fileRef} onChange={(e) => { const f = e.target.files?.[0]; if (f) onFile(f); e.target.value = ""; }} />
    </>
  );
}
```

Fix the stray `ref2={fileRef}` typo above — the `<input>` only needs `ref={fileRef}` once (already present); remove the duplicate attribute. Add `File as FileIcon` to the `lucide-react` import list, and `formatBytes` to the existing `@/lib/utils` import (already exported there).

- [ ] **Step 2: Wire `video` and `file` branches into `BlockView`**

```typescript
        {block.type === "video" && (
          <VideoBlockView content={block.content as VideoBlockContent} onChange={onChange} />
        )}
        {block.type === "file" && (
          <FileBlockView content={block.content as FileBlockContent} onChange={onChange} />
        )}
```

- [ ] **Step 3: Manual verification**

Create a Video block: paste a YouTube URL or upload a small video file, confirm it renders/persists. Create a File block: upload a small file, confirm the download link shows the correct name/size and works after reload.

- [ ] **Step 4: Commit**

```bash
git add src/components/app/block-view.tsx
git commit -m "feat: video and file blocks, both backed by Supabase Storage uploads"
```

---

### Task 12: Code block

**Files:**
- Modify: `src/components/app/block-view.tsx`

**Interfaces:**
- Consumes: `CodeBlockContent` (Task 6)

- [ ] **Step 1: Add `CodeBlockView`**

Plain `<textarea>`-backed editor with a monospace font and a language label — no syntax highlighting library, matching this project's existing preference for lightweight, dependency-free block editors (every other block type is a plain input/textarea too).

```typescript
const CODE_LANGUAGES = ["text", "javascript", "typescript", "python", "sql", "json", "bash"];

export function CodeBlockView({ content, onChange }: { content: CodeBlockContent; onChange: (c: BlockContentUpdater) => void }) {
  return (
    <div className="overflow-hidden rounded-lg border bg-muted/40">
      <div className="flex items-center justify-between border-b px-2 py-1">
        <select
          value={content.language}
          onChange={(e) => onChange({ ...content, language: e.target.value })}
          className="bg-transparent text-xs text-muted-foreground cursor-pointer"
        >
          {CODE_LANGUAGES.map((lang) => (
            <option key={lang} value={lang}>{lang}</option>
          ))}
        </select>
      </div>
      <Textarea
        value={content.code}
        onChange={(e) => onChange({ ...content, code: e.target.value })}
        placeholder="Type code…"
        rows={4}
        className="resize-y border-0 bg-transparent px-3 py-2 font-mono text-xs shadow-none focus-visible:ring-0"
      />
    </div>
  );
}
```

- [ ] **Step 2: Wire `code` branch into `BlockView`**

```typescript
        {block.type === "code" && (
          <CodeBlockView content={block.content as CodeBlockContent} onChange={onChange} />
        )}
```

- [ ] **Step 3: Manual verification**

Create a Code block, type a snippet, change the language dropdown, reload — both code and language persist.

- [ ] **Step 4: Commit**

```bash
git add src/components/app/block-view.tsx
git commit -m "feat: code block"
```

---

### Task 13: `database_view` block (adds Gallery/Dashboard/Calendar views) and Database Full Page

**Context for implementer:** The existing `table` block type already has a fully working multi-view mechanism (`TableBlockContent.tables[].views[]`, with `TableViewDef.type` currently `"table" | "timeline" | "board" | "list"`, rendered by `TableBlockView` in `block-view.tsx`). Per the design spec, `database_view` is meant to be the *exact same* component and content shape, just reached from a different slash-menu group and offering three more view types. Rather than duplicating `TableBlockView`, this task makes it handle both `BlockType`s identically, and adds `gallery`/`dashboard`/`calendar` as new `TableViewDef.type` values.

**Files:**
- Modify: `src/lib/types.ts`
- Modify: `src/components/app/block-view.tsx`

**Interfaces:**
- Consumes: existing `TableBlockContent`, `TableViewDef`, `SubTableDef` (this project already has these)
- Produces: `TableViewDef.type` gains `"gallery" | "dashboard" | "calendar"`

- [ ] **Step 1: Widen `TableViewDef.type` in `src/lib/types.ts`**

```typescript
export interface TableViewDef {
  id: string;
  name: string;
  type: "table" | "timeline" | "board" | "list" | "gallery" | "dashboard" | "calendar";
  startColumnId?: string;
  endColumnId?: string;
  groupByColumnId?: string;
}
```

- [ ] **Step 2: Add minimal Gallery/Dashboard/Calendar renderers**

Gallery is a card-grid over the same rows/columns; Dashboard is a set of simple per-numeric-column aggregate tiles; Calendar reuses a date column exactly like Timeline's start column, laid out as a month grid. Add these three small components above `TableBlockView`:

```typescript
export function GalleryView({ columns, rows }: { columns: TableColumnDef[]; rows: TableRowDef[] }) {
  const titleCol = columns[0];
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
      {rows.map((row) => (
        <div key={row.id} className="rounded-lg border p-3">
          <div className="truncate text-sm font-medium">{row.cells[titleCol?.id] || "Untitled"}</div>
          {columns.slice(1, 4).map((c) => (
            <div key={c.id} className="mt-1 truncate text-xs text-muted-foreground">{c.name}: {row.cells[c.id] || "—"}</div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function DashboardView({ columns, rows }: { columns: TableColumnDef[]; rows: TableRowDef[] }) {
  const numericCols = columns.filter((c) => c.type === "number");
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      <div className="rounded-lg border p-3">
        <div className="text-xs text-muted-foreground">Total rows</div>
        <div className="mt-1 font-display text-xl font-semibold">{rows.length}</div>
      </div>
      {numericCols.map((c) => {
        const sum = rows.reduce((s, r) => s + (Number(r.cells[c.id]) || 0), 0);
        return (
          <div key={c.id} className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">{c.name} (sum)</div>
            <div className="mt-1 font-display text-xl font-semibold">{sum}</div>
          </div>
        );
      })}
    </div>
  );
}

export function CalendarView({ columns, rows, dateColumnId }: { columns: TableColumnDef[]; rows: TableRowDef[]; dateColumnId?: string }) {
  const titleCol = columns[0];
  if (!dateColumnId) return <div className="p-3 text-sm text-muted-foreground">Add a Date column to use Calendar view.</div>;
  const byDate = new Map<string, TableRowDef[]>();
  for (const row of rows) {
    const d = row.cells[dateColumnId];
    if (!d) continue;
    byDate.set(d, [...(byDate.get(d) ?? []), row]);
  }
  const dates = [...byDate.keys()].sort();
  return (
    <div className="space-y-2">
      {dates.length === 0 && <div className="p-3 text-sm text-muted-foreground">No dated rows yet.</div>}
      {dates.map((d) => (
        <div key={d} className="rounded-lg border p-2">
          <div className="text-xs font-semibold text-muted-foreground">{d}</div>
          {byDate.get(d)!.map((row) => (
            <div key={row.id} className="truncate text-sm">{row.cells[titleCol?.id] || "Untitled"}</div>
          ))}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Wire the three new view types into `TableBlockView`'s view switch**

In the existing `activeView.type === "timeline" ? ... : activeView.type === "board" ? ... : ...` chain, add three more branches before the final `TableEditor` fallback:

```typescript
      ) : activeView.type === "gallery" ? (
        <GalleryView columns={activeTable.columns} rows={activeTable.rows} />
      ) : activeView.type === "dashboard" ? (
        <DashboardView columns={activeTable.columns} rows={activeTable.rows} />
      ) : activeView.type === "calendar" ? (
        <CalendarView columns={activeTable.columns} rows={activeTable.rows} dateColumnId={activeView.startColumnId} />
```

Add Gallery and Dashboard as one-click buttons in `AddViewMenu`'s "main" step, right after the existing Board button:

```typescript
            <button
              onClick={() => { onAdd({ id: generateUUID(), name: "Gallery", type: "gallery" }); reset(); }}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
            >
              <LayoutGrid className="h-4 w-4" /> Gallery
            </button>
            <button
              onClick={() => { onAdd({ id: generateUUID(), name: "Dashboard", type: "dashboard" }); reset(); }}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent cursor-pointer"
            >
              <LayoutDashboard className="h-4 w-4" /> Dashboard
            </button>
```

Calendar needs a date column picked first, exactly like Timeline — reuse the existing `"timeline"` step UI instead of adding a fourth step. Add a `pendingCalendar` boolean state (`const [pendingCalendar, setPendingCalendar] = React.useState(false);`) alongside the existing `step`/`startId`/`endId` state, a Calendar button that sets it before opening the picker:

```typescript
            <button
              onClick={() => { setPendingCalendar(true); openTimelinePicker(); }}
              disabled={dateColumns.length === 0}
              title={dateColumns.length === 0 ? "Add a Date column first" : undefined}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent disabled:cursor-not-allowed disabled:opacity-40 cursor-pointer"
            >
              <Calendar className="h-4 w-4" /> Calendar
            </button>
```

and change the existing Timeline step's "Create timeline view" button to branch on it (Calendar only needs the start date, not an end date — hide the End picker when `pendingCalendar` is true):

```typescript
            <Button
              size="sm"
              className="h-7 w-full text-xs"
              onClick={() => {
                if (pendingCalendar) {
                  onAdd({ id: generateUUID(), name: "Calendar", type: "calendar", startColumnId: startId });
                  setPendingCalendar(false);
                } else {
                  onAdd({ id: generateUUID(), name: "Timeline", type: "timeline", startColumnId: startId, endColumnId: endId });
                }
                reset();
              }}
            >
              {pendingCalendar ? "Create calendar view" : "Create timeline view"}
            </Button>
```

Reset `pendingCalendar` to `false` inside the existing `reset()` function too, so a cancelled Calendar flow doesn't leak into the next Timeline attempt.

- [ ] **Step 4: Make `database_view` render through the exact same `TableBlockView` component**

In `BlockView`'s render body, change:

```typescript
        {block.type === "table" && (
          <TableBlockView content={block.content as TableBlockContent} onChange={onChange} />
        )}
```

to:

```typescript
        {(block.type === "table" || block.type === "database_view") && (
          <TableBlockView content={block.content as TableBlockContent} onChange={onChange} />
        )}
```

- [ ] **Step 5: Database Full Page — no block type, a page-creation shortcut**

In `note-editor.tsx`'s `ADD_MENU` (and Task 18's slash-menu wiring), "Database Full Page" isn't a block at all: selecting it creates a new child page (same `POST /api/notes` call as Task 10's `PageBlockView`) and immediately seeds that new page with one `database_view` block instead of the usual auto-seeded `text` block. Implement as a small helper in `note-editor.tsx`:

```typescript
  const addDatabaseFullPage = async () => {
    const res = await fetch("/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: note?.workspace }),
    });
    if (!res.ok) return;
    const d = await res.json();
    await fetch("/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pageId: d.note.id, type: "database_view" }),
    });
    window.location.href = `/notes?id=${d.note.id}`;
  };
```

(This bypasses the auto-seed-with-text-block effect because that effect only fires when a *loaded* page has zero blocks — by the time the new page loads, it already has one `database_view` block from this call.)

- [ ] **Step 6: Manual verification**

Create a `database_view` block via the API (same manual approach as Task 6 Step 4, since Task 18 hasn't exposed it in the UI menu yet): confirm it renders identically to a `table` block. Add Gallery, Dashboard, and Calendar views via the "+" view menu, confirm each renders sensibly and switching tabs preserves the underlying rows. Trigger `addDatabaseFullPage` manually (temporary button, or via devtools calling the function if exposed) and confirm the created page opens directly into a working database view.

- [ ] **Step 7: Commit**

```bash
git add src/lib/types.ts src/components/app/block-view.tsx src/components/app/note-editor.tsx
git commit -m "feat: gallery/dashboard/calendar table views, database_view block type, Database Full Page"
```

---

### Task 14: Columns block (2/3/4)

**Files:**
- Modify: `src/components/app/block-view.tsx`

**Interfaces:**
- Consumes: `ColumnsBlockContent` (Task 6)

- [ ] **Step 1: Add `ColumnsBlockView`**

Same nested-`BlockDto[]`-per-column approach as Task 9's Toggle children, laid out in a CSS grid:

```typescript
export function ColumnsBlockView({ content, onChange }: { content: ColumnsBlockContent; onChange: (c: BlockContentUpdater) => void }) {
  const addToColumn = (colIndex: number) => {
    const child: BlockDto = { id: generateUUID(), workspace: "", order: content.columns[colIndex].length, type: "text", content: { text: "" } };
    onChange((prev) => {
      const p = prev as ColumnsBlockContent;
      const columns = p.columns.map((col, i) => (i === colIndex ? [...col, child] : col));
      return { ...p, columns };
    });
  };

  const updateChild = (colIndex: number, childIndex: number, next: BlockContentUpdater) => {
    onChange((prev) => {
      const p = prev as ColumnsBlockContent;
      const col = p.columns[colIndex];
      const child = col[childIndex];
      const resolved = typeof next === "function" ? next(child.content) : next;
      const newCol = col.map((c, i) => (i === childIndex ? { ...c, content: resolved } : c));
      const columns = p.columns.map((c, i) => (i === colIndex ? newCol : c));
      return { ...p, columns };
    });
  };

  const removeChild = (colIndex: number, childIndex: number) => {
    onChange((prev) => {
      const p = prev as ColumnsBlockContent;
      const columns = p.columns.map((c, i) => (i === colIndex ? c.filter((_, ci) => ci !== childIndex) : c));
      return { ...p, columns };
    });
  };

  return (
    <div className="grid gap-4" style={{ gridTemplateColumns: `repeat(${content.columnCount}, minmax(0, 1fr))` }}>
      {content.columns.map((col, colIndex) => (
        <div key={colIndex} className="space-y-1 border-l pl-3 first:border-l-0 first:pl-0">
          {col.map((child, childIndex) => (
            <BlockView
              key={child.id}
              block={child}
              onChange={(c) => updateChild(colIndex, childIndex, c)}
              onDelete={() => removeChild(colIndex, childIndex)}
              onMoveUp={() => {}}
              onMoveDown={() => {}}
              isFirst
              isLast
            />
          ))}
          <button onClick={() => addToColumn(colIndex)} className="flex items-center gap-1.5 px-1 text-xs text-muted-foreground hover:text-primary cursor-pointer">
            <Plus className="h-3.5 w-3.5" /> Add
          </button>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Wire `columns` branch into `BlockView`**

```typescript
        {block.type === "columns" && (
          <ColumnsBlockView content={block.content as ColumnsBlockContent} onChange={onChange} />
        )}
```

The `columnCount` (2, 3, or 4) is set once at creation time by which slash-menu item was picked (Task 18 passes it via `emptyBlockContent`-style seeding — see Task 18 Step 2's note on per-item content overrides).

- [ ] **Step 3: Manual verification**

Create a 3-column block (via direct API POST with a manually-set content of `columnCount: 3, columns: [[],[],[]]`, since Task 18 wires the menu), add a text block to each column, confirm they render side by side and persist after reload.

- [ ] **Step 4: Commit**

```bash
git add src/components/app/block-view.tsx
git commit -m "feat: columns block (2/3/4) with one level of nested children per column"
```

---

### Task 15: Chart block

**Files:**
- Modify: `src/components/app/block-view.tsx`

**Interfaces:**
- Consumes: `ChartBlockContent` (Task 6)

- [ ] **Step 1: Add `ChartBlockView`**

No charting library dependency — a small inline SVG bar/line renderer covers the "standalone data" case from the spec (the "reference a sibling database_view block" half of Chart Data is out of scope until a real need for it shows up; this task ships the standalone-data path, which is the concrete, testable half). Editable as a simple label/value row list plus a chart-type selector:

```typescript
export function ChartBlockView({ content, onChange }: { content: ChartBlockContent; onChange: (c: BlockContentUpdater) => void }) {
  const max = Math.max(1, ...content.data.map((d) => d.value));
  const setData = (next: typeof content.data) => onChange({ ...content, data: next });

  return (
    <div className="space-y-3 rounded-lg border p-3">
      <select value={content.chartType} onChange={(e) => onChange({ ...content, chartType: e.target.value as ChartBlockContent["chartType"] })} className="h-7 rounded border bg-transparent px-2 text-xs cursor-pointer">
        <option value="bar">Bar</option>
        <option value="line">Line</option>
        <option value="pie">Pie</option>
      </select>

      {content.chartType !== "line" && (
        <div className="flex h-32 items-end gap-2">
          {content.data.map((d, i) => (
            <div key={i} className="flex flex-1 flex-col items-center gap-1">
              <div className="w-full rounded-t bg-primary/70" style={{ height: `${(d.value / max) * 100}%` }} />
              <span className="truncate text-[10px] text-muted-foreground">{d.label}</span>
            </div>
          ))}
        </div>
      )}
      {content.chartType === "line" && (
        <svg viewBox={`0 0 ${Math.max(1, content.data.length - 1) * 40} 100`} className="h-32 w-full" preserveAspectRatio="none">
          <polyline
            fill="none"
            stroke="var(--primary)"
            strokeWidth="2"
            points={content.data.map((d, i) => `${i * 40},${100 - (d.value / max) * 100}`).join(" ")}
          />
        </svg>
      )}

      <div className="space-y-1">
        {content.data.map((d, i) => (
          <div key={i} className="flex items-center gap-2">
            <Input value={d.label} onChange={(e) => setData(content.data.map((x, xi) => (xi === i ? { ...x, label: e.target.value } : x)))} placeholder="Label" className="h-7 flex-1 text-xs" />
            <Input type="number" value={d.value} onChange={(e) => setData(content.data.map((x, xi) => (xi === i ? { ...x, value: Number(e.target.value) } : x)))} placeholder="Value" className="h-7 w-20 text-xs" />
            <button onClick={() => setData(content.data.filter((_, xi) => xi !== i))} className="shrink-0 text-muted-foreground hover:text-status-bad cursor-pointer">
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
        <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setData([...content.data, { label: "", value: 0 }])}>
          <Plus className="h-3 w-3 mr-1" /> Add data point
        </Button>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire `chart` branch into `BlockView`**

```typescript
        {block.type === "chart" && (
          <ChartBlockView content={block.content as ChartBlockContent} onChange={onChange} />
        )}
```

- [ ] **Step 3: Manual verification**

Create a Chart block, add 3-4 data points, switch between Bar/Line/Pie (Pie can share the Bar rendering path if a real pie isn't built — confirm at minimum Bar and Line render correctly with the entered values), reload and confirm data persists.

- [ ] **Step 4: Commit**

```bash
git add src/components/app/block-view.tsx
git commit -m "feat: chart block (bar/line, dependency-free inline SVG rendering)"
```

---

### Task 16: Table of Contents block

**Files:**
- Modify: `src/components/app/block-view.tsx`
- Modify: `src/components/app/note-editor.tsx`

**Context for implementer:** Unlike every other block, `toc` has no editable content (`TocBlockContent` is `{}`) — it's computed at render time from the *other* blocks on the same page, so it needs the full sibling block list passed down, not just its own content.

**Interfaces:**
- Consumes: `TocBlockContent` (Task 6)
- Produces: `BlockView` gains an optional `allBlocks?: BlockDto[]` prop, threaded from `note-editor.tsx`.

- [ ] **Step 1: Thread `allBlocks` through `BlockView`**

Add `allBlocks?: BlockDto[]` to `BlockView`'s props type. In `note-editor.tsx`'s `<BlockView ... />` call site, add `allBlocks={blocks}`.

- [ ] **Step 2: Add `TocBlockView`**

```typescript
export function TocBlockView({ allBlocks }: { allBlocks: BlockDto[] }) {
  const headings = allBlocks
    .filter((b) => b.type === "heading")
    .map((b) => b.content as HeadingBlockContent);

  if (headings.length === 0) {
    return <div className="rounded-lg border border-dashed p-3 text-sm text-muted-foreground">No headings on this page yet.</div>;
  }
  return (
    <div className="space-y-1 rounded-lg border p-3">
      {headings.map((h, i) => (
        <div key={i} style={{ paddingLeft: `${(h.level - 1) * 12}px` }} className="truncate text-sm text-muted-foreground hover:text-primary">
          {h.text || "Untitled heading"}
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 3: Wire `toc` branch into `BlockView`**

```typescript
        {block.type === "toc" && <TocBlockView allBlocks={allBlocks ?? []} />}
```

- [ ] **Step 4: Manual verification**

On a page with a few Heading blocks at different levels, add a Table of Content block: confirm it lists every heading, indented by level, and updates live as headings are added/edited/removed.

- [ ] **Step 5: Commit**

```bash
git add src/components/app/block-view.tsx src/components/app/note-editor.tsx
git commit -m "feat: table of contents block, computed from sibling heading blocks"
```

---

### Task 17: Mention Person and Mention Page blocks

**Files:**
- Modify: `src/components/app/block-view.tsx`

**Interfaces:**
- Consumes: `MentionPersonBlockContent`, `MentionPageBlockContent` (Task 6), `GET /api/notes?ws=<workspace>` (existing, for the page picker — same pattern as Task 10's `LinkPageBlockView`), `WORKSPACES` from `@/lib/workspaces` (for the person picker — this app has no separate "person" entity, so "person" means a teammate identified by workspace id, same list the Workspace Switcher already uses)

- [ ] **Step 1: Add `MentionPersonBlockView` and `MentionPageBlockView`**

Both render as a small inline chip, per the spec's design note that this block architecture is block-per-row rather than rich inline text:

```typescript
export function MentionPersonBlockView({ content, onChange }: { content: MentionPersonBlockContent; onChange: (c: BlockContentUpdater) => void }) {
  const [open, setOpen] = React.useState(!content.personId);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger className="inline-flex items-center gap-1.5 rounded-full border bg-accent/50 px-2.5 py-1 text-xs font-medium cursor-pointer">
        <AtSign className="h-3 w-3" /> {content.label || "Mention someone…"}
      </PopoverTrigger>
      <PopoverContent className="w-48 p-1">
        {WORKSPACES.map((w) => (
          <button key={w.id} onClick={() => { onChange({ personId: w.id, label: w.name }); setOpen(false); }} className="block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-accent cursor-pointer">
            {w.name}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}

export function MentionPageBlockView({ content, onChange, workspace }: { content: MentionPageBlockContent; onChange: (c: BlockContentUpdater) => void; workspace?: string }) {
  const [pages, setPages] = React.useState<{ id: string; title: string }[]>([]);
  const [open, setOpen] = React.useState(!content.pageId);

  React.useEffect(() => {
    if (!workspace) return;
    fetch(`/api/notes?ws=${workspace}`).then((r) => r.json()).then((d) => setPages(d.notes ?? []));
  }, [workspace]);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger className="inline-flex items-center gap-1.5 rounded-full border bg-accent/50 px-2.5 py-1 text-xs font-medium cursor-pointer">
        <FileText className="h-3 w-3" /> {content.label || "Mention a page…"}
      </PopoverTrigger>
      <PopoverContent className="w-64 p-1">
        {pages.map((p) => (
          <button key={p.id} onClick={() => { onChange({ pageId: p.id, label: p.title || "Untitled" }); setOpen(false); }} className="block w-full truncate rounded px-2 py-1.5 text-left text-sm hover:bg-accent cursor-pointer">
            {p.title || "Untitled"}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}
```

Add `AtSign` to the `lucide-react` import list, and `import { WORKSPACES } from "@/lib/workspaces";` at the top of the file.

- [ ] **Step 2: Wire `mention_person` and `mention_page` branches into `BlockView`**

```typescript
        {block.type === "mention_person" && (
          <MentionPersonBlockView content={block.content as MentionPersonBlockContent} onChange={onChange} />
        )}
        {block.type === "mention_page" && (
          <MentionPageBlockView content={block.content as MentionPageBlockContent} onChange={onChange} workspace={workspace} />
        )}
```

- [ ] **Step 3: Manual verification**

Create a Mention Person block: confirm the picker lists all six workspaces/people, selecting one shows their name as a chip and persists. Create a Mention Page block: confirm the picker lists real pages and persists the selection.

- [ ] **Step 4: Commit**

```bash
git add src/components/app/block-view.tsx
git commit -m "feat: mention person and mention page blocks (inline chip style)"
```

---

### Task 18: Wire the real slash menu, retire the hardcoded shortlists

**Context for implementer:** Right now there are *three* separate, inconsistent lists of block types in the UI: `slash-menu.tsx`'s `SLASH_MENU_GROUPS` (the full ~24-type categorized menu, built but never actually invoked), `TextBlockView`'s own hardcoded `SLASH_OPTIONS` (4 types, what `/` inside a text block actually triggers today), and `note-editor.tsx`'s `ADD_MENU` (5 types, what the "+ Add block" button offers). This task makes both real triggers — typing `/` and clicking "+ Add block" — open the one real `SlashMenu` component, now that every type it lists has a working implementation from Tasks 6-17.

**Files:**
- Modify: `src/components/app/block-view.tsx`
- Modify: `src/components/app/note-editor.tsx`
- Modify: `src/components/app/slash-menu.tsx`

**Interfaces:**
- Consumes: `SlashMenu`, `SLASH_MENU_GROUPS` (existing, from Task-untouched `slash-menu.tsx`, only its `type` values get corrected in Step 1 below)

- [ ] **Step 1: Correct `SLASH_MENU_GROUPS`'s `type` values to match the real `BlockType`s**

A few entries in the existing file use placeholder-ish or duplicated `type` strings that don't match Task 6's real `BlockType` union — fix them in place (everything else in the file — labels, icons, descriptions, grouping — is unchanged):

```typescript
      { id: "number", label: "Number List", type: "numbered", icon: ListOrdered, description: "Create a numbered list." },
```
(was `type: "number"` — the real `BlockType` is `"numbered"`)

```typescript
      { id: "db_table", label: "Table view", type: "database_view", icon: Table, description: "Display a database as a table.", initialViewType: "table" },
      { id: "db_board", label: "Board view", type: "database_view", icon: Kanban, description: "Display a database as a Kanban board.", initialViewType: "board" },
      { id: "db_gallery", label: "Gallery view", type: "database_view", icon: LayoutGrid, description: "Display a database as a visual gallery.", initialViewType: "gallery" },
      { id: "db_list", label: "List view", type: "database_view", icon: ListTodo, description: "Display a database as a compact list.", initialViewType: "list" },
      { id: "db_dashboard", label: "Dashboard view", type: "database_view", icon: LayoutDashboard, description: "Display a database as a metric dashboard.", initialViewType: "dashboard" },
      { id: "db_calendar", label: "Calendar view", type: "database_view", icon: Calendar, description: "Display a database as a calendar.", initialViewType: "calendar" },
      { id: "db_timeline", label: "Timeline view", type: "database_view", icon: Clock, description: "Display a database as a Gantt chart.", initialViewType: "timeline" },
      { id: "db_full", label: "Database Full Page", type: "database_full", icon: Database, description: "Create a full page database." },
```
(adds an `initialViewType` field so the created block seeds its `TableViewDef.type` to match which menu item was clicked, instead of always defaulting to plain Table)

```typescript
      { id: "toggle_h1", label: "Toggle Heading 1", type: "toggle", icon: Heading1, description: "Hide content inside a large heading.", contentOverride: { level: 1 } },
      { id: "toggle_h2", label: "Toggle Heading 2", type: "toggle", icon: Heading2, description: "Hide content inside a medium heading.", contentOverride: { level: 2 } },
      { id: "toggle_h3", label: "Toggle Heading 3", type: "toggle", icon: Heading3, description: "Hide content inside a small heading.", contentOverride: { level: 3 } },
      { id: "col_2", label: "2 Columns", type: "columns", icon: Columns2, description: "Create 2 columns of blocks.", contentOverride: { columnCount: 2, columns: [[], []] } },
      { id: "col_3", label: "3 Columns", type: "columns", icon: Columns3, description: "Create 3 columns of blocks.", contentOverride: { columnCount: 3, columns: [[], [], []] } },
      { id: "col_4", label: "4 Columns", type: "columns", icon: Columns4, description: "Create 4 columns of blocks.", contentOverride: { columnCount: 4, columns: [[], [], [], []] } },
```
(and for Heading 1-4 in the Basic group: `{ id: "h1", ..., type: "heading", contentOverride: { level: 1 } }` etc. for all four)

Add `initialViewType?: string` and `contentOverride?: Record<string, unknown>` to the `SlashMenuItem` type at the top of the file:

```typescript
export type SlashMenuItem = {
  id: string;
  label: string;
  icon: React.ElementType;
  description?: string;
  type: string;
  initialViewType?: string;
  contentOverride?: Record<string, unknown>;
};
```

- [ ] **Step 2: Give `note-editor.tsx`'s `addBlock` a way to apply per-item overrides**

`POST /api/blocks` already returns the type's default `emptyBlockContent`; when a slash-menu item carries `contentOverride`/`initialViewType`, patch the freshly created block's content immediately after creation:

```typescript
  const addBlock = async (type: BlockType, overrides?: { contentOverride?: Partial<BlockContent>; initialViewType?: string }) => {
    const res = await fetch("/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pageId: noteId, type }),
    });
    if (!res.ok) return;
    const d = await res.json();
    let block = d.block;
    if (overrides?.contentOverride) {
      const content = { ...block.content, ...overrides.contentOverride };
      await fetch(`/api/blocks/${block.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      block = { ...block, content };
    } else if (overrides?.initialViewType && overrides.initialViewType !== "table") {
      const activeTable = block.content.tables?.[0] ?? { id: "default", name: "Table 1", columns: block.content.columns, rows: block.content.rows };
      const view = { id: crypto.randomUUID(), name: overrides.initialViewType[0].toUpperCase() + overrides.initialViewType.slice(1), type: overrides.initialViewType };
      const content = { activeTableId: activeTable.id, tables: [{ ...activeTable, views: [view], activeViewId: view.id }] };
      await fetch(`/api/blocks/${block.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ content }),
      });
      block = { ...block, content };
    }
    setBlocks((prev) => [...prev, block]);
    setPendingFocusId(block.id);
  };
```

- [ ] **Step 3: Replace `note-editor.tsx`'s `ADD_MENU` dropdown with the real `SlashMenu`**

Remove the `ADD_MENU` constant and its `DropdownMenu`-based rendering; replace the "+ Add block" button with one that opens `SlashMenu` in a `Popover`:

```typescript
import { SlashMenu } from "@/components/app/slash-menu";
```

```typescript
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="ghost" size="sm" className="mt-2 text-muted-foreground hover:text-foreground">
                <Plus className="h-3.5 w-3.5" /> Add block
              </Button>
            </PopoverTrigger>
            <PopoverContent align="start" className="w-auto p-0">
              <SlashMenu onSelect={(type, itemId) => {
                const item = SLASH_MENU_GROUPS.flatMap((g) => g.items).find((i) => i.id === itemId);
                if (type === "database_full") { addDatabaseFullPage(); return; }
                addBlock(type as BlockType, { contentOverride: item?.contentOverride, initialViewType: item?.initialViewType });
              }} />
            </PopoverContent>
          </Popover>
```

Add `Popover, PopoverContent, PopoverTrigger` to the existing `@/components/ui/popover` import (or add the import if not already present in this file), and `SLASH_MENU_GROUPS` to the `slash-menu` import.

- [ ] **Step 4: Wire the same real `SlashMenu` into `TextBlockView`'s `/`-trigger, removing the old hardcoded `SLASH_OPTIONS`**

In `block-view.tsx`, delete the `SLASH_OPTIONS` constant and replace `TextBlockView`'s menu-rendering block (the `{showMenu && (...)}` section) so it filters `SLASH_MENU_GROUPS` by `slashQuery` and calls `onConvert`-equivalent logic. Since converting an existing text block into a richer type (with a different content shape) needs more than the current `onConvert?: (type: BlockType) => void` signature (some types need `contentOverride`/`initialViewType` too), widen it:

```typescript
  onConvert?: (type: BlockType, overrides?: { contentOverride?: Record<string, unknown>; initialViewType?: string }) => void;
```

(update this type at both the `BlockView` and `TextBlockView` prop declarations, and in `note-editor.tsx`'s `convertBlock` call site — `convertBlock` gains the same optional third argument and forwards it into the PATCH body's `content` merge, mirroring Step 2's override logic but PATCHing the existing block id instead of a freshly-created one)

```typescript
  const options = slashQuery === null
    ? []
    : SLASH_MENU_GROUPS.flatMap((g) => g.items).filter((o) => o.label.toLowerCase().includes(slashQuery.toLowerCase()));
```

Replace the inline dropdown markup with a mount of `<SlashMenu onSelect={(type, itemId) => { const item = options.find(o => o.id === itemId); onConvert?.(type as BlockType, { contentOverride: item?.contentOverride, initialViewType: item?.initialViewType }); }} query={slashQuery ?? ""} />` positioned the same way (`absolute left-0 top-full z-20 mt-1`), keeping the existing `ArrowUp`/`ArrowDown`/`Enter`/`Escape` keyboard handling in `onKeyDown` working against `options` (now sourced from `SLASH_MENU_GROUPS` instead of the old local list).

Import `SlashMenu, SLASH_MENU_GROUPS` from `@/components/app/slash-menu` at the top of `block-view.tsx`.

- [ ] **Step 5: Manual verification**

In a Note, type `/` at the start of an empty text block: confirm the full categorized menu (Basic/Media & Embeds/Database Views/Advanced & Layout/Mentions) appears, filters as you type, and arrow-key navigation + Enter still works. Select a few different types across categories (e.g. Heading 2, Callout, 3 Columns, Board view) and confirm each converts the block correctly with the right initial content. Click "+ Add block" at the bottom of the page and confirm it opens the same full menu and creates working blocks the same way.

- [ ] **Step 6: Full regression pass**

Run: `npx tsc --noEmit -p tsconfig.json`
Expected: no errors.

`npm run build && npm start`, exercise: creating/reordering/deleting blocks of several types, the sidebar's recursive page tree still works, Price Audit/Sales Dashboard/Salesman still read/write correctly against Supabase (final end-to-end confirmation that Stage 1's migration didn't regress anything else in the app).

- [ ] **Step 7: Commit**

```bash
git add src/components/app/block-view.tsx src/components/app/note-editor.tsx src/components/app/slash-menu.tsx
git commit -m "feat: wire the real categorized slash menu into both the '/' trigger and Add-block button"
```
