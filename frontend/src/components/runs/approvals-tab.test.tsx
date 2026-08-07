import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalsTab } from "./approvals-tab";
import { apiClient } from "@/lib/api-client";
import type { ToolApproval } from "@/types/runs";

/**
 * The two buttons that settle a parked run.
 *
 * `use-runs.test.tsx` proves the mutation posts what it is given; this proves the
 * buttons hand it the right thing. They are one word apart and opposite in
 * consequence - a Reject wired to `approved: true` sends the email the approver
 * refused, and every assertion about the queue's *appearance* passes while it
 * does.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/runs/approval-delegate", () => ({ ApprovalDelegate: () => null }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PARKED: ToolApproval = {
  id: "ap-1",
  run_id: "run-1",
  agent_id: "agent-1",
  tool_id: "send_email",
  tool_args: { to: "board@acme.test" },
  subagent_name: null,
  subagent_agent_id: null,
  status: "pending",
  decided_by_user_id: null,
  decided_at: null,
  note: null,
  created_at: "2026-08-04T09:00:00Z",
};

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.post).mockReset();
  vi.mocked(apiClient.post).mockResolvedValue({ ...PARKED, status: "approved" });
});

describe("deciding a parked call", () => {
  it("approves the call it is next to", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [PARKED], total: 1 });

    render(<ApprovalsTab />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/approvals/ap-1", {
        approved: true,
        note: undefined,
      }),
    );
  });

  it("rejects it, rather than approving it under another label", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [PARKED], total: 1 });

    render(<ApprovalsTab />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/approvals/ap-1", {
        approved: false,
        note: undefined,
      }),
    );
  });

  it("shows the arguments in full, not just the tool's name", async () => {
    // Approving a tool name without seeing what it will do is a rubber stamp.
    vi.mocked(apiClient.get).mockResolvedValue({ items: [PARKED], total: 1 });

    render(<ApprovalsTab />, { wrapper });

    expect(await screen.findByText("send_email")).toBeVisible();
    expect(screen.getByText(/board@acme\.test/)).toBeVisible();
  });

  it("says nothing waiting only when the queue answered and was empty", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });

    render(<ApprovalsTab />, { wrapper });

    expect(await screen.findByText("Nothing waiting")).toBeVisible();
  });

  it("disables both buttons while a decision is in flight, so a double-click sends one POST", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [PARKED], total: 1 });
    // A decision that never settles, so the in-flight state is observable.
    let settle: (value: unknown) => void = () => {};
    vi.mocked(apiClient.post).mockReturnValue(
      new Promise((resolve) => {
        settle = resolve;
      }) as ReturnType<typeof apiClient.post>,
    );

    render(<ApprovalsTab />, { wrapper });
    const approve = await screen.findByRole("button", { name: "Approve" });
    await userEvent.click(approve);

    // Both buttons disable the moment the mutation is pending, and a second click
    // on the disabled button does nothing - so the backend never sees a second
    // decision to refuse.
    await waitFor(() => expect(approve).toBeDisabled());
    expect(screen.getByRole("button", { name: "Reject" })).toBeDisabled();
    await userEvent.click(approve);
    expect(apiClient.post).toHaveBeenCalledTimes(1);

    settle({ ...PARKED, status: "approved" });
  });
});
