import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TriggerRow } from "./trigger-row";
import { apiClient } from "@/lib/api-client";
import { useTriggers } from "@/hooks/use-triggers";
import type { Trigger } from "@/types/triggers";

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
    trigger_type: "schedule",
    schedule_kind: "interval",
    interval_seconds: 900,
    cron_expression: null,
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
function serveRuns(runs: Record<string, unknown>[], total?: number) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/agents") return { items: [], total: 0 };
    if (path === "/runs") return { items: runs, total: total ?? runs.length };
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
