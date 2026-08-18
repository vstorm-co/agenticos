import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import RunsPage from "./page";
import { ApiError, apiClient } from "@/lib/api-client";
import type { AgentRun } from "@/types/runs";

/**
 * Activity telling a delegated run from one somebody started.
 *
 * The reported bug is arithmetic, not decoration. A fan-out turn of three
 * delegations wrote four `agent_runs` rows, all four listed identically, so the
 * cost column read $1.00 + $0.40 + $0.40 + $0.40 down the page next to a
 * month-to-date figure of $1.00 that correctly counts the parent once - and the
 * "Runs" figure said 4 beside it. The page contradicted itself, and both halves
 * were right about a different question.
 *
 * So the assertions here are about the numbers and about a delegated row's own
 * identity. Every dashboard page draws its empty state when a query fails, which
 * makes a test that asserts on a heading and a tab strip a test that passes
 * against a backend nobody started.
 */

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { ...actual.apiClient, get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));

const params = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useSearchParams: () => params,
  // The header's "?" reads the path to decide whether this page has tips.
  usePathname: () => "/runs",
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const SPEND = {
  period_days: null,
  // What the organization was actually billed for the turn below: the parent
  // once, its three delegations already inside it. The figure sums the
  // per-agent rows, which are top-level runs only.
  month_to_date_usd: "1.00",
  by_agent: [
    {
      agent_id: "agent-orchestrator",
      agent_name: "Orchestrator",
      cost_usd: "1.00",
      run_count: 1,
      partial_run_count: 0,
      month_to_date_usd: "1.00",
      monthly_cap_usd: null,
    },
  ],
  by_provider: [],
  by_key: [],
};

function run(overrides: Partial<AgentRun> = {}): AgentRun {
  return {
    id: "run-parent",
    agent_id: "agent-orchestrator",
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

const DELEGATED = [
  run({
    id: "run-child-1",
    agent_id: "agent-researcher",
    model_label: "anthropic · claude-sonnet-4-5",
    cost_usd: "0.400000",
    parent_run_id: "run-parent",
    subagent_task_id: "4f2a1b8c",
  }),
  run({
    id: "run-child-2",
    agent_id: "agent-researcher",
    model_label: "anthropic · claude-sonnet-4-5",
    cost_usd: "0.400000",
    parent_run_id: "run-parent",
    subagent_task_id: "9abbab49",
  }),
];

/**
 * The stat card holding `anchor`, read by its own copy rather than by position.
 *
 * "Runs" is anchored on the card's caption because the tab strip says "Runs"
 * too, and a locator that matched either would sometimes assert against a tab.
 */
function figure(anchor: string | RegExp) {
  return screen.getByText(anchor).parentElement as HTMLElement;
}

const RUNS_CARD = /Delegations are counted in the run they came from/;

async function openRunsTab() {
  await userEvent.click(await screen.findByRole("tab", { name: "Runs" }));
}

beforeEach(() => {
  params.delete("agent");
  params.delete("run");
  vi.mocked(apiClient.get).mockReset();
});

/** `/runs` answers the top level; `/runs/{id}` and `?parent_run_id=` answer the rest. */
function backend(
  options: {
    total?: number;
    runFails?: Error;
    traceUrl?: string;
    neighbors?: { prev?: string; next?: string };
    status?: AgentRun["status"];
  } = {},
) {
  vi.mocked(apiClient.get).mockImplementation((path: string, init?: unknown) => {
    if (path === "/spend") return Promise.resolve(SPEND);
    // The detail header resolves the agent's identity; the timeline reads the
    // thread. Neither is this suite's subject, so both answer minimally.
    if (path.startsWith("/agents/")) {
      return Promise.resolve({ id: path.split("/").at(-1), name: "Orchestrator" });
    }
    if (path.endsWith("/transcript")) {
      return Promise.resolve({ run_id: "run-parent", conversation_id: null, items: [], total: 0 });
    }
    if (path === "/runs/run-child-1") {
      return options.runFails === undefined
        ? Promise.resolve(DELEGATED[0])
        : Promise.reject(options.runFails);
    }
    if (path === "/runs/run-parent") {
      // The trace link and the neighbour ids are the single-run read's own
      // fields, so they are served here and nowhere else - as the API sends them.
      return Promise.resolve(
        run({
          ...(options.traceUrl === undefined ? {} : { logfire_url: options.traceUrl }),
          ...(options.status === undefined ? {} : { status: options.status }),
          prev_run_id: options.neighbors?.prev ?? null,
          next_run_id: options.neighbors?.next ?? null,
        }),
      );
    }
    if (path === "/runs") {
      const params = (init as { params?: Record<string, string> } | undefined)?.params;
      if (params?.parent_run_id === "run-parent") {
        return Promise.resolve({ items: DELEGATED, total: DELEGATED.length });
      }
      if (params?.parent_run_id !== undefined) return Promise.resolve({ items: [], total: 0 });
      return Promise.resolve({ items: [run()], total: options.total ?? 1 });
    }
    return Promise.resolve({ items: [], total: 0 });
  });
}

describe("the run count and the spend beside it", () => {
  it("counts what the bill counts, not the rows a fan-out wrote", async () => {
    backend();

    render(<RunsPage />, { wrapper });

    // One run and $1.00: the two figures are now answers to the same question.
    await waitFor(() => expect(figure(RUNS_CARD)).toHaveTextContent("1"));
    expect(figure(/Over the window above/)).toHaveTextContent("$1.00");
  });

  it("reports the whole history rather than the length of one page", async () => {
    // The card used to render `runs.length`, which is capped at the page size,
    // so an organization with two hundred runs read as fifty.
    backend({ total: 213 });

    render(<RunsPage />, { wrapper });

    await waitFor(() => expect(figure(RUNS_CARD)).toHaveTextContent("213"));
  });

  it("asks only for top-level runs, leaving delegations to be asked for by parent", async () => {
    backend();

    render(<RunsPage />, { wrapper });
    // Run history is asked for when its tab is opened: each tab fetches its own
    // rows and Radix mounts only the selected one, which is Approvals.
    await openRunsTab();

    await waitFor(() =>
      expect(vi.mocked(apiClient.get).mock.calls.some(([path]) => path === "/runs")).toBe(true),
    );
    expect(apiClient.get).not.toHaveBeenCalledWith("/runs", {
      params: expect.objectContaining({ parent_run_id: expect.anything() }),
    });
  });
});

describe("one run and what it delegated", () => {
  it("shows the run named in the URL together with its delegations", async () => {
    params.set("run", "run-parent");
    backend();

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    // Three rows: the run somebody started and the two it delegated - reached by
    // the delegation handle each carries, which is what ties a row here to a
    // panel in the transcript.
    const drawer = await screen.findByRole("dialog");
    const table = await within(drawer).findByRole("table");
    expect(within(table).getByText("Delegated · 4f2a1b8c")).toBeVisible();
    expect(within(table).getByText("Delegated · 9abbab49")).toBeVisible();
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    expect(
      screen.getByText(/2 delegations, and their cost is already inside the run above/),
    ).toBeVisible();
  });

  it("says the delegated rows do not add up, on the badge that marks them", async () => {
    params.set("run", "run-parent");
    backend();

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    // One per delegated row, and none on the run somebody started.
    expect(
      await screen.findAllByTitle(/already inside the run it was delegated from/),
    ).toHaveLength(2);
  });

  it("offers the way back up from a delegated run to the one that charged it", async () => {
    // Arriving from a chat panel lands on the child. Its cost was charged to the
    // parent, so a page about the child that cannot reach the parent is a page
    // that cannot explain its own number.
    params.set("run", "run-child-1");
    backend();

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    // An action, not a link: focusing the parent goes through the page's own
    // run state, so the period and the agent narrowing survive the step up.
    await userEvent.click(await screen.findByRole("button", { name: "Open the run it came from" }));

    expect(await screen.findByText("Delegated · 4f2a1b8c")).toBeVisible();
  });

  it("keeps the list on screen behind the drawer", async () => {
    // The detail is a drawer over the list, not a replacement for it - the
    // list is the context the run is read against, and closing the drawer
    // must land the reader exactly where they were.
    params.set("run", "run-parent");
    backend();

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    const drawer = await screen.findByRole("dialog");
    expect(within(drawer).getByText("Run detail")).toBeVisible();
    // Two tables: the drawer's delegations and the list still behind it.
    expect(screen.getAllByRole("table").length).toBeGreaterThanOrEqual(2);
  });

  it("says a run could not be read instead of drawing an empty table", async () => {
    // The trap this page is full of: a failed query and a run with nothing in it
    // are the same pixels, and the first is the one somebody needs to know about.
    params.set("run", "run-child-1");
    backend({ runFails: new ApiError(403, "Missing required permission: runs:view") });

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    expect(await screen.findByText("That run could not be read")).toBeVisible();
    // No table in the drawer - the list's own table behind it is not the run.
    expect(within(screen.getByRole("dialog")).queryByRole("table")).toBeNull();
  });

  it("calls a run that is not there a run that is not there", async () => {
    // 404 is also the answer for a run in another organization, deliberately -
    // so "not in this organization, or has been deleted" is the honest sentence,
    // and it is a different sentence from a refused permission.
    params.set("run", "run-child-1");
    backend({ runFails: new ApiError(404, "Run not found") });

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    expect(await screen.findByText("No such run")).toBeVisible();
    expect(screen.getByText(/not in this organization, or has been deleted/)).toBeVisible();
  });

  it("does not call a network failure a missing run", async () => {
    // A dropped connection is not an ApiError at all, and a page that answered
    // "no such run" for one would send somebody looking for a run that is there.
    params.set("run", "run-child-1");
    backend({ runFails: new Error("Failed to fetch") });

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    expect(await screen.findByText("That run could not be read")).toBeVisible();
  });
});

describe("walking the run's conversation from the detail", () => {
  it("steps to the next run with the arrow", async () => {
    params.set("run", "run-parent");
    backend({ neighbors: { next: "run-child-1" } });

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    await userEvent.click(await screen.findByRole("button", { name: "Next run" }));

    // Landed on the child, whose own view offers the way back up.
    expect(await screen.findByRole("button", { name: "Open the run it came from" })).toBeVisible();
  });

  it("closes the drawer back onto the list", async () => {
    params.set("run", "run-parent");
    backend();

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Close" }),
    );

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.getByRole("button", { name: "All runs" })).toBeVisible();
  });

  it("clicking the backdrop closes the drawer too", async () => {
    params.set("run", "run-parent");
    backend();

    const { baseElement } = render(<RunsPage />, { wrapper });
    await openRunsTab();
    await screen.findByRole("dialog");

    await userEvent.click(baseElement.querySelector('[aria-hidden="true"].fixed') as HTMLElement);

    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("steps back to the previous run with the other arrow", async () => {
    params.set("run", "run-parent");
    backend({ neighbors: { prev: "run-child-1" } });

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    await userEvent.click(await screen.findByRole("button", { name: "Previous run" }));

    expect(await screen.findByRole("button", { name: "Open the run it came from" })).toBeVisible();
  });

  it("disables the arrows at the history's edge rather than hiding them", async () => {
    params.set("run", "run-parent");
    backend();

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    expect(await screen.findByRole("button", { name: "Previous run" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Next run" })).toBeDisabled();
  });

  it("answers the operator's first questions in the header, without a click", async () => {
    params.set("run", "run-parent");
    backend();

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    // Tokens in → out, the cost, and the agent's name resolved from its id.
    // The cost also sits in the delegations table below, so the header's copy
    // is read as the first of the two rather than as the only one.
    expect(await screen.findByText("1000 → 100")).toBeVisible();
    expect(screen.getAllByText("$1.0000").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Orchestrator")).toBeVisible();
  });
});

describe("resuming a parked run from its detail", () => {
  it("offers Resume on a run awaiting approval, and posts the continuation", async () => {
    // The queue resumes a run when its last call is decided - but a run decided
    // before that wiring existed, or whose resume failed, stays parked with
    // nothing outstanding. This button is how such a run gets unstuck.
    params.set("run", "run-parent");
    backend({ status: "awaiting_approval" });
    vi.mocked(apiClient.post).mockResolvedValue({ run_id: "run-parent", status: "running" });

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    await userEvent.click(await screen.findByRole("button", { name: "Resume" }));

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledWith("/runs/run-parent/resume"));
  });

  it("offers no Resume on a run that is not parked", async () => {
    params.set("run", "run-parent");
    backend();

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    await within(await screen.findByRole("dialog")).findByRole("table");
    expect(screen.queryByRole("button", { name: "Resume" })).toBeNull();
  });
});

describe("the trace behind a run", () => {
  it("links to Logfire when the server resolved somewhere to land", async () => {
    params.set("run", "run-parent");
    backend({ traceUrl: "https://logfire.pydantic.dev/acme/agents/traces/abc123" });

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    const link = await screen.findByRole("link", { name: /Open the trace in Logfire/ });
    expect(link).toHaveAttribute("href", "https://logfire.pydantic.dev/acme/agents/traces/abc123");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("offers no trace link when nothing was tracing", async () => {
    // Null means no LOGFIRE_TOKEN or nowhere configured to link to - a dead
    // link dressed as observability would be worse than none.
    params.set("run", "run-parent");
    backend();

    render(<RunsPage />, { wrapper });
    await openRunsTab();

    const drawer = await screen.findByRole("dialog");
    await within(drawer).findByRole("table");
    expect(within(drawer).queryByRole("link", { name: /Open the trace in Logfire/ })).toBeNull();
  });
});
