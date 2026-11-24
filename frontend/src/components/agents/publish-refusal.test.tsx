import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { PublishRefusal } from "./publish-refusal";
import type { SpecFix } from "@/lib/spec-fixes";

const NO_SANDBOX = "This organization has registered no sandbox connection.";

function mount({
  fixes = ["use_state_workspace", "stop_sharing_unbound"] as SpecFix[],
  canEdit = true,
  fixing = false,
} = {}) {
  const onFix = vi.fn();
  render(
    <PublishRefusal
      problems={[NO_SANDBOX]}
      fixes={fixes}
      canEdit={canEdit}
      onFix={onFix}
      fixing={fixing}
      isModelProblem={() => false}
      onGoToModel={vi.fn()}
    />,
  );
  return onFix;
}

describe("PublishRefusal", () => {
  it("offers each fix the refusal named, and applies the one clicked", async () => {
    const onFix = mount();

    expect(screen.getByText(NO_SANDBOX)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Switch the workspace to Files" }));
    await userEvent.click(
      screen.getByRole("button", { name: "Stop sharing what this agent cannot share" }),
    );

    expect(onFix.mock.calls).toEqual([["use_state_workspace"], ["stop_sharing_unbound"]]);
    expect(screen.getByText(/Publishing stays a step of its own/)).toBeInTheDocument();
  });

  it("lists the problems alone when no fix was offered", () => {
    mount({ fixes: [] });

    expect(screen.getByText(NO_SANDBOX)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("offers no fix to a reader who may not change the draft", () => {
    mount({ canEdit: false });

    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText(/Publishing stays a step of its own/)).not.toBeInTheDocument();
  });

  it("holds the buttons while a fix is being saved", () => {
    mount({ fixing: true });

    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
  });
});
