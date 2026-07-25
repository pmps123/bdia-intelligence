import { describe, it, expect } from "vitest";
import { HOME_ORDER, noteToPageAndBlock, oldBlockToNewBlock, type OldNote, type OldBlock } from "./migrate-to-supabase";

describe("noteToPageAndBlock", () => {
  it("splits an old flat Note into a Page (same id/workspace/title/order) and a Block at order 0 holding type/content", () => {
    const note: OldNote = {
      id: "note-1",
      workspace: "rafli",
      title: "Meeting notes",
      type: "doc",
      content: '{"text":"hello"}',
      order: 2,
      createdAt: new Date("2026-01-01T00:00:00.000Z"),
      updatedAt: new Date("2026-01-02T00:00:00.000Z"),
    };

    const { page, block } = noteToPageAndBlock(note);

    expect(page).toEqual({
      id: "note-1",
      workspace: "rafli",
      title: "Meeting notes",
      order: 2,
      createdAt: note.createdAt,
      updatedAt: note.updatedAt,
    });
    expect(block).toEqual({
      pageId: "note-1",
      workspace: "rafli",
      order: 0,
      type: "doc",
      content: '{"text":"hello"}',
      createdAt: note.createdAt,
      updatedAt: note.updatedAt,
    });
  });
});

describe("oldBlockToNewBlock", () => {
  it("carries id/order/type/content/timestamps through and attaches the resolved home pageId", () => {
    const block: OldBlock = {
      id: "block-1",
      workspace: "rafli",
      order: 5,
      type: "paragraph",
      content: '{"text":"canvas content"}',
      createdAt: new Date("2026-01-01T00:00:00.000Z"),
      updatedAt: new Date("2026-01-02T00:00:00.000Z"),
    };

    const result = oldBlockToNewBlock(block, "home-page-rafli");

    expect(result).toEqual({
      id: "block-1",
      pageId: "home-page-rafli",
      workspace: "rafli",
      order: 5,
      type: "paragraph",
      content: '{"text":"canvas content"}',
      createdAt: block.createdAt,
      updatedAt: block.updatedAt,
    });
  });

  it("resolves different workspaces to different home pages", () => {
    const block: OldBlock = {
      id: "block-2",
      workspace: "other-ws",
      order: 0,
      type: "text",
      content: "{}",
      createdAt: new Date(),
      updatedAt: new Date(),
    };

    const result = oldBlockToNewBlock(block, "home-page-other-ws");

    expect(result.pageId).toBe("home-page-other-ws");
    expect(result.workspace).toBe("other-ws");
  });
});

describe("HOME_ORDER", () => {
  it("matches the Home-page sentinel order used by src/app/api/notes/home/route.ts", () => {
    expect(HOME_ORDER).toBe(-1);
  });
});
