import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { Permission } from "@/types/permissions";
import type { ToolApproval } from "@/types/runs";

/**
 * The approvals queue saying which delegate is asking.
 *
 * The case this exists for is two rows of the same tool: a gated tool inside a
 * delegation writes its approval against the parent's run, so a queue that names the
 * tool and not the actor shows `send_email` twice with nothing to choose between
 * them. In a delegation the thing being approved is often more consequential than
 * the agent the approver thinks they are talking to.
 *
 * Real `usePermissions` over a mocked `/me/permissions`, because whether the
 * delegate's name is a link is a permission decision.
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

function approval(overrides: Partial<ToolApproval>): ToolApproval {
  return {
    id: "ap-1",
    run_id: "run-1",
    agent_id: "agent-parent",
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
    ...overrides,
  };
}

/**
 * Answer the page's three requests: the queue, permissions, and spend.
 *
 * `/spend` has a shape of its own and the page reads `.length` off three of its
 * arrays, so a blanket `{items, total}` makes the whole page throw.
 */
function serve(approvals: ToolApproval[], permissions: Permission[]) {
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
      return Promise.resolve({ items: approvals, total: approvals.length });
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

/** The table row for one queued call, found by the row's own actor. */
function row(name: string): HTMLElement {
  const tableRow = screen.getByText(name).closest<HTMLElement>("tr");
  if (tableRow === null) throw new Error(`no queue row for ${name}`);
  return tableRow;
}

beforeEach(() => {
  params.delete("agent");
  vi.mocked(apiClient.get).mockReset();
});

/** The page opens on Runs now; the queue is one tab over. */
async function openApprovals() {
  await userEvent.click(await screen.findByRole("tab", { name: /^Approvals/ }));
}

describe("the approvals queue, under delegation", () => {
  it("tells two calls to the same tool apart by who is asking", async () => {
    serve(
      [
        approval({ id: "ap-1", subagent_name: "researcher", subagent_agent_id: "agent-99" }),
        approval({ id: "ap-2", subagent_name: "summariser", subagent_agent_id: null }),
      ],
      ["agents:view", "approvals:decide"],
    );

    render(<RunsPage />, { wrapper });
    await openApprovals();

    // Same tool, twice. What separates them is the actor, and each row carries
    // exactly one.
    expect(await screen.findAllByText("send_email")).toHaveLength(2);

    const published = row("Asked by researcher");
    const inline = row("Asked by summariser");
    expect(published).not.toBe(inline);

    // The published delegate is linkable; the inline specialist is not a published
    // agent and is not offered as one.
    expect(within(published).getByRole("link")).toHaveAttribute("href", "/agents/agent-99");
    expect(within(published).queryByText("Inline specialist")).toBeNull();
    expect(within(inline).queryByRole("link")).toBeNull();
    expect(within(inline).getByText("Inline specialist")).toBeVisible();
  });

  it("says nothing about a delegate on a call the run's own agent made", async () => {
    serve([approval({ subagent_name: null })], ["agents:view", "approvals:decide"]);

    render(<RunsPage />, { wrapper });
    await openApprovals();

    expect(await screen.findByText("send_email")).toBeVisible();
    expect(screen.queryByText(/Asked by \w/)).toBeNull();
    expect(screen.queryByText("Inline specialist")).toBeNull();
  });

  it("names the delegate but does not link it for a caller who may not view agents", async () => {
    // The link would land them on a page the server refuses. The name stays: it is
    // what the decision needs, not a control, and withholding it would put them
    // back to approving blind.
    serve(
      [approval({ subagent_name: "researcher", subagent_agent_id: "agent-99" })],
      ["approvals:decide"],
    );

    render(<RunsPage />, { wrapper });
    await openApprovals();

    // Waited on rather than assumed: `Approve` appears only once
    // `/me/permissions` has answered, so a missing link below is a decision this
    // page made and not a query still in flight.
    expect(await screen.findByRole("button", { name: "Approve" })).toBeVisible();

    expect(screen.getByText("Asked by researcher")).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByText("Inline specialist")).toBeNull();
  });
});
