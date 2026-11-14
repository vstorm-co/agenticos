import { render, screen, within } from "@testing-library/react";
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
const useResumeRunMock = vi.fn();
const useRetryRunMock = vi.fn();
vi.mock("@/hooks", () => ({
  useRun: (runId: string) => useRunMock(runId),
  useDelegatedRuns: () => ({ runs: [], total: 0, isLoading: false }),
  usePermissions: () => ({ can: () => true, isLoading: false }),
  usePrefetchRuns: (ids: unknown[]) => prefetched(ids),
  useResumeRun: (options?: unknown) => useResumeRunMock(options),
  useRetryRun: (options?: unknown) => useRetryRunMock(options),
  useAgent: () => ({ agent: undefined }),
}));
vi.mock("@/components/runs/run-timeline", () => ({
  RunTimeline: ({ runId }: { runId: string }) => <div data-testid="timeline">{runId}</div>,
}));
// The second tab reads the manifest, which is `run-manifest-panel`'s subject
// rather than this file's - and a tab that renders is a tab whose queries run,
// which the arrow-key tests reach by moving focus along the strip.
vi.mock("@/components/runs/run-manifest", () => ({
  RunManifest: () => <div data-testid="manifest" />,
}));
// The viewer, so the starter-only controls can tell their run from another
// person's. The fixture's runs belong to nobody by default, which reads as
// "not mine" for every control gated on it. The selector is honoured rather
// than answered with a bare id, because the component asks for the id through
// it.
vi.mock("@/stores", () => ({
  useAuthStore: (selector: (state: { user: { id: string } | null }) => unknown) =>
    selector({ user: { id: "user-1" } }),
}));
const datasets = vi.hoisted(() => ({ runnable: false }));
vi.mock("@/hooks/use-eval-runs", () => ({
  useRunsADataset: () => datasets.runnable,
}));

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
    fallback_used: false,
    serving_model: null,
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
    retry_of_run_id: null,
    subagent_task_id: null,
    modality: "text",
    voice_chain: null,
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
  datasets.runnable = false;
  useResumeRunMock.mockReset();
  useResumeRunMock.mockReturnValue({ mutate: vi.fn(), isPending: false });
  useRetryRunMock.mockReset();
  useRetryRunMock.mockReturnValue({ mutate: vi.fn(), isPending: false });
});

describe("stepping to a neighbour", () => {
  it("tells the resume a run outside any chat does not continue in one", () => {
    serve({ run: run() });
    renderRun();
    expect(useResumeRunMock).toHaveBeenCalledWith({ continuesInChat: false });
  });

  it("passes whether the run continues in its chat to the resume", () => {
    serve({ run: run({ continues_in_chat: true }) });
    renderRun();
    expect(useResumeRunMock).toHaveBeenCalledWith({ continuesInChat: true });
  });

  it("says when the run repaired malformed tool arguments, and only then (#2105)", () => {
    serve({ run: run({ tool_args_repaired: 2 }) });
    renderRun();
    expect(
      screen.getByText("Repaired 2 tool calls' malformed arguments instead of retrying them"),
    ).toBeInTheDocument();
  });

  it("names the skills the run used, each at its version and linked to the skill", () => {
    serve({
      run: run({
        skills_used: [
          { skill_id: "k1", name: "returns", version: 2, fork: null, loaded: true },
          { skill_id: "k2", name: "prints", version: 1, fork: "Shop", loaded: true },
          { skill_id: "k3", name: "legacy", version: null, fork: null, loaded: false },
        ],
      }),
    });
    renderRun();

    expect(screen.getByText("Skills used:")).toBeVisible();
    expect(screen.getByRole("link", { name: "returns · v2" })).toHaveAttribute(
      "href",
      "/skills/k1",
    );
    expect(screen.getByRole("link", { name: "prints · Shop v1" })).toBeVisible();
    expect(screen.getByRole("link", { name: "legacy" })).toBeVisible();
  });

  it("says nothing about repairs for a run that needed none", () => {
    serve({ run: run() });
    renderRun();
    expect(screen.queryByText(/malformed arguments/)).toBeNull();
  });

  it("says why a failed run stopped, in the run's own words", () => {
    serve({
      run: run({
        status: "failed",
        error: "The run did not finish (ModelHTTPError, HTTP 400)",
      }),
    });
    renderRun();
    // The label and the sentence are separate spans, so each is read on its
    // own rather than as one string.
    expect(screen.getByText(/Why it stopped/)).toBeInTheDocument();
    expect(
      screen.getByText("The run did not finish (ModelHTTPError, HTTP 400)"),
    ).toBeInTheDocument();
  });

  it("says why a budget stop stopped it, not only that it did", () => {
    serve({ run: run({ status: "budget_exceeded", error: "Monthly budget reached" }) });
    renderRun();
    expect(screen.getByText(/Why it stopped/)).toBeInTheDocument();
    expect(screen.getByText("Monthly budget reached")).toBeInTheDocument();
  });

  it("says nothing about why when the run has no error to explain", () => {
    serve({ run: run({ status: "failed" }) });
    renderRun();
    expect(screen.queryByText(/Why it stopped/)).toBeNull();
  });

  it("does not draw a held error as the live run's reason", () => {
    serve({ run: run({ status: "running", error: "The run did not finish" }) });
    renderRun();
    expect(screen.queryByText(/Why it stopped/)).toBeNull();
  });

  it("offers a retry on a failed run the viewer started", () => {
    serve({ run: run({ status: "failed", user_id: "user-1" }) });
    renderRun();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("offers a retry on a timed-out run the viewer started", () => {
    serve({ run: run({ status: "timed_out", user_id: "user-1" }) });
    renderRun();
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("opens the original run from a retry", async () => {
    serve({ run: run({ retry_of_run_id: "run-1" }) });
    const onFocusRun = renderRun();

    await userEvent.click(screen.getByRole("button", { name: "Open the run it came from" }));

    expect(onFocusRun).toHaveBeenCalledWith("run-1");
  });

  it("offers no retry on a run somebody else started", () => {
    serve({ run: run({ status: "failed", user_id: "user-2" }) });
    renderRun();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("offers no retry while the run is still going", () => {
    serve({ run: run({ status: "running", user_id: "user-1" }) });
    renderRun();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("offers no retry on a parked run - that one resumes", () => {
    serve({ run: run({ status: "awaiting_approval", user_id: "user-1" }) });
    renderRun();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("offers no retry on a run with no conversation to retry from", () => {
    serve({ run: run({ status: "failed", user_id: "user-1", conversation_id: null }) });
    renderRun();
    expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  });

  it("retries the run on screen, and steps to the new run", async () => {
    const mutate = vi.fn();
    useRetryRunMock.mockReturnValue({ mutate, isPending: false });
    serve({ run: run({ status: "failed", user_id: "user-1" }) });
    const onFocusRun = renderRun();

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    expect(mutate).toHaveBeenCalledWith("run-2");
    const options = useRetryRunMock.mock.calls[0]![0] as {
      onRetried: (runId: string) => void;
    };
    options.onRetried("run-9");
    expect(onFocusRun).toHaveBeenCalledWith("run-9");
  });

  it("says when a fallback served the run, and which model answered", () => {
    serve({ run: run({ fallback_used: true, serving_model: "gpt-5" }) });
    renderRun();
    expect(screen.getByText("Served by gpt-5 (fallback)")).toBeInTheDocument();
  });

  it("says nothing about a fallback for a run its primary served", () => {
    serve({ run: run() });
    renderRun();
    expect(screen.queryByText(/fallback/)).toBeNull();
  });

  it("names the primary profile when no serving model was recorded", () => {
    serve({ run: run({ fallback_used: true, serving_model: null }) });
    renderRun();
    expect(screen.getByText("Served by claude-sonnet-4-5 (fallback)")).toBeInTheDocument();
  });

  it("says how much of the input the cache served, when it did (#2170)", () => {
    serve({ run: run({ cache_read_tokens: 900, cache_write_tokens: 100 }) });
    renderRun();
    expect(
      screen.getByText(/900 read from the provider's cache and 100 written to it/),
    ).toBeVisible();
  });

  it.each([
    { read: 90, write: undefined, text: "90 read from the provider's cache and 0 written to it" },
    { read: undefined, write: 12, text: "0 read from the provider's cache and 12 written to it" },
  ])(
    "does not invent a missing cache counter ($read read, $write written)",
    ({ read, write, text }) => {
      serve({ run: run({ cache_read_tokens: read, cache_write_tokens: write }) });
      renderRun();
      expect(screen.getByText(new RegExp(text))).toBeInTheDocument();
    },
  );

  it("admits a fallback whose serving model and original label are unavailable", () => {
    serve({ run: run({ fallback_used: true, serving_model: null, model_label: null }) });
    renderRun();
    expect(screen.getByText("Served by - (fallback)")).toBeInTheDocument();
  });

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

  it("leaves the tab strip's own arrows to the tab strip", async () => {
    // ArrowLeft and ArrowRight are how Radix moves between Timeline and Input, and
    // a window listener sits above them - so moving between tabs also stepped
    // between runs, which took the tab strip with it.
    serve({ run: run() });
    const onFocusRun = renderRun();

    await userEvent.click(screen.getByRole("tab", { name: "Timeline" }));
    await userEvent.keyboard("{ArrowRight}");

    expect(onFocusRun).not.toHaveBeenCalled();
  });

  it("leaves an arrow a focused control already answered", async () => {
    // `defaultPrevented` is the general form of the rule above: a component that
    // has handled the key has handled it, whatever the component is.
    serve({ run: run() });
    const onFocusRun = renderRun();
    render(
      <div
        aria-label="slider"
        role="slider"
        aria-valuenow={1}
        tabIndex={0}
        onKeyDown={(event) => event.preventDefault()}
      />,
    );

    await userEvent.click(screen.getByLabelText("slider"));
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

describe("an eval run", () => {
  it("names the case it answered and opens the eval run, not an empty transcript", () => {
    serve({
      run: run({
        surface: "eval",
        eval_case: {
          eval_run_id: "eval-1",
          agent_id: "agent-9",
          case_id: "case-1",
          dataset_name: "refunds",
          case_input: "Can I return it?",
          graded: false,
        },
      }),
    });
    renderRun();
    expect(
      screen.getByRole("link", { name: "Eval case: refunds · Can I return it?" }),
    ).toHaveAttribute("href", "/agents/agent-9/evals/eval-1?case=case-1");
    expect(screen.getByText("A case from an eval run")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the eval run" })).toHaveAttribute(
      "href",
      "/agents/agent-9/evals/eval-1?case=case-1",
    );
    expect(screen.queryByTestId("timeline")).toBeNull();
  });

  it("says a judge's run graded an eval case, and opens the eval run", () => {
    serve({
      run: run({
        surface: "eval",
        eval_case: {
          eval_run_id: "eval-1",
          agent_id: "agent-9",
          case_id: "case-1",
          dataset_name: "refunds",
          case_input: "Can I return it?",
          graded: true,
        },
      }),
    });
    renderRun();
    expect(
      screen.getByRole("link", { name: "Grading an eval case: refunds · Can I return it?" }),
    ).toHaveAttribute("href", "/agents/agent-9/evals/eval-1?case=case-1");
    expect(screen.getByText("The judge grading a case of an eval run")).toBeInTheDocument();
  });

  it("links no eval run it cannot name - a judge has no evals of its own to point at", () => {
    serve({ run: run({ surface: "eval" }) });
    renderRun();
    expect(screen.queryByRole("link", { name: /eval/i })).toBeNull();
  });
});

describe("a voice call in focus", () => {
  it("says it was a call beside its surface", () => {
    serve({ run: run({ modality: "voice" }) });
    renderRun();
    expect(screen.getByText("Voice call")).toHaveClass("sr-only");
  });
});

describe("the header a run opens on", () => {
  it("steps up to the run a delegation came from, and out to its trace", async () => {
    serve({
      run: run({
        parent_run_id: "run-0",
        logfire_url: "https://logfire.example/trace/abc",
      } as Partial<AgentRun>),
    });
    const onFocusRun = renderRun();

    expect(screen.getByRole("link", { name: /Logfire/ })).toHaveAttribute(
      "href",
      "https://logfire.example/trace/abc",
    );
    await userEvent.click(screen.getByRole("button", { name: /run it came from/i }));

    expect(onFocusRun).toHaveBeenCalledWith("run-0");
  });

  it("says what it does not know rather than inventing it", () => {
    // A run with no model resolved and no start recorded: a dash for the model,
    // no age, and a cost marked as partial.
    serve({
      run: run({ provider: null, model_label: null, started_at: null, cost_is_partial: true }),
    });
    renderRun();

    expect(screen.getAllByText("-").length).toBeGreaterThan(0);
    expect(screen.getByTitle(/no price/i)).toHaveTextContent("+");
    expect(screen.queryByText(/ago$/)).toBeNull();
  });
});

describe("a run parked on a question", () => {
  it("shows the unanswered questions and how long is left to answer them", () => {
    serve({
      run: run({
        status: "awaiting_answer",
        waiting_questions: ["Which model should I use?", "And the budget?"],
        waiting_expires_at: new Date(Date.now() + 25 * 60 * 60 * 1000).toISOString(),
      }),
    });
    renderRun();

    expect(screen.getByRole("region", { name: "Waiting on you" })).toBeVisible();
    expect(screen.getByText("Which model should I use?")).toBeVisible();
    expect(screen.getByText("And the budget?")).toBeVisible();
    expect(screen.getByText(/Expires in 1 d/)).toBeVisible();
  });

  it("names every requested secret even when no ordinary question is pending", () => {
    serve({
      run: run({
        status: "awaiting_answer",
        waiting_secret_requests: ["Vendor API key", "Calendar token"],
        waiting_expires_at: null,
      }),
    });
    renderRun();
    const waiting = screen.getByRole("region", { name: "Waiting on you" });
    expect(within(waiting).getAllByRole("listitem")).toHaveLength(2);
    expect(within(waiting).getByText("Needs secret: Vendor API key")).toBeVisible();
    expect(within(waiting).getByText("Needs secret: Calendar token")).toBeVisible();
    expect(within(waiting).queryByText(/Expires in/)).not.toBeInTheDocument();
  });

  it("does not display an empty waiting section while pending details are absent", () => {
    serve({
      run: run({ status: "awaiting_answer", waiting_questions: [], waiting_secret_requests: [] }),
    });
    renderRun();
    expect(screen.queryByRole("region", { name: "Waiting on you" })).not.toBeInTheDocument();
  });

  it("shows no waiting section once the run has finished", () => {
    serve({ run: run({ status: "completed" }) });
    renderRun();

    expect(screen.queryByRole("region", { name: "Waiting on you" })).toBeNull();
  });
});

describe("scoring a run against a case", () => {
  it("is offered to who may run a dataset, whatever the role says", () => {
    datasets.runnable = true;
    serve({ run: run() });
    renderRun();

    expect(screen.getByRole("button", { name: "More actions for this run" })).toBeInTheDocument();
  });

  it("is not offered to who may run no dataset", () => {
    datasets.runnable = false;
    serve({ run: run() });
    renderRun();
    expect(screen.queryByRole("button", { name: "More actions for this run" })).toBeNull();
  });

  it("is not offered for a run with no transcript to score", () => {
    datasets.runnable = true;
    serve({ run: run({ conversation_id: null }) });
    renderRun();
    expect(screen.queryByRole("button", { name: "More actions for this run" })).toBeNull();
  });
});
