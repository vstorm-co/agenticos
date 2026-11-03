import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SaveConfirmDialog } from "./save-confirm-dialog";

function open(readers: string[], hidden: number, canCheck = true) {
  const handlers = { onCheck: vi.fn(), onSave: vi.fn(), onCancel: vi.fn() };
  render(
    <SaveConfirmDialog
      version="Returns v3"
      readers={readers}
      hidden={hidden}
      canCheck={canCheck}
      saving={false}
      {...handlers}
    />,
  );
  return handlers;
}

describe("SaveConfirmDialog", () => {
  it("says no agent's answers change on a line nobody follows, and offers no check", async () => {
    const { onSave } = open([], 0);

    expect(screen.getByText("Save Returns v3?")).toBeInTheDocument();
    expect(screen.getByText(/No agent follows this line yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check on agents first" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Save now" }));
    expect(onSave).toHaveBeenCalled();
  });

  it("counts the agents it cannot name once", () => {
    open([], 2);
    expect(
      screen.getByText("It reaches 2 agents you can't see on their next run."),
    ).toBeInTheDocument();
  });

  it("offers no check to a reader who may not read runs", () => {
    open(["Support"], 0, false);
    expect(screen.getByText("It reaches 1 agent on its next run: Support.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check on agents first" })).toBeNull();
  });

  it("goes back on Escape", async () => {
    const { onCancel } = open(["Support"], 0);
    await userEvent.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalled();
  });
});
