// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import "@testing-library/jest-dom/vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import {
  HeadingBlockView,
  DividerBlockView,
  QuoteBlockView,
  CalloutBlockView,
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
