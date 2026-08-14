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
  apiClient: { get: vi.fn(), raw: vi.fn() },
}));
vi.mock("@/lib/file-access", () => ({ saveBlob: vi.fn() }));

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
  vi.mocked(apiClient.raw).mockReset();
  vi.mocked(apiClient.raw).mockResolvedValue({
    blob: async () => new Blob(["run_id\n"], { type: "text/csv" }),
    headers: { get: () => null },
  } as unknown as Response);
});

describe("the rated-down filter", () => {
  it("asks the server for only the rated-down runs when narrowed to them", async () => {
    render(
      <RunHistoryTab
        agentId={null}
        focusedRunId={null}
        period={PERIOD}
        onAgentChange={vi.fn()}
        onFocusRun={vi.fn()}
      />,
      { wrapper },
    );
    await waitFor(() => expect(runsCalls()).not.toHaveLength(0));

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by rating" }));
    await userEvent.click(await screen.findByRole("option", { name: "Rated down" }));

    await waitFor(() =>
      expect(runsCalls().at(-1)?.[1]).toMatchObject({
        params: expect.objectContaining({ rated: "down" }),
      }),
    );
  });

  it("says the list is empty because of the filter, not because nothing ran", async () => {
    render(
      <RunHistoryTab
        agentId={null}
        focusedRunId={null}
        period={PERIOD}
        onAgentChange={vi.fn()}
        onFocusRun={vi.fn()}
      />,
      { wrapper },
    );
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by rating" }));
    await userEvent.click(await screen.findByRole("option", { name: "Rated down" }));

    expect(await screen.findByText("No runs rated down")).toBeVisible();
  });

  it("is not offered to a caller who may not read runs", async () => {
    perm.canView = false;

    render(
      <RunHistoryTab
        agentId={null}
        focusedRunId={null}
        period={PERIOD}
        onAgentChange={vi.fn()}
        onFocusRun={vi.fn()}
      />,
      { wrapper },
    );

    expect(screen.queryByRole("combobox", { name: "Filter by rating" })).toBeNull();
  });

  it("blames the window when the unfiltered list is empty, not a filter and not the org", async () => {
    render(
      <RunHistoryTab
        agentId={null}
        focusedRunId={null}
        period={PERIOD}
        onAgentChange={vi.fn()}
        onFocusRun={vi.fn()}
      />,
      { wrapper },
    );

    expect(await screen.findByText("No runs in this window")).toBeVisible();
    expect(screen.queryByText("No runs rated down")).toBeNull();
  });
});

describe("the export beside the filters", () => {
  it("carries exactly the filters on screen, so the file is the table (#763)", async () => {
    render(
      <RunHistoryTab
        agentId={null}
        focusedRunId={null}
        period={PERIOD}
        onAgentChange={vi.fn()}
        onFocusRun={vi.fn()}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by status" }));
    await userEvent.click(await screen.findByRole("option", { name: "failed" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by surface" }));
    await userEvent.click(await screen.findByRole("option", { name: "slack" }));

    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    await waitFor(() => expect(apiClient.raw).toHaveBeenCalledTimes(1));
    const call = vi.mocked(apiClient.raw).mock.calls.at(-1);
    const params = (call?.[1] as { params: Record<string, string> }).params;
    expect(params.status).toBe("failed");
    expect(params.surface).toBe("slack");
    expect(params.started_from).toBe("2026-07-16T00:00:00.000Z");
    expect(params.started_to).toBe("2026-08-14T23:59:59.999Z");
  });

  it("sends the problems narrowing as the two statuses it stands for", async () => {
    render(
      <RunHistoryTab
        agentId={null}
        focusedRunId={null}
        period={PERIOD}
        onAgentChange={vi.fn()}
        onFocusRun={vi.fn()}
      />,
      { wrapper },
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by status" }));
    await userEvent.click(await screen.findByRole("option", { name: "Problems" }));

    await userEvent.click(screen.getByRole("button", { name: "Export CSV" }));

    await waitFor(() => expect(apiClient.raw).toHaveBeenCalledTimes(1));
    const call = vi.mocked(apiClient.raw).mock.calls.at(-1);
    const params = (call?.[1] as { params: Record<string, string> }).params;
    expect(params.status).toBe("failed,budget_exceeded");
  });
});
