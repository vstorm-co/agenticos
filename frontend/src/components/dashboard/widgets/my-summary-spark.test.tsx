import { render } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import type { UsageStats } from "@/types/stats";
import { MySummaryWidget } from "./my-summary";

const figures = vi.hoisted(
  () => [] as { label: string; sparkFormat?: (value: number) => string }[],
);
vi.mock("@/components/ui", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/ui")>()),
  Figure: (props: { label: string; sparkFormat?: (value: number) => string }) => {
    figures.push(props);
    return null;
  },
}));
vi.mock("@/hooks", () => ({
  useUsageStats: () => ({
    usage: { total_runs: 0, by_status: [], cost: { period_usd: "0" } } as unknown as UsageStats,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  }),
}));

it("reads the spend sparkline's points as dollars", () => {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <MySummaryWidget
        title="Your period"
        hint=""
        period={{ preset: "30d", from: "2026-09-14", to: "2026-10-13" }}
      />
    </NextIntlClientProvider>,
  );
  const spent = figures.find((figure) => figure.sparkFormat !== undefined);
  expect(spent?.sparkFormat?.(1234.5)).toBe("$1,234.50");
});
