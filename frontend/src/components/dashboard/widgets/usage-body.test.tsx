import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { UsageBody } from "./usage-body";
import type { Period } from "@/lib/dashboard/period";
import type { UsageStats } from "@/types/stats";

/**
 * Ten cards read this one query, so what it does between two windows is what
 * the whole page does. Blanking them all was the "skeleton flash on refetch"
 * every dashboard guide names: pick a period and the page empties, reflows,
 * and comes back.
 */

const useUsageStatsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useUsageStats: (...args: unknown[]) => useUsageStatsMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-07", to: "2026-08-05" };
const USAGE = { total_runs: 40 } as UsageStats;

function renderBody() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <UsageBody period={PERIOD} emptyKey="runs">
        {(usage) => <p>{usage.total_runs}</p>}
      </UsageBody>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useUsageStatsMock.mockReset());

describe("a card reading the composed usage answer", () => {
  it("keeps the last window's numbers on screen while the next one is in flight", () => {
    useUsageStatsMock.mockReturnValue({
      usage: USAGE,
      isLoading: false,
      isStale: true,
      error: null,
      refetch: vi.fn(),
    });
    renderBody();

    // Still readable, and visibly the answer being replaced rather than the
    // answer to the window now selected.
    const held = screen.getByText("40");
    expect(held).toBeVisible();
    expect(held.parentElement).toHaveClass("opacity-50");
    expect(held.parentElement).toHaveAttribute("aria-busy", "true");
  });

  it("draws a skeleton on the first load, when there is nothing to hold", () => {
    useUsageStatsMock.mockReturnValue({
      usage: null,
      isLoading: true,
      isStale: false,
      error: null,
      refetch: vi.fn(),
    });
    renderBody();

    expect(screen.getByRole("status")).toBeVisible();
  });

  it("says nothing is stale once the answer has arrived", () => {
    useUsageStatsMock.mockReturnValue({
      usage: USAGE,
      isLoading: false,
      isStale: false,
      error: null,
      refetch: vi.fn(),
    });
    renderBody();

    expect(screen.getByText("40").parentElement).not.toHaveAttribute("aria-busy");
  });
});
