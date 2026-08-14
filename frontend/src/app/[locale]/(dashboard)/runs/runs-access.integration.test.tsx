import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunsPage from "./page";
import { apiClient } from "@/lib/api-client";
import type { Permission } from "@/types/permissions";

/**
 * The Activity page for a caller without `runs:view`.
 *
 * A deep link to `/runs` used to fire `GET /runs` and `GET /spend` for every
 * member, and both routes refuse a caller without the permission - so a Member
 * or Viewer landed on failure cards about requests that were always going to be
 * refused. The page now asks for nothing it cannot read and says whose decision
 * the absence is. Real `usePermissions` over a mocked `/me/permissions`,
 * because the permission decision is the thing on trial.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const params = new URLSearchParams();
vi.mock("next/navigation", () => ({ useSearchParams: () => params }));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function serve(permissions: Permission[]) {
  vi.mocked(apiClient.get).mockImplementation((path: string) => {
    if (path === "/me/permissions")
      return Promise.resolve({
        organization_id: "o1",
        role: "member",
        is_app_admin: false,
        permissions: permissions.map((permission) => ({ permission, scope: "all" })),
      });
    if (path === "/spend")
      return Promise.resolve({
        period_days: null,
        month_to_date_usd: "0.00",
        by_agent: [],
        by_provider: [],
        by_key: [],
      });
    return Promise.resolve({ items: [], total: 0 });
  });
}

const asked = (path: string) =>
  vi.mocked(apiClient.get).mock.calls.filter(([called]) => called === path);

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
});

describe("a deep link to /runs without runs:view", () => {
  it("fires neither of the requests the backend would refuse", async () => {
    serve([]);

    render(<RunsPage />, { wrapper });

    // Both surfaces say so - the figures row and the history tab each carry
    // the sentence, because each used to carry its own failure card.
    expect(await screen.findAllByText("No access to run activity")).not.toHaveLength(0);
    expect(asked("/runs")).toHaveLength(0);
    expect(asked("/spend")).toHaveLength(0);
    // The absence is a decision, not a failure: nothing was asked, so nothing
    // may be reported as having failed to load.
    expect(screen.queryByText("Couldn't load")).toBeNull();
    expect(screen.queryByText("Run history could not be read")).toBeNull();
  });
});

describe("the same link for a holder", () => {
  it("asks for the history and the bill exactly as before", async () => {
    serve(["runs:view"]);

    render(<RunsPage />, { wrapper });

    expect(await screen.findByText("No runs in this window")).toBeVisible();
    await waitFor(() => expect(asked("/runs").length).toBeGreaterThan(0));
    await waitFor(() => expect(asked("/spend").length).toBeGreaterThan(0));
    expect(screen.queryByText("No access to run activity")).toBeNull();
  });
});
