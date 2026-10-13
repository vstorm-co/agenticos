import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

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
});
