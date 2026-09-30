import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { apiClient } from "@/lib/api-client";
import type { WorkflowApprovalRead } from "@/lib/workflows/types";

import { WorkflowApprovalsCard } from "./workflow-approvals-card";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const ASKING: WorkflowApprovalRead = {
  id: "wa-1",
  workflow_id: "wf-1",
  workflow_name: "Refunds",
  workflow_run_id: "run-1",
  node_run_id: "nr-1",
  title: "Send the refund?",
  details: "Refund 40 EUR to order 1182",
  approver_user_ids: ["u-1"],
  status: "pending",
  expires_at: "2026-10-01T09:00:00Z",
  decided_by_user_id: null,
  decided_at: null,
  note: null,
  created_at: "2026-09-29T09:00:00Z",
};

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.post).mockReset();
});

describe("WorkflowApprovalsCard", () => {
  it("shows what each step asks, from which run, and answers it", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [ASKING], total: 1 });
    vi.mocked(apiClient.post).mockResolvedValue({ ...ASKING, status: "rejected" });
    render(<WorkflowApprovalsCard />, { wrapper });

    expect(await screen.findByText("Send the refund?")).toBeTruthy();
    expect(screen.getByText("Refund 40 EUR to order 1182")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Refunds" }).getAttribute("href")).toBe(
      "/workflows/wf-1/runs/run-1",
    );
    expect(screen.getByText("1 named approver")).toBeTruthy();
    expect(screen.getByText(/expires/)).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: /Reject/ }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/workflow-approvals/wa-1", { approved: false }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
  });

  it("approves, and says what went wrong when the decision is refused", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ ...ASKING, details: null, expires_at: null, approver_user_ids: [] }],
      total: 1,
    });
    vi.mocked(apiClient.post).mockResolvedValueOnce({ ...ASKING, status: "approved" });
    render(<WorkflowApprovalsCard />, { wrapper });

    await userEvent.click(await screen.findByRole("button", { name: /Approve/ }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/workflow-approvals/wa-1", { approved: true }),
    );
    expect(screen.queryByText(/expires/)).toBeNull();

    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("already decided"));
    await userEvent.click(screen.getByRole("button", { name: /Approve/ }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("draws nothing while nothing waits", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
    const { container } = render(<WorkflowApprovalsCard />, { wrapper });
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/workflow-approvals"));
    expect(container).toBeEmptyDOMElement();
  });
});
