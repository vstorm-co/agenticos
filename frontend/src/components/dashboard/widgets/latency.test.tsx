import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { LatencyWidget } from "./latency";
import type { Period } from "@/lib/dashboard/period";

/**
 * The p95 figure is the number *and its evidence*: it links to the runs behind
 * it, sorted by duration over the same window. That is the rule the dashboard and
 * Activity already follow for every other figure, and duration was the one it did
 * not (#210).
 */

const useUsageStatsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useUsageStats: (...args: unknown[]) => useUsageStatsMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-07", to: "2026-08-05" };

function withLatency(latency_ms: { p50: number; p95: number } | null) {
  useUsageStatsMock.mockReturnValue({
    usage: { total_runs: 40, latency_ms },
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
}

function renderWidget() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <LatencyWidget title="Latency" hint="" period={PERIOD} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useUsageStatsMock.mockReset());

describe("the latency widget's p95 figure", () => {
  it("links to run history sorted by duration over the same window", () => {
    withLatency({ p50: 3200, p95: 14800 });
    renderWidget();

    const link = screen.getByRole("link", { name: messages.dashboard.widgets.latency.viewSlowest });
    const href = decodeURIComponent(link.getAttribute("href") ?? "");

    expect(href).toContain("/runs?");
    expect(href).toContain("sort=duration");
    // The preset id, not resolved dates: the Activity page re-resolves it, so
    // the link means "the last 30 days" on the day it is clicked, like the
    // widget it came from.
    expect(href).toContain("period=30d");
    expect(link).toHaveTextContent("14.8 s");
  });

  it("carries a custom range as the range itself", () => {
    withLatency({ p50: 3200, p95: 14800 });
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <LatencyWidget
          title="Latency"
          hint=""
          period={{ preset: "custom", from: "2026-07-07", to: "2026-08-05" }}
        />
      </NextIntlClientProvider>,
    );

    const link = screen.getByRole("link", { name: messages.dashboard.widgets.latency.viewSlowest });
    expect(decodeURIComponent(link.getAttribute("href") ?? "")).toContain(
      "period=2026-07-07..2026-08-05",
    );
  });

  it("does not link when nothing finished, because there is nothing to reach", () => {
    // A null p95 is "no completed runs", so the figure stays a plain "—" rather
    // than a link into an empty list.
    withLatency(null);
    renderWidget();

    expect(screen.queryByRole("link")).toBeNull();
    // Both percentiles read "—" with nothing finished; the point is that neither
    // is a link.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(1);
  });
});
