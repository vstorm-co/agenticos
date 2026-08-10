import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RunTable } from "./run-table";
import type { AgentRun } from "@/types/runs";

/**
 * What a row says about itself.
 *
 * The delegation badge is the point: a delegated run's cost is already inside
 * the run it came from, so two rows that look identical invite a sum that
 * double-counts every delegation. The rest of the cells are here because each
 * one has an absent case - no model, no start time, a price that is only a floor
 * - and a run history that renders `undefined` in a column is worse than one
 * that admits it does not know.
 */

function run(overrides: Partial<AgentRun> = {}): AgentRun {
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
    down_rated: false,
    started_at: "2026-08-04T09:00:00Z",
    ended_at: "2026-08-04T09:00:30Z",
    parent_run_id: null,
    subagent_task_id: null,
    ...overrides,
  };
}

/** The one data row, so a cell is read inside it rather than anywhere on screen. */
function row() {
  return within(screen.getByRole("table")).getAllByRole("row")[1] as HTMLElement;
}

describe("a run history row", () => {
  it("says nothing about delegation for a run somebody started", () => {
    render(<RunTable runs={[run()]} />);

    expect(within(row()).queryByText(/Delegated/)).toBeNull();
  });

  it("marks a delegated run with the delegation that produced it", () => {
    // The task id is what makes this row and a panel in a transcript visibly one
    // delegation rather than two things about the same agent.
    render(<RunTable runs={[run({ parent_run_id: "run-0", subagent_task_id: "4f2a1b8c" })]} />);

    expect(within(row()).getByText("Delegated · 4f2a1b8c")).toBeVisible();
  });

  it("still marks an orphaned delegation, without a handle it cannot honour", () => {
    // Deleting the parent nulls the handle - the transcript it named went with
    // the parent - but the row is still a delegation and still must not be read
    // as a run somebody started.
    render(<RunTable runs={[run({ parent_run_id: "run-0", subagent_task_id: null })]} />);

    const badge = within(row()).getByText("Delegated");
    expect(badge).toBeVisible();
    expect(badge).not.toHaveTextContent("·");
  });

  it("adds both halves of the token count, which is what a run cost in tokens", () => {
    render(<RunTable runs={[run({ input_tokens: 1000, output_tokens: 100 })]} />);

    expect(within(row()).getByText("1100")).toBeVisible();
  });

  it("marks a cost that is only a floor rather than presenting it as the price", () => {
    // A model with no entry in the price table contributed nothing to the total,
    // so the number is a lower bound and a reader deciding on a budget needs to
    // know which kind of number they are looking at.
    render(<RunTable runs={[run({ cost_is_partial: true })]} />);

    expect(within(row()).getByTitle(/had no price/)).toBeVisible();
  });

  it("admits a model it does not know and a run that never started", () => {
    render(<RunTable runs={[run({ model_label: null, started_at: null })]} />);

    expect(within(row()).getAllByText("-")).toHaveLength(2);
  });

  it("marks a run somebody rated down, and says nothing on one nobody did", () => {
    // The reason to read this list top to bottom: an answer somebody said was
    // wrong. A marker on the row, with the comment behind the run detail.
    render(<RunTable runs={[run({ down_rated: true })]} />);

    expect(within(row()).getByRole("img", { name: "Rated down" })).toBeVisible();
  });

  it("shows no rated-down marker on a run nobody rated down", () => {
    render(<RunTable runs={[run({ down_rated: false })]} />);

    expect(within(row()).queryByRole("img", { name: "Rated down" })).toBeNull();
  });
});
