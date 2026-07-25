// @vitest-environment jsdom
import * as React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import type { NumberedBlockContent, NumberedItem } from "@/lib/types";
import {
  HeadingBlockView,
  DividerBlockView,
  QuoteBlockView,
  CalloutBlockView,
  NumberedBlockView,
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
