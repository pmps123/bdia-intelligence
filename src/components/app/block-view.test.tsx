// @vitest-environment jsdom
import * as React from "react";
import { describe, it, expect, vi, afterEach, beforeEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import type { BlockDto, NumberedBlockContent, NumberedItem, ToggleBlockContent } from "@/lib/types";
import {
  HeadingBlockView,
  DividerBlockView,
  QuoteBlockView,
  CalloutBlockView,
  NumberedBlockView,
  ToggleBlockView,
  PageBlockView,
  LinkPageBlockView,
  VideoBlockView,
  FileBlockView,
} from "@/components/app/block-view";

// this project's vitest config doesn't set `test.globals: true`, so RTL's auto-cleanup (which
// hooks a global `afterEach`) never registers — without this, renders from one test leak into
// the next and multi-match queries below fail non-deterministically depending on run order.
afterEach(cleanup);

describe("HeadingBlockView", () => {
  it("renders level 1 with the text-2xl size class", () => {
    render(<HeadingBlockView content={{ text: "Big", level: 1 }} onChange={() => {}} />);
    const input = screen.getByPlaceholderText("Heading");
    expect(input).toHaveValue("Big");
    expect(input).toHaveClass("text-2xl");
  });

  it("renders level 3 with the text-lg size class, not the level 1 class", () => {
    render(<HeadingBlockView content={{ text: "Smaller", level: 3 }} onChange={() => {}} />);
    const input = screen.getByPlaceholderText("Heading");
    expect(input).toHaveClass("text-lg");
    expect(input).not.toHaveClass("text-2xl");
  });
});

describe("DividerBlockView", () => {
  it("renders an hr", () => {
    const { container } = render(<DividerBlockView />);
    expect(container.querySelector("hr")).toBeInTheDocument();
  });
});

describe("QuoteBlockView", () => {
  it("renders the given text and calls onChange when edited", () => {
    const onChange = vi.fn();
    render(<QuoteBlockView content={{ text: "A wise quote" }} onChange={onChange} />);
    const textarea = screen.getByPlaceholderText("Quote");
    expect(textarea).toHaveValue("A wise quote");

    fireEvent.change(textarea, { target: { value: "An updated quote" } });
    expect(onChange).toHaveBeenCalledWith({ text: "An updated quote" });
  });
});

describe("CalloutBlockView", () => {
  it("renders the given icon/text, and clicking a different icon in the popover calls onChange with it", () => {
    const onChange = vi.fn();
    render(<CalloutBlockView content={{ text: "Heads up", icon: "💡" }} onChange={onChange} />);

    const trigger = screen.getByText("💡");
    expect(screen.getByPlaceholderText("Callout text")).toHaveValue("Heads up");

    // popover options aren't in the DOM until the trigger opens it
    expect(screen.queryByText("⚠️")).not.toBeInTheDocument();
    fireEvent.click(trigger);
    const warningOption = screen.getByText("⚠️");
    expect(warningOption).toBeInTheDocument();

    fireEvent.click(warningOption);
    expect(onChange).toHaveBeenCalledWith({ text: "Heads up", icon: "⚠️" });
  });

  it("calls onChange with updated text when the textarea is edited", () => {
    const onChange = vi.fn();
    render(<CalloutBlockView content={{ text: "", icon: "💡" }} onChange={onChange} />);
    fireEvent.change(screen.getByPlaceholderText("Callout text"), { target: { value: "New text" } });
    expect(onChange).toHaveBeenCalledWith({ text: "New text", icon: "💡" });
  });
});

/** Stateful wrapper: NumberedBlockView is a controlled component whose interactions (Enter,
 *  Backspace) only take visible effect once the parent applies onChange back into `content` —
 *  exactly how the real page component drives it. */
function NumberedBlockHarness({ initialItems, onEmptyBackspaceOnly }: { initialItems: NumberedItem[]; onEmptyBackspaceOnly?: () => void }) {
  const [content, setContent] = React.useState<NumberedBlockContent>({ items: initialItems });
  return (
    <NumberedBlockView
      content={content}
      onChange={(c) => setContent((prev) => (typeof c === "function" ? (c(prev) as NumberedBlockContent) : (c as NumberedBlockContent)))}
      onEmptyBackspaceOnly={onEmptyBackspaceOnly}
    />
  );
}

describe("NumberedBlockView", () => {
  it("renders items with correct 1. 2. 3. prefixes", () => {
    render(
      <NumberedBlockHarness
        initialItems={[
          { id: "a", text: "First" },
          { id: "b", text: "Second" },
          { id: "c", text: "Third" },
        ]}
      />
    );
    const prefixes = ["1.", "2.", "3."].map((p) => screen.getByText(p));
    expect(prefixes).toHaveLength(3);
    expect(screen.getByDisplayValue("First")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Second")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Third")).toBeInTheDocument();
  });

  it("pressing Enter in an item adds a new one after it and renumbers", () => {
    render(
      <NumberedBlockHarness
        initialItems={[
          { id: "a", text: "First" },
          { id: "b", text: "Second" },
        ]}
      />
    );
    fireEvent.keyDown(screen.getByDisplayValue("First"), { key: "Enter" });

    // three items now: First, (new empty), Second — with a fresh "1. 2. 3." numbering
    const inputs = screen.getAllByPlaceholderText("List item");
    expect(inputs).toHaveLength(3);
    expect(inputs[0]).toHaveValue("First");
    expect(inputs[1]).toHaveValue("");
    expect(inputs[2]).toHaveValue("Second");
    expect(screen.getByText("1.")).toBeInTheDocument();
    expect(screen.getByText("2.")).toBeInTheDocument();
    expect(screen.getByText("3.")).toBeInTheDocument();
  });

  it("pressing Backspace on an empty item removes it and renumbers", () => {
    render(
      <NumberedBlockHarness
        initialItems={[
          { id: "a", text: "First" },
          { id: "b", text: "" },
          { id: "c", text: "Third" },
        ]}
      />
    );
    const emptyInput = screen.getAllByPlaceholderText("List item")[1];
    fireEvent.keyDown(emptyInput, { key: "Backspace" });

    const inputs = screen.getAllByPlaceholderText("List item");
    expect(inputs).toHaveLength(2);
    expect(inputs[0]).toHaveValue("First");
    expect(inputs[1]).toHaveValue("Third");
    expect(screen.getByText("1.")).toBeInTheDocument();
    expect(screen.getByText("2.")).toBeInTheDocument();
    expect(screen.queryByText("3.")).not.toBeInTheDocument();
  });

  it("Backspace on the sole remaining empty item calls onEmptyBackspaceOnly instead of removing it", () => {
    const onEmptyBackspaceOnly = vi.fn();
    render(<NumberedBlockHarness initialItems={[{ id: "a", text: "" }]} onEmptyBackspaceOnly={onEmptyBackspaceOnly} />);
    fireEvent.keyDown(screen.getByPlaceholderText("List item"), { key: "Backspace" });
    expect(onEmptyBackspaceOnly).toHaveBeenCalledTimes(1);
    expect(screen.getAllByPlaceholderText("List item")).toHaveLength(1);
  });

  it("shows an empty-state Add item button with zero items, and clicking it creates the first item", () => {
    render(<NumberedBlockHarness initialItems={[]} />);
    expect(screen.queryByPlaceholderText("List item")).not.toBeInTheDocument();
    const addButton = screen.getByRole("button", { name: /add item/i });
    expect(addButton).toBeInTheDocument();

    fireEvent.click(addButton);
    expect(screen.getByPlaceholderText("List item")).toBeInTheDocument();
    expect(screen.getByText("1.")).toBeInTheDocument();
  });
});

const TEXT_PLACEHOLDER = "Type something, or '/' for commands…";

/** Stateful wrapper: mirrors how the real page drives ToggleBlockView — onChange always hands back
 *  an updater function, and this harness resolves it against the latest state exactly like the
 *  real save flow does. */
function ToggleBlockHarness({ initial }: { initial: ToggleBlockContent }) {
  const [content, setContent] = React.useState<ToggleBlockContent>(initial);
  return (
    <ToggleBlockView
      content={content}
      onChange={(c) => setContent((prev) => (typeof c === "function" ? (c(prev) as ToggleBlockContent) : (c as ToggleBlockContent)))}
    />
  );
}

describe("ToggleBlockView", () => {
  const makeChild = (id: string, text: string): BlockDto => ({
    id,
    workspace: "",
    order: 0,
    type: "text",
    content: { text },
  });

  it("starts collapsed — a nested child isn't in the DOM until expanded — then expand/collapse toggles it", () => {
    const content: ToggleBlockContent = { text: "My toggle", children: [makeChild("c1", "Hidden text")] };
    render(<ToggleBlockView content={content} onChange={() => {}} />);

    expect(screen.queryByPlaceholderText(TEXT_PLACEHOLDER)).not.toBeInTheDocument();

    const toggleButton = screen.getByRole("button");
    fireEvent.click(toggleButton);
    expect(screen.getByPlaceholderText(TEXT_PLACEHOLDER)).toHaveValue("Hidden text");

    fireEvent.click(toggleButton);
    expect(screen.queryByPlaceholderText(TEXT_PLACEHOLDER)).not.toBeInTheDocument();
  });

  it("Add inside toggle creates a new nested text block, which can be typed into", () => {
    render(<ToggleBlockHarness initial={{ text: "Empty toggle", children: [] }} />);

    fireEvent.click(screen.getByRole("button")); // expand
    expect(screen.queryByPlaceholderText(TEXT_PLACEHOLDER)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /add inside toggle/i }));
    const childTextarea = screen.getByPlaceholderText(TEXT_PLACEHOLDER);
    expect(childTextarea).toHaveValue("");

    fireEvent.change(childTextarea, { target: { value: "typed inside toggle" } });
    expect(screen.getByPlaceholderText(TEXT_PLACEHOLDER)).toHaveValue("typed inside toggle");
  });

  it("editing a nested child's content resolves, via the onChange updater, into the parent's content.children array", () => {
    const onChange = vi.fn();
    const content: ToggleBlockContent = { text: "Toggle", children: [makeChild("child-1", "original")] };
    render(<ToggleBlockView content={content} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button")); // expand — local `open` state, no onChange call
    expect(onChange).not.toHaveBeenCalled();

    fireEvent.change(screen.getByPlaceholderText(TEXT_PLACEHOLDER), { target: { value: "updated text" } });

    expect(onChange).toHaveBeenCalledTimes(1);
    const updater = onChange.mock.calls[0][0];
    expect(typeof updater).toBe("function");

    // resolve the updater against the real prior content, exactly as the page's save flow would
    const result = updater(content) as ToggleBlockContent;
    expect(result.children).toHaveLength(1);
    expect(result.children[0].id).toBe("child-1");
    expect(result.children[0].content).toEqual({ text: "updated text" });
    expect(result.text).toBe("Toggle"); // rest of the parent's own content is untouched
  });

  it("removing a nested child drops it from content.children", () => {
    const onChange = vi.fn();
    const content: ToggleBlockContent = {
      text: "Toggle",
      children: [makeChild("child-1", "keep me"), makeChild("child-2", "remove me")],
    };
    render(<ToggleBlockView content={content} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button")); // expand
    const deleteButtons = screen.getAllByTitle("Delete text block");
    expect(deleteButtons).toHaveLength(2);
    fireEvent.click(deleteButtons[1]); // remove "remove me"

    expect(onChange).toHaveBeenCalledTimes(1);
    const updater = onChange.mock.calls[0][0];
    expect(typeof updater).toBe("function");
    const result = updater(content) as ToggleBlockContent;
    expect(result).toEqual({ text: "Toggle", children: [content.children[0]] });
  });

  it("addChild and removeChild resolve against the latest content, not a stale closure (same-tick safety)", () => {
    const content: ToggleBlockContent = {
      text: "Toggle",
      children: [makeChild("child-1", "first")],
    };
    const onChange = vi.fn();
    render(<ToggleBlockView content={content} onChange={onChange} />);

    fireEvent.click(screen.getByRole("button")); // expand
    fireEvent.click(screen.getByRole("button", { name: /add inside toggle/i }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const addUpdater = onChange.mock.calls[0][0];
    expect(typeof addUpdater).toBe("function");

    // Simulate a same-tick race: resolve addChild's updater against content that already
    // reflects a concurrent removeChild, proving addChild doesn't clobber it with a stale
    // closure-captured `content`.
    const staleRaceBase: ToggleBlockContent = { text: "Toggle", children: [] };
    const result = addUpdater(staleRaceBase) as ToggleBlockContent;
    expect(result.children).toHaveLength(1);
    expect(result.text).toBe("Toggle");
  });

  it("renders the toggle's own label at plain text size with no level set", () => {
    render(<ToggleBlockView content={{ text: "Plain toggle", children: [] }} onChange={() => {}} />);
    const label = screen.getByPlaceholderText("Toggle");
    expect(label).toHaveClass("text-sm");
    expect(label).not.toHaveClass("text-lg");
  });

  it("renders the toggle's own label at heading size for level 1/2/3 (Toggle Heading)", () => {
    for (const level of [1, 2, 3] as const) {
      const { unmount } = render(
        <ToggleBlockView content={{ text: `Heading ${level}`, level, children: [] }} onChange={() => {}} />
      );
      const label = screen.getByPlaceholderText("Toggle");
      expect(label).toHaveClass("font-display", "font-semibold", "text-lg");
      expect(label).not.toHaveClass("text-sm");
      unmount();
    }
  });
});

describe("PageBlockView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("shows a New sub-page button when content.pageId is empty, and never calls fetch", () => {
    const mockFetch = vi.fn();
    global.fetch = mockFetch;
    render(<PageBlockView content={{ pageId: "" }} onChange={() => {}} workspace="rafli" />);

    expect(screen.getByRole("button", { name: /new sub-page/i })).toBeInTheDocument();
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("clicking New sub-page POSTs /api/notes with the workspace and current page's id as parentId, then calls onChange with the returned page's id", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ note: { id: "new-page-1", workspace: "rafli", parentId: "page-parent-1", title: "Untitled" } }),
    });
    global.fetch = mockFetch;
    const onChange = vi.fn();
    render(<PageBlockView content={{ pageId: "" }} onChange={onChange} workspace="rafli" pageId="page-parent-1" />);

    fireEvent.click(screen.getByRole("button", { name: /new sub-page/i }));

    await waitFor(() => expect(onChange).toHaveBeenCalledWith({ pageId: "new-page-1" }));

    expect(mockFetch).toHaveBeenCalledTimes(1);
    const [url, options] = mockFetch.mock.calls[0];
    expect(url).toBe("/api/notes");
    expect(options.method).toBe("POST");
    // this is the regression this task fixes: the sub-page must be created as a genuine child
    // of the current page (parentId), not a top-level page.
    expect(JSON.parse(options.body)).toEqual({ workspace: "rafli", parentId: "page-parent-1" });
  });

  it("once content.pageId is set, fetches /api/notes?ws=<workspace>, finds the matching page, and renders its title as a link", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        notes: [
          { id: "other-page", title: "Not this one" },
          { id: "page-42", title: "My Sub Page" },
        ],
      }),
    });
    global.fetch = mockFetch;
    render(<PageBlockView content={{ pageId: "page-42" }} onChange={() => {}} workspace="rafli" />);

    expect(mockFetch).toHaveBeenCalledWith("/api/notes?ws=rafli");

    const link = await screen.findByRole("link", { name: /my sub page/i });
    expect(link).toHaveAttribute("href", "/notes?id=page-42");
    expect(screen.queryByRole("button", { name: /new sub-page/i })).not.toBeInTheDocument();
  });
});

describe("LinkPageBlockView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("fetches /api/notes?ws=<workspace> on mount, and the popover lists the returned pages", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        notes: [
          { id: "p1", title: "Page One" },
          { id: "p2", title: "Page Two" },
        ],
      }),
    });
    global.fetch = mockFetch;
    render(<LinkPageBlockView content={{ pageId: "" }} onChange={() => {}} workspace="rafli" />);

    expect(mockFetch).toHaveBeenCalledWith("/api/notes?ws=rafli");

    fireEvent.click(screen.getByRole("button", { name: /link to page/i }));

    expect(await screen.findByRole("button", { name: "Page One" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Page Two" })).toBeInTheDocument();
  });

  it("selecting a page calls onChange with its id and closes the popover", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ notes: [{ id: "p1", title: "Page One" }] }),
    });
    global.fetch = mockFetch;
    const onChange = vi.fn();
    render(<LinkPageBlockView content={{ pageId: "" }} onChange={onChange} workspace="rafli" />);

    fireEvent.click(screen.getByRole("button", { name: /link to page/i }));
    const option = await screen.findByRole("button", { name: "Page One" });
    fireEvent.click(option);

    expect(onChange).toHaveBeenCalledWith({ pageId: "p1" });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Page One" })).not.toBeInTheDocument());
  });

  it("once content.pageId matches a fetched page, the trigger shows its title instead of the placeholder", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ notes: [{ id: "p1", title: "Selected Page" }] }),
    });
    global.fetch = mockFetch;
    render(<LinkPageBlockView content={{ pageId: "p1" }} onChange={() => {}} workspace="rafli" />);

    expect(await screen.findByRole("button", { name: /selected page/i })).toBeInTheDocument();
    expect(screen.queryByText("Link to page…")).not.toBeInTheDocument();
  });
});

describe("VideoBlockView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders a placeholder when there's no url", () => {
    render(<VideoBlockView content={{ url: "", caption: "" }} onChange={() => {}} />);
    expect(screen.getByText("No video yet")).toBeInTheDocument();
    expect(document.querySelector("video")).not.toBeInTheDocument();
  });

  it("renders a <video> element with the url once set", () => {
    render(<VideoBlockView content={{ url: "https://example.com/clip.mp4", caption: "" }} onChange={() => {}} />);
    const video = document.querySelector("video");
    expect(video).toBeInTheDocument();
    expect(video).toHaveAttribute("src", "https://example.com/clip.mp4");
    expect(screen.queryByText("No video yet")).not.toBeInTheDocument();
  });

  it("typing a URL directly calls onChange, without touching fetch", () => {
    const mockFetch = vi.fn();
    global.fetch = mockFetch;
    const onChange = vi.fn();
    render(<VideoBlockView content={{ url: "", caption: "" }} onChange={onChange} />);

    fireEvent.change(screen.getByPlaceholderText("Paste a video URL…"), { target: { value: "https://youtu.be/abc123" } });

    expect(onChange).toHaveBeenCalledWith({ url: "https://youtu.be/abc123", caption: "" });
    expect(mockFetch).not.toHaveBeenCalled();
  });

  it("clicking Upload and selecting a file uploads it and calls onChange with the resulting url", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ url: "https://storage.example.com/videos/clip.mp4", name: "clip.mp4", size: 1234 }),
    });
    global.fetch = mockFetch;
    const onChange = vi.fn();
    const { container } = render(<VideoBlockView content={{ url: "", caption: "" }} onChange={onChange} />);

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["binary-video-bytes"], "clip.mp4", { type: "video/mp4" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() => expect(onChange).toHaveBeenCalledWith({ url: "https://storage.example.com/videos/clip.mp4", caption: "" }));
    expect(mockFetch).toHaveBeenCalledWith("/api/blocks/upload", expect.objectContaining({ method: "POST" }));
  });
});

describe("FileBlockView", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders an upload prompt when there's no url", () => {
    render(<FileBlockView content={{ url: "", name: "", size: 0 }} onChange={() => {}} />);
    expect(screen.getByRole("button", { name: /upload a file/i })).toBeInTheDocument();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("renders a download link with name and size once url is set", () => {
    render(<FileBlockView content={{ url: "https://storage.example.com/files/report.pdf", name: "report.pdf", size: 2048 }} onChange={() => {}} />);
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "https://storage.example.com/files/report.pdf");
    expect(link).toHaveTextContent("report.pdf");
    expect(link).toHaveTextContent("(2.0 KB)");
    expect(screen.queryByRole("button", { name: /upload a file/i })).not.toBeInTheDocument();
  });

  it("upload flow calls onChange with {url, name, size} from the upload response", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ url: "https://storage.example.com/files/notes.txt", name: "notes.txt", size: 42 }),
    });
    global.fetch = mockFetch;
    const onChange = vi.fn();
    const { container } = render(<FileBlockView content={{ url: "", name: "", size: 0 }} onChange={onChange} />);

    const fileInput = container.querySelector('input[type="file"]') as HTMLInputElement;
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    fireEvent.change(fileInput, { target: { files: [file] } });

    await waitFor(() =>
      expect(onChange).toHaveBeenCalledWith({ url: "https://storage.example.com/files/notes.txt", name: "notes.txt", size: 42 })
    );
    expect(mockFetch).toHaveBeenCalledWith("/api/blocks/upload", expect.objectContaining({ method: "POST" }));
  });
});
