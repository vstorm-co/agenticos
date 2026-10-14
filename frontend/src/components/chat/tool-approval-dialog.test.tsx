import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToolApprovalDialog } from "./tool-approval-dialog";
import type { ActionRequest } from "@/types";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

/**
 * What the caller may do. Every case below describes the decision itself, which
 * is offered only to somebody holding `approvals:decide` - the permission on the
 * two endpoints `onDecisions` calls. `tool-approval-dialog.integration.test.tsx`
 * covers that gate, against the real hook.
 */
const held: { permissions: Permission[] } = { permissions: [] };

vi.mock("@/hooks", () => ({
  usePermissions: () => ({
    can: (permission: Permission) => held.permissions.includes(permission),
  }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizationList: () => ({ data: [] }),
}));

beforeEach(() => {
  held.permissions = [Perm.approvalsDecide];
});

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
 * The decision used to be *derived* from an editable JSON box - approve if the
 * arguments were untouched, edit if they changed, reject if what was typed no
 * longer parsed. None of it reached anything: every `review_config` the backend
 * sends carries `allow_edit: false`, because the arguments were already recorded
 * on the row being decided about and letting the chat rewrite them would mean
 * approving something other than what was asked. So the decision is now the two
 * answers there actually are, and the arguments are read.
 */
describe("the tool approval dialog", () => {
  it("says what is waiting, and names each call", () => {
    mount([action("a-1", { tool_name: "run_python" })]);

    expect(screen.getByText("Tool approval required")).toBeVisible();
    // The catalog's words - the same ones the step above it uses - as a question.
    expect(screen.getByText("Allow Run Python?")).toBeVisible();
  });

  it("reads a call from an MCP server as its service and what it does there", () => {
    mount([action("a-1", { tool_name: "notion_notion-search", args: { query: "changelog" } })]);

    expect(screen.getByText("Allow Search in Notion?")).toBeVisible();
    expect(screen.getByText("changelog")).toBeVisible();
  });

  it("leads with a command's first line, and keeps the whole of it a click away", async () => {
    // A gated call is nearly always one string that matters, and
    // `{"command": "python - <<'PY'\nimport …"}` hides it: the newlines that make
    // a script readable arrive as `\n`.
    mount([action("a-1", { tool_name: "execute", args: { command: "ls -la\ncat x.txt" } })]);

    expect(screen.getByText("ls -la")).toHaveClass("font-mono");
    await userEvent.click(screen.getByRole("button", { name: "Details" }));
    // The literal text, newline and all - read off the element rather than
    // matched, because the matcher normalises the whitespace this is about.
    expect(screen.getByText(/cat x\.txt/).textContent).toBe("ls -la\ncat x.txt");
  });

  it("names the rest of the arguments in words once asked, not as JSON", async () => {
    mount([action("a-1")]);

    // An email's subject says what it is about; who it goes to is the detail.
    expect(screen.getByText("Refund")).toBeVisible();
    expect(screen.queryByText("customer@example.com")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByText("To")).toBeVisible();
    expect(screen.getByText("customer@example.com")).toBeVisible();
  });

  it("asks about a call that takes nothing without a line of arguments", () => {
    mount([action("a-1", { tool_name: "run_python", args: undefined })]);
    expect(screen.getByText("Allow Run Python?")).toBeVisible();
  });

  it("approves every call it is showing", async () => {
    const onDecisions = mount([action("a-1"), action("a-2")]);

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(onDecisions).toHaveBeenCalledWith([{ type: "approve" }, { type: "approve" }]);
  });

  it("refuses every call it is showing", async () => {
    const onDecisions = mount([action("a-1"), action("a-2")]);

    await userEvent.click(screen.getByRole("button", { name: "Reject" }));

    expect(onDecisions).toHaveBeenCalledWith([{ type: "reject" }, { type: "reject" }]);
  });

  it("offers no decision to somebody who cannot make one, and says why", () => {
    // `member` and `builder` hold `agents:run` and not the decision, so the
    // everyday chat user was offered a control the API refuses on the first call.
    held.permissions = [];

    mount([action("a-1")]);

    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.getByText(/needs a permission you do not hold/)).toBeVisible();
  });

  it("still shows what the run is waiting for, to somebody who cannot decide", () => {
    // A panel that goes quiet leaves a stopped conversation unexplained.
    held.permissions = [];

    mount([action("a-1", { tool_name: "run_python" })]);

    expect(screen.getByText("Tool approval required")).toBeVisible();
    expect(screen.getByText("Allow Run Python?")).toBeVisible();
  });

  it("accepts nothing at all while the decision is being sent", () => {
    const onDecisions = vi.fn();
    render(
      <ToolApprovalDialog
        actionRequests={[action("a-1")]}
        reviewConfigs={[]}
        onDecisions={onDecisions}
        disabled
      />,
    );

    expect(screen.getByRole("button", { name: "Approve" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
  });

  it("shows the AI Architect's agent draft as a draft, not as a call (#1799)", () => {
    mount([
      action("a-1", {
        tool_name: "agenticos_create_agent_draft",
        args: { name: "Helpdesk", instructions: "Answer from the handbook." },
      }),
      action("a-2", { tool_name: "agenticos_create_agent_draft", args: { instructions: "x" } }),
    ]);

    expect(screen.getByText("A new agent draft")).toBeVisible();
    expect(screen.getByText("Helpdesk")).toBeVisible();
    // Arguments that are not a draft are asked about as any call is.
    expect(screen.getByText("Allow Agenticos create agent draft?")).toBeVisible();
  });
});
