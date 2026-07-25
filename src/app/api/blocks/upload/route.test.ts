import { describe, it, expect, vi, beforeEach } from "vitest";
import { NextRequest } from "next/server";

vi.mock("@/lib/supabase", () => ({
  supabaseAdmin: {
    storage: {
      from: vi.fn(),
    },
  },
  NOTE_ATTACHMENTS_BUCKET: "note-attachments",
}));

import { supabaseAdmin } from "@/lib/supabase";
import { POST } from "@/app/api/blocks/upload/route";

const mockedSupabaseAdmin = vi.mocked(supabaseAdmin, { deep: true });

function formDataRequest(fields: Record<string, string | Blob>) {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.append(key, value);
  return new NextRequest("http://localhost/api/blocks/upload", {
    method: "POST",
    body: form,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("POST /api/blocks/upload", () => {
  it("uploads the file to the correct bucket/path/content-type and returns the public URL", async () => {
    const upload = vi.fn().mockResolvedValue({ error: null });
    const getPublicUrl = vi.fn().mockReturnValue({ data: { publicUrl: "https://example.supabase.co/storage/v1/object/public/note-attachments/mock-path.png" } });
    mockedSupabaseAdmin.storage.from.mockReturnValue({ upload, getPublicUrl } as never);

    const file = new File(["hello world"], "photo.png", { type: "image/png" });
    const req = formDataRequest({ file });

    const res = await POST(req);
    const body = await res.json();

    expect(res.status).toBe(200);
    expect(mockedSupabaseAdmin.storage.from).toHaveBeenCalledWith("note-attachments");
    expect(upload).toHaveBeenCalledTimes(1);
    const [path, buffer, options] = upload.mock.calls[0];
    expect(path).toMatch(/\.png$/);
    expect(Buffer.isBuffer(buffer)).toBe(true);
    expect(options).toEqual({ contentType: "image/png" });
    expect(body.url).toBe("https://example.supabase.co/storage/v1/object/public/note-attachments/mock-path.png");
    expect(body.name).toBe("photo.png");
  });

  it("rejects without a file field and never calls upload", async () => {
    const upload = vi.fn();
    mockedSupabaseAdmin.storage.from.mockReturnValue({ upload, getPublicUrl: vi.fn() } as never);

    const req = formDataRequest({ notFile: "oops" });
    const res = await POST(req);

    expect(res.status).toBe(400);
    expect(upload).not.toHaveBeenCalled();
  });

  it("returns 500 with the error message when Storage upload fails", async () => {
    const upload = vi.fn().mockResolvedValue({ error: { message: "bucket not found" } });
    const getPublicUrl = vi.fn();
    mockedSupabaseAdmin.storage.from.mockReturnValue({ upload, getPublicUrl } as never);

    const file = new File(["hello world"], "photo.png", { type: "image/png" });
    const req = formDataRequest({ file });

    const res = await POST(req);
    const body = await res.json();

    expect(res.status).toBe(500);
    expect(body.error).toBe("bucket not found");
    expect(getPublicUrl).not.toHaveBeenCalled();
  });
});
