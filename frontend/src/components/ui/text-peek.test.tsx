import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { BlankPeek, peekLines, TextPeek } from "./text-peek";

describe("peekLines", () => {
  it("reads headings by level, list items by marker and joins a hard-wrapped paragraph", () => {
    const lines = peekLines(
      "# Refunds\n\n\nCheck the order\nbefore anything else.\n## Steps\n1. Look it up\n- Use **the** `refund` tool\n```\ncode\n```",
    );

    expect(lines).toEqual([
      { kind: "heading", level: 1, text: "Refunds" },
      { kind: "gap" },
      { kind: "text", text: "Check the order before anything else." },
      { kind: "heading", level: 2, text: "Steps" },
      { kind: "item", marker: "1.", text: "Look it up" },
      { kind: "item", marker: "•", text: "Use the refund tool" },
      { kind: "text", text: "code" },
    ]);
  });

  it("drops a leading blank line and strips links and emphasis", () => {
    expect(peekLines("\n[the docs](https://x.test) and _this_")).toEqual([
      { kind: "text", text: "the docs and this" },
    ]);
  });
});

describe("TextPeek", () => {
  it("draws markdown as headings, items and paragraphs", () => {
    render(<TextPeek source={"# Title\n## Sub\n- one\nplain line"} />);

    expect(screen.getByText("Title")).toBeInTheDocument();
    expect(screen.getByText("Sub")).toBeInTheDocument();
    expect(screen.getByText("one")).toBeInTheDocument();
    expect(screen.getByText("plain line")).toBeInTheDocument();
  });

  it("shows plain content as it is", () => {
    render(<TextPeek source={"region,value\nEU,1"} format="plain" />);

    expect(screen.getByText(/region,value/)).toBeInTheDocument();
  });

  it("draws a blank page with nothing to announce", () => {
    const { container } = render(<BlankPeek />);

    expect(container.firstElementChild).toHaveAttribute("aria-hidden", "true");
  });
});
