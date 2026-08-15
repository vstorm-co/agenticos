import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { OutcomesWidget } from "@/components/dashboard/widgets/outcomes";
import { VersionStrip } from "@/components/runs/version-strip";
import { useAgent, useUsageStats, useVersionUsage } from "@/hooks";
import type { Period } from "@/lib/dashboard/period";
import type { UsageStats, VersionUsageRow } from "@/types/stats";

/**
 * The invariant of §8a.4, proven by rendering both surfaces.
 *
 * The dashboard's Outcomes donut and the Activity version strip both read one
 * window's runs and print a "completed" share. They compute it through one
 * shared function (`completedShare`), so over the same rows the two numbers are
 * the same - and if either side ever started excluding a status from its
 * denominator, the string this test reads off each would diverge and the test
 * would fail. That is the drift the issue exists to prevent.
 */

vi.mock("@/hooks", () => ({
  useUsageStats: vi.fn(),
  useVersionUsage: vi.fn(),
  useAgent: vi.fn(),
}));

// The donut paints inside recharts, which measures 0x0 in jsdom and draws no
// SVG text - so its centre label is captured here rather than read off a chart
// that never renders. The label is what the widget computes; the chart is not
// the subject.
vi.mock("@/components/dashboard/primitives/donut-chart", () => ({
  DonutChart: ({ centerLabel }: { centerLabel: string }) => (
    <div data-testid="donut-share">{centerLabel}</div>
  ),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-01", to: "2026-07-30" };

/** One completed, one cancelled, one budget_exceeded - the §8a.4 window. */
const BY_STATUS = [
  { status: "completed" as const, runs: 1 },
  { status: "cancelled" as const, runs: 1 },
  { status: "budget_exceeded" as const, runs: 1 },
];

const USAGE = {
  from: "2026-07-01",
  to: "2026-07-30",
  scope: "org",
  total_runs: 3,
  previous_total_runs: null,
  by_day: null,
  by_surface: null,
  by_agent: null,
  by_status: BY_STATUS,
  by_model: null,
  latency_ms: null,
  cost: null,
  active_users: null,
  pending_approvals: null,
  agent_id: null,
  by_version: null,
  by_user: null,
} satisfies UsageStats;

const VERSION: VersionUsageRow = {
  agent_version_id: "v1",
  version: 1,
  runs: 3,
  completed_runs: 1,
  p95_ms: null,
  avg_cost_usd: null,
  like_count: 0,
  rating_count: 0,
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useUsageStats).mockReturnValue({
    usage: USAGE,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  } as ReturnType<typeof useUsageStats>);
  vi.mocked(useVersionUsage).mockReturnValue({
    byVersion: [VERSION],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  } as ReturnType<typeof useVersionUsage>);
  vi.mocked(useAgent).mockReturnValue({ agent: undefined } as ReturnType<typeof useAgent>);
});

describe("the version strip and the Outcomes donut, rendered from the same rows", () => {
  it("print the same completed share, with cancelled in both denominators", () => {
    render(
      <>
        <OutcomesWidget title="Outcomes" hint="" period={PERIOD} />
        <VersionStrip agentId="a1" period={PERIOD} />
      </>,
    );

    const donutShare = screen.getByTestId("donut-share").textContent;
    // The strip prints its share under a lowercase "completed" label.
    const stripShare = screen
      .getByText("completed")
      .parentElement?.querySelector("dd")?.textContent;

    expect(stripShare).toBe(donutShare);
    // A third, not a half: the cancelled run is in the denominator on both sides.
    expect(donutShare).toBe("33%");
  });
});
