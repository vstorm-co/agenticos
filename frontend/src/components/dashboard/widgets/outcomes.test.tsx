import { render, screen, within } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { OutcomesWidget } from "./outcomes";
import type { Period } from "@/lib/dashboard/period";

/**
 * The ring reports the statuses a window held; the legend reports the statuses
 * it could have held. A status at zero is the difference between the two, and
 * "nothing was refused for budget" is an answer worth keeping on the card.
 */

const useUsageStatsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useUsageStats: (...args: unknown[]) => useUsageStatsMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-07", to: "2026-08-05" };

function withStatuses(byStatus: { status: string; runs: number }[]) {
  useUsageStatsMock.mockReturnValue({
    usage: { total_runs: byStatus.reduce((sum, row) => sum + row.runs, 0), by_status: byStatus },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
}

function renderWidget() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <OutcomesWidget title="Outcomes" hint="" period={PERIOD} />
    </NextIntlClientProvider>,
  );
}

const rowFor = (name: string): HTMLElement => screen.getByText(name).closest("li") as HTMLElement;

beforeEach(() => useUsageStatsMock.mockReset());

describe("the outcomes widget", () => {
  it("keeps a status that did not happen, at zero", () => {
    withStatuses([
      { status: "completed", runs: 56 },
      { status: "failed", runs: 2 },
    ]);
    renderWidget();

    const budget = rowFor(messages.dashboard.widgets.outcomes.status.budget_exceeded);
    expect(within(budget).getByText("0")).toBeInTheDocument();
    expect(within(budget).getByText("0%")).toBeInTheDocument();
  });

  it("prints each status's share as well as its count", () => {
    // The count answers "how many" and the share answers "how much of the
    // window", and a ring read by area is asking the second one.
    withStatuses([
      { status: "completed", runs: 3 },
      { status: "failed", runs: 1 },
    ]);
    renderWidget();

    const failed = rowFor(messages.dashboard.widgets.outcomes.status.failed);
    expect(within(failed).getByText("25%")).toBeInTheDocument();
    expect(within(failed).getByText("1")).toBeInTheDocument();
  });

  it("gives every status its own colour rather than sorting them into two", () => {
    withStatuses([
      { status: "completed", runs: 4 },
      { status: "failed", runs: 1 },
      { status: "awaiting_approval", runs: 1 },
    ]);
    const { container } = renderWidget();

    const swatches = Array.from(container.querySelectorAll<HTMLElement>("li span[style]")).map(
      (span) => span.style.background,
    );
    expect(new Set(swatches).size).toBe(5);
  });

  it("says how often a run needed attention, and only when one did", () => {
    withStatuses([
      { status: "completed", runs: 57 },
      { status: "failed", runs: 1 },
    ]);
    const { unmount } = renderWidget();
    expect(screen.getByText(/needed attention/)).toBeInTheDocument();

    unmount();
    withStatuses([{ status: "completed", runs: 58 }]);
    renderWidget();
    expect(screen.queryByText(/needed attention/)).toBeNull();
  });
});
