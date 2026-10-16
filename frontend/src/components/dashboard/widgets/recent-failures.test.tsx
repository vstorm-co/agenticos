import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import type { Period } from "@/lib/dashboard/period";
import { RecentFailuresWidget } from "./recent-failures";

/**
 * Runs that went wrong, grouped by agent and by what went wrong.
 *
 * What is pinned is the grouping and how it is said: the same failure five
 * times is one row whose line says "5 times" in words, beside the reason -
 * not a red pill shouting over the agent's name.
 */

const useRecentFailuresMock = vi.fn();

vi.mock("@/hooks", () => ({
  useRecentFailures: (...args: unknown[]) => useRecentFailuresMock(...args),
  useAgents: () => ({
    agents: [{ id: "a-1", name: "Browser check", slug: "browser-check", has_avatar: false }],
  }),
}));

const PERIOD: Period = { preset: "30d", from: "2026-07-19", to: "2026-08-18" };
const CONNECT = "The run did not finish (ConnectError) - retry it, and check the service";

function failure(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    agent_id: "a-1",
    status: "failed",
    error: CONNECT,
    started_at: null,
    ...overrides,
  };
}

function renderWidget(state: Record<string, unknown>) {
  useRecentFailuresMock.mockReturnValue({
    failures: [],
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    ...state,
  });
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TooltipProvider>
        <RecentFailuresWidget title="Recent failures" hint="" period={PERIOD} />
      </TooltipProvider>
    </NextIntlClientProvider>,
  );
}

beforeEach(() => useRecentFailuresMock.mockReset());

describe("the recent failures widget", () => {
  it("says a repeated failure once, with how many times in words", () => {
    renderWidget({ failures: [failure("r-1"), failure("r-2"), failure("r-3"), failure("r-4")] });

    expect(screen.getAllByText("Browser check")).toHaveLength(1);
    expect(screen.getByText(/The run did not finish \(ConnectError\) · 4 times/)).toBeVisible();
    expect(screen.queryByText(/×/)).toBeNull();
  });

  it("keeps a single failure free of a count, and names a budget stop", () => {
    renderWidget({
      failures: [
        failure("r-1", { started_at: new Date().toISOString() }),
        failure("r-2", { status: "budget_exceeded", error: null }),
      ],
    });

    expect(screen.queryByText(/times/)).toBeNull();
    expect(
      screen.getByText(messages.dashboard.widgets["recent-failures"].budgetExceeded),
    ).toBeVisible();
  });

  it("reads a run with no message as failed, and an unknown agent by default", () => {
    renderWidget({ failures: [failure("r-1", { agent_id: "gone", error: null })] });

    expect(
      screen.getByText(messages.dashboard.widgets["recent-failures"].unknownAgent),
    ).toBeVisible();
    expect(screen.getByText(messages.dashboard.widgets["recent-failures"].failed)).toBeVisible();
  });

  it("asks again when the list did not load", async () => {
    const refetch = vi.fn();
    renderWidget({ error: new Error("boom"), refetch });

    await userEvent.click(screen.getByRole("button", { name: /retry|try again/i }));

    expect(refetch).toHaveBeenCalledOnce();
  });

  it("says nothing failed when nothing did", () => {
    renderWidget({});
    expect(
      screen.getByText(messages.dashboard.widgets["recent-failures"].empty.title),
    ).toBeVisible();
  });

  it("shows a skeleton while loading", () => {
    renderWidget({ isLoading: true });
    expect(screen.queryByText("Browser check")).toBeNull();
  });
});
