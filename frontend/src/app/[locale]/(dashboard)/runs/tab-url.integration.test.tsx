import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { Permission } from "@/types/permissions";

/**
 * Which tab is open is the page's state and travels in `?tab=` (#934).
 *
 * Two things were wrong, and they were the same thing. `Tabs` was uncontrolled,
 * so the tab was the only piece of this page's state not in the URL - there was
 * no address for the approvals queue, which is why the alert that says a run is
 * parked linked to the agent's Builder page instead (#935). And a focused run
 * outlived the tab that opened it: the detail panel sat beside a queue it has
 * nothing to do with, and below `lg` the focused run *replaces* the list, so the
 * strip was live while every tab's content stayed hidden and clicking Approvals
 * appeared to do nothing at all.
 *
 * The width case is asserted through the class that carries it. jsdom applies no
 * stylesheet, so `hidden lg:block` is not observable as layout; what is
 * observable is whether the page still asks for it, which is the decision under
 * test.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

let params = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => params,
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

/** Enough of a run for the detail panel to draw its header. */
const RUN = {
  id: "run-1",
  agent_id: "agent-1",
  agent_version_id: null,
  user_id: null,
  surface: "web",
  status: "completed",
  model_label: "claude-sonnet-4-5",
  provider: "anthropic",
  input_tokens: 1200,
  output_tokens: 340,
  cost_usd: "0.0182",
  cost_is_partial: false,
  logfire_trace_id: null,
  prev_run_id: null,
  next_run_id: null,
  error: null,
  down_rated: false,
  conversation_id: null,
  started_at: "2026-08-14T09:00:00Z",
  ended_at: "2026-08-14T09:00:04Z",
  parent_run_id: null,
  subagent_task_id: null,
};

function serve(permissions: Permission[]) {
  vi.mocked(apiClient.get).mockImplementation((path: string) => {
    if (path === "/spend") return Promise.resolve(EMPTY_SPEND);
    if (path === "/runs/run-1") return Promise.resolve(RUN);
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

/** Arrive at the page with this query string, as a pasted link would. */
function arriveAt(query: string) {
  params = new URLSearchParams(query);
  window.history.replaceState({}, "", `/runs${query ? `?${query}` : ""}`);
}

const tab = (name: RegExp) => screen.getByRole("tab", { name });
const url = () => new URL(window.location.href);

/**
 * The column the tab panels share. Below `lg` it is hidden whenever a run is
 * focused, which is the half of the bug that made switching tabs read as a dead
 * control.
 */
function listColumn(container: HTMLElement): HTMLElement {
  const panel = container.querySelector<HTMLElement>(
    "[data-tour='activity-runs'], [data-tour='activity-approvals'], [data-tour='activity-spend']",
  );
  if (!panel?.parentElement) throw new Error("no tab panel is mounted");
  return panel.parentElement;
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  arriveAt("");
});

describe("the open tab in the URL", () => {
  it("opens the queue for a link that names it", async () => {
    serve(["runs:view", "approvals:decide"]);
    arriveAt("tab=approvals");

    render(<RunsPage />, { wrapper });

    expect(await screen.findByRole("tab", { name: /^Approvals/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("opens the run history for a link naming a tab the reader may not open", async () => {
    // A blank page under a live strip is what the alternative looks like: a
    // selected value with no trigger and no content.
    serve(["runs:view"]);
    arriveAt("tab=approvals");

    render(<RunsPage />, { wrapper });

    expect(await screen.findByRole("tab", { name: /^Runs/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByRole("tab", { name: /Approvals/ })).toBeNull();
  });

  it("opens the run history for a tab name this build does not have", async () => {
    serve(["runs:view", "approvals:decide"]);
    arriveAt("tab=budgets");

    render(<RunsPage />, { wrapper });

    expect(await screen.findByRole("tab", { name: /^Runs/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("leaves no `tab=runs` behind when a reader switches back", async () => {
    // An unset narrowing writes nothing on this page - that is what makes a
    // pasted link carry only what it actually narrows.
    serve(["runs:view", "approvals:decide"]);
    arriveAt("tab=approvals");

    render(<RunsPage />, { wrapper });
    await userEvent.click(await screen.findByRole("tab", { name: /^Runs/ }));

    expect(url().searchParams.get("tab")).toBeNull();
    expect(tab(/^Runs/)).toHaveAttribute("aria-selected", "true");
  });

  it("writes the tab a reader switches to, so a reload comes back to it", async () => {
    serve(["runs:view", "approvals:decide"]);

    render(<RunsPage />, { wrapper });
    await userEvent.click(await screen.findByRole("tab", { name: /^Spend/ }));

    expect(url().searchParams.get("tab")).toBe("spend");
    expect(tab(/^Spend/)).toHaveAttribute("aria-selected", "true");
  });
});

describe("a focused run and a tab switch", () => {
  it("closes the panel and gives the list back its column", async () => {
    serve(["runs:view", "approvals:decide"]);
    arriveAt("run=run-1");

    const { container } = render(<RunsPage />, { wrapper });

    expect(await screen.findByRole("complementary", { name: "Run detail" })).toBeVisible();
    // The half that makes it read as a dead control below `lg`: with a run
    // focused, every tab's content is hidden.
    expect(listColumn(container)).toHaveClass("hidden");

    await userEvent.click(tab(/^Approvals/));

    expect(screen.queryByRole("complementary", { name: "Run detail" })).toBeNull();
    expect(listColumn(container)).not.toHaveClass("hidden");
    expect(tab(/^Approvals/)).toHaveAttribute("aria-selected", "true");
  });

  it("closes with a link that changes the tab and does not name the run", async () => {
    // Radix does not call `onValueChange` for a prop-driven change, so this
    // could look like the panel outliving the switch again. It does not: the
    // navigation replaces the whole query string, and `useUrlState` resets a
    // value whose parameter changed under it. There is nothing to clear.
    serve(["runs:view", "approvals:decide"]);
    arriveAt("run=run-1");

    const { rerender } = render(<RunsPage />, { wrapper });
    expect(await screen.findByRole("complementary", { name: "Run detail" })).toBeVisible();

    arriveAt("tab=approvals");
    rerender(<RunsPage />);

    await waitFor(() =>
      expect(screen.queryByRole("complementary", { name: "Run detail" })).toBeNull(),
    );
    expect(tab(/^Approvals/)).toHaveAttribute("aria-selected", "true");
  });

  it("honours a link that names both, because that link is asking for both", async () => {
    serve(["runs:view", "approvals:decide"]);
    arriveAt("tab=approvals&run=run-1");

    render(<RunsPage />, { wrapper });

    expect(await screen.findByRole("complementary", { name: "Run detail" })).toBeVisible();
    expect(tab(/^Approvals/)).toHaveAttribute("aria-selected", "true");
  });

  it("takes the run out of the URL with it", async () => {
    serve(["runs:view", "approvals:decide"]);
    arriveAt("run=run-1");

    render(<RunsPage />, { wrapper });
    await userEvent.click(await screen.findByRole("tab", { name: /^Approvals/ }));

    // Left behind, a reload would reopen a panel on a tab that never had it.
    expect(url().searchParams.get("run")).toBeNull();
    expect(url().searchParams.get("tab")).toBe("approvals");
  });
});
