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

  it("names the account a call acts as, and none where there is only one", () => {
    mount([
      action("a-1", { tool_name: "gmail_send", account: "Work" }),
      action("a-2", { tool_name: "notion_notion-search", args: { query: "changelog" } }),
    ]);

    expect(screen.getAllByText(/^Account: /).map((badge) => badge.textContent)).toEqual([
      "Account: Work",
    ]);
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

  it("says why the agent asks before what it would run", async () => {
    mount([
      action("a-1", {
        tool_name: "update_record",
        args: { table_id: "t-1", reason: "So the order shows as shipped." },
      }),
    ]);

    expect(screen.getByText("So the order shows as shipped.")).toBeVisible();
    // The reason is the sentence on top, not one more row.
    await userEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.queryByText("Reason")).toBeNull();
    // Once as the call's one telling argument, once in the details.
    expect(screen.getAllByText("t-1")).toHaveLength(2);
  });

  it("says what the call will do in names, under the reason and over the ids", async () => {
    mount([
      action("a-1", {
        tool_name: "update_record",
        args: { table_id: "t-1", reason: "So the order shows as shipped." },
        capability_tool_id: "update_record",
        context: { table: "E2E Live Tickets" },
      }),
    ]);

    const sentence = screen.getByText("Change a record in E2E Live Tickets");
    expect(sentence).toBeVisible();
    // After the agent's own reason, and the ids it names are still there below.
    expect(
      screen.getByText("So the order shows as shipped.").compareDocumentPosition(sentence),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    await userEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByText("t-1")).toBeVisible();
  });

  it("names the table a record is written to, never the record", () => {
    mount([
      action("a-1", {
        tool_name: "delete_record",
        args: { table_id: "t-1", record_id: "r-1", expected_revision: 2 },
        capability_tool_id: "delete_record",
        context: { table: "Orders" },
      }),
      action("a-2", {
        tool_name: "create_record",
        args: { table_id: "t-1", values: { Quantity: 2 } },
        capability_tool_id: "create_record",
        context: { table: "Orders" },
      }),
    ]);

    expect(screen.getByText("Delete a record from Orders")).toBeVisible();
    expect(screen.getByText("Add a record to Orders")).toBeVisible();
  });

  it("finds the sentence for a renamed tool by its stable id, not its name", () => {
    mount([
      action("a-1", {
        tool_name: "change_order",
        args: { table_id: "t-1" },
        capability_tool_id: "update_record",
        context: { table: "Orders" },
      }),
      // The name of a described tool, with no stable id: an MCP server's tool under
      // "ask about everything" is not the capability's tool and gets no sentence.
      action("a-2", {
        tool_name: "update_record",
        args: { table_id: "t-2" },
        context: { table: "Archive" },
      }),
    ]);

    expect(screen.getByText("Change a record in Orders")).toBeVisible();
    expect(screen.queryByText(/Archive/)).toBeNull();
  });

  it("draws the plain card when the call came with no names, or not the ones it needs", async () => {
    mount([
      action("a-1", {
        tool_name: "update_record",
        args: { table_id: "t-1" },
        capability_tool_id: "update_record",
      }),
      action("a-2", {
        tool_name: "update_record",
        args: { table_id: "t-2" },
        capability_tool_id: "update_record",
        context: { view: "Orders" },
      }),
      action("a-3", { context: { recipient: "Ops" } }),
    ]);

    expect(screen.queryByText(/Change a record/)).toBeNull();
    for (const details of screen.getAllByRole("button", { name: "Details" })) {
      await userEvent.click(details);
    }
    expect(screen.getAllByText("t-1")).toHaveLength(2);
    expect(screen.getAllByText("t-2")).toHaveLength(2);
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
