import { describe, it, expect, vi, beforeEach } from "vitest";
import { uploadBlockFile } from "@/lib/upload-block-file";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("uploadBlockFile", () => {
  it("POSTs a FormData containing the file to /api/blocks/upload", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        url: "https://example.supabase.co/storage/v1/object/public/note-attachments/test.png",
        name: "test.png",
        size: 1024,
      }),
    });
    global.fetch = mockFetch;

    const file = new File(["hello world"], "test.png", { type: "image/png" });
    const result = await uploadBlockFile(file);

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/blocks/upload");
    expect(options.method).toBe("POST");
    expect(options.body instanceof FormData).toBe(true);

    // Verify the FormData contains the file
    const formData = options.body as FormData;
    const formFile = formData.get("file");
    expect(formFile).toBe(file);

    // Verify the result
    expect(result.url).toBe("https://example.supabase.co/storage/v1/object/public/note-attachments/test.png");
    expect(result.name).toBe("test.png");
    expect(result.size).toBe(1024);
  });

  it("returns the parsed response on success", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        url: "https://cdn.example.com/image.jpg",
        name: "image.jpg",
        size: 2048,
      }),
    });
    global.fetch = mockFetch;

    const file = new File(["image data"], "image.jpg", { type: "image/jpeg" });
    const result = await uploadBlockFile(file);

    expect(result).toEqual({
      url: "https://cdn.example.com/image.jpg",
      name: "image.jpg",
      size: 2048,
    });
  });

  it("throws when the response is not ok", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
    });
    global.fetch = mockFetch;

    const file = new File(["data"], "file.txt", { type: "text/plain" });

    await expect(uploadBlockFile(file)).rejects.toThrow("Upload failed with status 500");
  });

  it("throws on 400 error", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
    });
    global.fetch = mockFetch;

    const file = new File(["data"], "file.txt", { type: "text/plain" });

    await expect(uploadBlockFile(file)).rejects.toThrow("Upload failed with status 400");
  });
});
