import { describe, it, expect } from "vitest";
import { emptyBlockContent, type BlockType } from "@/lib/types";

describe("emptyBlockContent", () => {
  it("returns the pre-existing shapes unchanged", () => {
    expect(emptyBlockContent("text")).toEqual({ text: "" });
    expect(emptyBlockContent("table")).toEqual({
      columns: [{ id: expect.any(String), name: "Column 1" }],
      rows: [],
    });
    expect(emptyBlockContent("bullet")).toEqual({ items: [] });
    expect(emptyBlockContent("image")).toEqual({ url: "", caption: "" });
    expect(emptyBlockContent("heading")).toEqual({ text: "", level: 1 });
  });

  const expected: Record<Exclude<BlockType, "text" | "table" | "bullet" | "image" | "heading">, unknown> = {
    numbered: { items: [] },
    todo: { items: [] },
    toggle: { text: "", children: [] },
    page: { pageId: "" },
    callout: { text: "", icon: "💡" },
    quote: { text: "" },
    divider: {},
    link_page: { pageId: "" },
    video: { url: "", caption: "" },
    file: { url: "", name: "", size: 0 },
    code: { code: "", language: "text" },
    database_view: { columns: [{ id: expect.any(String), name: "Column 1" }], rows: [] },
    chart: { chartType: "bar", data: [] },
    toc: {},
    columns: { columnCount: 2, columns: [[], []] },
    mention_person: { personId: "", label: "" },
    mention_page: { pageId: "", label: "" },
  };

  for (const [type, shape] of Object.entries(expected)) {
    it(`returns the correct default content for "${type}"`, () => {
      expect(emptyBlockContent(type as BlockType)).toEqual(shape);
    });
  }
});
