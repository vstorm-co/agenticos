import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ConfirmDialog } from "./confirm-dialog";
import { Dialog, DialogContent, DialogTitle } from "./dialog";

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
