import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import type { UsageStats } from "@/types/stats";
import { MySummaryWidget } from "./my-summary";

const useUsageStatsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useUsageStats: (...args: unknown[]) => useUsageStatsMock(...args),
}));

const others = vi.hoisted(() => ({
  review: 0,
  suites: 0,
  suggestions: 0,
  settled: true,
  failed: false,
  retry: (() => {}) as () => void,
}));
vi.mock("@/hooks/use-waiting-on-me", async (original) => ({
  ...(await original<typeof import("@/hooks/use-waiting-on-me")>()),
  useWaitingOnMe: () => others,
}));

const PERIOD: Period = { preset: "30d", from: "2026-09-14", to: "2026-10-13" };

function usage(overrides: Partial<UsageStats> = {}): UsageStats {
  return {
    from: PERIOD.from,
    to: PERIOD.to,
    scope: "own",
    total_runs: 73,
    previous_total_runs: 0,
    by_day: [
      { date: "2026-10-12", runs: 30, completed: 25, cost_usd: "2.00" },
      { date: "2026-10-13", runs: 43, completed: 38, cost_usd: "3.00" },
    ],
    timeline: {
      step_seconds: 86400,
      buckets: [
        { start: "2026-10-12T00:00:00Z", runs: 30, completed: 25, cost_usd: "2.00" },
        { start: "2026-10-13T00:00:00Z", runs: 43, completed: 38, cost_usd: "3.00" },
      ],
    },
    by_surface: null,
    by_agent: null,
    by_status: [
      { status: "completed", runs: 63 },
      { status: "failed", runs: 10 },
    ],
    by_model: null,
    latency_ms: null,
    cost: {
      period_usd: "5.00",
      previous_period_usd: "0",
      model_usd: "5.00",
      ingestion_usd: "0",
      by_provider: [],
    },
    active_users: null,
    pending_approvals: 1,
    agent_id: null,
    by_version: null,
    ...overrides,
  } as UsageStats;
}

function renderWidget(state: Record<string, unknown>) {
  useUsageStatsMock.mockReturnValue({
    usage: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...state,
  });
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TooltipProvider>
        <MySummaryWidget title="Your period" hint="" period={PERIOD} />
      </TooltipProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  useUsageStatsMock.mockReset();
  others.settled = true;
  others.failed = false;
  others.retry = vi.fn();
});

describe("a person's own period", () => {
  it("reads the caller's own usage, for the period on screen", () => {
    renderWidget({ usage: usage() });

    expect(useUsageStatsMock).toHaveBeenCalledWith(
      { from: PERIOD.from, to: PERIOD.to },
      { scope: "own" },
    );
  });

  it("draws the four measures, and counts what waits as the greeting does", () => {
    others.review = 2;
    others.suggestions = 1;
    renderWidget({ usage: usage() });

    expect(screen.getByText("Your runs")).toBeVisible();
    expect(screen.getByText("86%")).toBeVisible();
    expect(screen.getByText("of 73 runs")).toBeVisible();
    expect(screen.getByRole("link", { name: "1 call" })).toHaveAttribute(
      "href",
      "/runs?tab=approvals",
    );
    expect(screen.getByText(/2 answers to review, and 1 suggestion/)).toBeVisible();
    expect(screen.getByText("Spent")).toBeVisible();
    others.review = 0;
    others.suggestions = 0;
  });

  it("links nothing when no call waits among what does", () => {
    others.suites = 1;
    renderWidget({ usage: usage({ pending_approvals: 0 }) });

    expect(screen.getByText("1 failing suite")).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
    others.suites = 0;
  });

  it("says nothing is waiting, at zero, rather than drawing an empty card", () => {
    renderWidget({
      usage: usage({ total_runs: 0, pending_approvals: 0, by_day: [], by_status: [] }),
    });

    expect(screen.getByText("Nothing waiting")).toBeVisible();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("draws zeros while a period has no usage behind it", () => {
    renderWidget({ usage: null });

    expect(screen.getByText("Nothing waiting")).toBeVisible();
  });

  it("offers a retry when the read fails, and a skeleton while it loads", async () => {
    const refetch = vi.fn();
    renderWidget({ error: new Error("502"), refetch });
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });

  it("holds a skeleton while the first read is in flight", () => {
    renderWidget({ isLoading: true });

    expect(screen.queryByText("Your runs")).toBeNull();
  });

  it("counts nothing as waiting until every list behind that figure answered", () => {
    others.settled = false;
    renderWidget({ usage: usage({ pending_approvals: 0 }) });

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("Nothing waiting")).toBeNull();
  });

  it("fails as a whole when a list behind the waiting figure is refused, and reads it again", async () => {
    const refetch = vi.fn();
    others.settled = false;
    others.failed = true;
    renderWidget({ usage: usage({ pending_approvals: 0 }), refetch });

    expect(screen.queryByText("Nothing waiting")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(others.retry).toHaveBeenCalled();
    expect(refetch).not.toHaveBeenCalled();
  });
});
