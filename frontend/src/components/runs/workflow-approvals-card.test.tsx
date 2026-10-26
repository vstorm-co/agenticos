import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { apiClient, ApiError } from "@/lib/api-client";
import { MAX_PROPOSAL_CHARS } from "@/lib/workflows/types";
import { useAuthStore } from "@/stores/auth-store";
import type { User } from "@/types";
import type { WorkflowApprovalRead } from "@/lib/workflows/types";

import { DecidedWorkflowApproval, WorkflowApprovalsCard } from "./workflow-approvals-card";

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
  editable: false,
  proposal: null,
  proposal_format: "text",
  proposal_label: null,
  final: null,
  edited: false,
};

const EDITABLE: WorkflowApprovalRead = {
  ...ASKING,
  editable: true,
  proposal: "Hello Ann\nYour refund is on its way",
  proposal_label: "Reply to the customer",
};

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.post).mockReset();
  vi.mocked(toast.error).mockReset();
  useAuthStore.setState({ user: { id: "u-1" } as User });
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

describe("WorkflowApprovalsCard editing", () => {
  function queue(item: WorkflowApprovalRead) {
    vi.mocked(apiClient.get).mockResolvedValue({ items: [item], total: 1 });
    vi.mocked(apiClient.post).mockResolvedValue({ ...item, status: "approved" });
  }

  async function replaceDraft(text: string) {
    const editor = await screen.findByRole("textbox", { name: "Reply to the customer" });
    await userEvent.clear(editor);
    await userEvent.type(editor, text);
    return editor;
  }

  it("approves the edited version", async () => {
    queue(EDITABLE);
    render(<WorkflowApprovalsCard />, { wrapper });

    await replaceDraft("Hello Ann, sorry");
    await userEvent.click(screen.getByRole("button", { name: /Approve/ }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/workflow-approvals/wa-1", {
        approved: true,
        final: "Hello Ann, sorry",
      }),
    );
  });

  it("approves an untouched proposal without sending it back", async () => {
    queue(EDITABLE);
    render(<WorkflowApprovalsCard />, { wrapper });

    await screen.findByRole("textbox", { name: "Reply to the customer" });
    await userEvent.click(screen.getByRole("button", { name: /Approve/ }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/workflow-approvals/wa-1", { approved: true }),
    );
  });

  it("says why Approve is disabled when the draft is empty", async () => {
    queue(EDITABLE);
    render(<WorkflowApprovalsCard />, { wrapper });

    expect(screen.queryByText("Write the proposal before approving it.")).toBeNull();
    const editor = await screen.findByRole("textbox", { name: "Reply to the customer" });
    await userEvent.clear(editor);

    expect(screen.getByText("Write the proposal before approving it.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Approve/ })).toBeDisabled();
  });

  it("restores the original", async () => {
    queue(EDITABLE);
    render(<WorkflowApprovalsCard />, { wrapper });

    const restore = await screen.findByRole("button", { name: "Restore original" });
    expect(restore).toBeDisabled();
    const editor = await replaceDraft("Something else");
    await userEvent.click(restore);

    expect(editor).toHaveValue(EDITABLE.proposal);
    expect(restore).toBeDisabled();
  });

  it("shows what changed", async () => {
    queue(EDITABLE);
    render(<WorkflowApprovalsCard />, { wrapper });

    await replaceDraft("Hello Ann\nSorry for the wait");
    await userEvent.click(screen.getByRole("button", { name: "Show changes" }));

    expect(screen.getByText("Your refund is on its way")).toBeTruthy();
    expect(screen.getByText("Sorry for the wait")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Hide changes" }));
    expect(screen.queryByText("Sorry for the wait")).toBeNull();
  });

  it("rejects without sending the edit", async () => {
    queue(EDITABLE);
    render(<WorkflowApprovalsCard />, { wrapper });

    await replaceDraft("Not this");
    await userEvent.click(screen.getByRole("button", { name: /Reject/ }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/workflow-approvals/wa-1", { approved: false }),
    );
  });

  it("shows a plain step's proposal read-only and approves it as it is", async () => {
    queue({ ...ASKING, proposal: "Refund 40 EUR", proposal_label: "The refund" });
    render(<WorkflowApprovalsCard />, { wrapper });

    expect(await screen.findByText("The refund")).toBeTruthy();
    expect(screen.getByText("Refund 40 EUR")).toBeTruthy();
    expect(screen.queryByRole("textbox")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /Approve/ }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/workflow-approvals/wa-1", { approved: true }),
    );
  });

  it("keeps a step it does not name read-only", async () => {
    useAuthStore.setState({ user: { id: "u-2" } as User });
    queue(EDITABLE);
    render(<WorkflowApprovalsCard />, { wrapper });

    expect(await screen.findByRole("textbox", { name: "Reply to the customer" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Approve/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Reject/ })).toBeDisabled();
    expect(screen.getByText("Only the people this step names can decide it.")).toBeTruthy();
  });

  it("does not tell someone the step does not name to write a proposal", async () => {
    useAuthStore.setState({ user: { id: "u-2" } as User });
    queue({ ...EDITABLE, proposal: null });
    render(<WorkflowApprovalsCard />, { wrapper });

    expect(await screen.findByRole("textbox", { name: "Reply to the customer" })).toBeDisabled();
    expect(screen.queryByText("Write the proposal before approving it.")).toBeNull();
  });

  it("will not approve an empty or over-long edit", async () => {
    queue({ ...EDITABLE, proposal: "x".repeat(MAX_PROPOSAL_CHARS) });
    render(<WorkflowApprovalsCard />, { wrapper });

    const editor = await screen.findByRole("textbox", { name: "Reply to the customer" });
    const approve = screen.getByRole("button", { name: /Approve/ });
    expect(approve).toBeEnabled();
    expect(screen.getByText("100,000 of 100,000 characters")).toBeTruthy();

    await userEvent.type(editor, "y");
    expect(approve).toBeDisabled();
    expect(screen.getByText("100,001 of 100,000 characters")).toBeTruthy();

    await userEvent.clear(editor);
    await userEvent.type(editor, "   ");
    expect(approve).toBeDisabled();
    expect(screen.getByRole("button", { name: /Reject/ })).toBeEnabled();
  });

  it("keeps the draft when the queue is read again", async () => {
    queue(EDITABLE);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<WorkflowApprovalsCard />, {
      wrapper: ({ children }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });

    const editor = await replaceDraft("Half-written");
    const reads = vi.mocked(apiClient.get).mock.calls.length;
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [{ ...EDITABLE, proposal: "A newer draft" }],
      total: 1,
    });
    await act(() => client.refetchQueries());

    expect(vi.mocked(apiClient.get).mock.calls.length).toBeGreaterThan(reads);
    expect(screen.getByRole("textbox", { name: "Reply to the customer" })).toBe(editor);
    expect(editor).toHaveValue("Half-written");
  });

  it("edits markdown with a preview", async () => {
    queue({ ...EDITABLE, proposal_format: "markdown", proposal: "**Hi** Ann" });
    render(<WorkflowApprovalsCard />, { wrapper });

    expect(await screen.findByRole("textbox", { name: "Reply to the customer" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Preview" })).toBeTruthy();
  });

  it("keeps the draft and says why when someone else decided first", async () => {
    queue(EDITABLE);
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(400, "This request was already approved", {
        error: { code: "BAD_REQUEST", message: "This request was already approved" },
      }),
    );
    render(<WorkflowApprovalsCard />, { wrapper });

    const editor = await replaceDraft("My version");
    await userEvent.click(screen.getByRole("button", { name: /Approve/ }));

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("This request was already approved"),
    );
    expect(editor).toHaveValue("My version");
  });

  it("shows markup in a proposal as text, not as a page element", async () => {
    const markup = "<b>bold</b><iframe src=x></iframe>";
    queue({ ...ASKING, proposal_format: "markdown", proposal: markup });
    const { container } = render(<WorkflowApprovalsCard />, { wrapper });

    await screen.findByText("Proposal");
    await waitFor(() => expect(container.textContent).toContain("<b>"));
    expect(container.querySelector("b, iframe")).toBeNull();
  });

  it("shows markup in an editable proposal's preview as text", async () => {
    queue({
      ...EDITABLE,
      proposal_format: "markdown",
      proposal: "<b>bold</b><iframe src=x></iframe>",
    });
    const { container } = render(<WorkflowApprovalsCard />, { wrapper });

    await screen.findByRole("textbox", { name: "Reply to the customer" });
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));

    const preview = await screen.findByRole("region", { name: /Reply to the customer/ });
    await waitFor(() => expect(preview.textContent).toContain("<b>"));
    expect(container.querySelector("b, iframe")).toBeNull();
  });

  it("does not load an image from an editable proposal's preview", async () => {
    queue({
      ...EDITABLE,
      proposal_format: "markdown",
      proposal: "![x](https://example.test/p.png)",
    });
    const { container } = render(<WorkflowApprovalsCard />, { wrapper });

    await screen.findByRole("textbox", { name: "Reply to the customer" });
    await userEvent.click(screen.getByRole("button", { name: "Preview" }));

    const preview = await screen.findByRole("region", { name: /Reply to the customer/ });
    await waitFor(() => expect(preview.querySelector("a")).not.toBeNull());
    expect(container.querySelector("img")).toBeNull();
  });
});

describe("DecidedWorkflowApproval", () => {
  it("shows the answer, its note and when it was given", () => {
    render(
      <ul>
        <DecidedWorkflowApproval
          approval={{
            ...ASKING,
            status: "approved",
            note: "Looks right",
            decided_at: "2026-09-30T10:00:00Z",
          }}
        />
      </ul>,
    );

    expect(screen.getByText("Approved")).toBeTruthy();
    expect(screen.getByText("Looks right")).toBeTruthy();
    expect(screen.getByRole("link").getAttribute("href")).toBe("/workflows/wf-1/runs/run-1");
  });

  it("marks an edited decision", () => {
    render(
      <ul>
        <DecidedWorkflowApproval approval={{ ...ASKING, status: "approved", edited: true }} />
      </ul>,
    );

    expect(screen.getByText("Edited")).toBeTruthy();
  });

  it("shows a lapsed request with no note, dated by when it was asked", () => {
    render(
      <ul>
        <DecidedWorkflowApproval approval={{ ...ASKING, status: "expired" }} />
      </ul>,
    );

    expect(screen.getByText("Expired")).toBeTruthy();
    expect(screen.queryByTitle(/./)).toBeNull();
    expect(screen.getByText(/2026/)).toBeTruthy();
  });

  it("shows a status this build does not know as the value it is", () => {
    render(
      <ul>
        <DecidedWorkflowApproval
          approval={{ ...ASKING, status: "escalated" as WorkflowApprovalRead["status"] }}
        />
      </ul>,
    );

    expect(screen.getByText("escalated")).toBeTruthy();
  });
});
