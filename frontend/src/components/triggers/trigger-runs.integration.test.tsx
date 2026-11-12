import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TriggerRow } from "./trigger-row";
import { TriggerRunsView } from "./trigger-runs-view";
import { apiClient } from "@/lib/api-client";
import { useTriggers } from "@/hooks/use-triggers";
import type { Trigger, TriggerAttempt, TriggerAttemptList } from "@/types/triggers";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
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

  it("links each fire to its own run detail", async () => {
    // The point of listing runs rather than turns: the requests, the tools and
    // the cost per turn are on that page, and there was no way to reach it.
    serveRuns([run({ id: "r-42" })]);
    render(<TriggerRow trigger={trigger()} />, { wrapper });

    await userEvent.click(screen.getByRole("button", OPEN));

    const link = within(await screen.findByRole("dialog")).getByRole("link", { name: /Open run/ });
    expect(link).toHaveAttribute("href", "/runs?run=r-42");
  });

  it("asks only for this trigger's own fires", async () => {
    // Every fire of one trigger appends to a single run-log conversation, so the
    // conversation is the trigger's identity in the run history.
    serveRuns([run()]);
    render(<TriggerRow trigger={trigger({ conversation_id: "c-9" })} />, { wrapper });

    await userEvent.click(screen.getByRole("button", OPEN));
    await screen.findByRole("dialog");

    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith("/runs", {
        params: expect.objectContaining({ conversation_id: "c-9" }),
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
    vi.mocked(apiClient.post).mockResolvedValue(trigger());
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
    activation_id: "activation",
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
        pendingSince={Date.now() - 1000}
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
      render(<TriggerRunsView trigger={trigger()} pendingSince={null} />, { wrapper });
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
    render(<TriggerRunsView trigger={trigger()} pendingSince={null} />, { wrapper });
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
      if (path.includes("/attempts?")) throw new Error("unavailable");
      return normal(path, options);
    });
    render(<TriggerRunsView trigger={trigger()} pendingSince={null} />, { wrapper });
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
    occurred_at: new Date(Date.now() - 3600000).toISOString(),
  };
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/runs") return { items: [], total: 0 };
    if (path.includes("/attempts?")) {
      const newest = firing && path.includes("skip=0&");
      return { items: [newest ? attempt() : old], total: 11 };
    }
    if (path === "/agents") return { items: [], total: 0 };
    return { items: [trigger()], total: 1 };
  });
  const view = render(<TriggerRunsView trigger={trigger()} pendingSince={null} />, { wrapper });
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
  view.rerender(<TriggerRunsView trigger={trigger()} pendingSince={Date.now() - 1000} />);
  expect(await screen.findByText(/Enable Act as creator/)).toBeVisible();
  expect(screen.queryByText("Starting…")).toBeNull();
});
