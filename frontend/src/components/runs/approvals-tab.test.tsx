import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApprovalsTab } from "./approvals-tab";
import type { Period } from "@/lib/dashboard/period";
import { apiClient } from "@/lib/api-client";
import type { WorkflowApprovalRead } from "@/lib/workflows/types";
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
  return {
    ...actual,
    apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn(), raw: vi.fn() },
  };
});
vi.mock("@/lib/file-access", () => ({ saveBlob: vi.fn() }));
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
  decided_via: "click" as const,
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
 * `/approvals` twice over: the decided record asks with an array of pairs
 * (`status` repeats), the queue asks with a `skip`. One endpoint, two questions
 * - the shape of `params` is what keeps them apart, which is also why the mock
 * cannot discriminate on params being present at all: the queue grew a `skip`
 * when it became server-paged (#1336) and every queue assertion then read the
 * record's rows. The caller holds `approvals:decide`, which is the only state
 * the page ever renders this tab in; the totals let either report more rows
 * than it returned, the way the capped endpoint does.
 */
function backend({
  queue = [] as ToolApproval[],
  queueTotal,
  decided = [] as ToolApproval[],
  decidedTotal,
  stepQueue = [] as WorkflowApprovalRead[],
  stepDecided = [] as WorkflowApprovalRead[],
  failing = [] as ("queue" | "stepQueue" | "stepDecided" | "toolDecided")[],
}: {
  queue?: ToolApproval[];
  queueTotal?: number;
  decided?: ToolApproval[];
  decidedTotal?: number;
  stepQueue?: WorkflowApprovalRead[];
  stepDecided?: WorkflowApprovalRead[];
  /** Reads that answer with a failure instead. */
  failing?: ("queue" | "stepQueue" | "stepDecided" | "toolDecided")[];
} = {}) {
  vi.mocked(apiClient.get).mockImplementation((path: string, options?: unknown) => {
    if (path === "/me/permissions")
      return Promise.resolve({
        organization_id: "o1",
        role: "operator",
        is_app_admin: false,
        permissions: [{ permission: "approvals:decide", scope: "all" }],
      });
    const params = (options as { params?: unknown } | undefined)?.params;
    if (path === "/workflow-approvals") {
      if (failing.includes(Array.isArray(params) ? "stepDecided" : "stepQueue"))
        return Promise.reject(new Error("unreadable"));
      const items = Array.isArray(params) ? stepDecided : stepQueue;
      return Promise.resolve({ items, total: items.length });
    }
    if (failing.includes(Array.isArray(params) ? "toolDecided" : "queue"))
      return Promise.reject(new Error("unreadable"));
    return Promise.resolve(
      Array.isArray(params)
        ? { items: decided, total: decidedTotal ?? decided.length }
        : { items: queue, total: queueTotal ?? queue.length },
    );
  });
}

/** The `skip` each queue request was made with, in order. */
function queueSkips(): string[] {
  return vi
    .mocked(apiClient.get)
    .mock.calls.filter(([path, options]) => {
      const params = (options as { params?: unknown } | undefined)?.params;
      return path === "/approvals" && !Array.isArray(params);
    })
    .map(([, options]) => (options as { params: { skip: string } }).params.skip);
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.post).mockReset();
  vi.mocked(apiClient.raw).mockReset();
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

  it("says what a pending call does and what it is about, not just the tool's name", async () => {
    // Approving a tool name without seeing what it will do is a rubber stamp.
    backend({ queue: [PARKED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText("send email")).toBeVisible();
    expect(screen.getByText(/board@acme\.test/)).toBeVisible();
  });

  it("says what a described call will do in names, over its arguments", async () => {
    backend({
      queue: [
        {
          ...PARKED,
          // Renamed by its binding: the sentence is found by the stable id.
          tool_id: "change_ticket",
          capability_tool_id: "update_record",
          tool_args: { table_id: "6f1c" },
          context: { table: "Support" },
        },
        { ...PARKED, id: "ap-3" },
      ],
    });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText("Change a record in Support")).toBeVisible();
    // The ids it was made with stay one click away, under the sentence.
    const [described] = screen.getAllByRole("button", { name: "Details" });
    await userEvent.click(described as HTMLElement);
    expect(screen.getByText(/6f1c/)).toBeVisible();
    expect(screen.getByText("change_ticket")).toBeVisible();
    // A call nobody described gets no sentence.
    expect(screen.getAllByText("Change a record in Support")).toHaveLength(1);
  });

  it("says nothing waiting only when both reads answered and were empty", async () => {
    backend();

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText("No approvals pending")).toBeVisible();
    expect(screen.getByText("Requests that need your decision will appear here.")).toBeVisible();
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
    const row = screen.getByText("Rejected").closest("li") as HTMLElement;
    expect(row).toHaveTextContent("Send email");
    expect(row).toHaveTextContent("For ada@acme.test");
    expect(row).toHaveTextContent("by grace@acme.test");
    expect(within(row).queryByRole("button", { name: "Approve" })).toBeNull();
    expect(within(row).queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("says when a decision was a standing consent rather than a click", async () => {
    // Both are `approved` and nobody read these arguments before they ran, so a
    // record that does not say which is a list of green ticks (#925).
    backend({
      decided: [
        {
          ...DECIDED,
          status: "approved",
          decided_via: "standing" as const,
          decided_by_email: "grace@acme.test",
        },
      ],
    });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    const row = (await screen.findByText("by grace@acme.test")).closest("li") as HTMLElement;
    expect(row).toHaveTextContent("waived in advance for the conversation");
  });

  it("says nothing extra about a decision somebody actually made", async () => {
    backend({ decided: [DECIDED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    const row = (await screen.findByText("by grace@acme.test")).closest("li") as HTMLElement;
    expect(row).not.toHaveTextContent("waived in advance");
  });

  it("folds a decided row's arguments behind a disclosure", async () => {
    // The decision has been made; the arguments are the record's detail, not
    // the thing the reader is being asked to weigh.
    backend({ decided: [DECIDED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    const disclosure = await screen.findByRole("button", { name: "Details" });
    expect(screen.queryByText(/board@acme\.test/)).toBeNull();

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
    await userEvent.click(await screen.findByRole("button", { name: /Send email/ }));

    expect(onFocusRun).toHaveBeenCalledWith("run-2");
  });

  it("opens the run behind a waiting request from the request itself", async () => {
    backend({ queue: [PARKED] });
    const onFocusRun = vi.fn();

    render(<ApprovalsTab period={PERIOD} onFocusRun={onFocusRun} />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: /Open the run/ }));

    expect(onFocusRun).toHaveBeenCalledWith("run-1");
  });

  it("shows a status this build does not know as the value it is, not as Expired", async () => {
    // The backend can grow a status before the frontend learns its label; a
    // fallback to "Expired" would put a specific, wrong claim on that row.
    backend({ decided: [{ ...DECIDED, status: "escalated" as ToolApproval["status"] }] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText("escalated")).toBeVisible();
    expect(screen.queryByText("Expired")).toBeNull();
  });

  it("says the record is a page of the window's decisions when there are more", async () => {
    // The endpoint answers fifty rows; the counted line reports the window's
    // total, so the gap between the two needs the same footnote the queue has.
    backend({ queue: [PARKED], decided: [DECIDED], decidedTotal: 214 });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(
      await screen.findByText(/Showing the newest of 214 decided in this window/),
    ).toBeVisible();
  });

  it("says nothing about a record that fits on its one page", async () => {
    backend({ decided: [DECIDED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    await screen.findByText("Rejected");
    expect(screen.queryByText(/Showing the newest/)).toBeNull();
  });
});

const STEP: WorkflowApprovalRead = {
  id: "wa-1",
  workflow_id: "wf-1",
  workflow_name: "Refunds",
  workflow_run_id: "wr-1",
  node_run_id: "nr-1",
  title: "Send the refund?",
  details: null,
  approver_user_ids: [],
  status: "approved",
  expires_at: null,
  decided_by_user_id: "u-1",
  decided_at: "2026-08-05T10:00:00Z",
  note: "Looks right",
  created_at: "2026-08-05T09:00:00Z",
  editable: false,
  proposal: null,
  proposal_format: "text",
  proposal_label: null,
  final: null,
  edited: false,
  choices: [],
  choice: null,
};

describe("the workflow steps beside the tool calls", () => {
  it("keeps a decided step in the record and counts it", async () => {
    backend({ stepDecided: [STEP] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText("Send the refund?", { exact: false })).toBeVisible();
    expect(screen.getByText("Refunds")).toBeVisible();
    expect(screen.getByText("Approved")).toBeVisible();
    expect(screen.getByText("Looks right")).toBeVisible();
    expect(screen.getByText(/1 decided in this window/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
  });

  it("asks for the record newest first, within the window", async () => {
    backend({ stepDecided: [STEP] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });
    await screen.findByText("Looks right");

    const asked = vi
      .mocked(apiClient.get)
      .mock.calls.filter(([path, options]) => {
        const params = (options as { params?: unknown } | undefined)?.params;
        return path === "/workflow-approvals" && Array.isArray(params);
      })
      .map(([, options]) => (options as { params: string[][] }).params);
    expect(asked).toHaveLength(1);
    expect(asked[0]).toContainEqual(["oldest_first", "false"]);
    expect(asked[0]).toContainEqual(["status", "approved"]);
    expect(asked[0]?.map(([key]) => key)).toContain("created_from");
  });

  it("does not say nothing waits while a step waits on the person", async () => {
    backend({ stepQueue: [{ ...STEP, status: "pending" }] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText(/1 waiting/)).toBeVisible();
    expect(screen.queryByText("Nothing waiting")).toBeNull();
    expect(screen.queryByText("Agents are running without needing you.")).toBeNull();
  });

  it("does not say nothing waits when the step queue could not be read", async () => {
    backend({ failing: ["stepQueue"] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    await waitFor(() => expect(apiClient.get).toHaveBeenCalledWith("/workflow-approvals"));
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(screen.queryByText("Agents are running without needing you.")).toBeNull();
  });

  it("offers a retry when the tool queue could not be read", async () => {
    backend({ failing: ["queue"] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    await userEvent.click(await screen.findByRole("button", { name: "Try again" }));
    expect(screen.queryByText("Agents are running without needing you.")).toBeNull();
  });

  it("says the record could not be read when only the steps' half failed", async () => {
    backend({ decided: [DECIDED], failing: ["stepDecided"] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText("The decided record could not be read.")).toBeVisible();
  });

  it("says the record could not be read when only the tool calls' half failed", async () => {
    backend({ stepDecided: [STEP], failing: ["toolDecided"] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText("The decided record could not be read.")).toBeVisible();
  });

  it("interleaves decided steps and tool calls newest first", async () => {
    backend({
      decided: [
        { ...DECIDED, id: "ap-new", created_at: "2026-08-07T09:00:00Z", tool_id: "newest_tool" },
        { ...DECIDED, id: "ap-old", created_at: "2026-08-03T09:00:00Z", tool_id: "oldest_tool" },
        // No timestamp reads as oldest rather than breaking the sort.
        { ...DECIDED, id: "ap-undated", created_at: undefined, tool_id: "undated_tool" },
      ],
      stepDecided: [
        { ...STEP, id: "wa-mid", title: "Middle step", created_at: "2026-08-05T09:00:00Z" },
      ],
    });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    await screen.findByText("Middle step", { exact: false });
    const rows = within(screen.getByRole("region", { name: "Decided" })).getAllByRole("listitem");
    expect(rows).toHaveLength(4);
    expect(rows[0]).toHaveTextContent("Newest tool");
    expect(rows[1]).toHaveTextContent("Middle step");
    expect(rows[2]).toHaveTextContent("Oldest tool");
    expect(rows[3]).toHaveTextContent("Undated tool");
  });

  it("shows one page of the merged record and counts both halves in the footnote", async () => {
    const tools = Array.from({ length: 50 }, (_, i) => ({
      ...DECIDED,
      id: `ap-${i}`,
      created_at: "2026-08-10T09:00:00Z",
    }));
    backend({
      decided: tools,
      decidedTotal: 200,
      stepDecided: [{ ...STEP, title: "Weeks old step", created_at: "2026-07-20T09:00:00Z" }],
    });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(
      await screen.findByText(/Showing the newest 50 of 201 decided in this window/),
    ).toBeVisible();
    expect(screen.queryByText("Weeks old step", { exact: false })).toBeNull();
    expect(
      within(screen.getByRole("region", { name: "Decided" })).getAllByRole("listitem"),
    ).toHaveLength(50);
  });
});

describe("reaching a request past the first page of the queue", () => {
  /**
   * The alert an approval sends addresses `/runs?tab=approvals` and names
   * neither the run nor the request - deliberately, because the decide controls
   * live on the queue row and below `lg` a focused run replaces the list
   * (#935). So with fifty or more waiting, the newly parked request the email
   * was about was the one row its reader could not reach, until enough older
   * calls had been decided (#1336).
   */
  const parked = (index: number): ToolApproval => ({
    ...PARKED,
    id: `ap-${index}`,
    run_id: `run-${index}`,
    tool_id: `tool_${index}`,
  });
  const FULL = Array.from({ length: 50 }, (_, index) => parked(index));

  it("asks the server for the page it is showing", async () => {
    backend({ queue: FULL, queueTotal: 62 });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });
    await screen.findByText("tool 0");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    await waitFor(() => expect(queueSkips()).toContain("50"));
  });

  it("offers no pager for a queue that fits on one page", async () => {
    backend({ queue: [PARKED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    await screen.findByText("send email");
    expect(screen.queryByRole("button", { name: /next/i })).toBeNull();
  });

  it("counts the whole queue, not the page", async () => {
    backend({ queue: FULL, queueTotal: 62 });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    expect(await screen.findByText(/62 requests/)).toBeVisible();
  });

  it("steps back when deciding empties the page the reader is on", async () => {
    // The one request on page two, decided. Left where they were, somebody is
    // looking at an empty table under a badge saying fifty are waiting - so the
    // page they are on is clamped to one that exists.
    let waiting = 51;
    vi.mocked(apiClient.get).mockImplementation((path: string, options?: unknown) => {
      if (path === "/me/permissions")
        return Promise.resolve({
          organization_id: "o1",
          role: "operator",
          is_app_admin: false,
          permissions: [{ permission: "approvals:decide", scope: "all" }],
        });
      const params = (options as { params?: { skip?: string } } | undefined)?.params;
      if (Array.isArray(params)) return Promise.resolve({ items: [], total: 0 });
      const skip = Number(params?.skip ?? "0");
      return Promise.resolve({
        items: skip === 0 ? FULL : waiting > 50 ? [parked(50)] : [],
        total: waiting,
      });
    });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });
    await screen.findByText("tool 0");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    const decide = await screen.findByRole("button", { name: "Approve" });

    waiting = 50;
    await userEvent.click(decide);

    await waitFor(() => expect(queueSkips().at(-1)).toBe("0"));
    expect(await screen.findByText("tool 0")).toBeVisible();
  });
});

describe("the export beside the table", () => {
  it("asks for every status the table shows, over the page's window", async () => {
    backend({ queue: [PARKED], decided: [DECIDED] });
    vi.mocked(apiClient.raw).mockResolvedValue({
      blob: async () => new Blob(["approval_id\n"], { type: "text/csv" }),
      headers: { get: () => null },
    } as unknown as Response);

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });
    await userEvent.click(await screen.findByRole("button", { name: "Export CSV" }));

    await waitFor(() => expect(apiClient.raw).toHaveBeenCalledTimes(1));
    const call = vi.mocked(apiClient.raw).mock.calls.at(-1);
    expect(call?.[0]).toBe("/approvals/export");
    const pairs = (call?.[1] as { params: [string, string][] }).params;
    expect(pairs).toEqual([
      ["status", "pending"],
      ["status", "approved"],
      ["status", "rejected"],
      ["status", "expired"],
      ["created_from", "2026-07-16T00:00:00.000Z"],
      ["created_to", "2026-08-14T23:59:59.999Z"],
    ]);
  });

  it("is withheld from a caller the export route would refuse", async () => {
    // The page never renders this tab without `approvals:decide`, but the
    // control carries its own gate like every export on the page.
    vi.mocked(apiClient.get).mockImplementation((path: string, options?: unknown) => {
      if (path === "/me/permissions")
        return Promise.resolve({
          organization_id: "o1",
          role: "viewer",
          is_app_admin: false,
          permissions: [],
        });
      return Promise.resolve(
        Array.isArray((options as { params?: unknown } | undefined)?.params)
          ? { items: [], total: 0 }
          : { items: [PARKED], total: 1 },
      );
    });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    await screen.findByText("send email");
    expect(screen.queryByRole("button", { name: "Export CSV" })).toBeNull();
  });
});
