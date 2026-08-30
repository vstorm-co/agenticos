import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { Permission } from "@/types/permissions";

/**
 * The Approvals tab, for somebody who may not decide.
 *
 * Reading the queue takes the same permission as deciding one: `GET /approvals`
 * and `POST /approvals/{id}` both carry `require(Perm.APPROVALS_DECIDE)`, and it
 * is the only approvals permission in the catalog. So for a caller without it
 * there is no queue, and the tab has nothing to show rather than nothing in it.
 *
 * It used to show it anyway. The page computed `canDecide` and gated only the
 * Approve and Reject buttons with it, while the tab, its default selection and
 * the queue's own count were rendered unconditionally - so a Builder
 * landed on a 403 drawn as **"Nothing waiting · Agents are running without
 * needing you."** A refusal rendered as reassurance, on the one page whose
 * purpose is to keep those two apart.
 *
 * Real `usePermissions` over a mocked `/me/permissions`, because the thing under
 * test is a permission decision. The requests are asserted as well as the pixels:
 * a tab that is absent while the query behind it still polls is a 403 every
 * thirty seconds for as long as the page is open.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const params = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => params,
  // The header's "?" reads the path to decide whether this page has tips.
  usePathname: () => "/runs",
}));

const EMPTY_SPEND = {
  period_days: 30,
  month_to_date_usd: "0.00",
  by_agent: [],
  by_provider: [],
  by_key: [],
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/**
 * Serve the page, with one queued approval waiting.
 *
 * A queue with something in it on purpose: served an empty one, a tab that
 * wrongly renders and a tab that correctly does not both show no rows, and the
 * test would pass against the defect it exists to catch.
 */
function serve(permissions: Permission[]) {
  vi.mocked(apiClient.get).mockImplementation((path: string, options?: unknown) => {
    // The decided record asks with an array of pairs (`status` repeats);
    // the queue asks with a `skip` since it became server-paged (#1336).
    if (
      path === "/approvals" &&
      Array.isArray((options as { params?: unknown } | undefined)?.params)
    ) {
      return Promise.resolve({ items: [], total: 0 });
    }
    if (path === "/spend") return Promise.resolve(EMPTY_SPEND);
    if (path === "/approvals")
      return Promise.resolve({
        items: [
          {
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
          },
        ],
        total: 1,
      });
    if (path === "/me/permissions")
      return Promise.resolve({
        organization_id: "o1",
        role: "operator",
        is_app_admin: false,
        permissions: permissions.map((permission) => ({ permission, scope: "all" })),
      });
    return Promise.resolve({ items: [], total: 0 });
  });
}

const asked = (path: string) =>
  vi.mocked(apiClient.get).mock.calls.filter(([called]) => called === path);

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
});

/** The page opens on Runs now; the queue is one tab over. */
async function openApprovals() {
  await userEvent.click(await screen.findByRole("tab", { name: /^Approvals/ }));
}

describe("the Approvals tab without approvals:decide", () => {
  it("is absent, rather than showing a refusal as an empty queue", async () => {
    serve(["runs:view"]);

    render(<RunsPage />, { wrapper });

    // Waited on rather than assumed: the Runs tab appears once the page is past
    // its loading state, so anything missing below is a decision and not a query
    // still in flight.
    expect(await screen.findByRole("tab", { name: /^Runs/ })).toBeVisible();

    expect(screen.queryByRole("tab", { name: /Approvals/ })).toBeNull();
    // The sentence the defect produced. Absent is the whole point: an approver
    // reading it would have been told nothing was waiting while one call was.
    expect(screen.queryByText("Nothing waiting")).toBeNull();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Reject" })).toBeNull();
  });

  it("takes the count down with it, rather than printing a nought", async () => {
    // `approvals.length` on a refused query is zero, and a tab badge reading 0
    // is the same lie as the empty queue with a number in front of it.
    serve(["runs:view"]);

    render(<RunsPage />, { wrapper });

    expect(await screen.findByRole("tab", { name: /^Runs/ })).toBeVisible();
    expect(screen.queryByRole("tab", { name: /Approvals/ })).toBeNull();
  });

  it("does not ask for the queue at all", async () => {
    serve(["runs:view"]);

    render(<RunsPage />, { wrapper });

    expect(await screen.findByRole("tab", { name: /^Runs/ })).toBeVisible();
    // Polled every thirty seconds, so a query left enabled behind a hidden tab
    // is a 403 for as long as the page stays open.
    expect(asked("/approvals")).toHaveLength(0);
    // And the rest of the page is unaffected - this is one tab withheld, not a
    // page that gave up.
    expect(asked("/spend").length).toBeGreaterThan(0);
  });

  it("selects Runs, so the page does not open on a tab that is not there", async () => {
    serve(["runs:view"]);

    render(<RunsPage />, { wrapper });

    expect(await screen.findByRole("tab", { name: /^Runs/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});

describe("the Approvals tab with approvals:decide", () => {
  it("renders the queue and its decide controls", async () => {
    // The positive control. Without it every assertion above would also pass
    // against a page that had lost the tab entirely.
    serve(["runs:view", "approvals:decide"]);

    render(<RunsPage />, { wrapper });
    await openApprovals();

    expect(await screen.findByRole("button", { name: "Approve" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Reject" })).toBeVisible();
    expect(screen.getByRole("tab", { name: /Approvals/ })).toHaveAttribute("aria-selected", "true");
    // The count rides on the tab now: a card of one number was a lot of the
    // page's height for something a badge says.
    expect(screen.getByRole("tab", { name: /^Approvals/ })).toHaveTextContent("1");
    await waitFor(() => expect(asked("/approvals").length).toBeGreaterThan(0));
  });
});
