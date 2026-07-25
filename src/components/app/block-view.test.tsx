// @vitest-environment jsdom
import * as React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import type { BlockDto, NumberedBlockContent, NumberedItem, ToggleBlockContent } from "@/lib/types";
import {
  HeadingBlockView,
  DividerBlockView,
  QuoteBlockView,
  CalloutBlockView,
  NumberedBlockView,
  ToggleBlockView,
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

/** Stateful wrapper: mirrors how the real page drives ToggleBlockView — onChange may hand back
 *  either a plain content object (addChild/removeChild) or an updater function (updateChild),
 *  and this harness resolves both against the latest state exactly like the real save flow does. */
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

    expect(onChange).toHaveBeenCalledWith({ text: "Toggle", children: [content.children[0]] });
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
