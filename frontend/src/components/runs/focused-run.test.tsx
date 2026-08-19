import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { FocusedRun } from "./focused-run";
import { ApiError } from "@/lib/api-client";
import type { AgentRun } from "@/types/runs";

/**
 * Stepping through a conversation, and the two things that make it readable.
 *
 * **What is on screen is the answer being held.** Each run is a query key of its
 * own, so the detail view keeps the previous row while the next is in flight
 * rather than dropping to a skeleton on every arrow press. That has one
 * consequence worth a test each: nothing may *navigate* from a held row - its
 * neighbours are its own, so an arrow pressed twice quickly would walk back to
 * where it started - and a failure for the run in the URL must not be drawn as
 * the run that is still on screen.
 *
 * The arrow keys do what the arrow buttons do, because reading a bad afternoon
 * is a sequence of runs and reaching for the mouse between each of them is the
 * friction this view exists to remove.
 */

const useRunMock = vi.fn();
const prefetched = vi.fn();
vi.mock("@/hooks", () => ({
  useRun: (runId: string) => useRunMock(runId),
  useDelegatedRuns: () => ({ runs: [], total: 0, isLoading: false }),
  usePermissions: () => ({ can: () => true, isLoading: false }),
  usePrefetchRuns: (ids: unknown[]) => prefetched(ids),
  useResumeRun: () => ({ mutate: vi.fn(), isPending: false }),
  useAgent: () => ({ agent: undefined }),
}));
vi.mock("@/components/runs/run-timeline", () => ({
  RunTimeline: ({ runId }: { runId: string }) => <div data-testid="timeline">{runId}</div>,
}));
vi.mock("@/stores", () => ({ useAuthStore: () => null }));

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "run-2",
    agent_id: "agent-1",
    agent_version_id: null,
    user_id: null,
    surface: "web",
    status: "completed",
    model_label: "claude-sonnet-4-5",
    provider: "anthropic",
    input_tokens: 1200,
    output_tokens: 340,
    cost_usd: "0.0182",
    cost_is_partial: false,
    logfire_trace_id: null,
    prev_run_id: "run-1",
    next_run_id: "run-3",
    error: null,
    down_rated: false,
    conversation_id: "conv-1",
    started_at: "2026-08-14T09:00:00Z",
    ended_at: "2026-08-14T09:00:04Z",
    parent_run_id: null,
    subagent_task_id: null,
    ...overrides,
  };
}

function serve(answer: { run?: AgentRun; isLoading?: boolean; error?: unknown }) {
  useRunMock.mockReturnValue({
    run: answer.run,
    isLoading: answer.isLoading ?? false,
    error: answer.error ?? null,
  });
}

function renderRun(runId = "run-2", onFocusRun = vi.fn()) {
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <FocusedRun runId={runId} onFocusRun={onFocusRun} />
    </NextIntlClientProvider>,
  );
  return onFocusRun;
}

beforeEach(() => {
  useRunMock.mockReset();
  prefetched.mockReset();
});

describe("stepping to a neighbour", () => {
  it("warms both neighbours on arrival, so the step is a cache hit", () => {
    serve({ run: run() });

    renderRun();

    expect(prefetched).toHaveBeenCalledWith(["run-1", "run-3"]);
  });

  it("steps with the arrow keys, not only with the buttons", async () => {
    serve({ run: run() });
    const onFocusRun = renderRun();

    await userEvent.keyboard("{ArrowRight}");
    expect(onFocusRun).toHaveBeenCalledWith("run-3");

    await userEvent.keyboard("{ArrowLeft}");
    expect(onFocusRun).toHaveBeenCalledWith("run-1");
  });

  it("leaves a modified arrow to the browser", async () => {
    serve({ run: run() });
    const onFocusRun = renderRun();

    await userEvent.keyboard("{Meta>}{ArrowLeft}{/Meta}");

    expect(onFocusRun).not.toHaveBeenCalled();
  });

  it("does not step while somebody is typing", async () => {
    serve({ run: run() });
    const onFocusRun = renderRun();
    render(<input aria-label="filter" />);

    await userEvent.click(screen.getByLabelText("filter"));
    await userEvent.keyboard("{ArrowLeft}");

    expect(onFocusRun).not.toHaveBeenCalled();
  });

  it("offers a way out only to a surface that has one", async () => {
    // The panel passes a dismissal; a page that *is* the run detail does not,
    // and a close button that closes nothing is worse than none.
    serve({ run: run() });
    renderRun();
    expect(screen.queryByLabelText("Close the run detail")).toBeNull();

    const closed = vi.fn();
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <FocusedRun runId="run-2" onFocusRun={vi.fn()} onClose={closed} />
      </NextIntlClientProvider>,
    );
    await userEvent.click(screen.getByLabelText("Close the run detail"));

    expect(closed).toHaveBeenCalled();
  });

  it("disables both arrows at the edges of the thread", () => {
    serve({ run: run({ prev_run_id: null, next_run_id: null }) });

    renderRun();

    expect(screen.getByLabelText("Previous run")).toBeDisabled();
    expect(screen.getByLabelText("Next run")).toBeDisabled();
  });
});

describe("the row being held while the next one loads", () => {
  it("refuses to navigate from a neighbour it is only holding", async () => {
    // The answer on screen is `run-2`; the URL already says `run-3`. Its
    // `prev_run_id` points back at where the reader just came from, so acting on
    // it would undo the step somebody just made.
    serve({ run: run() });
    const onFocusRun = renderRun("run-3");

    expect(screen.getByLabelText("Previous run")).toBeDisabled();
    expect(screen.getByLabelText("Next run")).toBeDisabled();
    await userEvent.keyboard("{ArrowLeft}");
    expect(onFocusRun).not.toHaveBeenCalled();
    // And says so, rather than presenting a stale row as the answer.
    expect(screen.getByTestId("timeline").closest("[aria-busy]")).toHaveAttribute(
      "aria-busy",
      "true",
    );
  });

  it("draws the refusal for the run asked for, not the row still on screen", () => {
    serve({ run: run(), error: new ApiError(404, "gone", undefined) });

    renderRun("run-3");

    expect(screen.getByText("No such run")).toBeVisible();
    expect(screen.queryByText("claude-sonnet-4-5")).toBeNull();
  });

  it("separates a run that is gone from a request that failed", () => {
    serve({ error: new Error("502") });

    renderRun();

    expect(screen.getByText("That run could not be read")).toBeVisible();
  });

  it("waits with a skeleton only when it is holding nothing at all", () => {
    serve({ isLoading: true });

    renderRun();

    expect(screen.queryByTestId("timeline")).toBeNull();
  });
});
