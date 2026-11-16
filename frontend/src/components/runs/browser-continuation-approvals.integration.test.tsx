import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PendingApproval, DecidedApproval } from "./approval-cards";
import { ApprovalsTab } from "./approvals-tab";
import { apiClient } from "@/lib/api-client";
import { browserCredentialApproval } from "@/lib/browser-credential-approval";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import {
  CONTINUATION_IDS as ids,
  browserContinuationFixture,
  continuationSourceFixture,
} from "@/test-utils/browser-credential-continuation-fixtures";
import type { BrowserCredentialContinuation } from "@/types/browser-credential-continuation";
import type { ToolApproval } from "@/types/runs";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), raw: vi.fn() } }));
vi.mock("@/components/dashboard/agent-face", () => ({ AgentFace: () => <span>Agent</span> }));
vi.mock("@/components/runs/approval-delegate", () => ({ ApprovalDelegate: () => null }));
vi.mock("@/lib/file-access", () => ({ saveBlob: vi.fn() }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const continuationApproval = (overrides: Partial<ToolApproval> = {}): ToolApproval => ({
  id: ids.continuation,
  run_id: ids.run,
  agent_id: "agent",
  agent_name: "Demo assistant",
  tool_id: "browser_continue_credential_session",
  capability_tool_id: "browser_continue_credential_session",
  tool_args: { continuation_id: ids.continuation, source_submission_id: ids.child },
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
const selection = { runId: ids.run, planId: ids.child, continuationId: ids.continuation };
let client: QueryClient;
let row: BrowserCredentialContinuation | null;
let queue: ToolApproval[];
function setup(ui: ReactElement) {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
beforeEach(() => {
  vi.clearAllMocks();
  sessionStorage.clear();
  useAuthStore.setState({ user: { id: ids.owner } as never, accessToken: "token" });
  useOrgStore.setState({ activeOrgId: ids.org });
  queue = [continuationApproval()];
  row = browserContinuationFixture();
  vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
    if (path === "/me/permissions")
      return {
        organization_id: ids.org,
        role: "operator",
        is_app_admin: false,
        permissions: [{ permission: "approvals:decide", scope: "all" }],
      } as never;
    if (path === "/approvals") {
      const items = Array.isArray(options?.params) ? [] : queue;
      return { items, total: items.length } as never;
    }
    if (path.endsWith("/continuation")) return row as never;
    if (path === `/runs/${ids.run}/browser-credential-plans/${ids.child}`)
      return continuationSourceFixture() as never;
    return { items: [], total: 0 } as never;
  });
});
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
  sessionStorage.clear();
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
});

describe("dedicated continuation queue handoff", () => {
  it.each([
    { operation: "fill", state: "awaiting_confirmation", parent_plan_id: null },
    { operation: "fill", state: "filled", parent_plan_id: null },
    { operation: "submit", state: "awaiting_confirmation" },
  ] as const)(
    "refuses an addressed continuation whose source is $operation/$state",
    async (overrides) => {
      const get = vi.mocked(apiClient.get).getMockImplementation()!;
      vi.mocked(apiClient.get).mockImplementation(async (path, options) =>
        path === `/runs/${ids.run}/browser-credential-plans/${ids.child}`
          ? ({ ...continuationSourceFixture(), ...overrides } as never)
          : get(path, options),
      );
      setup(
        <ApprovalsTab
          period={{ preset: "30d", from: "2026-10-17", to: "2026-11-16" }}
          onFocusRun={vi.fn()}
        />,
      );
      await userEvent.click(await screen.findByRole("button", { name: "Review continuation" }));
      await waitFor(() => expect(client.isFetching()).toBe(0));
      const dialog = screen.getByRole("dialog");
      expect(within(dialog).queryByTestId("browser-credential-state")).not.toBeInTheDocument();
      expect(within(dialog).queryAllByRole("alert").length).toBeGreaterThan(0);
      expect(
        within(dialog).queryByRole("checkbox", { name: "Keep me signed in" }),
      ).not.toBeInTheDocument();
      expect(
        within(dialog).queryByRole("button", { name: "Prepare continuation" }),
      ).not.toBeInTheDocument();
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
  it("routes only the exact server continuation and source IDs, with no generic or swipe decision", async () => {
    const decide = vi.fn(),
      review = vi.fn();
    const view = setup(
      <ul>
        <PendingApproval
          approval={continuationApproval()}
          deciding={false}
          onDecide={decide}
          onOpenRun={vi.fn()}
          onReviewCredential={review}
        />
      </ul>,
    );
    expect(browserCredentialApproval(continuationApproval())).toEqual({
      kind: "plan",
      ...selection,
    });
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(view.container.querySelector("[class*=touch-pan-y]")).toBeNull();
    const card = screen.getByRole("listitem");
    fireEvent.pointerDown(card, { pointerId: 1, pointerType: "touch", clientX: 0, clientY: 0 });
    fireEvent.pointerMove(card, { pointerId: 1, pointerType: "touch", clientX: 200, clientY: 0 });
    fireEvent.pointerUp(card, { pointerId: 1, pointerType: "touch" });
    await userEvent.click(screen.getByRole("button", { name: "Review continuation" }));
    expect(review).toHaveBeenCalledExactlyOnceWith(selection);
    expect(decide).not.toHaveBeenCalled();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(screen.queryByText(ids.continuation)).not.toBeInTheDocument();
  });
  it.each([
    { tool_args: null as never },
    { tool_args: [] as never },
    { tool_args: {} },
    { tool_args: { source_submission_id: ids.child, wrong: ids.continuation } },
    { tool_args: { continuation_id: ids.continuation, wrong: ids.child } },
    { tool_args: { continuation_id: ids.other, source_submission_id: ids.child } },
    { tool_args: { continuation_id: ids.continuation, source_submission_id: "invalid" } },
    {
      tool_args: {
        continuation_id: ids.continuation,
        source_submission_id: ids.child,
        private: "DO NOT RENDER",
      },
    },
    { id: "invalid", tool_args: { continuation_id: "invalid", source_submission_id: ids.child } },
    { run_id: "invalid" },
    { content_hidden: true },
    { content_hidden: undefined as never },
    { always_asks: false },
  ])("keeps unverifiable continuation metadata out of generic decisions: %j", async (override) => {
    const open = vi.fn(),
      decide = vi.fn(),
      review = vi.fn();
    const approval = continuationApproval(override);
    expect(browserCredentialApproval(approval)).toEqual({ kind: "unavailable" });
    setup(
      <ul>
        <PendingApproval
          approval={approval}
          deciding={false}
          onDecide={decide}
          onOpenRun={open}
          onReviewCredential={review}
        />
      </ul>,
    );
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Review continuation" })).not.toBeInTheDocument();
    expect(screen.queryByText("DO NOT RENDER")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open the run" }));
    expect(open).toHaveBeenCalledOnce();
    expect(decide).not.toHaveBeenCalled();
    expect(review).not.toHaveBeenCalled();
  });
  it("uses the canonical capability rather than a similarly named transport", () => {
    expect(
      browserCredentialApproval(continuationApproval({ capability_tool_id: "other" })),
    ).toEqual({ kind: "ordinary" });
    expect(browserCredentialApproval(continuationApproval({ capability_tool_id: null }))).toEqual({
      kind: "plan",
      ...selection,
    });
  });
  it.each(["pending", "approved"] as const)(
    "links %s receipts without a callback to the run, never to an approval effect",
    async (status) => {
      const open = vi.fn(),
        decide = vi.fn();
      setup(
        <ul>
          {status === "pending" ? (
            <PendingApproval
              approval={continuationApproval()}
              deciding={false}
              onDecide={decide}
              onOpenRun={open}
            />
          ) : (
            <DecidedApproval approval={continuationApproval({ status })} onOpenRun={open} />
          )}
        </ul>,
      );
      await userEvent.click(screen.getByRole("button", { name: "Review continuation" }));
      expect(open).toHaveBeenCalledOnce();
      expect(decide).not.toHaveBeenCalled();
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
  it("opens a decided continuation with its exact ID and no second generic approval", async () => {
    const review = vi.fn();
    setup(
      <ul>
        <DecidedApproval
          approval={continuationApproval({ status: "approved" })}
          onOpenRun={vi.fn()}
          onReviewCredential={review}
        />
      </ul>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Review continuation" }));
    expect(review).toHaveBeenCalledExactlyOnceWith(selection);
    expect(apiClient.post).not.toHaveBeenCalled();
  });
  it.each([null, "different"] as const)(
    "refuses %s recovery for an addressed approval without offering another preparation",
    async (value) => {
      row = value === null ? null : browserContinuationFixture({ id: ids.other });
      setup(
        <ApprovalsTab
          period={{ preset: "30d", from: "2026-10-17", to: "2026-11-16" }}
          onFocusRun={vi.fn()}
        />,
      );
      await userEvent.click(await screen.findByRole("button", { name: "Review continuation" }));
      const dialog = screen.getByRole("dialog");
      await within(dialog).findByText(/current continuation receipt could not be verified/);
      expect(
        within(dialog).queryByRole("button", { name: "Prepare continuation" }),
      ).not.toBeInTheDocument();
      expect(
        within(dialog).queryByRole("button", { name: "Continue in protected browser" }),
      ).not.toBeInTheDocument();
      await userEvent.click(within(dialog).getByRole("button", { name: "Check continuation" }));
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );
  it("uses only the dedicated exact-document confirmation and keeps its receipt open after the queue entry leaves", async () => {
    vi.mocked(apiClient.post).mockImplementation(async (path, body) => {
      expect(path).toBe(
        `/runs/${ids.run}/browser-credential-plans/${ids.child}/continuation/${ids.continuation}/confirmation`,
      );
      expect(body).toEqual({
        document_id: ids.continuationDocument,
        authorization_generation: ids.generation,
        approve: true,
        keep_signed_in: false,
      });
      queue = [];
      row = browserContinuationFixture({ state: "approved", keep_signed_in: false });
      return row as never;
    });
    setup(
      <ApprovalsTab
        period={{ preset: "30d", from: "2026-10-17", to: "2026-11-16" }}
        onFocusRun={vi.fn()}
      />,
    );
    await userEvent.click(await screen.findByRole("button", { name: "Review continuation" }));
    const dialog = screen.getByRole("dialog");
    const confirm = await within(dialog).findByRole("button", {
      name: "Continue in protected browser",
    });
    await waitFor(() => expect(confirm).toBeEnabled());
    expect(within(dialog).getByRole("checkbox", { name: "Keep me signed in" })).not.toBeChecked();
    expect(apiClient.post).not.toHaveBeenCalled();
    await userEvent.click(confirm);
    await act(async () => {
      await client.invalidateQueries();
    });
    expect(screen.getByRole("dialog")).toBeVisible();
    await within(dialog).findByText("Decision recorded");
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    act(() => useOrgStore.setState({ activeOrgId: ids.other }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
