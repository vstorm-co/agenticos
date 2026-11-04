import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { WorkflowLogsWidget } from "./workflow-logs";
import type { Period } from "@/lib/dashboard/period";
import type { WorkflowRecentLogs } from "@/lib/workflows/types";

const useLogsMock = vi.fn();

vi.mock("@/hooks", () => ({
  useRecentWorkflowLogs: (...args: unknown[]) => useLogsMock(...args),
}));

const PERIOD: Period = { preset: "7d", from: "2026-10-05", to: "2026-10-11" };

const LINE = {
  workflow_id: "wf-1",
  node_instance_id: "n-1",
  status: "succeeded",
  is_test: false,
  is_pinned: false,
};

const BUSY: WorkflowRecentLogs = {
  counts: { out: 9, error: 3 },
  items: [
    {
      ...LINE,
      id: "e-1",
      run_id: "run-1",
      step_label: "Send the mail",
      outcome: "out",
      message: "Mailed the reply",
      created_at: new Date().toISOString(),
      workflow_name: "Inbox triage",
    },
    {
      ...LINE,
      id: "e-2",
      run_id: "run-2",
      step_label: "Charge",
      outcome: "error",
      message: "Card declined",
      created_at: new Date(Date.now() - 3 * 3600 * 1000).toISOString(),
      workflow_name: "Refunds",
      workflow_id: "wf-2",
    },
  ],
};

function renderWidget(
  logs: WorkflowRecentLogs | null,
  overrides: Partial<ReturnType<typeof useLogsMock>> = {},
) {
  useLogsMock.mockReturnValue({
    logs,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...overrides,
  });
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <WorkflowLogsWidget title="Workflow logs" hint="" period={PERIOD} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  useLogsMock.mockReset();
});

describe("the workflow logs widget", () => {
  it("counts the last 24 hours and the errors among them", () => {
    renderWidget(BUSY);

    expect(useLogsMock).toHaveBeenCalledWith(6);
    expect(screen.getByText("Lines, last 24 hours")).toBeVisible();
    expect(screen.getByText("12")).toBeVisible();
    expect(screen.getByText("Errors")).toBeVisible();
    expect(screen.getByText("3")).toBeVisible();
  });

  it("shows no errors as zero when none of the lines left by error", () => {
    renderWidget({ ...BUSY, counts: { out: 2 } });

    expect(screen.getByText("0")).toBeVisible();
  });

  it("links each line to its run and its workflow to its Logs page", () => {
    renderWidget(BUSY);

    expect(screen.getByRole("link", { name: "Mailed the reply" })).toHaveAttribute(
      "href",
      "/workflows/wf-1/runs/run-1",
    );
    expect(screen.getByRole("link", { name: "Inbox triage" })).toHaveAttribute(
      "href",
      "/workflows/wf-1/logs",
    );
    expect(screen.getByRole("link", { name: "Refunds" })).toHaveAttribute(
      "href",
      "/workflows/wf-2/logs",
    );
    expect(screen.getByText("· Charge ·")).toBeVisible();
    expect(screen.getByText("· 3h ago")).toBeVisible();
    // A failure keeps the Logs page's destructive tone; another port is plain.
    expect(screen.getByText("error")).toHaveClass("text-destructive");
    expect(screen.getByText("out")).not.toHaveClass("text-destructive");
  });

  it("shows its empty state when no workflow has logged a line", () => {
    renderWidget({ items: [], counts: {} });

    expect(screen.getByText("No log lines yet")).toBeVisible();
  });

  it("draws a placeholder while the lines are being read", () => {
    renderWidget(null, { isLoading: true });

    expect(screen.getByRole("status", { name: "Loading" })).toBeVisible();
    expect(screen.queryByText("No log lines yet")).not.toBeInTheDocument();
  });

  it("offers a retry when the request fails", async () => {
    const refetch = vi.fn();
    renderWidget(null, { error: new Error("boom"), refetch });

    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalledOnce();
  });
});
