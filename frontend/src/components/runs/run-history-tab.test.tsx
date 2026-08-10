import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { RunHistoryTab } from "./run-history-tab";
import type { AgentRun } from "@/types/runs";

/**
 * The sort, the window and the "slow runs" preset - the controls #210 adds.
 *
 * All three are the server's over the whole narrowed set, so the assertion is on
 * the options `useRuns` is called with rather than on which rows come back: a
 * duration sort applied over one page of twenty-five sorts the wrong set, and a
 * test reading rows off the page would pass just as happily when it did.
 */

const useRunsMock = vi.fn();
vi.mock("@/hooks", () => ({
  useRuns: (agentId?: string, options?: unknown) => useRunsMock(agentId, options),
  // Imported by FocusedRun, which never renders on the list path exercised here.
  useRun: () => ({ run: undefined, isLoading: false, error: null }),
  useDelegatedRuns: () => ({ runs: [], total: 0, isLoading: false }),
}));

function aRun(): AgentRun {
  return {
    id: "run-1",
    agent_id: "agent-1",
    agent_version_id: "version-1",
    user_id: "user-1",
    surface: "web",
    status: "completed",
    model_label: "openai · gpt-5",
    input_tokens: 1000,
    output_tokens: 100,
    cost_usd: "1.000000",
    cost_is_partial: false,
    logfire_trace_id: null,
    error: null,
    started_at: "2026-08-04T09:00:00Z",
    ended_at: "2026-08-04T09:00:30Z",
    parent_run_id: null,
    subagent_task_id: null,
  };
}

function renderTab(props: Partial<Parameters<typeof RunHistoryTab>[0]> = {}) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RunHistoryTab agentId={null} focusedRunId={null} {...props} />
    </NextIntlClientProvider>,
  );
}

/** The options the most recent `useRuns` call asked with. */
function lastOptions() {
  return useRunsMock.mock.calls.at(-1)?.[1];
}

const tookHeader = () => screen.getByText("Took").closest("button")!;
const startedHeader = () => screen.getByText("Started").closest("button")!;

beforeEach(() => {
  useRunsMock.mockReset();
  useRunsMock.mockReturnValue({
    runs: [aRun()],
    total: 1,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
  });
});

describe("run history controls", () => {
  it("opens on the feed - newest first, unfiltered", () => {
    renderTab();

    expect(lastOptions()).toEqual({
      startedFrom: undefined,
      startedTo: undefined,
      orderBy: "started_at",
      descending: true,
      tookOverMs: undefined,
    });
  });

  it("opens sorted by duration when the dashboard's p95 link asks for it", () => {
    renderTab({ initialDurationSort: true });

    expect(lastOptions()).toMatchObject({ orderBy: "duration", descending: true });
  });

  it("carries the p95 link's window through to the query", () => {
    renderTab({
      startedFrom: "2026-08-01T00:00:00.000Z",
      startedTo: "2026-08-31T23:59:59.999Z",
    });

    expect(lastOptions()).toMatchObject({
      startedFrom: "2026-08-01T00:00:00.000Z",
      startedTo: "2026-08-31T23:59:59.999Z",
    });
  });

  it("the slow-runs view sorts by duration over a threshold", async () => {
    renderTab();

    await userEvent.click(screen.getByRole("button", { name: "Slow runs" }));

    expect(lastOptions()).toMatchObject({
      orderBy: "duration",
      descending: true,
      tookOverMs: 30_000,
    });
    expect(screen.getByRole("button", { name: "Slow runs" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("the all-runs view returns to the feed and drops the threshold", async () => {
    renderTab();

    await userEvent.click(screen.getByRole("button", { name: "Slow runs" }));
    await userEvent.click(screen.getByRole("button", { name: "All runs" }));

    expect(lastOptions()).toMatchObject({
      orderBy: "started_at",
      descending: true,
      tookOverMs: undefined,
    });
    expect(screen.getByRole("button", { name: "All runs" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("the Took header flips the duration sort each time it is used", async () => {
    renderTab();

    await userEvent.click(tookHeader());
    expect(lastOptions()).toMatchObject({ orderBy: "duration", descending: true });

    await userEvent.click(tookHeader());
    expect(lastOptions()).toMatchObject({ orderBy: "duration", descending: false });

    await userEvent.click(tookHeader());
    expect(lastOptions()).toMatchObject({ orderBy: "duration", descending: true });
  });

  it("the Started header reverses the feed without leaving it", async () => {
    renderTab();

    await userEvent.click(startedHeader());

    expect(lastOptions()).toMatchObject({ orderBy: "started_at", descending: false });
  });
});
