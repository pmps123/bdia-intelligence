// scripts/migrate-to-supabase.ts
// One-shot: copies every row from the old local SQLite dev.db into the live
// Supabase Postgres database. Run once, from a repo root with SQLITE_MIGRATION_URL set.
import { PrismaClient as SqliteClient } from "../generated/sqlite-source-client";
import { prisma as pg } from "../src/lib/db";

export const HOME_ORDER = -1;

// --- pure conversion logic (unit-testable without a database) ---

export type OldNote = {
  id: string;
  workspace: string;
  title: string;
  type: string;
  content: string;
  order: number;
  createdAt: Date;
  updatedAt: Date;
};

export type OldBlock = {
  id: string;
  workspace: string;
  order: number;
  type: string;
  content: string;
  createdAt: Date;
  updatedAt: Date;
};

/** Old flat Note (one row = one whole page) -> new Page + new Block (order 0) holding its content. */
export function noteToPageAndBlock(note: OldNote) {
  return {
    page: {
      id: note.id,
      workspace: note.workspace,
      title: note.title,
      order: note.order,
      createdAt: note.createdAt,
      updatedAt: note.updatedAt,
    },
    block: {
      pageId: note.id,
      workspace: note.workspace,
      order: 0,
      type: note.type,
      content: note.content,
      createdAt: note.createdAt,
      updatedAt: note.updatedAt,
    },
  };
}

/** Old workspace-scoped Block (the shared per-workspace canvas) -> new Block under that workspace's Home page. */
export function oldBlockToNewBlock(block: OldBlock, homePageId: string) {
  return {
    id: block.id,
    pageId: homePageId,
    workspace: block.workspace,
    order: block.order,
    type: block.type,
    content: block.content,
    createdAt: block.createdAt,
    updatedAt: block.updatedAt,
  };
}

// --- script wiring (talks to real databases) ---

const sqlite = new SqliteClient();

async function copyDirect(model: string, chunkSize = 500) {
  const rows: any[] = await (sqlite as any)[model].findMany();
  let inserted = 0;
  for (let i = 0; i < rows.length; i += chunkSize) {
    // Supabase already holds a prior partial migration snapshot for most models — skipDuplicates
    // (Postgres ON CONFLICT DO NOTHING under the hood) makes this a safe merge: rows whose id
    // already exists in the destination are left untouched, only new rows get inserted.
    const result = await (pg as any)[model].createMany({ data: rows.slice(i, i + chunkSize), skipDuplicates: true });
    inserted += result.count;
  }
  const skipped = rows.length - inserted;
  const destTotal = await (pg as any)[model].count();
  console.log(`${model}: ${rows.length} source rows, ${skipped} already present (skipped), ${inserted} newly inserted, destination now has ${destTotal} total`);
}

async function migratePagesAndBlocks() {
  const oldNotes = await sqlite.note.findMany();
  for (const note of oldNotes) {
    const { page, block } = noteToPageAndBlock(note);
    await pg.page.create({ data: page });
    await pg.block.create({ data: block });
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
    await pg.block.create({ data: oldBlockToNewBlock(block, homePageId) });
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

if (require.main === module) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
