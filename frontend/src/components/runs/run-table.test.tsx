import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { RunTable } from "./run-table";
import { useAuthStore } from "@/stores";
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
    conversation_id: null,
    provider: null,
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

  it("draws the vendor's mark beside the model it ran", () => {
    // The same presentation the Builder's current-model row uses: the brand
    // mark keyed on `provider`, never parsed out of the display label.
    render(<RunTable runs={[run({ provider: "openai" })]} />);

    // Beside the label rather than inside it: the label truncates on one line,
    // so it is a span of its own with the mark next to it.
    expect(
      within(row()).getByText("openai · gpt-5").closest("td")?.querySelector("svg"),
    ).not.toBeNull();
  });

  it("draws no vendor mark for a run recorded before the vendor was tracked", () => {
    render(<RunTable runs={[run({ provider: null })]} />);

    expect(
      within(row()).getByText("openai · gpt-5").closest("td")?.querySelector("svg"),
    ).toBeNull();
  });

  it("marks a cost that is only a floor rather than presenting it as the price", () => {
    // A model with no entry in the price table contributed nothing to the total,
    // so the number is a lower bound and a reader deciding on a budget needs to
    // know which kind of number they are looking at.
    render(<RunTable runs={[run({ cost_is_partial: true })]} />);

    expect(within(row()).getByTitle(/had no price/)).toBeVisible();
  });

  it("admits a model it does not know, and a run that never started or finished", () => {
    // Three absences in one row: the model, the start time, and the duration -
    // a run with no start has no measurable duration either, and each reads "-"
    // rather than an invented value.
    render(<RunTable runs={[run({ model_label: null, started_at: null })]} />);

    expect(within(row()).getAllByText("-")).toHaveLength(3);
  });

  it("says how long a finished run took", () => {
    render(
      <RunTable
        runs={[run({ started_at: "2026-08-04T09:00:00Z", ended_at: "2026-08-04T09:00:30Z" })]}
      />,
    );

    expect(within(row()).getByText("30 s")).toBeVisible();
  });
});

describe("a sortable run table", () => {
  it("has no sort controls when the caller hands it none", () => {
    // A delegations table and a focused run render rows whose order came from the
    // one query that asked for them; there is nothing on this page to re-sort.
    render(<RunTable runs={[run()]} />);

    expect(screen.queryByRole("button")).toBeNull();
  });

  it("sorts by duration when the Took header is used, slowest first", async () => {
    const onSort = vi.fn();
    render(<RunTable runs={[run()]} sort={{ by: "started_at", dir: "desc" }} onSort={onSort} />);

    await userEvent.click(screen.getByRole("button", { name: "Took" }));

    expect(onSort).toHaveBeenCalledWith({ by: "duration", dir: "desc" });
  });

  it("sorts by start time when the Started header is used", async () => {
    const onSort = vi.fn();
    render(<RunTable runs={[run()]} sort={{ by: "duration", dir: "desc" }} onSort={onSort} />);

    await userEvent.click(screen.getByRole("button", { name: "Started" }));

    expect(onSort).toHaveBeenCalledWith({ by: "started_at", dir: "desc" });
  });

  it("flips the direction when the sorted header is pressed again", async () => {
    const onSort = vi.fn();
    render(<RunTable runs={[run()]} sort={{ by: "duration", dir: "desc" }} onSort={onSort} />);

    await userEvent.click(screen.getByRole("button", { name: "Took" }));

    expect(onSort).toHaveBeenCalledWith({ by: "duration", dir: "asc" });
  });

  it("sorts by token weight when the Tokens header is used, heaviest first", async () => {
    const onSort = vi.fn();
    render(<RunTable runs={[run()]} sort={{ by: "started_at", dir: "desc" }} onSort={onSort} />);

    await userEvent.click(screen.getByRole("button", { name: "Tokens" }));

    expect(onSort).toHaveBeenCalledWith({ by: "tokens", dir: "desc" });
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

describe("opening a run from its row", () => {
  it("hands the clicked run to the caller", async () => {
    const onOpen = vi.fn();
    render(<RunTable runs={[run()]} onOpen={onOpen} />);

    await userEvent.click(within(row()).getByText("openai · gpt-5"));

    expect(onOpen).toHaveBeenCalledTimes(1);
    expect(onOpen.mock.calls[0]?.[0]).toMatchObject({ id: "run-1" });
  });

  it("does not open the run under the chat link's navigation", async () => {
    // The chat link leaves the page; a row click firing beneath it would open
    // the run detail under the navigation.
    useAuthStore.setState({ user: { id: "user-1" } as never });
    const onOpen = vi.fn();
    render(<RunTable runs={[run({ conversation_id: "conv-9" })]} onOpen={onOpen} />);

    await userEvent.click(
      within(row()).getByRole("link", { name: "Open the chat this run happened in" }),
    );

    expect(onOpen).not.toHaveBeenCalled();
  });
});

describe("when a run started", () => {
  it("reads relative on the row with the absolute instant on hover", () => {
    // Recent, so the relative branch renders rather than the past-a-week date
    // fallback - the test must not age into a different branch.
    const startedAt = new Date(Date.now() - 2 * 3600 * 1000).toISOString();
    render(<RunTable runs={[run({ started_at: startedAt })]} />);

    const cell = within(row()).getByText("2h ago");
    expect(cell).toHaveAttribute(
      "title",
      expect.stringContaining(String(new Date().getFullYear())),
    );
  });
});

describe("the chat behind a run", () => {
  const CHAT_LINK = "Open the chat this run happened in";

  it("links the reader's own run to its conversation", () => {
    useAuthStore.setState({ user: { id: "user-1" } as never });
    render(<RunTable runs={[run({ conversation_id: "conv-9" })]} />);

    expect(within(row()).getByRole("link", { name: CHAT_LINK })).toHaveAttribute(
      "href",
      "/chat?id=conv-9",
    );
  });

  it("offers nothing for a run with no conversation behind it", () => {
    // An API call has a run and no thread - a link would land on nothing.
    useAuthStore.setState({ user: { id: "user-1" } as never });
    render(<RunTable runs={[run({ conversation_id: null })]} />);

    expect(within(row()).queryByRole("link", { name: CHAT_LINK })).toBeNull();
  });

  it("offers nothing on somebody else's run", () => {
    // The chat page lists its owner's threads: anybody else's link would land
    // on an empty sidebar dressed as the conversation.
    useAuthStore.setState({ user: { id: "user-2" } as never });
    render(<RunTable runs={[run({ conversation_id: "conv-9" })]} />);

    expect(within(row()).queryByRole("link", { name: CHAT_LINK })).toBeNull();
  });
});

describe("who ran it, and which agent", () => {
  it("names the agent and the person when the lookups are given", () => {
    render(
      <RunTable
        runs={[run()]}
        agentsById={new Map([["agent-1", { name: "Support agent" }]])}
        membersById={
          new Map([["user-1", { user_id: "user-1", email: "kim@acme.test", full_name: "Kim" }]])
        }
      />,
    );

    expect(within(row()).getByText("Support agent")).toBeVisible();
    expect(within(row()).getByText("Kim")).toBeVisible();
  });

  it("admits an id the lookups cannot name", () => {
    // A deleted agent or a member no longer in the organization reads "-",
    // never a guess.
    render(
      <RunTable
        runs={[run({ agent_id: "agent-gone", user_id: "user-gone" })]}
        agentsById={new Map()}
        membersById={new Map()}
      />,
    );

    expect(within(row()).getAllByText("-").length).toBeGreaterThanOrEqual(2);
  });

  it("withholds the Agent column entirely when the names cannot be resolved", () => {
    // No agents:view means no agent list - a column of dashes would read as
    // data missing rather than a permission withheld.
    render(<RunTable runs={[run()]} />);

    expect(screen.queryByText("Support agent")).toBeNull();
    expect(screen.queryByRole("columnheader", { name: "Agent" })).toBeNull();
  });
});

describe("the run the panel beside the table is showing", () => {
  it("marks that row and no other", () => {
    render(
      <RunTable
        runs={[run({ id: "run-1" }), run({ id: "run-2" })]}
        onOpen={() => {}}
        openRunId="run-2"
      />,
    );

    const rows = within(screen.getByRole("table")).getAllByRole("row").slice(1);
    expect(rows[0]).not.toHaveAttribute("aria-selected", "true");
    expect(rows[1]).toHaveAttribute("aria-selected", "true");
  });

  it("marks nothing when no run is open", () => {
    // A delegations table and the focused run's own table pass none: the detail
    // is already on screen, so there is nothing for a row to point at.
    render(<RunTable runs={[run()]} />);

    expect(within(screen.getByRole("table")).getAllByRole("row")[1]).not.toHaveAttribute(
      "aria-selected",
    );
  });
});
