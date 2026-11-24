import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import { PendingApproval, DecidedApproval } from "./approval-cards";
import { ApprovalsTab } from "./approvals-tab";
import { ToolApprovalDialog } from "@/components/chat/tool-approval-dialog";
import { apiClient } from "@/lib/api-client";
import { browserCredentialApproval } from "@/lib/browser-credential-approval";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { BROWSER_IDS as ids } from "@/test-utils/browser-credential-fixtures";
import {
  browserEligibilityFixture,
  browserPlanFixture,
} from "@/test-utils/browser-credential-plan-fixtures";
import type { ToolApproval } from "@/types/runs";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), raw: vi.fn() } }));
vi.mock("@/components/dashboard/agent-face", () => ({ AgentFace: () => <span>Agent</span> }));
vi.mock("@/components/runs/approval-delegate", () => ({ ApprovalDelegate: () => null }));
vi.mock("@/lib/file-access", () => ({ saveBlob: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
let client: QueryClient;
const planApproval = (overrides: Partial<ToolApproval> = {}): ToolApproval => ({
  id: ids.plan,
  run_id: ids.run,
  agent_id: "agent",
  agent_name: "Demo assistant",
  tool_id: "browser_fill_credential",
  capability_tool_id: "browser_fill_credential",
  tool_args: { plan_id: ids.plan },
  subagent_name: null,
  subagent_agent_id: null,
  status: "pending",
  always_asks: true,
  content_hidden: false,
  decided_by_user_id: null,
  decided_at: null,
  decided_via: "click",
  note: null,
  ...overrides,
});
function setup(ui: ReactElement) {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: { id: ids.owner } as never, accessToken: "token" });
  useOrgStore.setState({ activeOrgId: ids.org });
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/me/permissions")
      return {
        organization_id: ids.org,
        role: "operator",
        is_app_admin: false,
        permissions: [{ permission: "approvals:decide", scope: "all" }],
      } as never;
    return { items: [], total: 0 } as never;
  });
});
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
});

describe("credential plan approval routing", () => {
  it("does not infer dedicated consent when an ordinary request has no argument object", () => {
    expect(browserCredentialApproval(planApproval({ tool_args: null as never }))).toEqual({
      kind: "ordinary",
    });
  });
  it("routes the verified plan to exact review and exposes neither generic decisions nor swipe consent", async () => {
    const decide = vi.fn(),
      review = vi.fn();
    const view = setup(
      <ul>
        <PendingApproval
          approval={planApproval()}
          deciding={false}
          onDecide={decide}
          onOpenRun={vi.fn()}
          onReviewCredential={review}
        />
      </ul>,
    );
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(view.container.querySelector("[class*=touch-pan-y]")).toBeNull();
    const row = screen.getByRole("listitem");
    fireEvent.pointerDown(row, { pointerId: 1, pointerType: "touch", clientX: 0, clientY: 0 });
    fireEvent.pointerMove(row, { pointerId: 1, pointerType: "touch", clientX: 200, clientY: 0 });
    fireEvent.pointerUp(row, { pointerId: 1, pointerType: "touch" });
    await userEvent.click(screen.getByRole("button", { name: "Review destination" }));
    expect(review).toHaveBeenCalledExactlyOnceWith({ runId: ids.run, planId: ids.plan });
    expect(decide).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(screen.queryByText(ids.plan)).not.toBeInTheDocument();
  });
  it.each([
    { tool_args: { plan_id: ids.child } },
    { content_hidden: true },
    { run_id: "not-a-run-id" },
  ])("refuses to turn unverifiable plan metadata into generic approval %j", async (override) => {
    const decide = vi.fn(),
      openRun = vi.fn();
    setup(
      <ul>
        <PendingApproval
          approval={planApproval(override)}
          deciding={false}
          onDecide={decide}
          onOpenRun={openRun}
        />
      </ul>,
    );
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open the run" }));
    expect(openRun).toHaveBeenCalledOnce();
    expect(decide).not.toHaveBeenCalled();
  });
  it("keeps ordinary request-tool decisions and explains that destination confirmation still follows", async () => {
    const decide = vi.fn();
    setup(
      <ul>
        <PendingApproval
          approval={planApproval({
            tool_args: {
              secret_id: ids.secret,
              authorization_generation: ids.generation,
              fields: [{ field: "password", element_id: 0 }],
            },
            always_asks: false,
          })}
          deciding={false}
          onDecide={decide}
          onOpenRun={vi.fn()}
        />
      </ul>,
    );
    expect(screen.getByText(/This approval only permits preparing/)).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(decide).toHaveBeenCalledExactlyOnceWith(true);
  });
  it("does not mistake a similarly named transport tool for the canonical capability", () => {
    expect(
      browserCredentialApproval(planApproval({ capability_tool_id: "external_tool" })),
    ).toEqual({ kind: "ordinary" });
    expect(browserCredentialApproval(planApproval({ capability_tool_id: null }))).toMatchObject({
      kind: "plan",
    });
  });
  it.each(["browser_fill_credential", "browser_submit_credential_form"])(
    "opens the existing decided %s receipt without offering another decision",
    async (tool) => {
      const review = vi.fn();
      setup(
        <ul>
          <DecidedApproval
            approval={planApproval({ tool_id: tool, capability_tool_id: tool, status: "approved" })}
            onOpenRun={vi.fn()}
            onReviewCredential={review}
          />
        </ul>,
      );
      await userEvent.click(screen.getByRole("button", { name: "Review credential receipt" }));
      expect(review).toHaveBeenCalledExactlyOnceWith({ runId: ids.run, planId: ids.plan });
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
  it("keeps a hidden historical credential decision as a run link without exposing plan details or another consent", async () => {
    const openRun = vi.fn(),
      review = vi.fn();
    setup(
      <ul>
        <DecidedApproval
          approval={planApproval({
            status: "approved",
            content_hidden: true,
            tool_args: { plan_id: ids.plan, unexpected: "PRIVATE FIXTURE DETAIL" },
          })}
          onOpenRun={openRun}
          onReviewCredential={review}
        />
      </ul>,
    );
    expect(screen.queryByText("PRIVATE FIXTURE DETAIL")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Review credential receipt" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open the run" }));
    expect(openRun).toHaveBeenCalledOnce();
    expect(review).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it("keeps the ordinary framework batch positional while describing the preparation boundary", async () => {
    const decisions = vi.fn();
    setup(
      <ToolApprovalDialog
        actionRequests={[
          {
            id: "request",
            tool_call_id: "call",
            tool_name: "browser_fill_credential",
            capability_tool_id: "browser_fill_credential",
            args: { secret_id: ids.secret },
          },
          {
            id: "other",
            tool_call_id: "other-call",
            tool_name: "write_memory",
            args: { name: "memory" },
          },
        ]}
        reviewConfigs={[]}
        onDecisions={decisions}
      />,
    );
    expect(
      screen.getByText(/exact destination and fields still require a separate confirmation/),
    ).toBeVisible();
    const approve = await screen.findByRole("button", { name: "Approve" });
    await userEvent.click(approve);
    expect(decisions).toHaveBeenCalledExactlyOnceWith([{ type: "approve" }, { type: "approve" }]);
  });
  it("retains the exact review dialog after the pending row disappears and clears it on an organization switch", async () => {
    let queue = [planApproval()];
    let plan = browserPlanFixture();
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (path === "/me/permissions")
        return {
          organization_id: ids.org,
          role: "operator",
          is_app_admin: false,
          permissions: [{ permission: "approvals:decide", scope: "all" }],
        } as never;
      if (path === "/approvals") {
        const rows = Array.isArray(options?.params) ? [] : queue;
        return { items: rows, total: rows.length } as never;
      }
      if (path.endsWith("/browser-credentials")) return [browserEligibilityFixture()] as never;
      if (path.endsWith("/submission")) return null as never;
      if (path.includes("/browser-credential-plans/")) return plan as never;
      return { items: [], total: 0 } as never;
    });
    vi.mocked(apiClient.post).mockImplementation(async (path) => {
      expect(path).toBe(`/runs/${ids.run}/browser-credential-plans/${ids.plan}/confirmation`);
      queue = [];
      plan = {
        ...plan,
        state: "filled",
        output_protected: true,
        submission_expires_at: new Date(Date.now() + 60_000).toISOString(),
      };
      return plan as never;
    });
    setup(
      <ApprovalsTab
        period={{ preset: "30d", from: "2026-10-17", to: "2026-11-16" }}
        onFocusRun={vi.fn()}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Review destination" }));
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Review destination" }));
    const dialog = screen.getByRole("dialog");
    const confirm = await within(dialog).findByRole("button", { name: "Confirm fill" });
    await waitFor(() => expect(confirm).toBeEnabled());
    await userEvent.click(confirm);
    await act(async () => {
      await client.invalidateQueries();
    });
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(await within(dialog).findByRole("button", { name: "Submit this form" })).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    act(() => useOrgStore.setState({ activeOrgId: ids.child }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
