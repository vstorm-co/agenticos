import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { SummaryWidget } from "./summary";
import type { Period } from "@/lib/dashboard/period";
import type { UsageStats } from "@/types/stats";

/**
 * The strip is a reading of the same window the cards below it read, so the
 * two ways it could go wrong are both agreement failures: computing a completed
 * share on a denominator the Outcomes donut does not use, and issuing a second
 * request for numbers already in hand.
 */

const useUsageStatsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useUsageStats: (...args: unknown[]) => useUsageStatsMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-07", to: "2026-08-05" };

const USAGE = {
  total_runs: 40,
  previous_total_runs: 32,
  by_status: [
    { status: "completed", runs: 30 },
    { status: "failed", runs: 6 },
    { status: "cancelled", runs: 4 },
  ],
  cost: { period_usd: "12.50", previous_period_usd: "10.00", by_provider: [] },
  active_users: { active: 7, total_members: 23 },
} as unknown as UsageStats;

function withUsage(usage: UsageStats = USAGE) {
  useUsageStatsMock.mockReturnValue({ usage, isLoading: false, error: null, refetch: vi.fn() });
}

function renderWidget(node: React.ReactNode) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      {node}
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useUsageStatsMock.mockReset());

describe("the summary strip", () => {
  it("counts a cancelled run in the denominator, as the Outcomes donut does", () => {
    withUsage();
    renderWidget(<SummaryWidget title="At a glance" hint="" period={PERIOD} />);

    // 30 completed of 40, with the four cancelled runs in the denominator like
    // every other outcome - the rule `run-outcomes` fixes so the strip and the
    // donut two rows below it cannot print different percentages of one window.
    // Excluding them would read 30 of 36, or 83%.
    expect(screen.getByText("75%")).toBeVisible();
    expect(screen.getByText("of 40 runs")).toBeVisible();
  });

  it("reads the window's cost and people rather than asking for them again", () => {
    withUsage();
    renderWidget(<SummaryWidget title="At a glance" hint="" period={PERIOD} />);

    expect(screen.getByText("$12.50")).toBeVisible();
    expect(screen.getByText("of 23 members")).toBeVisible();
    // One query, the same one every other composed-response card reads.
    expect(useUsageStatsMock).toHaveBeenCalledTimes(1);
    expect(useUsageStatsMock).toHaveBeenCalledWith({ from: PERIOD.from, to: PERIOD.to });
  });

  it("says rising spend is the bad direction and rising runs the good one", () => {
    withUsage();
    renderWidget(<SummaryWidget title="At a glance" hint="" period={PERIOD} />);

    // +25% runs (32 → 40) and +25% spend (10.00 → 12.50): the same number, and
    // the tones must differ, because adoption and a bill are not the same news.
    const [runs, spend] = screen.getAllByText("25%");
    expect(runs).toHaveClass("text-success");
    expect(spend).toHaveClass("text-destructive");
  });

  it("draws no change at all when the previous window had nothing to compare", () => {
    withUsage({
      ...USAGE,
      previous_total_runs: 0,
      cost: { period_usd: "12.50", previous_period_usd: "0", by_provider: [] },
    } as unknown as UsageStats);
    renderWidget(<SummaryWidget title="At a glance" hint="" period={PERIOD} />);

    // A share of nothing is not a hundred-percent rise; the chip is absent.
    expect(screen.queryByText(/vs the previous period/)).not.toBeInTheDocument();
  });
});
