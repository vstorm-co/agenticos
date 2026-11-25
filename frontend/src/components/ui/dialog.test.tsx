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

describe("focus after a dialog opened from state closes", () => {
  function Opener({ onCloseAutoFocus }: { onCloseAutoFocus?: (event: Event) => void }) {
    const [open, setOpen] = useState(false);
    return (
      <>
        <button onClick={() => setOpen(true)}>End session</button>
        <button>Elsewhere</button>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogContent onCloseAutoFocus={onCloseAutoFocus}>
            <DialogTitle>End this session?</DialogTitle>
          </DialogContent>
        </Dialog>
      </>
    );
  }

  it("returns keyboard focus to the control that opened it", async () => {
    const user = userEvent.setup();
    render(<Opener />);
    await user.click(screen.getByRole("button", { name: "End session" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "End session" })).toHaveFocus();
  });

  it("returns it from a confirmation opened the same way", async () => {
    const user = userEvent.setup();
    function Confirming() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>Discard</button>
          <ConfirmDialog
            open={open}
            onOpenChange={setOpen}
            title="Discard the suggestions?"
            confirmLabel="Discard"
            onConfirm={vi.fn()}
          />
        </>
      );
    }
    render(<Confirming />);
    await user.click(screen.getByRole("button", { name: "Discard" }));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Discard" })).toHaveFocus();
  });

  it("leaves focus where a caller that prevents the default puts it", async () => {
    const user = userEvent.setup();
    render(
      <Opener
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          screen.getByRole("button", { name: "Elsewhere" }).focus();
        }}
      />,
    );
    await user.click(screen.getByRole("button", { name: "End session" }));
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Elsewhere" })).toHaveFocus();
  });

  it("does not reach for an opener that is gone, such as a menu item", async () => {
    const user = userEvent.setup();
    function FromMenu() {
      const [open, setOpen] = useState(false);
      return (
        <>
          {!open && <button onClick={() => setOpen(true)}>Fork</button>}
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogContent>
              <DialogTitle>Fork for the helped agents</DialogTitle>
            </DialogContent>
          </Dialog>
        </>
      );
    }
    render(<FromMenu />);
    const item = screen.getByRole("button", { name: "Fork" });
    await user.click(item);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(item).not.toHaveFocus();
  });
});
