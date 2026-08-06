import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunSummary } from "./run-summary";
import type { AgentRun } from "@/types/runs";

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: crypto.randomUUID(),
    agent_id: "agent-1",
    agent_version_id: "version-1",
    user_id: "user-1",
    surface: "web",
    status: "completed",
    model_label: "openai · gpt-5",
    input_tokens: 100,
    output_tokens: 50,
    cost_usd: "0.0100",
    cost_is_partial: false,
    logfire_trace_id: null,
    error: null,
    started_at: "2026-07-30T10:00:00Z",
    ended_at: "2026-07-30T10:00:05Z",
    parent_run_id: null,
    subagent_task_id: null,
    ...overrides,
  };
}

function figure(label: string) {
  // Each figure is a label above a value, so the value is read relative to its
  // own label rather than by position in the grid.
  return screen.getByText(label).parentElement as HTMLElement;
}

describe("the run summary", () => {
  it("answers 'is this agent working' before anything has to be read", () => {
    // The panel this replaced was ten rows of status, model and cost, with no
    // times and no totals - ten identical-looking rows do not answer the question
    // somebody opens the page for.
    render(<RunSummary agentId="agent-1" runs={[run(), run({ status: "failed" }), run()]} />);

    expect(within(figure("Runs")).getByText("3")).toBeInTheDocument();
    expect(within(figure("Failed")).getByText("1")).toBeInTheDocument();
  });

  it("sums what the window cost", () => {
    render(
      <RunSummary
        agentId="agent-1"
        runs={[run({ cost_usd: "1.2500" }), run({ cost_usd: "0.7500" })]}
      />,
    );

    expect(within(figure("Spent")).getByText("$2.00")).toBeInTheDocument();
  });

  it("marks a total that is only a floor", () => {
    // A run whose model had no price is recorded at zero, so the total under-
    // reports. Presenting it as exact is the one thing that would make the
    // figure worse than absent.
    render(<RunSummary agentId="agent-1" runs={[run({ cost_is_partial: true })]} />);

    expect(within(figure("Spent")).getByText("$0.01+")).toBeInTheDocument();
    expect(screen.getByText(/had no price/)).toBeInTheDocument();
  });

  it("does not claim the total is a floor when every run was priced", () => {
    render(<RunSummary agentId="agent-1" runs={[run(), run()]} />);

    expect(screen.queryByText(/had no price/)).toBeNull();
    expect(within(figure("Spent")).getByText("$0.02")).toBeInTheDocument();
  });

  it("hands off to Activity, filtered to this agent", () => {
    // A link to the whole organization's history would be a dead end dressed as
    // a filter.
    render(<RunSummary agentId="agent-42" runs={[run()]} />);

    expect(screen.getByRole("link", { name: /See every run in Activity/ })).toHaveAttribute(
      "href",
      "/runs?agent=agent-42",
    );
  });

  it("shows the most recent runs, not all of them", () => {
    // Five is the glance; the page behind the link is where a history is read.
    render(<RunSummary agentId="agent-1" runs={Array.from({ length: 9 }, () => run())} />);

    expect(screen.getAllByText("openai · gpt-5")).toHaveLength(5);
  });

  it("says what to do next when the agent has never run", () => {
    // Rather than an empty panel, which reads as a failed request.
    render(<RunSummary agentId="agent-1" runs={[]} />);

    expect(screen.getByText(/has not run yet/)).toBeInTheDocument();
    expect(screen.queryByText("Runs")).toBeNull();
  });

  it("leaves a dash where the run recorded no model", () => {
    // A run refused before a model request has no label, and a blank cell there
    // reads as a rendering fault rather than as "it never got that far".
    render(<RunSummary agentId="agent-1" runs={[run({ model_label: null })]} />);

    expect(screen.getByText("-")).toBeInTheDocument();
  });

  it("survives a run that never started", () => {
    // `started_at` is nullable, and a run that was refused before it began is
    // exactly the kind this panel exists to surface.
    render(<RunSummary agentId="agent-1" runs={[run({ started_at: null })]} />);

    expect(screen.getByText("not started")).toBeInTheDocument();
  });
});
