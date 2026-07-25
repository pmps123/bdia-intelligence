import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/db", () => ({
  prisma: {
    page: {
      findMany: vi.fn(),
      findFirst: vi.fn(),
      create: vi.fn(),
    },
  },
}));

import { prisma } from "@/lib/db";
import { GET, POST } from "@/app/api/notes/route";

const mockedPrisma = vi.mocked(prisma, { deep: true });

beforeEach(() => {
  vi.clearAllMocks();
});

describe("POST /api/notes", () => {
  it("with parentId: scopes the order lookup to {workspace, parentId} and includes parentId in the created page", async () => {
    mockedPrisma.page.findFirst.mockResolvedValue({ order: 2 } as never);
    mockedPrisma.page.create.mockResolvedValue({
      id: "page-child-1",
      workspace: "rafli",
      parentId: "page-parent-1",
      order: 3,
      title: "Untitled",
    } as never);

    const req = new NextRequest("http://localhost/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: "rafli", parentId: "page-parent-1" }),
    });

    const res = await POST(req);

    expect(res.status).toBe(200);
    expect(mockedPrisma.page.findFirst).toHaveBeenCalledWith(
      expect.objectContaining({ where: { workspace: "rafli", parentId: "page-parent-1" } })
    );
    expect(mockedPrisma.page.create).toHaveBeenCalledTimes(1);
    expect(mockedPrisma.page.create.mock.calls[0][0]).toMatchObject({
      data: expect.objectContaining({ workspace: "rafli", parentId: "page-parent-1", order: 3 }),
    });

    const body = await res.json();
    expect(body.note.parentId).toBe("page-parent-1");
  });

  it("without parentId: creates a root-level page exactly as before (parentId null)", async () => {
    mockedPrisma.page.findFirst.mockResolvedValue(null);
    mockedPrisma.page.create.mockResolvedValue({
      id: "page-root-1",
      workspace: "rafli",
      parentId: null,
      order: 0,
      title: "Untitled",
    } as never);

    const req = new NextRequest("http://localhost/api/notes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ workspace: "rafli" }),
    });

    const res = await POST(req);

    expect(res.status).toBe(200);
    expect(mockedPrisma.page.findFirst).toHaveBeenCalledWith(
      expect.objectContaining({ where: { workspace: "rafli", parentId: null } })
    );
    expect(mockedPrisma.page.create.mock.calls[0][0]).toMatchObject({
      data: expect.objectContaining({ workspace: "rafli", parentId: null, order: 0 }),
    });

    const body = await res.json();
    expect(body.note.parentId).toBeNull();
  });
});

describe("GET /api/notes", () => {
  it("lists pages for the given workspace", async () => {
    mockedPrisma.page.findMany.mockResolvedValue([{ id: "p1", workspace: "rafli" }] as never);

    const req = new NextRequest("http://localhost/api/notes?ws=rafli");
    const res = await GET(req);

    expect(res.status).toBe(200);
    expect(mockedPrisma.page.findMany).toHaveBeenCalledWith(
      expect.objectContaining({ where: { workspace: "rafli" } })
    );
  });
});
