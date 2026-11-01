import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { ApprovalOutcomesWidget } from "./approval-outcomes";
import type { Period } from "@/lib/dashboard/period";
import type { WorkflowApprovalsSummary } from "@/lib/workflows/types";

const useSummaryMock = vi.fn();

vi.mock("@/hooks", () => ({
  useWorkflowApprovalsSummary: (...args: unknown[]) => useSummaryMock(...args),
}));

const PERIOD: Period = { preset: "7d", from: "2026-10-05", to: "2026-10-11" };

const OUTCOMES = {
  requests: 0,
  pending: 0,
  approved_unchanged: 0,
  approved_edited: 0,
  rejected: 0,
  expired: 0,
  cancelled: 0,
  acceptance_rate: null,
  unchanged_rate: null,
  decide_p50_seconds: null,
  decide_p95_seconds: null,
  edit_ratio_median: null,
  edit_ratios: [],
};

const QUIET: WorkflowApprovalsSummary = { ...OUTCOMES, workflows: [] };

function renderWidget(
  summary: WorkflowApprovalsSummary | null,
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
      <ApprovalOutcomesWidget title="Approval outcomes" hint="" period={PERIOD} />
    </NextIntlClientProvider>,
  );
}

const BUSY: WorkflowApprovalsSummary = {
  ...OUTCOMES,
  requests: 10,
  approved_unchanged: 6,
  approved_edited: 2,
  rejected: 2,
  acceptance_rate: 0.8,
  unchanged_rate: 0.6,
  decide_p50_seconds: 90,
  decide_p95_seconds: 600,
  edit_ratio_median: 0.25,
  workflows: [
    { ...OUTCOMES, id: "wf-1", name: "Reply drafts", requests: 8, unchanged_rate: 0.5 },
    { ...OUTCOMES, id: "wf-2", name: "Refund check", requests: 1, unchanged_rate: null },
  ],
};

beforeEach(() => {
  useSummaryMock.mockReset();
});

describe("the approval outcomes widget", () => {
  it("shows the period's approval outcomes", () => {
    renderWidget(BUSY);

    expect(useSummaryMock).toHaveBeenCalledWith("2026-10-05", "2026-10-11");
    expect(screen.getByText("Approved as proposed")).toBeVisible();
    expect(screen.getByText("60%")).toBeVisible();
    expect(screen.getByText("Edited")).toBeVisible();
    expect(screen.getByText("Median change 25%")).toBeVisible();
    expect(screen.getByText("Time to decide")).toBeVisible();
    expect(screen.getByText("1 min 30 s")).toBeVisible();
  });

  it("says a change was not measured when edits exist without a stored ratio", () => {
    renderWidget({ ...BUSY, approved_edited: 2, edit_ratio_median: null });

    expect(screen.getByText("Change not measured")).toBeVisible();
  });

  it("leaves the edited caption out when nothing was edited", () => {
    renderWidget({ ...BUSY, approved_edited: 0, edit_ratio_median: null });

    expect(screen.queryByText("Change not measured")).not.toBeInTheDocument();
    expect(screen.queryByText(/Median change/)).not.toBeInTheDocument();
  });

  it("shows a dash where nothing was decided or measured", () => {
    renderWidget({
      ...BUSY,
      unchanged_rate: null,
      edit_ratio_median: null,
      decide_p50_seconds: null,
    });

    expect(screen.getAllByText("-")).toHaveLength(2);
    expect(screen.queryByText(/Median change/)).not.toBeInTheDocument();
  });

  it("lists the busiest workflows", () => {
    renderWidget(BUSY);

    expect(screen.getByRole("link", { name: /Reply drafts/ })).toHaveAttribute(
      "href",
      "/workflows/wf-1/runs",
    );
    expect(screen.getByText("8 requests, 50% approved as proposed")).toBeVisible();
    expect(screen.getByText("1 request")).toBeVisible();
    expect(screen.queryByText(/- approved as proposed/)).not.toBeInTheDocument();
  });

  it("shows its empty state when nobody was asked", () => {
    renderWidget(QUIET);

    expect(screen.getByText("No approval requests in this period")).toBeVisible();
  });

  it("draws a placeholder while the figures are being read", () => {
    renderWidget(null, { isLoading: true });

    expect(screen.getByRole("status", { name: "Loading" })).toBeVisible();
    expect(screen.queryByText("Approved as proposed")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /retry/i })).not.toBeInTheDocument();
    expect(screen.queryByText("No approval requests in this period")).not.toBeInTheDocument();
  });

  it("offers a retry when the request fails", async () => {
    const refetch = vi.fn();
    renderWidget(null, { error: new Error("boom"), refetch });

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledOnce();
  });
});
