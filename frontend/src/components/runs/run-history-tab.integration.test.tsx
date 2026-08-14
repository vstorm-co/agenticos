import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RunHistoryTab } from "./run-history-tab";
import { apiClient } from "@/lib/api-client";
import type { Period } from "@/lib/dashboard/period";

/**
 * The "rated down" filter on run history, and who is offered it.
 *
 * The filter narrows the list to the answers real people said were wrong - the
 * queue that makes the dashboard's quality number actionable. Two things are
 * proven here: the toggle actually asks the server to narrow (a filter that
 * silently does nothing sends a reader into the whole history), and it is not
 * rendered for a caller who may not read runs (a control that would 403 is not
 * shown - the permission-aware rule this codebase holds).
 */

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn() },
}));

const perm = vi.hoisted(() => ({ canView: true }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => perm.canView, isLoading: false }),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const PERIOD: Period = { preset: "30d", from: "2026-07-16", to: "2026-08-14" };

/** Every `/runs` request made, with its options. */
function runsCalls() {
  return vi.mocked(apiClient.get).mock.calls.filter(([path]) => path === "/runs");
}

beforeEach(() => {
  perm.canView = true;
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
});

describe("the rated-down filter", () => {
  it("asks the server for only the rated-down runs when toggled on", async () => {
    render(<RunHistoryTab agentId={null} focusedRunId={null} period={PERIOD} />, { wrapper });
    await waitFor(() => expect(runsCalls()).not.toHaveLength(0));

    await userEvent.click(screen.getByRole("button", { name: /Rated down/ }));

    await waitFor(() =>
      expect(runsCalls().at(-1)?.[1]).toMatchObject({
        params: expect.objectContaining({ rated: "down" }),
      }),
    );
  });

  it("says the list is empty because of the filter, not because nothing ran", async () => {
    render(<RunHistoryTab agentId={null} focusedRunId={null} period={PERIOD} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: /Rated down/ }));

    expect(await screen.findByText("No runs rated down")).toBeVisible();
  });

  it("is not offered to a caller who may not read runs", async () => {
    perm.canView = false;

    render(<RunHistoryTab agentId={null} focusedRunId={null} period={PERIOD} />, { wrapper });

    expect(screen.queryByRole("button", { name: /Rated down/ })).toBeNull();
  });

  it("blames the window when the unfiltered list is empty, not a filter and not the org", async () => {
    render(<RunHistoryTab agentId={null} focusedRunId={null} period={PERIOD} />, { wrapper });

    expect(await screen.findByText("No runs in this window")).toBeVisible();
    expect(screen.queryByText("No runs rated down")).toBeNull();
  });
});
