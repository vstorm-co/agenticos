import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunsPage from "./page";
import { ApiError, apiClient } from "@/lib/api-client";

/**
 * A tab that could not load says so, rather than saying there is nothing.
 *
 * This is the trap the whole page is built around, one tab at a time. Every
 * dashboard surface here fans out to several queries and draws its empty state
 * when one of them fails, so "no runs yet" and "the request answered 502" are the
 * same pixels - and on this page the three of them are the sentences an operator
 * would act on: nothing is waiting, nothing has run, nothing was spent. All three
 * are reassuring, and all three are wrong when the request never arrived.
 *
 * A 502 rather than a 403, deliberately. A refusal has an honest empty reading
 * for two of these tabs; a bad gateway has none, so nothing but the error state
 * is a correct answer to it.
 *
 * Each tab is failed *on its own*, with the other two served normally, because
 * the arrangement being tested is that they fail independently: one page-wide
 * error state would take a working Spend tab down with a broken queue, and one
 * page-wide empty state is the defect itself.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, isLoading: false }),
}));

const params = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => params,
  // The header's "?" reads the path to decide whether this page has tips.
  usePathname: () => "/runs",
}));

const SPEND = {
  period_days: null,
  month_to_date_usd: "12.40",
  // The window figure sums these rows, so the $12.40 the test reads back is
  // the window's spend, not the calendar month's.
  by_agent: [
    {
      agent_id: "agent-1",
      agent_name: "Agent",
      cost_usd: "12.40",
      run_count: 3,
      partial_run_count: 0,
      month_to_date_usd: "12.40",
      monthly_cap_usd: null,
    },
  ],
  by_provider: [],
  by_key: [],
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const GATEWAY = () => Promise.reject(new ApiError(502, "Bad gateway"));

/** Serve the page, failing exactly one of its three requests. */
function backend(failing: "/approvals" | "/runs" | "/spend") {
  vi.mocked(apiClient.get).mockImplementation((path: string) => {
    if (path === failing) return GATEWAY();
    if (path === "/spend") return Promise.resolve(SPEND);
    return Promise.resolve({ items: [], total: 0 });
  });
}

async function open(tab: "Runs" | "Spend" | "Approvals") {
  // Every trigger can carry a figure now - the three stat cards became three tab
  // badges - so all of them are matched by prefix.
  await userEvent.click(await screen.findByRole("tab", { name: new RegExp(`^${tab}`) }));
}

beforeEach(() => {
  params.delete("agent");
  params.delete("run");
  vi.mocked(apiClient.get).mockReset();
});

describe("a tab whose request failed", () => {
  it("does not tell an approver that nothing is waiting", async () => {
    backend("/approvals");

    render(<RunsPage />, { wrapper });
    await open("Approvals");

    expect(await screen.findByText("The approvals queue could not be read")).toBeVisible();
    // The sentence a parked run must never be reported as. Somebody reading it
    // closes the page, and the run stays parked.
    expect(screen.queryByText("Nothing waiting")).toBeNull();
  });

  it("does not report an empty history for a history it could not read", async () => {
    backend("/runs");

    render(<RunsPage />, { wrapper });
    await open("Runs");

    expect(await screen.findByText("Run history could not be read")).toBeVisible();
    expect(screen.queryByText("No runs yet")).toBeNull();
  });

  it("does not report nothing spent for a bill it could not read", async () => {
    backend("/spend");

    render(<RunsPage />, { wrapper });
    await open("Spend");

    expect(await screen.findByText("Spend could not be read")).toBeVisible();
    expect(screen.queryByText("Nothing spent yet.")).toBeNull();
  });

  // A retry that re-renders without re-requesting is a button that looks like it
  // works: React Query holds the rejected query and would serve it back. So the
  // assertion is on the request count, per tab, because each tab wires its own.
  it.each([
    {
      failing: "/approvals" as const,
      tab: "Approvals" as const,
      title: "The approvals queue could not be read",
    },
    { failing: "/runs" as const, tab: "Runs" as const, title: "Run history could not be read" },
    { failing: "/spend" as const, tab: "Spend" as const, title: "Spend could not be read" },
  ])("offers a way to ask $failing again, and asking reaches the server", async (tabCase) => {
    backend(tabCase.failing);

    render(<RunsPage />, { wrapper });
    await open(tabCase.tab);
    expect(await screen.findByText(tabCase.title)).toBeVisible();

    const asked = () =>
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === tabCase.failing).length;
    const before = asked();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));

    await waitFor(() => expect(asked()).toBeGreaterThan(before));
  });

  it("takes down only the tab that failed", async () => {
    // One page-wide error state would be its own defect: a broken queue would
    // hide a Spend tab that is answering perfectly well.
    backend("/approvals");

    render(<RunsPage />, { wrapper });
    await open("Approvals");
    expect(await screen.findByText("The approvals queue could not be read")).toBeVisible();

    await open("Spend");

    expect(await screen.findByText("By provider")).toBeVisible();
    expect(screen.queryByText("Spend could not be read")).toBeNull();
  });
});

describe("a tab's own figure, when its request failed", () => {
  /**
   * The three stat cards became three tab badges, and the claim they were
   * protecting is unchanged: a figure whose request never answered must not be
   * drawn as a number. `$0.00` and `0` are what a working, empty deployment looks
   * like, so printing either for a failed read tells the reader something false
   * about their own money.
   *
   * Absent rather than marked, which the cards could not be - a card with no
   * number is a hole in a row, where a tab with no badge is simply a tab.
   */
  it("leaves the spend badge off rather than printing a fabricated $0.00", async () => {
    backend("/spend");

    render(<RunsPage />, { wrapper });

    await waitFor(() => expect(screen.getByRole("tab", { name: /^Spend/ })).toBeVisible());
    expect(screen.getByRole("tab", { name: /^Spend/ })).not.toHaveTextContent("$0.00");
  });

  it("leaves the run badge off rather than printing a fabricated 0", async () => {
    backend("/runs");

    render(<RunsPage />, { wrapper });

    await waitFor(() => expect(screen.getByRole("tab", { name: /^Runs/ })).toBeVisible());
    expect(screen.getByRole("tab", { name: /^Runs/ })).not.toHaveTextContent("0");
  });

  it("keeps the badge its own request answered", async () => {
    // The queue fails; spend comes from its own request, so the strip keeps the
    // figure it has - one failing query must not blank the others.
    backend("/approvals");

    render(<RunsPage />, { wrapper });

    await waitFor(() =>
      expect(screen.getByRole("tab", { name: /^Spend/ })).toHaveTextContent("$12.40"),
    );
  });
});
