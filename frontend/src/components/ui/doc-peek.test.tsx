import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DocPeek } from "./doc-peek";

describe("DocPeek", () => {
  it("stacks one sheet per page behind, at most two", () => {
    const { container, rerender } = render(<DocPeek sheets={5}>page</DocPeek>);
    expect(container.querySelectorAll(".peek-sheet")).toHaveLength(2);

    rerender(<DocPeek sheets={1}>page</DocPeek>);
    expect(container.querySelectorAll(".peek-sheet")).toHaveLength(1);

    rerender(<DocPeek sheets={-1}>page</DocPeek>);
    expect(container.querySelectorAll(".peek-sheet")).toHaveLength(0);
  });

  it("puts the content on the page and the badge in the corner", () => {
    render(<DocPeek badge="+3 files">first lines</DocPeek>);

    expect(screen.getByText("first lines")).toBeInTheDocument();
    expect(screen.getByText("+3 files")).toBeInTheDocument();
  });

  it("tucks the page in for a small tile", () => {
    const { container } = render(<DocPeek size="compact">page</DocPeek>);

    expect(container.firstElementChild).toHaveClass("peek-compact");
  });
});
