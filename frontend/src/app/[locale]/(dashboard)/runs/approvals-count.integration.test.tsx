import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunsPage from "./page";
import { apiClient } from "@/lib/api-client";

/**
 * How many calls are waiting, when more are waiting than fit on a page.
 *
 * `GET /approvals` answers fifty rows at a time and nothing on this page asks
 * for more, so `items.length` is a page length wearing the name of a count. The
 * figure and the tab badge both drew it: a queue of a hundred and twenty read
 * **50**, and went on reading 50 however long the queue grew. That is the same
 * defect as #198 - the Runs figure counting `runs.length` instead of the
 * server's `total` - one figure to the right of where it was fixed.
 *
 * A count that saturates is worse than a missing one. Nothing on screen looks
 * unusual, and the number a person uses to decide whether the queue is under
 * control is exactly the number that stops moving.
 *
 * Served with `total` far above the page on purpose: with the two equal, a
 * component reading either passes.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const params = new URLSearchParams();
vi.mock("next/navigation", () => ({ useSearchParams: () => params }));

const EMPTY_SPEND = {
  period_days: 30,
  from_date: "2026-07-08T00:00:00Z",
  to_date: null,
  month_to_date_usd: "0.00",
  partial_run_count: 0,
  by_agent: [],
  by_provider: [],
  by_key: [],
};

function approval(id: string) {
  return {
    id,
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
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** One page of `shown` rows out of `total` waiting. */
function serve(shown: number, total: number) {
  vi.mocked(apiClient.get).mockImplementation((path: string, options?: unknown) => {
    // The decided record asks /approvals with params; the queue asks bare.
    if (path === "/approvals" && (options as { params?: unknown } | undefined)?.params) {
      return Promise.resolve({ items: [], total: 0 });
    }
    if (path === "/spend") return Promise.resolve(EMPTY_SPEND);
    if (path === "/approvals")
      return Promise.resolve({
        items: Array.from({ length: shown }, (_, i) => approval(`ap-${i}`)),
        total,
      });
    if (path === "/me/permissions")
      return Promise.resolve({
        organization_id: "o1",
        role: "operator",
        is_app_admin: false,
        permissions: [
          { permission: "runs:view", scope: "all" },
          { permission: "approvals:decide", scope: "all" },
        ],
      });
    return Promise.resolve({ items: [], total: 0 });
  });
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
});

/** The page opens on Runs now; the queue is one tab over. */
async function openApprovals() {
  await userEvent.click(await screen.findByRole("tab", { name: /^Approvals/ }));
}

describe("the count of calls waiting on a person", () => {
  it("is the server's total, not the number of rows on one page", async () => {
    serve(2, 120);

    render(<RunsPage />, { wrapper });

    expect(await screen.findByText("Waiting on a person")).toBeVisible();
    // The card holding the label, so the figure is read against its own subject
    // rather than against whichever "120" is on screen. `items.length` here is 2,
    // which is what a page length looks like once the queue is over the ceiling.
    await waitFor(() =>
      expect(screen.getByText("Waiting on a person").parentElement).toHaveTextContent("120"),
    );
  });

  it("counts the same way on the tab badge", async () => {
    serve(2, 120);

    render(<RunsPage />, { wrapper });

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: /Approvals/ })).toHaveTextContent("120"),
    );
  });

  it("says the queue below it is one page of that total", async () => {
    // Otherwise a badge reading 120 sits over two cards with nothing explaining
    // the gap, and the reading available to whoever is working down the queue is
    // that a hundred and eighteen calls went missing.
    serve(2, 120);

    render(<RunsPage />, { wrapper });
    await openApprovals();

    expect(await screen.findByText(/Showing the oldest 2 of 120 waiting/)).toBeVisible();
  });

  it("says nothing about paging when the page is the whole queue", async () => {
    serve(2, 2);

    render(<RunsPage />, { wrapper });

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: /Approvals/ })).toHaveTextContent("2"),
    );
    expect(screen.queryByText(/Showing the oldest/)).toBeNull();
  });
});
