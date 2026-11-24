import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SaveConfirmDialog } from "./save-confirm-dialog";

function open(readers: string[], reach: number, canCheck = true) {
  const handlers = { onCheck: vi.fn(), onSave: vi.fn(), onCancel: vi.fn() };
  render(
    <SaveConfirmDialog
      version="Returns v3"
      reach={reach}
      readers={readers}
      canCheck={canCheck}
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

  it("counts the reach as the server does, and names only the agents the reader sees", () => {
    open(["Support"], 3);
    expect(
      screen.getByText("It reaches 3 agents on their next run, among them Support."),
    ).toBeInTheDocument();
  });

  it("counts a reach of agents it cannot name", () => {
    open([], 2);
    expect(screen.getByText("It reaches 2 agents on their next run.")).toBeInTheDocument();
  });

  it("offers no check to a reader who may not read runs", () => {
    open(["Support"], 1, false);
    expect(
      screen.getByText("It reaches 1 agent on its next run, among them Support."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check on agents first" })).toBeNull();
  });

  it("goes back on Escape", async () => {
    const { onCancel } = open(["Support"], 1);
    await userEvent.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalled();
  });
});
