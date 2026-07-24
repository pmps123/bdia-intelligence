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
