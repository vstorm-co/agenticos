import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TriggerRow } from "./trigger-row";
import { TriggerRunsView } from "./trigger-runs-view";
import { apiClient } from "@/lib/api-client";
import { useAuthStore } from "@/stores";
import { qk } from "@/lib/query-keys";
import { useTriggers } from "@/hooks/use-triggers";
import type { Trigger, TriggerAttempt, TriggerAttemptList } from "@/types/triggers";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

it.each(["run", "attempt"])(
  "waits for its own activation when another %s finishes first",
  async (outcome) => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    serveRuns(
      [run({ id: "other-run", routine_activation_id: "other-fire", status: "completed" })],
      1,
      { items: [{ ...attempt(), activation_id: "other-fire" }], total: 1 },
    );
    render(
      <QueryClientProvider client={client}>
        <TriggerRunsView trigger={trigger()} activationId="requested-fire" />
      </QueryClientProvider>,
    );
    await screen.findByRole("link", { name: "Open run" });
    expect(screen.getByText("Starting…")).toBeVisible();
    serveRuns(outcome === "run" ? [run({ status: "completed" })] : [], outcome === "run" ? 1 : 0, {
      items: outcome === "attempt" ? [attempt()] : [],
      total: outcome === "attempt" ? 1 : 0,
    });
    await client.invalidateQueries();
    await waitFor(() => expect(screen.queryByText("Starting…")).toBeNull());
  },
);

function trigger(overrides: Partial<Trigger> = {}): Trigger {
  return {
    id: "t1",
    agent_id: "a1",
    agent_name: "Digest bot",
    name: null,
    created_by_user_id: null,
    is_active: true,
    can_manage: true,
    environment_id: null,
    runs_as_creator: false,
    trigger_type: "schedule",
    schedule_kind: "interval",
    interval_seconds: 900,
    cron_expression: null,
    time_zone: null,
    overlap: "skip",
    event_source: null,
    event_config: {},
    prompt: "Summarise the day",
    next_fire_at: null,
    last_fired_at: null,
    last_run_id: null,
    conversation_id: "c1",
    webhook_url: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function run(overrides: Record<string, unknown> = {}) {
  return {
    id: "r1",
    routine_activation_id: "requested-fire",
    agent_id: "a1",
    agent_version_id: null,
    user_id: null,
    surface: "schedule",
    status: "completed",
    model_label: null,
    provider: null,
    input_tokens: 0,
    output_tokens: 0,
    cost_usd: "0.0042",
    cost_is_partial: false,
    logfire_trace_id: null,
    error: null,
    down_rated: false,
    conversation_id: "c1",
    started_at: "2026-08-21T07:00:00Z",
    ended_at: "2026-08-21T07:00:09Z",
    ...overrides,
  };
}

/** The runs listing, as the drawer asks for it. */
function serveRuns(
  runs: Record<string, unknown>[],
  total?: number,
  attempts: TriggerAttemptList = { items: [], total: 0 },
) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.includes("/activations/")) return { state: "pending" };
    if (path === "/agents") return { items: [], total: 0 };
    if (path === "/runs") return { items: runs, total: total ?? runs.length };
    if (path.includes("/attempts?")) return attempts;
    if (path.startsWith("/agents/")) return { items: [trigger()], total: 1 };
    throw new Error(`unexpected GET ${path}`);
  });
}

const OPEN = { name: "See what this trigger has done" };

/**
 * What a trigger has done, as a list of runs.
 *
 * It was the chat's own transcript over the run-log conversation, which reads
 * well for one fire and badly for forty identical ones: the prompt is the same
 * every time, the only thing distinguishing two fires is the reply, and a failed
 * run's half-answer looks exactly like a complete one. There was also nowhere to
 * go from it - the run detail is where "why did this fail" is answered.
 */
describe("TriggerRow run list", () => {
  beforeEach(() => vi.clearAllMocks());

  it("keeps a constrained chat card readable with its independent management controls", async () => {
    serveRuns([]);
    const previousUser = useAuthStore.getState().user;
    useAuthStore.setState({
      user: {
        id: "creator",
        email: "creator@example.com",
        is_active: true,
        created_at: "2026-11-16T00:00:00Z",
      },
    });
    const prompt = "Prepare an actionable weekly report covering all the open work and deadlines.";
    const view = render(
      <div style={{ width: 320 }}>
        <TriggerRow
          trigger={trigger({
            name: "Weekly planning and priorities",
            prompt,
            created_by_user_id: "creator",
            runs_as_creator: true,
          })}
          showAgent
        />
      </div>,
      { wrapper },
    );
    const summary = screen.getByRole("button", OPEN);
    const article = summary.closest("article");
    expect(article).toHaveClass("@container/routine");
    expect(summary).toHaveClass("basis-full", "@min-[48rem]/routine:basis-0");
    expect(within(summary).getByText("Weekly planning and priorities")).toBeVisible();
    expect(within(summary).getByText(prompt)).toBeVisible();
    for (const name of ["Run now", "Edit", "Pause", "Delete"]) {
      const action = screen.getByRole("button", { name });
      expect(action).toBeEnabled();
      expect(summary).not.toContainElement(action);
    }
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(await screen.findByRole("dialog")).toBeVisible();
    expect(apiClient.delete).not.toHaveBeenCalled();
    view.unmount();
    useAuthStore.setState({ user: previousUser });
  });

  it("shows action labels on hover and keyboard focus", async () => {
    const user = userEvent.setup();
    serveRuns([]);
    const { rerender } = render(<TriggerRow trigger={trigger()} />, { wrapper });
    await user.hover(screen.getByRole("button", { name: "Edit" }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("Edit");
    await user.unhover(screen.getByRole("button", { name: "Edit" }));
    fireEvent.focus(screen.getByRole("button", { name: "Pause" }));
    await waitFor(() => expect(screen.getByRole("tooltip")).toHaveTextContent("Pause"));
    rerender(<TriggerRow trigger={trigger({ is_active: false })} />);
    expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
    await user.hover(screen.getByRole("button", { name: "Run now" }).parentElement!);
    await waitFor(() => expect(screen.getByRole("tooltip")).toHaveTextContent("Run now"));
  });

  it("lists each fire with when it ran and how it went", async () => {
    serveRuns([
      run({ id: "r1", status: "completed" }),
      run({ id: "r2", status: "failed", started_at: "2026-08-21T08:00:00Z" }),
    ]);
    render(<TriggerRow trigger={trigger()} />, { wrapper });

    await userEvent.click(screen.getByRole("button", OPEN));

    const drawer = within(await screen.findByRole("dialog"));
    expect(drawer.getAllByRole("time")).toHaveLength(2);
    expect(drawer.getByText(/succeeded/)).toBeVisible();
    expect(drawer.getByText(/failed/)).toBeVisible();
  });

  it("marks a fire the loop guard stopped as one that did not finish", async () => {
    serveRuns([run({ id: "r1", status: "loop_stopped" })]);
    render(<TriggerRow trigger={trigger()} />, { wrapper });

    await userEvent.click(screen.getByRole("button", OPEN));

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/stopped: looping/)).toBeVisible();
    expect(dialog.querySelector(".text-destructive")).not.toBeNull();
  });

  it("says what each fire cost, which the transcript could not", async () => {
    serveRuns([run()]);
    render(<TriggerRow trigger={trigger()} />, { wrapper });

    await userEvent.click(screen.getByRole("button", OPEN));

    expect(within(await screen.findByRole("dialog")).getByText(/\$0\.0042/)).toBeVisible();
  });

  it("links each fire to its own run detail and execution chat", async () => {
    // The point of listing runs rather than turns: the requests, the tools and
    // the cost per turn are on that page, and there was no way to reach it.
    serveRuns([run({ id: "r-42", conversation_id: "execution-chat" })]);
    render(<TriggerRow trigger={trigger({ conversation_id: "execution-chat" })} />, { wrapper });

    await userEvent.click(screen.getByRole("button", OPEN));

    const link = within(await screen.findByRole("dialog")).getByRole("link", { name: /Open run/ });
    expect(link).toHaveAttribute("href", "/runs?run=r-42");
    expect(screen.getByRole("link", { name: "Open chat" })).toHaveAttribute(
      "href",
      "/chat?id=execution-chat",
    );
  });

  it("asks only for this trigger's own fires", async () => {
    // Routine identity spans independent execution chats and shared histories.
    serveRuns([run()]);
    render(<TriggerRow trigger={trigger({ conversation_id: "c-9" })} />, { wrapper });

    await userEvent.click(screen.getByRole("button", OPEN));
    await screen.findByRole("dialog");

    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/runs", {
        params: expect.objectContaining({ trigger_id: "t1" }),
      }),
    );
  });

  it("says nothing has run rather than drawing an empty list", async () => {
    serveRuns([]);
    render(<TriggerRow trigger={trigger({ conversation_id: null })} />, { wrapper });

    await userEvent.click(screen.getByRole("button", OPEN));

    expect(await screen.findByText(/has not run yet/)).toBeVisible();
  });

  it("pages a trigger that has fired more times than one request answers", async () => {
    serveRuns([run()], 130);
    render(<TriggerRow trigger={trigger()} />, { wrapper });

    await userEvent.click(screen.getByRole("button", OPEN));

    const drawer = within(await screen.findByRole("dialog"));
    expect(drawer.getByText(/130 runs/)).toBeVisible();

    await userEvent.click(drawer.getByRole("button", { name: "Next page" }));

    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/runs", {
        params: expect.objectContaining({ skip: "50" }),
      }),
    );
  });

  it("shows a starting row for a fire that has no run yet", async () => {
    // A fire is dispatched after its request commits, so for a second there is no
    // row for it - and "has not run yet" is the opposite of what just happened.
    const user = userEvent.setup();
    serveRuns([]);
    vi.mocked(apiClient.post).mockResolvedValue({
      ...trigger(),
      activation_id: "requested-fire",
      job_id: "job1",
    });
    render(<TriggerRow trigger={trigger()} />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Run now" }));

    expect(await screen.findByText("Starting…")).toBeVisible();
  });

  it("keeps the action buttons working without opening the view", async () => {
    const user = userEvent.setup();
    serveRuns([]);
    vi.mocked(apiClient.patch).mockResolvedValue(trigger({ is_active: false }));
    render(<TriggerRow trigger={trigger()} />, { wrapper });

    await user.click(screen.getByRole("button", { name: "Pause" }));

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/triggers/t1", { is_active: false });
  });

  it("closes the drawer from its close button", async () => {
    const user = userEvent.setup();
    serveRuns([run()]);
    render(<TriggerRow trigger={trigger()} />, { wrapper });
    await user.click(screen.getByRole("button", OPEN));
    await screen.findByRole("dialog");

    await user.click(screen.getByRole("button", { name: "Close" }));

    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("says a failed read out loud rather than as an empty list", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.includes("/activations/")) return { state: "pending" };
      if (path === "/agents") return { items: [], total: 0 };
      if (path.includes("/attempts?")) return { items: [], total: 0 };
      if (path.startsWith("/agents/")) return { items: [trigger()], total: 1 };
      throw new Error("boom");
    });
    render(<TriggerRow trigger={trigger()} />, { wrapper });

    await userEvent.click(screen.getByRole("button", OPEN));

    expect(await screen.findByText(/could not be read/)).toBeVisible();
  });
});

/** `useTriggers` is imported so the row's own mutations resolve against it. */
void useTriggers;

function attempt(reason: TriggerAttempt["reason"] = "platform_identity_required"): TriggerAttempt {
  return {
    id: reason,
    activation_id: "requested-fire",
    status: "blocked",
    stage: "source_review",
    reason,
    occurred_at: new Date().toISOString(),
  };
}

describe("before-run attempts", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows a blocked attempt and an actionable reason even when no agent run exists", async () => {
    serveRuns([], 0, { items: [attempt()], total: 1 });
    render(
      <TriggerRunsView
        trigger={trigger({ conversation_id: null })}
        activationId="requested-fire"
      />,
      { wrapper },
    );
    expect(await screen.findByRole("heading", { name: "Before the agent started" })).toBeVisible();
    expect(screen.getByText(/Enable Act as creator/)).toBeVisible();
    expect(screen.getByText(/did not start an agent run or incur model charges/)).toBeVisible();
    expect(screen.queryByText("Starting…")).toBeNull();
    expect(screen.queryByRole("link", { name: "Open run" })).toBeNull();
  });

  it.each(["source_review_required", "agent_unavailable", "preparation_failed"] as const)(
    "explains %s without exposing provider text",
    async (reason) => {
      serveRuns([], 0, {
        items: [{ ...attempt(reason), status: "failed", stage: "preparation" }],
        total: 1,
      });
      render(<TriggerRunsView trigger={trigger()} activationId={null} />, { wrapper });
      expect(
        await screen.findByRole("heading", { name: "Before the agent started" }),
      ).toBeVisible();
      expect(screen.getByText(/Preparing the agent/)).toBeVisible();
      expect(screen.getByText(/Failed ·/)).toBeVisible();
      expect(screen.queryByText(reason)).toBeNull();
    },
  );

  it("paginates attempts independently from agent runs", async () => {
    serveRuns([run()], 130, { items: [attempt()], total: 11 });
    render(<TriggerRunsView trigger={trigger()} activationId={null} />, { wrapper });
    await screen.findByRole("heading", { name: "Before the agent started" });
    await userEvent.click(
      within(screen.getByRole("group", { name: "Before the agent started" })).getByRole("button", {
        name: "Next page",
      }),
    );
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith(
        "/agents/a1/triggers/t1/attempts?skip=10&limit=10",
      ),
    );
  });

  it("reports an unavailable history and retries it", async () => {
    serveRuns([]);
    const normal = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (path.includes("/activations/")) return { state: "pending" };
      if (path.includes("/attempts?")) throw new Error("unavailable");
      return normal(path, options);
    });
    render(<TriggerRunsView trigger={trigger()} activationId={null} />, { wrapper });
    expect(await screen.findByText("Could not read attempts before run creation.")).toBeVisible();
    serveRuns([], 0, { items: [attempt()], total: 1 });
    await userEvent.click(screen.getByRole("button", { name: "Retry history" }));
    expect(await screen.findByRole("heading", { name: "Before the agent started" })).toBeVisible();
  });
});

it("returns to the newest attempt page when another fire starts", async () => {
  let firing = false;
  const old = {
    ...attempt("preparation_failed"),
    activation_id: "old-fire",
    occurred_at: new Date(Date.now() - 3600000).toISOString(),
  };
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.includes("/activations/")) return { state: "pending" };
    if (path === "/runs") return { items: [], total: 0 };
    if (path.includes("/attempts?")) {
      const newest = firing && path.includes("skip=0&");
      return { items: [newest ? attempt() : old], total: 11 };
    }
    if (path === "/agents") return { items: [], total: 0 };
    return { items: [trigger()], total: 1 };
  });
  const view = render(<TriggerRunsView trigger={trigger()} activationId={null} />, { wrapper });
  await screen.findByRole("heading", { name: "Before the agent started" });
  await userEvent.click(
    within(screen.getByRole("group", { name: "Before the agent started" })).getByRole("button", {
      name: "Next page",
    }),
  );
  await waitFor(() =>
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/triggers/t1/attempts?skip=10&limit=10"),
  );
  firing = true;
  view.rerender(<TriggerRunsView trigger={trigger()} activationId="requested-fire" />);
  expect(await screen.findByText(/Enable Act as creator/)).toBeVisible();
  expect(screen.queryByText("Starting…")).toBeNull();
});

it("shows paused setup status without granting non-owners a source-review control", () => {
  render(
    <TriggerRow
      trigger={trigger({
        setup_required: true,
        can_manage: false,
        created_by_user_id: "someone-else",
      })}
    />,
    { wrapper },
  );
  expect(screen.getByText("Setup required")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Setup required" })).not.toBeInTheDocument();
});

it.each([true, false])(
  "shows stop for a parked routine only when the server allows it (%s)",
  async (allowed) => {
    vi.mocked(apiClient.post).mockClear();
    serveRuns([run({ status: "awaiting_approval" })]);
    const normal = vi.mocked(apiClient.get).getMockImplementation()!;
    let stopped = false;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (path.includes("/activations/")) return { state: "pending" };
      if (path.endsWith("/can-stop")) return allowed;
      if (path === "/runs" && stopped) return { items: [run({ status: "cancelled" })], total: 1 };
      return normal(path, options);
    });
    vi.mocked(apiClient.post).mockImplementation(async () => {
      stopped = true;
      return null;
    });
    render(<TriggerRunsView trigger={trigger({ conversation_id: "c1" })} activationId={null} />, {
      wrapper,
    });
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/runs/r1/can-stop", {
        signal: expect.any(AbortSignal),
      }),
    );
    if (allowed) {
      await userEvent.click(await screen.findByRole("button", { name: "Stop waiting run" }));
      expect(apiClient.post).toHaveBeenCalledWith("/runs/r1/cancel");
      expect(await screen.findByText(/cancelled/i)).toBeVisible();
      expect(screen.queryByRole("button", { name: "Stop waiting run" })).toBeNull();
    } else {
      expect(screen.queryByRole("button", { name: "Stop waiting run" })).toBeNull();
      expect(apiClient.post).not.toHaveBeenCalled();
    }
  },
);

it("explains a skipped overlap in the routine's history", async () => {
  serveRuns([], 0, { items: [attempt("previous_run_active")], total: 1 });
  render(<TriggerRunsView trigger={trigger()} activationId={null} />, { wrapper });
  expect(await screen.findByText(/Skipped because a previous run is still running/)).toBeVisible();
});

it("keeps a waiting run visible and reports a refused stop", async () => {
  serveRuns([run({ status: "awaiting_approval" })]);
  const normal = vi.mocked(apiClient.get).getMockImplementation()!;
  vi.mocked(apiClient.get).mockImplementation(async (path, options) =>
    path.endsWith("/can-stop") ? true : normal(path, options),
  );
  vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("Cannot stop now"));
  render(<TriggerRunsView trigger={trigger({ conversation_id: "c1" })} activationId={null} />, {
    wrapper,
  });
  await userEvent.click(await screen.findByRole("button", { name: "Stop waiting run" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  expect(screen.getByRole("button", { name: "Stop waiting run" })).toBeEnabled();
  expect(screen.getByText(/awaiting approval/i)).toBeVisible();
});

it("reopens pending setup from Resume without enabling an unreviewed routine", async () => {
  const { useAuthStore } = await import("@/stores/auth-store");
  useAuthStore.setState({
    user: {
      id: "creator",
      email: "creator@example.com",
      is_active: true,
      created_at: "2026-11-16T00:00:00Z",
    },
  });
  vi.mocked(apiClient.patch).mockClear();
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path.includes("/activations/")) return { state: "pending" };
    if (path.endsWith("/sources"))
      return {
        current: false,
        review_token: "sources",
        version_id: "v1",
        resources: [],
        accounts: [],
        unavailable_sources: [],
      };
    if (path.endsWith("/action-consents"))
      return { can_waive: false, review_token: "actions", items: [] };
    return { items: [], total: 0 };
  });
  render(
    <TriggerRow
      trigger={trigger({ created_by_user_id: "creator", setup_required: true, is_active: false })}
    />,
    { wrapper },
  );
  await userEvent.click(screen.getByRole("button", { name: "Resume" }));
  expect(await screen.findByRole("dialog", { name: "Review routine access" })).toBeVisible();
  expect(apiClient.patch).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Finish later" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(apiClient.patch).not.toHaveBeenCalled();
});

it("finishes deferred setup before enabling the routine", async () => {
  const { useAuthStore } = await import("@/stores/auth-store");
  useAuthStore.setState({
    user: {
      id: "creator",
      email: "creator@example.com",
      is_active: true,
      created_at: "2026-11-16T00:00:00Z",
    },
  });
  const pending = trigger({
    created_by_user_id: "creator",
    setup_required: true,
    is_active: false,
  });
  const sources = {
    current: true,
    review_token: "sources",
    version_id: "v1",
    resources: [],
    accounts: [],
    unavailable_sources: [],
  };
  const actions = { can_waive: false, review_token: "actions", items: [] };
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path.includes("/activations/")) return { state: "pending" };
    if (path.endsWith("/sources")) return sources;
    if (path.endsWith("/action-consents")) return actions;
    return { items: [], total: 0 };
  });
  vi.mocked(apiClient.put).mockImplementation(async (path) =>
    path.endsWith("/sources") ? sources : actions,
  );
  vi.mocked(apiClient.patch).mockResolvedValue({
    ...pending,
    setup_required: false,
    is_active: true,
  });
  render(<TriggerRow trigger={pending} />, { wrapper });
  await userEvent.click(screen.getByRole("button", { name: "Resume" }));
  await userEvent.click(await screen.findByRole("button", { name: "Enable routine" }));
  await waitFor(() =>
    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/triggers/t1", { is_active: true }),
  );
  expect(apiClient.put).toHaveBeenCalledWith("/agents/a1/triggers/t1/sources", {
    review_token: "sources",
    mode: "restricted",
  });
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it.each(["running", "awaiting_approval", "awaiting_answer", "completed", "failed", "cancelled"])(
  "retires the starting placeholder when the dispatched run is recorded as %s",
  async (status) => {
    const requestedAt = Date.now() - 1000;
    serveRuns([run({ status, started_at: new Date(requestedAt + 100).toISOString() })]);
    render(<TriggerRunsView trigger={trigger()} activationId="requested-fire" />, { wrapper });
    expect(await screen.findByRole("link", { name: "Open run" })).toBeVisible();
    expect(screen.queryByText("Starting…")).toBeNull();
    if (status === "awaiting_approval" || status === "awaiting_answer") {
      expect(
        screen.getByText(status === "awaiting_approval" ? /awaiting approval/ : /awaiting answer/),
      ).toBeVisible();
    }
  },
);

it.each(["completed", "running"])(
  "does not mistake an older %s occurrence for the newly dispatched run",
  async (status) => {
    const requestedAt = Date.now();
    serveRuns([
      run({
        status,
        routine_activation_id: "old-fire",
        started_at: new Date(requestedAt - 60_000).toISOString(),
      }),
    ]);
    render(<TriggerRunsView trigger={trigger()} activationId="requested-fire" />, { wrapper });
    expect(await screen.findByRole("link", { name: "Open run" })).toBeVisible();
    expect(screen.getByText("Starting…")).toBeVisible();
  },
);

it.each([-300_000, 300_000])(
  "retires starting after a fast completed run with a %s ms clock offset",
  async (offset) => {
    serveRuns([run({ id: "previous-run", status: "completed" })]);
    vi.mocked(apiClient.post).mockImplementation(async () => {
      serveRuns([
        run({ status: "completed", started_at: new Date(Date.now() + offset).toISOString() }),
      ]);
      return {
        ...trigger({ last_run_id: "previous-run" }),
        activation_id: "requested-fire",
      };
    });
    render(<TriggerRow trigger={trigger({ last_run_id: "previous-run" })} />, { wrapper });
    await userEvent.click(screen.getByRole("button", { name: "Run now" }));
    expect(await screen.findByRole("link", { name: "Open run" })).toBeVisible();
    expect(screen.queryByText("Starting…")).toBeNull();
  },
);

it("waits for the new occurrence when a history row has no start timestamp", async () => {
  serveRuns([run({ started_at: null, routine_activation_id: "old-fire" })]);
  render(<TriggerRunsView trigger={trigger()} activationId="requested-fire" />, { wrapper });
  expect(await screen.findByRole("link", { name: "Open run" })).toBeVisible();
  expect(screen.getByText("Starting…")).toBeVisible();
});

it("does not mistake an already running fire for another manual dispatch", async () => {
  serveRuns([run({ id: "already-running", status: "running", routine_activation_id: "old-fire" })]);
  vi.mocked(apiClient.post).mockResolvedValue({
    ...trigger({ last_run_id: "older-finished-run" }),
    activation_id: "requested-fire",
  });
  render(<TriggerRow trigger={trigger({ last_run_id: "older-finished-run" })} />, { wrapper });
  await userEvent.click(screen.getByRole("button", { name: "Run now" }));
  expect(await screen.findByRole("link", { name: "Open run" })).toBeVisible();
  expect(screen.getByText("Starting…")).toBeVisible();
});

it("stops dispatch invalidations once the new run is recorded", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  serveRuns([run({ status: "completed" })]);
  render(
    <QueryClientProvider client={client}>
      <TriggerRunsView trigger={trigger()} activationId="requested-fire" />
    </QueryClientProvider>,
  );
  expect(await screen.findByRole("link", { name: "Open run" })).toBeVisible();
  expect(screen.queryByText("Starting…")).toBeNull();
  const reads = vi.mocked(apiClient.get).mock.calls.length;
  await new Promise((resolve) => setTimeout(resolve, 3200));
  expect(apiClient.get).toHaveBeenCalledTimes(reads);
});

it.each([false, true])("matches before-run attempts by identity (new: %s)", async (isNew) => {
  serveRuns([], 0, {
    items: [
      {
        ...attempt(),
        id: isNew ? "new-attempt" : "old-attempt",
        activation_id: isNew ? "requested-fire" : "old-fire",
        occurred_at: "2020-01-01T00:00:00Z",
      },
    ],
    total: 1,
  });
  render(
    <TriggerRunsView trigger={trigger({ conversation_id: null })} activationId="requested-fire" />,
    { wrapper },
  );
  await screen.findByRole("heading", { name: "Before the agent started" });
  await waitFor(() => expect(screen.queryByText("Starting…") !== null).toBe(!isNew));
});

it("does not settle a dispatch from cached rows older than its history snapshot", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const runKey = qk.runs.list({ triggerId: "t1" });
  const attemptKey = qk.triggers.attempts("a1", "t1", 0);
  client.setQueryData(runKey, {
    items: [run({ id: "older-run", routine_activation_id: "old-fire" })],
    total: 1,
  });
  client.setQueryData(attemptKey, {
    items: [{ ...attempt(), id: "older-attempt", activation_id: "old-fire" }],
    total: 1,
  });
  await client.invalidateQueries();
  serveRuns([]);
  const normal = vi.mocked(apiClient.get).getMockImplementation()!;
  let releaseHistory: (() => void) | undefined;
  const held = new Promise<void>((resolve) => {
    releaseHistory = resolve;
  });
  vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
    if (path.includes("/activations/")) return { state: "pending" };
    if (path === "/runs" || path.includes("/attempts?")) {
      await held;
      return path === "/runs"
        ? { items: [run({ id: "previous-run", routine_activation_id: "old-fire" })], total: 1 }
        : {
            items: [{ ...attempt(), id: "previous-attempt", activation_id: "old-fire" }],
            total: 1,
          };
    }
    return normal(path, options);
  });
  render(
    <QueryClientProvider client={client}>
      <TriggerRunsView trigger={trigger({ conversation_id: "c1" })} activationId="requested-fire" />
    </QueryClientProvider>,
  );
  expect(await screen.findByText("Starting…")).toBeVisible();
  releaseHistory?.();
  await waitFor(() =>
    expect(screen.queryByRole("link", { name: "Open run" })).toHaveAttribute(
      "href",
      "/runs?run=previous-run",
    ),
  );
  expect(screen.getByText("Starting…")).toBeVisible();
});

it.each(["recorded", "not_started"] as const)(
  "settles %s independently of paginated history",
  async (state) => {
    serveRuns([run({ id: "newer-run", routine_activation_id: "another-fire" })], 100, {
      items: [{ ...attempt(), activation_id: "another-fire" }],
      total: 40,
    });
    const normal = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) =>
      path.includes("/activations/") ? { state } : normal(path, options),
    );
    render(<TriggerRunsView trigger={trigger()} activationId="requested-fire" jobId="job1" />, {
      wrapper,
    });
    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith(
        "/agents/a1/triggers/t1/activations/requested-fire",
        { params: { job_id: "job1" } },
      ),
    );
    await waitFor(() => expect(screen.queryByText("Starting…")).toBeNull());
    if (state === "not_started")
      expect(
        await screen.findByText("This request finished without a run available in history."),
      ).toBeVisible();
  },
);

it("reports an unavailable activation receipt without polling it indefinitely", async () => {
  serveRuns([]);
  const normal = vi.mocked(apiClient.get).getMockImplementation()!;
  vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
    if (path.includes("/activations/")) throw new Error("Unavailable");
    return normal(path, options);
  });
  render(<TriggerRunsView trigger={trigger()} activationId="requested-fire" />, { wrapper });
  expect(await screen.findByText("This trigger's runs could not be read.")).toBeVisible();
  expect(screen.queryByText("Starting…")).toBeNull();
});

describe("GitHub filtered delivery diagnostics", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({
      user: {
        id: "owner",
        email: "owner@example.com",
        is_active: true,
        created_at: "2026-11-17T09:00:00Z",
      },
    });
  });
  function serveDiagnostic(last_event: unknown) {
    serveRuns([]);
    const previous = vi.mocked(apiClient.get).getMockImplementation();
    vi.mocked(apiClient.get).mockImplementation(
      async (path: string, options?: Parameters<typeof apiClient.get>[1]) => {
        if (path.endsWith("/filtered-event")) return { last_event };
        return previous?.(path, options);
      },
    );
  }
  it("shows the owner's latest rejection even when the routine has never run", async () => {
    serveDiagnostic({ received_at: "2026-11-17T09:00:00Z", reason: "author", authors: "members" });
    render(
      <TriggerRunsView
        trigger={trigger({
          created_by_user_id: "owner",
          event_source: "github",
          conversation_id: null,
        })}
        activationId={null}
      />,
      { wrapper },
    );
    expect(
      await screen.findByText("The author association was excluded by the author filter."),
    ).toBeVisible();
    expect(
      screen.getByText("Author filter at receipt: Repository members (default)"),
    ).toBeVisible();
    expect(screen.getByText(/has not run yet/)).toBeVisible();
  });
  it("distinguishes no recorded refusal from a webhook receipt", async () => {
    serveDiagnostic(null);
    render(
      <TriggerRunsView
        trigger={trigger({ created_by_user_id: "owner", event_source: "github" })}
        activationId={null}
      />,
      { wrapper },
    );
    expect(
      await screen.findByText(/This does not confirm that a webhook has arrived/),
    ).toBeVisible();
  });
  it("shows a diagnostic request failure instead of claiming no filtered events", async () => {
    serveRuns([]);
    const previous = vi.mocked(apiClient.get).getMockImplementation();
    vi.mocked(apiClient.get).mockImplementation(
      async (path: string, options?: Parameters<typeof apiClient.get>[1]) => {
        if (path.endsWith("/filtered-event")) throw new Error("unavailable");
        return previous?.(path, options);
      },
    );
    render(
      <TriggerRunsView
        trigger={trigger({ created_by_user_id: "owner", event_source: "github" })}
        activationId={null}
      />,
      { wrapper },
    );
    expect(await screen.findByText("Could not read filtered event diagnostics")).toBeVisible();
    expect(screen.queryByText(/No filtered event has been recorded/)).toBeNull();
  });
  it.each(["other-person", null])(
    "does not fetch owner diagnostics for %s",
    async (created_by_user_id) => {
      serveDiagnostic(null);
      render(
        <TriggerRunsView
          trigger={trigger({ created_by_user_id, event_source: "github" })}
          activationId={null}
        />,
        { wrapper },
      );
      await screen.findByText(/has not run yet/);
      expect(screen.queryByText("Latest filtered GitHub event")).toBeNull();
      expect(
        vi.mocked(apiClient.get).mock.calls.some(([path]) => path.endsWith("/filtered-event")),
      ).toBe(false);
    },
  );
});

it.each([
  { reader: "creator", project: null, visible: true },
  { reader: "operator", project: null, visible: false },
  { reader: "operator", project: "project-1", visible: true },
])(
  "shows private execution chat only to its creator or project readers: $reader/$project",
  async ({ reader, project, visible }) => {
    const previous = useAuthStore.getState().user;
    useAuthStore.setState({
      user: {
        id: reader,
        email: "reader@example.com",
        is_active: true,
        created_at: "2026-11-23T00:00:00Z",
      },
    });
    try {
      serveRuns([run({ user_id: "creator", conversation_id: "private-execution" })]);
      render(
        <TriggerRunsView
          trigger={trigger({
            chat_mode: "per_run",
            project_id: project,
            created_by_user_id: "creator",
          })}
          activationId={null}
        />,
        { wrapper },
      );
      await screen.findByRole("link", { name: "Open run" });
      expect(screen.queryByRole("link", { name: "Open chat" }) !== null).toBe(visible);
    } finally {
      useAuthStore.setState({ user: previous });
    }
  },
);
