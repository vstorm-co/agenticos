import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TooltipProvider } from "@/components/ui";
import { useVoiceUsage } from "@/hooks/use-voice-usage";
import { resolvePreset, type Period } from "@/lib/dashboard/period";
import type { VoiceUsage } from "@/types/voice";
import { VoiceMinutesWidget } from "./voice-minutes";

vi.mock("@/hooks/use-voice-usage", () => ({ useVoiceUsage: vi.fn() }));

const PERIOD: Period = { preset: "30d", from: "2026-08-23", to: "2026-09-22" };

function usage(overrides: Partial<VoiceUsage> = {}): VoiceUsage {
  return {
    start: "2026-08-23T00:00:00.000Z",
    end: "2026-09-22T23:59:59.999Z",
    seconds: 720,
    calls: 4,
    month_seconds: 900,
    monthly_minutes: 600,
    by_agent: [
      { agent_id: "a", agent_name: "Support", seconds: 600, calls: 3 },
      { agent_id: "b", agent_name: "Sales", seconds: 60, calls: 1 },
      { agent_id: "c", agent_name: "Billing", seconds: 40, calls: 1 },
      { agent_id: "d", agent_name: "Onboarding", seconds: 20, calls: 1 },
    ],
    ...overrides,
  };
}

function answer(value: Partial<ReturnType<typeof useVoiceUsage>>) {
  vi.mocked(useVoiceUsage).mockReturnValue({
    usage: null,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...value,
  });
}

function widget(period: Period = PERIOD) {
  return render(
    <TooltipProvider>
      <VoiceMinutesWidget title="Voice minutes" hint="" period={period} />
    </TooltipProvider>,
  );
}

describe("VoiceMinutesWidget", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows the period's minutes, the calls and the month against the limit", () => {
    answer({ usage: usage() });
    widget();
    expect(useVoiceUsage).toHaveBeenCalledWith(
      { start: "2026-08-23T00:00:00.000Z", end: "2026-09-22T23:59:59.999Z" },
      { enabled: true },
    );
    expect(screen.getByText("12 min")).toBeInTheDocument();
    expect(screen.getByText("4 calls")).toBeInTheDocument();
    const meter = screen.getByRole("meter", { name: "Call minutes this month" });
    expect(meter).toHaveAttribute("aria-valuenow", "15");
    expect(meter).toHaveAttribute("aria-valuemax", "600");
    expect(screen.getByText("Support")).toBeInTheDocument();
    // The top three agents; the rest are a click away.
    expect(screen.getByText("Billing")).toBeInTheDocument();
    expect(screen.queryByText("Onboarding")).toBeNull();
  });

  it.each([
    // Seven days including today: from six days back, to the end of today.
    ["7d", resolvePreset("7d", new Date("2026-09-22T10:00:00Z")), "2026-09-16", "2026-09-22"],
    // Last month is a closed window, not "the last N days" counted from now.
    ["lm", resolvePreset("lm", new Date("2026-09-22T10:00:00Z")), "2026-08-01", "2026-08-31"],
    [
      "a custom past range",
      { preset: "custom", from: "2026-05-04", to: "2026-05-10" } as Period,
      "2026-05-04",
      "2026-05-10",
    ],
  ])("asks for %s by its first and last instant", (_name, period, from, to) => {
    answer({ usage: usage() });
    widget(period);
    expect(useVoiceUsage).toHaveBeenCalledWith(
      { start: `${from}T00:00:00.000Z`, end: `${to}T23:59:59.999Z` },
      { enabled: true },
    );
  });

  it("names a deleted agent's calls, and links the others to their calls in Activity", () => {
    answer({
      usage: usage({
        by_agent: [
          { agent_id: null, agent_name: null, seconds: 600, calls: 2 },
          { agent_id: "a", agent_name: "Support", seconds: 120, calls: 2 },
        ],
      }),
    });
    widget();
    expect(screen.getByText("Deleted agent")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Deleted agent/ })).toBeNull();
    const support = screen.getByRole("link", { name: /Support/ });
    expect(support.getAttribute("href")).toContain("modality=voice");
    expect(support.getAttribute("href")).toContain("agent=a");
    expect(screen.getByRole("link", { name: /see all/i }).getAttribute("href")).toContain(
      "modality=voice",
    );
  });

  it("colours a nearly spent month as a warning, and a spent one as a stop", () => {
    answer({ usage: usage({ month_seconds: 450 * 60 }) });
    const { unmount } = widget();
    expect(
      screen.getByRole("meter", { name: "Call minutes this month" }).firstElementChild,
    ).toHaveClass("bg-warning");
    unmount();
    answer({ usage: usage({ month_seconds: 700 * 60 }) });
    widget();
    const meter = screen.getByRole("meter", { name: "Call minutes this month" });
    expect(meter.firstElementChild).toHaveClass("bg-destructive");
    expect(meter.firstElementChild).toHaveStyle({ width: "100%" });
  });

  it("states the month alone when only budgets bound calls", () => {
    answer({ usage: usage({ monthly_minutes: null, by_agent: [] }) });
    widget();
    expect(screen.queryByRole("meter")).toBeNull();
    expect(screen.getByText("This month: 15 min · no monthly limit")).toBeInTheDocument();
  });

  it("says so when nobody called", () => {
    answer({ usage: usage({ seconds: 0, calls: 0, month_seconds: 0, by_agent: [] }) });
    widget();
    expect(screen.getByText("No voice calls yet")).toBeInTheDocument();
  });

  it("still shows the month when the period itself was quiet", () => {
    answer({ usage: usage({ seconds: 0, calls: 0, by_agent: [] }) });
    widget();
    expect(screen.getByText("0 calls")).toBeInTheDocument();
    expect(screen.getByRole("meter", { name: "Call minutes this month" })).toHaveAttribute(
      "aria-valuenow",
      "15",
    );
  });

  it("shows a skeleton while loading", () => {
    answer({ isLoading: true });
    widget();
    expect(screen.queryByText("No voice calls yet")).toBeNull();
    expect(screen.queryByRole("meter")).toBeNull();
  });

  it("offers a retry when the read failed", async () => {
    const refetch = vi.fn();
    answer({ error: new Error("502"), refetch });
    widget();
    await userEvent.click(screen.getByRole("button", { name: /retry/i }));
    expect(refetch).toHaveBeenCalled();
  });
});
