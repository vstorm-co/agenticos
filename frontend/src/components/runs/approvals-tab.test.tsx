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
}: {
  queue?: ToolApproval[];
  queueTotal?: number;
  decided?: ToolApproval[];
  decidedTotal?: number;
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

    const row = (await screen.findByText("grace@acme.test")).closest("tr") as HTMLElement;
    expect(row).toHaveTextContent("waived in advance for the conversation");
  });

  it("says nothing extra about a decision somebody actually made", async () => {
    backend({ decided: [DECIDED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    const row = (await screen.findByText("grace@acme.test")).closest("tr") as HTMLElement;
    expect(row).not.toHaveTextContent("waived in advance");
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
    await screen.findByText("tool_0");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));

    await waitFor(() => expect(queueSkips()).toContain("50"));
  });

  it("offers no pager for a queue that fits on one page", async () => {
    backend({ queue: [PARKED] });

    render(<ApprovalsTab period={PERIOD} onFocusRun={vi.fn()} />, { wrapper });

    await screen.findByText("send_email");
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
    await screen.findByText("tool_0");
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    const decide = await screen.findByRole("button", { name: "Approve" });

    waiting = 50;
    await userEvent.click(decide);

    await waitFor(() => expect(queueSkips().at(-1)).toBe("0"));
    expect(await screen.findByText("tool_0")).toBeVisible();
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

    await screen.findByText("send_email");
    expect(screen.queryByRole("button", { name: "Export CSV" })).toBeNull();
  });
});
