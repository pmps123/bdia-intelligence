import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/db", () => ({
  prisma: {
    block: {
      findMany: vi.fn(),
      findFirst: vi.fn(),
      create: vi.fn(),
    },
    page: {
      findUnique: vi.fn(),
    },
  },
}));

import { prisma } from "@/lib/db";
import { GET, POST } from "@/app/api/blocks/route";

const mockedPrisma = vi.mocked(prisma, { deep: true });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("POST /api/blocks", () => {
  it("creates a block with pageId wired into the Page relation", async () => {
    mockedPrisma.page.findUnique.mockResolvedValue({ id: "page-1", workspace: "rafli" } as never);
    mockedPrisma.block.findFirst.mockResolvedValue(null);
    mockedPrisma.block.create.mockResolvedValue({
      id: "block-1",
      pageId: "page-1",
      workspace: "rafli",
      type: "text",
      order: 0,
      content: "{}",
    } as never);

    const req = new NextRequest("http://localhost/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pageId: "page-1", type: "text" }),
    });

    const res = await POST(req);

    expect(res.status).toBe(200);
    expect(mockedPrisma.block.create).toHaveBeenCalledTimes(1);
    // This is the regression this task fixes: pageId must be part of the create data,
    // not dropped in favor of the old workspace-as-pageid hack.
    expect(mockedPrisma.block.create.mock.calls[0][0]).toMatchObject({
      data: expect.objectContaining({ pageId: "page-1" }),
    });
  });

  it("rejects without pageId and never calls block.create", async () => {
    const req = new NextRequest("http://localhost/api/blocks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type: "text" }),
    });

    const res = await POST(req);

    expect(res.status).toBe(400);
    expect(mockedPrisma.block.create).not.toHaveBeenCalled();
  });
});

describe("GET /api/blocks", () => {
  it("rejects without a pageId query param", async () => {
    const req = new NextRequest("http://localhost/api/blocks");

    const res = await GET(req);

    expect(res.status).toBe(400);
    expect(mockedPrisma.block.findMany).not.toHaveBeenCalled();
  });
});
