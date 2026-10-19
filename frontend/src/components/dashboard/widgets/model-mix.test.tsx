import { render, screen } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { ModelMixWidget } from "./model-mix";
import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import type { UsageStats } from "@/types/stats";

const useUsageStatsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useUsageStats: (...args: unknown[]) => useUsageStatsMock(...args),
}));

const PERIOD: Period = { preset: "30d", from: "2026-09-16", to: "2026-10-16" };

function renderWidget(byModel: UsageStats["by_model"]) {
  useUsageStatsMock.mockReturnValue({
    usage: { total_runs: 12, by_model: byModel } as UsageStats,
    isLoading: false,
    isStale: false,
    error: null,
    refetch: vi.fn(),
  });
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TooltipProvider>
        <ModelMixWidget title="Models" hint="" period={PERIOD} />
      </TooltipProvider>
    </NextIntlClientProvider>,
  );
}

describe("ModelMixWidget", () => {
  it("says how many tool calls a model needed repaired, beside its name (#2105)", () => {
    renderWidget([
      { model_label: "qwen3:32b", provider: "ollama", runs: 9, tool_args_repaired: 4 },
      { model_label: "claude-sonnet-5-5", provider: "anthropic", runs: 3, tool_args_repaired: 0 },
    ]);

    expect(screen.getByText("qwen3:32b · 4 repaired")).toBeInTheDocument();
    expect(screen.getByText("claude-sonnet-5-5")).toBeInTheDocument();
  });
});

describe("ModelMixWidget as a donut", () => {
  it("keeps the repair count in the legend, where the donut puts the names", () => {
    useUsageStatsMock.mockReturnValue({
      usage: {
        total_runs: 9,
        by_model: [{ model_label: "qwen3:32b", provider: null, runs: 9, tool_args_repaired: 4 }],
      } as UsageStats,
      isLoading: false,
      isStale: false,
      error: null,
      refetch: vi.fn(),
    });
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <TooltipProvider>
          <ModelMixWidget title="Models" hint="" period={PERIOD} options={{ style: "donut" }} />
        </TooltipProvider>
      </NextIntlClientProvider>,
    );
    expect(screen.getByText("qwen3:32b · 4 repaired")).toBeInTheDocument();
  });
});
