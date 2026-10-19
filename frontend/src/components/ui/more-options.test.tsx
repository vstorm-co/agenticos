import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MoreOptions } from "./more-options";

/** Folded until asked for, and folded again on a second click. */
describe("MoreOptions", () => {
  it("opens and closes what it holds", async () => {
    render(
      <MoreOptions label="More options">
        <p>A note</p>
      </MoreOptions>,
    );
    const toggle = screen.getByRole("button", { name: "More options" });

    expect(screen.queryByText("A note")).toBeNull();
    await userEvent.click(toggle);
    expect(screen.getByText("A note")).toBeVisible();
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    await userEvent.click(toggle);
    expect(screen.queryByText("A note")).toBeNull();
  });

  it("starts open where the caller says so", () => {
    render(
      <MoreOptions label="More options" defaultOpen>
        <p>A note</p>
      </MoreOptions>,
    );

    expect(screen.getByText("A note")).toBeVisible();
  });

  it("is held by a caller that has to open it itself, and reports a click", async () => {
    const onOpenChange = vi.fn();
    const { rerender } = render(
      <MoreOptions label="More options" open={false} onOpenChange={onOpenChange}>
        <p>A note</p>
      </MoreOptions>,
    );

    await userEvent.click(screen.getByRole("button", { name: "More options" }));
    expect(onOpenChange).toHaveBeenCalledWith(true);
    // Still the caller's to open: nothing shows until it says so.
    expect(screen.queryByText("A note")).toBeNull();

    rerender(
      <MoreOptions label="More options" open onOpenChange={onOpenChange}>
        <p>A note</p>
      </MoreOptions>,
    );
    expect(screen.getByText("A note")).toBeVisible();
  });
});
