import { describe, expect, it, vi } from "vitest";

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { useState } from "react";

import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
} from "./dropdown-menu";
import { Sheet, SheetContent, SheetTitle } from "./sheet";

function renderSheet(open: boolean) {
  const onOpenChange = vi.fn();
  render(
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right">
        <SheetTitle>settings</SheetTitle>
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

  it("closes a nested menu on Escape before closing the sheet", async () => {
    const onOpenChange = vi.fn();
    render(
      <Sheet open onOpenChange={onOpenChange}>
        <SheetContent>
          <SheetTitle>Settings</SheetTitle>
          <DropdownMenu>
            <DropdownMenuTrigger>Options</DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem>Edit</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </SheetContent>
      </Sheet>,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Options" }));
    expect(screen.getByRole("menu")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
    expect(onOpenChange).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("listens for nothing while closed", async () => {
    const onOpenChange = renderSheet(false);

    await userEvent.keyboard("{Escape}");

    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

function ControlledSheet() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)}>Open details</button>
      <button>Outside action</button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent>
          <SheetTitle>Details</SheetTitle>
          <button>First action</button>
          <button onClick={() => setOpen(false)}>Close details</button>
        </SheetContent>
      </Sheet>
    </>
  );
}

it("traps keyboard focus and restores the opener when dismissed", async () => {
  render(<ControlledSheet />);
  const user = userEvent.setup();
  const opener = screen.getByRole("button", { name: "Open details" });
  await user.click(opener);
  expect(screen.getByRole("dialog", { name: "Details" })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "First action" })).toHaveFocus();
  expect(screen.queryByRole("button", { name: "Outside action" })).not.toBeInTheDocument();
  await user.tab({ shift: true });
  expect(screen.getByRole("button", { name: "Close details" })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("button", { name: "First action" })).toHaveFocus();
  await user.keyboard("{Escape}");
  await waitFor(() => expect(opener).toHaveFocus());
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
