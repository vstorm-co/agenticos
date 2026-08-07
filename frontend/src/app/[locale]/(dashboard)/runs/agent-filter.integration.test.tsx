import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunsPage from "./page";
import { apiClient } from "@/lib/api-client";

/**
 * Activity honouring `?agent=`.
 *
 * This is the Builder's hand-off: its Recent runs panel answers the summary
 * question and links here for the detail. A filter that silently did nothing
 * would send somebody who clicked through from one agent into the whole
 * organization's history - which looks like a working page, so nothing would ever
 * report it.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));

const params = new URLSearchParams();
vi.mock("next/navigation", () => ({ useSearchParams: () => params }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const EMPTY_SPEND = {
  period_days: 30,
  month_to_date_usd: "0.00",
  by_agent: [],
  by_provider: [],
  by_key: [],
};

beforeEach(() => {
  params.delete("agent");
  vi.mocked(apiClient.get).mockReset();
  // `/spend` has a shape of its own, and the page reads `.length` off three of
  // its arrays - a blanket `{items, total}` makes the whole page throw.
  vi.mocked(apiClient.get).mockImplementation((path: string) =>
    Promise.resolve(path === "/spend" ? EMPTY_SPEND : { items: [], total: 0 }),
  );
});

/** Every `/runs` request the page made, with its options. */
function runsCalls() {
  return vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === "/runs");
}

describe("Activity, arriving from the Builder", () => {
  it("asks for one agent's runs when the URL names one", async () => {
    params.set("agent", "agent-42");

    render(<RunsPage />, { wrapper });

    await waitFor(() => expect(runsCalls()).not.toHaveLength(0));
    // Including what the agent did as somebody's delegate: narrowed to one
    // agent, that is the only record of what it itself cost.
    expect(runsCalls().map((call) => call[1])).toContainEqual({
      params: { agent_id: "agent-42", include_delegations: "true" },
    });
  });

  it("still counts the organization's runs beside the organization's bill", async () => {
    // The stat cards above the tabs are the organization's, and the middle one
    // used to follow the table's filter - so arriving from the Builder put one
    // agent's run count next to the whole organization's month.
    params.set("agent", "agent-42");

    render(<RunsPage />, { wrapper });

    await waitFor(() => expect(runsCalls()).not.toHaveLength(0));
    // No `agent_id`, so it is still the organization's count - and windowed to
    // the calendar month, which is what makes it comparable to the money beside
    // it rather than a total since the organization was created (#198).
    const organizationCall = runsCalls()
      .map((call) => call[1])
      .find((options) => options?.params?.agent_id === undefined);
    expect(organizationCall?.params?.started_from).toBeDefined();
  });

  it("asks for the whole organization when the URL names nobody", async () => {
    render(<RunsPage />, { wrapper });

    await waitFor(() => expect(runsCalls()).not.toHaveLength(0));
    expect(runsCalls()[0]?.[1]).toBeUndefined();
  });

  it("says the table is narrowed, and offers the way out", async () => {
    // A filtered table that does not mention the filter is one somebody reads as
    // the whole history, and then wonders where the rest of the runs went.
    // The notice lives with the table, and the page opens on Approvals.
    params.set("agent", "agent-42");

    render(<RunsPage />, { wrapper });
    await userEvent.click(await screen.findByRole("tab", { name: "Runs" }));

    expect(await screen.findByText(/Narrowed to one agent/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Show every agent" })).toHaveAttribute("href", "/runs");
  });

  it("says nothing about narrowing when nothing is narrowed", async () => {
    render(<RunsPage />, { wrapper });
    await userEvent.click(await screen.findByRole("tab", { name: "Runs" }));

    expect(screen.queryByText(/Narrowed to one agent/)).toBeNull();
  });
});
