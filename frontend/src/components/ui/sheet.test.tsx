import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { Sheet, SheetContent } from "./sheet";

function renderSheet(open: boolean) {
  const onOpenChange = vi.fn();
  render(
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right">
        <p>settings</p>
      </SheetContent>
    </Sheet>,
  );
  return onOpenChange;
}

describe("the sheet", () => {
  it("closes on Escape", async () => {
    const onOpenChange = renderSheet(true);

    await userEvent.keyboard("{Escape}");

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("leaves an Escape a control inside already handled", async () => {
    // An open select or menu in the panel closes itself on Escape first; the
    // same key must not take the whole panel with it.
    const onOpenChange = renderSheet(true);
    screen.getByText("settings").addEventListener("keydown", (event) => event.preventDefault());

    screen
      .getByText("settings")
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
      );

    expect(onOpenChange).not.toHaveBeenCalled();
  });

  it("listens for nothing while closed", async () => {
    const onOpenChange = renderSheet(false);

    await userEvent.keyboard("{Escape}");

    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
