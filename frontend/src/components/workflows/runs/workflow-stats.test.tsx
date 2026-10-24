import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { WorkflowStats as Stats } from "@/lib/workflows/types";

import { WorkflowStats } from "./workflow-stats";

const state = vi.hoisted(() => ({
  stats: null as Stats | null,
  isLoading: false,
  asked: [] as number[],
}));

vi.mock("@/hooks", () => ({
  useNodeCatalog: () => ({ nodes: [{ id: "agent.run", name: "Run an agent" }] }),
  useWorkflowStats: (_id: string, days: number) => {
    state.asked.push(days);
    return { stats: state.stats, isLoading: state.isLoading };
  },
}));

function stats(overrides: Partial<Stats> = {}): Stats {
  return {
    days: 30,
    since: "2026-09-11T00:00:00Z",
    runs: 12,
    succeeded: 9,
    failed: 2,
    ended: 11,
    success_rate: 0.818,
    duration_p50_seconds: 4.2,
    duration_p95_seconds: 75,
    cost_usd: 0.0123,
    cost_is_partial: false,
    month_cost_usd: 0.5,
    monthly_budget_usd: null,
    by_day: [
      { day: "2026-10-10", succeeded: 4, failed: 1, other: 0, cost_usd: 0.004 },
      { day: "2026-10-11", succeeded: 5, failed: 1, other: 1, cost_usd: 0.0083 },
    ],
    steps: [
      {
        node_instance_id: "s1",
        label: "Classify",
        definition_id: "ai.classify",
        runs: 12,
        failed: 0,
        cost_usd: 0.002,
        avg_seconds: 1.5,
      },
      {
        node_instance_id: "s2",
        label: null,
        definition_id: "agent.run",
        runs: 12,
        failed: 2,
        cost_usd: 0.01,
        avg_seconds: null,
      },
      {
        node_instance_id: "s3",
        label: null,
        definition_id: null,
        runs: 1,
        failed: 0,
        cost_usd: 0,
        avg_seconds: 0.2,
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  state.stats = stats();
  state.isLoading = false;
  state.asked = [];
});

describe("WorkflowStats", () => {
  it("shows how its runs ended, how long they took and what they cost", () => {
    render(<WorkflowStats workflowId="wf" />);

    expect(screen.getByText("2 failed").previousSibling).toHaveTextContent("12");
    expect(screen.getByText("82%")).toBeVisible();
    expect(screen.getByText("9 of 11 runs that ended")).toBeVisible();
    expect(screen.getByText("4.2 s")).toBeVisible();
    expect(screen.getByText("95 in 100 within 1 min 15 s")).toBeVisible();
    expect(screen.getByText("$0.0123")).toBeVisible();
    expect(screen.getByText("$0.5000 this month, test runs included")).toBeVisible();
  });

  it("lists the steps costliest first, naming one by its type or as gone", () => {
    render(<WorkflowStats workflowId="wf" />);

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((row) => within(row).getAllByRole("cell")[0]!.textContent)).toEqual([
      "Run an agent",
      "Classify",
      "A step no longer in the workflow",
    ]);
    expect(within(rows[0]!).getAllByRole("cell")[2]).toHaveClass("text-destructive");
    expect(within(rows[0]!).getAllByRole("cell")[3]).toHaveTextContent("-");
    expect(within(rows[2]!).getAllByRole("cell")[4]).toHaveTextContent("$0.00");
  });

  it("measures the month against its budget, and says so once it is spent", () => {
    state.stats = stats({ monthly_budget_usd: 0.5, cost_is_partial: true, cost_usd: 2 });
    render(<WorkflowStats workflowId="wf" />);

    expect(screen.getByText("$2.00+")).toBeVisible();
    expect(screen.getByText("$0.5000 of $0.5000 this month, test runs included")).toHaveClass(
      "text-destructive",
    );
  });

  it("asks for the window picked", async () => {
    render(<WorkflowStats workflowId="wf" />);

    expect(screen.getByRole("button", { name: "30 days" })).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(screen.getByRole("button", { name: "7 days" }));

    expect(state.asked.at(-1)).toBe(7);
    expect(screen.getByRole("button", { name: "7 days" })).toHaveAttribute("aria-pressed", "true");
  });

  it("waits for the figures, and says when no step ran", () => {
    state.isLoading = true;
    const { rerender } = render(<WorkflowStats workflowId="wf" />);
    expect(screen.queryByText("Runs")).toBeNull();

    state.isLoading = false;
    state.stats = stats({ steps: [], success_rate: null, duration_p50_seconds: null });
    rerender(<WorkflowStats workflowId="wf" />);
    expect(screen.getByText("No step has run in this window.")).toBeVisible();
    expect(screen.getAllByText("-").length).toBeGreaterThanOrEqual(2);
  });
});
