import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./confirm-dialog";
import { Dialog, DialogContent, DialogTitle, DialogTrigger } from "./dialog";

function Harness({ dismissible = true }: { dismissible?: boolean }) {
  const [open, setOpen] = useState(true);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent dismissible={dismissible}>
        <DialogTitle>Settings</DialogTitle>
      </DialogContent>
    </Dialog>
  );
}

describe("dialog dismissal", () => {
  it("keeps the confirmation phrase and its surrounding spaces in the same text flow", () => {
    render(
      <ConfirmDialog
        open
        onOpenChange={vi.fn()}
        title="Delete project?"
        confirmText="Example"
        onConfirm={vi.fn()}
      />,
    );

    const textbox = screen.getByRole<HTMLInputElement>("textbox");
    const label = textbox.labels?.[0];
    expect(label?.firstElementChild?.textContent).toBe("Type Example to confirm");
  });

  it("keeps contextual sheets modal and returns keyboard focus to their invoker", async () => {
    const user = userEvent.setup();
    render(
      <Dialog>
        <DialogTrigger>Edit title</DialogTrigger>
        <DialogContent mobilePresentation="sheet">
          <DialogTitle>Conversation title</DialogTitle>
          <label>
            Title
            <input defaultValue="Draft title" />
          </label>
        </DialogContent>
      </Dialog>,
    );
    const invoker = screen.getByRole("button", { name: "Edit title" });
    await user.click(invoker);
    expect(screen.getByRole("dialog")).toHaveAttribute("data-mobile-presentation", "sheet");
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveFocus();
    await user.keyboard("{Shift>}{Tab}{/Shift}");
    expect(screen.getByRole("button", { name: "Close" })).toHaveFocus();
    await user.keyboard("{Tab}");
    expect(screen.getByRole("textbox", { name: "Title" })).toHaveFocus();
    await user.type(screen.getByRole("textbox"), " changed");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(invoker).toHaveFocus();
  });

  it("also keeps a pending confirmation open", async () => {
    const changed = vi.fn();
    render(
      <ConfirmDialog
        open
        onOpenChange={changed}
        title="Remove member?"
        loading
        onConfirm={vi.fn()}
      />,
    );
    expect(screen.getByRole("dialog")).toHaveAttribute("data-mobile-presentation", "center");
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    expect(changed).not.toHaveBeenCalled();
  });

  it("keeps a pending operation visible, then restores dismissal", async () => {
    const user = userEvent.setup();
    const view = render(<Harness dismissible={false} />);
    expect(screen.getByRole("button", { name: "Close" })).toBeDisabled();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("dialog")).toBeVisible();
    view.rerender(<Harness dismissible />);
    expect(screen.getByRole("button", { name: "Close" })).toBeEnabled();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("keeps ordinary dialogs dismissible by default", async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
