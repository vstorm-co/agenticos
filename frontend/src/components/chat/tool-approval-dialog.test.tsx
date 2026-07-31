import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ToolApprovalDialog } from "./tool-approval-dialog";
import type { ActionRequest } from "@/types";

function action(id: string, overrides: Partial<ActionRequest> = {}): ActionRequest {
  return {
    id,
    tool_name: "send_email",
    args: { to: "customer@example.com", subject: "Refund" },
    ...overrides,
  } as ActionRequest;
}

function mount(actionRequests: ActionRequest[]) {
  const onDecisions = vi.fn();
  render(
    <ToolApprovalDialog
      actionRequests={actionRequests}
      reviewConfigs={[]}
      onDecisions={onDecisions}
    />,
  );
  return onDecisions;
}

/**
 * The dialog that stands between an agent and something it cannot undo.
 *
 * The decision it produces is derived rather than chosen: the arguments are
 * editable, and what comes back is `approve` if they are untouched, `edit` if
 * they changed, and `reject` if what was typed is not valid JSON. That last one
 * is the important one - a malformed edit must not be sent as an approval of the
 * original arguments, which is exactly what a "submit anyway" would do.
 */
describe("the tool approval dialog", () => {
  it("says what is waiting, and shows each tool's arguments", () => {
    mount([action("ar-1"), action("ar-2", { tool_name: "delete_row" })]);

    expect(screen.getByText("Tool approval required")).toBeInTheDocument();
    expect(screen.getByText("send_email")).toBeInTheDocument();
    expect(screen.getByText("delete_row")).toBeInTheDocument();
    expect(screen.getAllByRole("textbox")).toHaveLength(2);
  });

  it("shows the arguments as readable JSON rather than one line", () => {
    mount([action("ar-1")]);

    expect(screen.getByRole("textbox")).toHaveValue(
      JSON.stringify({ to: "customer@example.com", subject: "Refund" }, null, 2),
    );
  });

  it("counts what a submission covers, so nobody approves more than they read", () => {
    mount([action("ar-1"), action("ar-2")]);

    expect(screen.getByRole("button", { name: "Submit (2)" })).toBeInTheDocument();
  });

  it("approves every untouched call", async () => {
    const onDecisions = mount([action("ar-1"), action("ar-2")]);

    await userEvent.click(screen.getByRole("button", { name: "Submit (2)" }));

    expect(onDecisions).toHaveBeenCalledWith([{ type: "approve" }, { type: "approve" }]);
  });

  it("sends an edited call as an edit, carrying what was typed", async () => {
    const onDecisions = mount([action("ar-1")]);

    await userEvent.clear(screen.getByRole("textbox"));
    await userEvent.type(screen.getByRole("textbox"), '{{"to":"someone@else.example"}');
    await userEvent.click(screen.getByRole("button", { name: "Submit (1)" }));

    expect(onDecisions).toHaveBeenCalledWith([
      {
        type: "edit",
        editedAction: {
          id: "ar-1",
          tool_name: "send_email",
          args: { to: "someone@else.example" },
        },
      },
    ]);
  });

  it("treats a reformatted edit as no edit at all", async () => {
    // Whitespace is not a change: comparing the parsed values rather than the text
    // is what keeps a re-indent from being recorded as a departure.
    const onDecisions = mount([action("ar-1", { args: { to: "a@b.c" } })]);

    await userEvent.clear(screen.getByRole("textbox"));
    await userEvent.type(screen.getByRole("textbox"), '{{ "to" : "a@b.c" }');
    await userEvent.click(screen.getByRole("button", { name: "Submit (1)" }));

    expect(onDecisions).toHaveBeenCalledWith([{ type: "approve" }]);
  });

  it("rejects a call whose arguments no longer parse", async () => {
    // The safe reading of "I broke the JSON": never the original arguments, which
    // is what approving would send.
    const onDecisions = mount([action("ar-1")]);

    await userEvent.clear(screen.getByRole("textbox"));
    await userEvent.type(screen.getByRole("textbox"), "{{ oops");
    await userEvent.click(screen.getByRole("button", { name: "Submit (1)" }));

    expect(onDecisions).toHaveBeenCalledWith([{ type: "reject" }]);
  });

  it("decides each call on its own", async () => {
    const onDecisions = mount([
      action("ar-1", { args: { to: "a@b.c" } }),
      action("ar-2", { tool_name: "delete_row", args: { id: 1 } }),
    ]);

    const [first] = screen.getAllByRole("textbox");
    await userEvent.clear(first!);
    await userEvent.type(first!, "not json");
    await userEvent.click(screen.getByRole("button", { name: "Submit (2)" }));

    expect(onDecisions).toHaveBeenCalledWith([{ type: "reject" }, { type: "approve" }]);
  });

  it("offers a way back only once something has been typed", async () => {
    // Two buttons that do nothing are two buttons somebody has to read.
    mount([action("ar-1")]);
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();

    await userEvent.type(screen.getByRole("textbox"), " ");

    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();
  });

  it("puts the original arguments back on cancel", async () => {
    const original = JSON.stringify({ to: "customer@example.com", subject: "Refund" }, null, 2);
    mount([action("ar-1")]);
    await userEvent.clear(screen.getByRole("textbox"));
    await userEvent.type(screen.getByRole("textbox"), "changed");

    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.getByRole("textbox")).toHaveValue(original);
    expect(screen.queryByRole("button", { name: "Cancel" })).toBeNull();
  });

  it("accepts an edit that parses, and keeps offering the way back when it does not", async () => {
    // `Save` is a checkpoint, not a submission: it clears the unsaved marker only
    // when every edit is valid JSON.
    mount([action("ar-1")]);
    await userEvent.clear(screen.getByRole("textbox"));
    await userEvent.type(screen.getByRole("textbox"), "{{ oops");

    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByRole("button", { name: "Save" })).toBeInTheDocument();

    await userEvent.clear(screen.getByRole("textbox"));
    await userEvent.type(screen.getByRole("textbox"), '{{"to":"a@b.c"}');
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("accepts nothing at all while the decision is being sent", async () => {
    const onDecisions = vi.fn();
    render(
      <ToolApprovalDialog
        actionRequests={[action("ar-1")]}
        reviewConfigs={[]}
        onDecisions={onDecisions}
        disabled
      />,
    );

    await userEvent.type(screen.getByRole("textbox"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Submit (1)" }));

    expect(onDecisions).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox")).toBeDisabled();
  });

  it("grows the box with the arguments, up to a limit", () => {
    // A twenty-line payload in a three-line box is a payload nobody reads before
    // approving it.
    mount([action("ar-1", { args: { lines: Array.from({ length: 30 }, (_, i) => i) } })]);

    expect(screen.getByRole("textbox")).toHaveAttribute("rows", "10");
  });

  it("keeps a minimum height for a tool that takes nothing", () => {
    mount([action("ar-1", { args: {} })]);

    expect(screen.getByRole("textbox")).toHaveAttribute("rows", "2");
  });
});
