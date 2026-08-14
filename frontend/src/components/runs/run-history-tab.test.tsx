import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { RunHistoryTab } from "./run-history-tab";
import type { Period } from "@/lib/dashboard/period";
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
  // The tab gates its filters on runs:view and the filter bar gates its agent
  // and version selects on agents:view; these tests exercise the sort and
  // filter controls, so the holder is given everything.
  usePermissions: () => ({ can: () => true }),
  // What the filter bar's selects offer. One agent and two versions are enough
  // to prove the narrowing each control asks for.
  useAgents: () => ({ agents: [{ id: "agent-1", name: "Support agent" }], isLoading: false }),
  useAgentVersions: () => ({
    versions: [
      { id: "ver-2", version: 2 },
      { id: "ver-1", version: 1 },
    ],
    isLoading: false,
  }),
  useMembers: () => ({
    members: [{ user_id: "user-7", email: "kim@example.com", full_name: "Kim" }],
  }),
  // Mounted by the version strip when the tab is narrowed to an agent; an
  // empty window collapses the strip, which is all these tests need of it.
  useVersionUsage: () => ({ byVersion: [], isLoading: false, error: null, refetch: vi.fn() }),
  useAgent: () => ({ agent: undefined, isLoading: false }),
}));
vi.mock("@/stores", () => ({
  useOrgStore: (selector: (state: { activeOrgId: string | null }) => unknown) =>
    selector({ activeOrgId: "org-1" }),
  // Read by the run table for the chat-behind-a-run link; nobody signed in
  // means no link, which is not what these tests are about.
  useAuthStore: (selector: (state: { user: null }) => unknown) => selector({ user: null }),
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
    down_rated: false,
    conversation_id: null,
    provider: null,
  };
}

const PERIOD: Period = { preset: "30d", from: "2026-07-16", to: "2026-08-14" };

function renderTab(props: Partial<Parameters<typeof RunHistoryTab>[0]> = {}) {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RunHistoryTab
        agentId={null}
        focusedRunId={null}
        period={PERIOD}
        onAgentChange={vi.fn()}
        onFocusRun={vi.fn()}
        {...props}
      />
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
  it("opens on the feed - newest first, over the page's window", () => {
    renderTab();

    expect(lastOptions()).toEqual({
      startedFrom: "2026-07-16T00:00:00.000Z",
      startedTo: "2026-08-14T23:59:59.999Z",
      orderBy: "started_at",
      descending: true,
      tookOverMs: undefined,
      rated: undefined,
      statuses: undefined,
      surface: undefined,
      userId: undefined,
      agentVersionId: undefined,
      skip: 0,
    });
  });

  it("opens sorted by duration when the dashboard's p95 link asks for it", () => {
    renderTab({ initialDurationSort: true });

    expect(lastOptions()).toMatchObject({ orderBy: "duration", descending: true });
  });

  it("widens the window's dates into whole-day instants for the query", () => {
    // The period is inclusive whole days, so the last day must reach its final
    // instant - cut at midnight it silently drops the day the reader picked.
    renderTab({ period: { preset: "custom", from: "2026-08-01", to: "2026-08-31" } });

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

  it("the Cost header asks for the most expensive of the whole set", async () => {
    renderTab();

    await userEvent.click(screen.getByText("Cost").closest("button")!);

    expect(lastOptions()).toMatchObject({ orderBy: "cost", descending: true });
  });

  it("the Tokens header asks for the heaviest of the whole set", async () => {
    renderTab();

    await userEvent.click(screen.getByText("Tokens").closest("button")!);

    expect(lastOptions()).toMatchObject({ orderBy: "tokens", descending: true });
  });

  it("narrows to one status the server filters by", async () => {
    renderTab();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by status" }));
    await userEvent.click(screen.getByRole("option", { name: "Failed" }));

    expect(lastOptions()).toMatchObject({ statuses: ["failed"] });
  });

  it("problems is failed and stopped-by-budget together, the way they are stored apart", async () => {
    renderTab();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by status" }));
    await userEvent.click(screen.getByRole("option", { name: "Problems" }));

    expect(lastOptions()).toMatchObject({ statuses: ["failed", "budget_exceeded"] });
  });

  it("narrows to one surface", async () => {
    renderTab();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by surface" }));
    await userEvent.click(screen.getByRole("option", { name: "slack" }));

    expect(lastOptions()).toMatchObject({ surface: "slack" });
  });

  it("asks for the runs people liked, not only the ones they did not", async () => {
    renderTab();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by rating" }));
    await userEvent.click(screen.getByRole("option", { name: "Rated up" }));

    expect(lastOptions()).toMatchObject({ rated: "up" });
  });

  it("narrows to one person's runs", async () => {
    renderTab();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by person" }));
    await userEvent.click(screen.getByRole("option", { name: "Kim" }));

    expect(lastOptions()).toMatchObject({ userId: "user-7" });
  });

  it("hands a picked agent to the page, which owns that narrowing", async () => {
    const onAgentChange = vi.fn();
    renderTab({ onAgentChange });

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));
    await userEvent.click(screen.getByRole("option", { name: "Support agent" }));

    expect(onAgentChange).toHaveBeenCalledWith("agent-1");
  });

  it("narrows to one version, offered only when an agent is", async () => {
    renderTab();
    expect(screen.queryByRole("combobox", { name: "Filter by version" })).toBeNull();

    renderTab({ agentId: "agent-1" });
    await userEvent.click(screen.getByRole("combobox", { name: "Filter by version" }));
    await userEvent.click(screen.getByRole("option", { name: "v2" }));

    expect(lastOptions()).toMatchObject({ agentVersionId: "ver-2" });
  });

  it("pages through the whole narrowed set, and says where the reader is", async () => {
    useRunsMock.mockReturnValue({
      runs: [aRun()],
      total: 120,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderTab();

    expect(screen.getByText("1–50 of 120")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));

    expect(lastOptions()).toMatchObject({ skip: 50 });
    expect(screen.getByText("51–100 of 120")).toBeInTheDocument();
  });

  it("snaps back to the first page when a filter redefines the set", async () => {
    // Page three of the failed runs is not page three of everything: a filter
    // change that kept the offset would show an arbitrary slice.
    useRunsMock.mockReturnValue({
      runs: [aRun()],
      total: 120,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderTab();

    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    expect(lastOptions()).toMatchObject({ skip: 50 });

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by status" }));
    await userEvent.click(screen.getByRole("option", { name: "Failed" }));

    expect(lastOptions()).toMatchObject({ statuses: ["failed"], skip: 0 });
  });

  it("opens a run's detail when its row is clicked", async () => {
    const onFocusRun = vi.fn();
    renderTab({ onFocusRun });

    await userEvent.click(screen.getByText("openai · gpt-5"));

    expect(onFocusRun).toHaveBeenCalledWith("run-1");
  });

  it("the focused notice's way out clears the focus it names", async () => {
    const onFocusRun = vi.fn();
    renderTab({ focusedRunId: "run-1", onFocusRun });

    await userEvent.click(screen.getByRole("button", { name: "Show every run" }));

    expect(onFocusRun).toHaveBeenCalledWith(null);
  });

  it("drops the version narrowing when the agent changes under it", async () => {
    // v2 of one agent is not a version of the next: carried across, the filter
    // would silently empty the other agent's history.
    renderTab({ agentId: "agent-1" });

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by version" }));
    await userEvent.click(screen.getByRole("option", { name: "v2" }));
    expect(lastOptions()).toMatchObject({ agentVersionId: "ver-2" });

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by agent" }));
    await userEvent.click(screen.getByRole("option", { name: "All agents" }));

    expect(lastOptions()).toMatchObject({ agentVersionId: undefined });
  });

  it("says the filters emptied the list, not that nothing has ever run", async () => {
    useRunsMock.mockReturnValue({
      runs: [],
      total: 0,
      isLoading: false,
      error: null,
      refetch: vi.fn(),
    });
    renderTab();

    await userEvent.click(screen.getByRole("combobox", { name: "Filter by surface" }));
    await userEvent.click(screen.getByRole("option", { name: "slack" }));

    expect(screen.getByText("No runs match these filters")).toBeInTheDocument();
    expect(screen.queryByText("No runs in this window")).not.toBeInTheDocument();
  });

  it("keeps the export inside the card, beside the filters it exports the result of", () => {
    renderTab();

    expect(screen.getByRole("button", { name: "Export CSV" })).toBeInTheDocument();
  });
});
