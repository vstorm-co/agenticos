import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToolApprovalDialog } from "./tool-approval-dialog";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { ActionRequest } from "@/types";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

/**
 * Who is offered the decision, against a mocked backend.
 *
 * `tool-approval-dialog.test.tsx` covers what a decision is made of with the
 * permission stubbed in; this covers the question a stub cannot answer - whether
 * the permission the two endpoints enforce is the one this component reads.
 * Deciding is `POST /approvals/{id}` and then `POST /runs/{id}/resume`, both
 * `approvals:decide`, and chatting with the agent that parked is `agents:run`.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});

const ACTION: ActionRequest = {
  id: "ar-1",
  tool_call_id: "call-1",
  tool_name: "send_email",
  args: { to: "customer@example.com" },
};

async function mount(permissions: Permission[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/me/permissions")
      return {
        organization_id: "org-1",
        role: "member",
        is_app_admin: false,
        permissions: permissions.map((permission) => ({ permission, scope: "all" })),
      };
    throw new Error(`unexpected GET ${path}`);
  });
  const onDecisions = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ToolApprovalDialog actionRequests={[ACTION]} reviewConfigs={[]} onDecisions={onDecisions} />
    </QueryClientProvider>,
  );
  // Waited for, not assumed: `can()` answers false until the permission set
  // lands, so a control asserted absent before then is absent for the wrong
  // reason and the test would pass with the gate deleted.
  await waitFor(() =>
    expect(client.getQueryData(qk.organizations.permissions("current"))).toBeDefined(),
  );
  return onDecisions;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("who may decide a parked tool call from the conversation", () => {
  it("offers the decision to a caller holding approvals:decide", async () => {
    await mount([Perm.agentsRun, Perm.approvalsDecide]);

    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reject" })).toBeInTheDocument();
    expect(screen.queryByText(/permission you do not hold/)).toBeNull();
  });

  it("offers none of it without, and says the run is waiting on somebody else", async () => {
    // A member: they may run this agent, which is what parked the call, and may
    // not decide the approval it parked on.
    await mount([Perm.agentsRun]);

    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
    // What is not a write stays: the banner and the arguments are how the reader
    // knows why the answer stopped, and they arrived over their own socket.
    expect(screen.getByText("Tool approval required")).toBeInTheDocument();
    expect(screen.getByText("send_email")).toBeInTheDocument();
    // Read, not edited: the arguments were a textarea whose contents were diffed
    // into an `edit` decision the backend never offered.
    expect(screen.queryByRole("textbox")).toBeNull();
    // Paired with the absence deliberately: a footer rendering nothing would
    // satisfy the first assertion and leave a stopped conversation unexplained.
    expect(screen.getByText(/permission you do not hold/)).toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});
