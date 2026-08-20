import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { SpendWidget } from "./spend";
import type { Period } from "@/lib/dashboard/period";
import type { CostBlock } from "@/types/stats";

/**
 * The headline is the whole bill; the caption underneath splits it into the
 * parts that spent. A part at zero is left off, so a deployment that only ran
 * models reads no split at all - and a search is reported as search, never
 * folded into indexing.
 */

const useUsageStatsMock = vi.fn();
const useSpendMock = vi.fn();
vi.mock("@/hooks", () => ({
  useUsageStats: (...args: unknown[]) => useUsageStatsMock(...args),
  useSpend: (...args: unknown[]) => useSpendMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-07", to: "2026-08-05" };

function withCost(cost: Partial<CostBlock>) {
  useUsageStatsMock.mockReturnValue({
    usage: { total_runs: 5, cost: { by_provider: [], ...cost } },
    isLoading: false,
    isStale: false,
    error: null,
    refetch: vi.fn(),
  });
  useSpendMock.mockReturnValue({ spend: null });
}

function renderWidget() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <SpendWidget title="Spend" hint="" period={PERIOD} />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  useUsageStatsMock.mockReset();
  useSpendMock.mockReset();
});

describe("the spend widget", () => {
  it("splits the bill into models, indexing and search when each spent", () => {
    withCost({
      period_usd: "2.60",
      previous_period_usd: "1.30",
      model_usd: "2.00",
      ingestion_usd: "0.50",
      retrieval_usd: "0.10",
    });
    renderWidget();

    expect(screen.getByText(/on models/)).toBeInTheDocument();
    expect(screen.getByText(/on indexing/)).toBeInTheDocument();
    expect(screen.getByText(/on search/)).toBeInTheDocument();
  });

  it("shows no split when only model requests spent", () => {
    withCost({
      period_usd: "2.00",
      previous_period_usd: "1.00",
      model_usd: "2.00",
      ingestion_usd: "0",
      retrieval_usd: "0",
    });
    renderWidget();

    expect(screen.queryByText(/on models/)).toBeNull();
    expect(screen.queryByText(/on indexing/)).toBeNull();
    expect(screen.queryByText(/on search/)).toBeNull();
  });

  it("reports search without indexing when a search spent but nothing was indexed", () => {
    withCost({
      period_usd: "2.10",
      previous_period_usd: "1.00",
      model_usd: "2.00",
      ingestion_usd: "0",
      retrieval_usd: "0.10",
    });
    renderWidget();

    expect(screen.getByText(/on models/)).toBeInTheDocument();
    expect(screen.queryByText(/on indexing/)).toBeNull();
    expect(screen.getByText(/on search/)).toBeInTheDocument();
  });
});
