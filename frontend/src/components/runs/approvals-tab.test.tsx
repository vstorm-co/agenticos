import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalsTab } from "./approvals-tab";
import type { Period } from "@/lib/dashboard/period";
import { apiClient } from "@/lib/api-client";
import type { ToolApproval } from "@/types/runs";

/**
 * The two buttons that settle a parked run, and the one table around them.
 *
 * `use-runs.test.tsx` proves the mutation posts what it is given; this proves the
 * buttons hand it the right thing. They are one word apart and opposite in
 * consequence - a Reject wired to `approved: true` sends the email the approver
 * refused, and every assertion about the queue's *appearance* passes while it
 * does. The decided record shares the table: same rows, read later, and
 * deliberately without buttons - a second decision on a decided approval is one
 * of the things the platform refuses.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/runs/approval-delegate", () => ({ ApprovalDelegate: () => null }));

const PERIOD: Period = { preset: "30d", from: "2026-07-16", to: "2026-08-14" };
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

const DECIDED: ToolApproval = {
  ...PARKED,
  id: "ap-2",
  run_id: "run-2",
  status: "rejected",
  triggered_by_email: "ada@acme.test",
  decided_by_email: "grace@acme.test",
};

/**
 * `/approvals` twice over: the decided record asks with params (statuses + the
 * window), the queue asks bare. One endpoint, two questions - the mock keeps
 * them apart.
 */
function backend({ queue = [] as ToolApproval[], decided = [] as ToolApproval[] } = {}) {
  vi.mocked(apiClient.get).mockImplementation((_path: string, options?: unknown) =>
    Promise.resolve(
      (options as { params?: unknown } | undefined)?.params
        ? { items: decided, total: decided.length }
        : { items: queue, total: queue.length },
    ),
  );
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.post).mockReset();
  vi.mocked(apiClient.post).mockResolvedValue({ ...PARKED, status: "approved" });
});

describe("deciding a parked call", () => {
  it("approves the call it is next to", async () => {
    backend({ queue: [PARKED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/approvals/ap-1", {
        approved: true,
        note: undefined,
      }),
    );
  });

  it("rejects it, rather than approving it under another label", async () => {
    backend({ queue: [PARKED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/approvals/ap-1", {
        approved: false,
        note: undefined,
      }),
    );
  });

  it("shows a pending row's arguments in full, not just the tool's name", async () => {
    // Approving a tool name without seeing what it will do is a rubber stamp.
    backend({ queue: [PARKED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText("send_email")).toBeVisible();
    expect(screen.getByText(/board@acme\.test/)).toBeVisible();
  });

  it("says nothing waiting only when both reads answered and were empty", async () => {
    backend();

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText("Nothing waiting")).toBeVisible();
    expect(screen.getByText("Agents are running without needing you.")).toBeVisible();
  });

  it("disables both buttons while a decision is in flight, so a double-click sends one POST", async () => {
    backend({ queue: [PARKED] });
    // A decision that never settles, so the in-flight state is observable.
    let settle: (value: unknown) => void = () => {};
    vi.mocked(apiClient.post).mockReturnValue(
      new Promise((resolve) => {
        settle = resolve;
      }) as ReturnType<typeof apiClient.post>,
    );

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });
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

  it("deciding does not also open the run the row would", async () => {
    // The buttons sit in a clickable row; a decision that also swung the drawer
    // out would bury the queue under the run it just settled.
    backend({ queue: [PARKED] });
    const onFocusRun = vi.fn();

    render(<ApprovalsTab period={PERIOD} onFocusRun={onFocusRun} />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "Approve" }));

    expect(onFocusRun).not.toHaveBeenCalled();
  });
});

describe("the decided record in the same table", () => {
  it("reads who asked, who decided, and what the answer was - with no buttons", async () => {
    backend({ decided: [DECIDED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText("Rejected")).toBeVisible();
    const row = screen.getByText("Rejected").closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("send_email");
    expect(row).toHaveTextContent("ada@acme.test");
    expect(row).toHaveTextContent("grace@acme.test");
    expect(within(row).queryByRole("button")).toBeNull();
  });

  it("folds a decided row's arguments behind a disclosure", async () => {
    // The decision has been made; the arguments are the record's detail, not
    // the thing the reader is being asked to weigh.
    backend({ decided: [DECIDED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    const disclosure = await screen.findByText("Arguments");
    expect(screen.getByText(/board@acme\.test/)).not.toBeVisible();

    await userEvent.click(disclosure);

    expect(screen.getByText(/board@acme\.test/)).toBeVisible();
  });

  it("counts both halves over the table, waiting beside decided", async () => {
    backend({ queue: [PARKED], decided: [DECIDED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText("1 waiting · 1 decided in this window")).toBeVisible();
  });

  it("opens the run behind a row when the row is clicked", async () => {
    backend({ decided: [DECIDED] });
    const onFocusRun = vi.fn();

    render(<ApprovalsTab period={PERIOD} onFocusRun={onFocusRun} />, { wrapper });
    await userEvent.click(await screen.findByText("Rejected"));

    expect(onFocusRun).toHaveBeenCalledWith("run-2");
  });
});
