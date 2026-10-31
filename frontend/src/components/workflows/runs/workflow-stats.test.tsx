import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  WorkflowApprovalStats,
  WorkflowApprovalStep,
  WorkflowStats as Stats,
} from "@/lib/workflows/types";

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

const BUCKETS = [0, 0.1, 0.25, 0.5, 1].map((upto) => ({ upto, count: 0 }));

/** The figure card under `label` inside an approvals section. */
function figure(section: HTMLElement, label: string): HTMLElement {
  return within(section).getByText(label, { selector: "p > span" }).closest("p")!.parentElement!;
}

/** An approval figure block with nothing in it - a workflow that asked nobody. */
function noApprovals(): WorkflowApprovalStats {
  return {
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
    edit_ratios: BUCKETS,
    by_day: [],
    steps: [],
  };
}

function approvalStep(overrides: Partial<WorkflowApprovalStep> = {}): WorkflowApprovalStep {
  const { by_day: _byDay, steps: _steps, ...none } = noApprovals();
  return {
    ...none,
    node_instance_id: "a1",
    label: "Review the reply",
    definition_id: "human.approval",
    ...overrides,
  };
}

/** Ten requests: six sent as proposed, two edited, one rejected, one expired. */
function approvals(overrides: Partial<WorkflowApprovalStats> = {}): WorkflowApprovalStats {
  return {
    ...noApprovals(),
    requests: 10,
    approved_unchanged: 6,
    approved_edited: 2,
    rejected: 1,
    expired: 1,
    acceptance_rate: 8 / 9,
    unchanged_rate: 6 / 9,
    decide_p50_seconds: 90,
    decide_p95_seconds: 3600,
    edit_ratio_median: 0.25,
    by_day: [
      { day: "2026-10-10", approved_unchanged: 2, approved_edited: 1, rejected: 0, expired: 0 },
      { day: "2026-10-11", approved_unchanged: 4, approved_edited: 1, rejected: 1, expired: 1 },
    ],
    steps: [
      approvalStep({
        requests: 3,
        approved_unchanged: 1,
        approved_edited: 1,
        rejected: 1,
        unchanged_rate: 1 / 3,
        edit_ratio_median: 0.4,
        decide_p50_seconds: 30,
      }),
      approvalStep({
        node_instance_id: "a2",
        label: null,
        definition_id: "agent.run",
        requests: 7,
        approved_unchanged: 5,
        approved_edited: 1,
        expired: 1,
        unchanged_rate: 5 / 6,
        edit_ratio_median: null,
      }),
    ],
    ...overrides,
  };
}

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
    approvals: noApprovals(),
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

  it("lists the steps costliest first, naming one by its type, and a removed one when asked", async () => {
    render(<WorkflowStats workflowId="wf" />);
    const names = () =>
      screen
        .getAllByRole("row")
        .slice(1)
        .map((row) => within(row).getAllByRole("cell")[0]!.textContent);
    expect(names()).toEqual(["Run an agent", "Classify"]);

    const toggle = screen.getByRole("button", { name: "Show removed steps" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(names()).toEqual(["Run an agent", "Classify", "A step no longer in the workflow"]);
    const rows = screen.getAllByRole("row").slice(1);
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

  it("shows how people decided the approval steps", () => {
    state.stats = stats({ approvals: approvals() });
    render(<WorkflowStats workflowId="wf" />);

    const section = screen.getByRole("region", { name: "Approvals" });
    expect(
      within(section).getByText(
        "How people decided what this workflow's approval steps asked, over the same days.",
      ),
    ).toBeVisible();
    // 6 of the 9 that were decided went out as proposed; an expired request is not a decision.
    expect(figure(section, "Approved as proposed")).toHaveTextContent("67%6 of 9 approved");
    expect(figure(section, "Edited before approval")).toHaveTextContent("2Median change 25%");
    expect(figure(section, "Rejected")).toHaveTextContent("11 expired");
    expect(figure(section, "Time to decide")).toHaveTextContent("1 min 30 s95% within 1 h");
  });

  it("lists each approval step with its figures", () => {
    state.stats = stats({ approvals: approvals() });
    render(<WorkflowStats workflowId="wf" />);

    const table = within(screen.getByRole("region", { name: "Approvals" })).getByRole("table");
    const rows = within(table).getAllByRole("row");
    expect(
      within(rows[0]!)
        .getAllByRole("columnheader")
        .map((cell) => cell.textContent),
    ).toEqual([
      "Step",
      "Requests",
      "Approved as proposed",
      "Edited before approval",
      "Rejected",
      "Expired",
      "Median change",
      "Time to decide",
    ]);
    const cells = (row: HTMLElement) =>
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent);
    expect(cells(rows[1]!)).toEqual(["Review the reply", "3", "33%", "1", "1", "0", "40%", "30 s"]);
    // A step named by its type; no decision measured as a change, no decision made in time.
    expect(cells(rows[2]!)).toEqual(["Run an agent", "7", "83%", "1", "0", "1", "-", "-"]);
  });

  it("says a change was not measured when edits exist but no ratio does", () => {
    state.stats = stats({
      approvals: approvals({ edit_ratio_median: null, approved_edited: 2, unchanged_rate: 0.5 }),
    });
    render(<WorkflowStats workflowId="wf" />);

    const section = screen.getByRole("region", { name: "Approvals" });
    expect(figure(section, "Edited before approval")).toHaveTextContent("2Change not measured");
  });

  it("gives the edited figure no caption when nothing was edited", () => {
    state.stats = stats({
      approvals: approvals({ edit_ratio_median: null, approved_edited: 0, unchanged_rate: 1 }),
    });
    render(<WorkflowStats workflowId="wf" />);

    const section = screen.getByRole("region", { name: "Approvals" });
    expect(figure(section, "Edited before approval")).toHaveTextContent(
      /^Edited before approval0$/,
    );
    expect(figure(section, "Edited before approval")).not.toHaveTextContent("not measured");
  });

  it("shows no value for a rate when nothing was decided yet", () => {
    state.stats = stats({
      approvals: approvals({
        requests: 2,
        approved_unchanged: 0,
        approved_edited: 0,
        rejected: 0,
        expired: 0,
        pending: 2,
        unchanged_rate: null,
        decide_p50_seconds: null,
        decide_p95_seconds: null,
        edit_ratio_median: null,
        by_day: [],
        steps: [],
      }),
    });
    render(<WorkflowStats workflowId="wf" />);

    const section = screen.getByRole("region", { name: "Approvals" });
    expect(figure(section, "Approved as proposed")).toHaveTextContent("-0 of 0 approved");
    expect(figure(section, "Time to decide")).toHaveTextContent("-95% within -");
    expect(within(section).queryByRole("table")).toBeNull();
  });

  it("hides a removed approval step until the By step switch shows it", async () => {
    state.stats = stats({
      approvals: approvals({
        steps: [
          approvalStep(),
          approvalStep({ node_instance_id: "s3", label: null, definition_id: null }),
        ],
      }),
    });
    render(<WorkflowStats workflowId="wf" />);
    const table = () =>
      within(screen.getByRole("region", { name: "Approvals" })).getByRole("table");
    expect(within(table()).getAllByRole("row")).toHaveLength(2);

    await userEvent.click(screen.getByRole("button", { name: "Show removed steps" }));

    expect(within(table()).getAllByRole("row")).toHaveLength(3);
  });

  it("offers no toggle when every step is still in the workflow", () => {
    state.stats = stats({ steps: stats().steps.filter((step) => step.definition_id !== null) });
    render(<WorkflowStats workflowId="wf" />);

    expect(screen.queryByRole("button", { name: /removed step/ })).toBeNull();
  });

  it("shows no approvals section for a workflow without approvals", () => {
    render(<WorkflowStats workflowId="wf" />);

    expect(screen.queryByRole("region", { name: "Approvals" })).toBeNull();
    expect(screen.queryByText("Approved as proposed")).toBeNull();
  });
});
