import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { WorkflowsWidget } from "./workflows-widget";
import type { Period } from "@/lib/dashboard/period";
import type { WorkflowsSummary } from "@/lib/workflows/types";

const useSummaryMock = vi.fn();

vi.mock("@/hooks", () => ({
  useWorkflowsSummary: (...args: unknown[]) => useSummaryMock(...args),
}));

const PERIOD: Period = { preset: "7d", from: "2026-10-05", to: "2026-10-11" };

const QUIET: WorkflowsSummary = {
  runs: 0,
  succeeded: 0,
  failed: 0,
  cost_usd: 0,
  needs_you: 0,
  workflows: [],
};

function renderWidget(
  summary: WorkflowsSummary | null,
  overrides: Partial<ReturnType<typeof useSummaryMock>> = {},
) {
  useSummaryMock.mockReturnValue({
    summary,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  });
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <WorkflowsWidget title="Workflows" hint="" period={PERIOD} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  useSummaryMock.mockReset();
});

describe("the workflows widget", () => {
  it("reads the page's window and shows its figures, each workflow linking to its runs", () => {
    renderWidget({
      runs: 5,
      succeeded: 3,
      failed: 2,
      cost_usd: 1.5,
      needs_you: 0,
      workflows: [
        { id: "wf-1", name: "Lead triage", runs: 4, failed: 2, cost_usd: 1 },
        { id: "wf-2", name: "Order watcher", runs: 1, failed: 0, cost_usd: 0.5 },
      ],
    });

    expect(useSummaryMock).toHaveBeenCalledWith("2026-10-05", "2026-10-11");
    expect(screen.getByText("3 succeeded")).toBeVisible();
    expect(screen.getByText("$1.50")).toBeVisible();
    expect(screen.getByRole("link", { name: /Lead triage/ })).toHaveAttribute(
      "href",
      "/workflows/wf-1/runs",
    );
    expect(screen.getByText("4 runs, 2 failed")).toBeVisible();
    expect(screen.getByText("1 run")).toBeVisible();
    expect(screen.queryByText(/wait for you|waits for you/)).not.toBeInTheDocument();
  });

  it("leads with the runs waiting for a person, even in a window with no runs", () => {
    renderWidget({ ...QUIET, needs_you: 2 });

    expect(screen.getByRole("link", { name: "2 runs wait for you" })).toHaveAttribute(
      "href",
      "/workflows/runs",
    );
  });

  it("says nothing ran, rather than drawing a row of zeros", () => {
    renderWidget(QUIET);

    expect(screen.getByText("No workflow runs in this period")).toBeVisible();
  });

  it("draws a placeholder while the figures are being read", () => {
    renderWidget(null, { isLoading: true });

    expect(screen.queryByText("No workflow runs in this period")).not.toBeInTheDocument();
  });

  it("says the figures could not be read, and offers a retry that reaches the query", async () => {
    const refetch = vi.fn();
    renderWidget(null, { error: new Error("boom"), refetch });

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledOnce();
  });
});
