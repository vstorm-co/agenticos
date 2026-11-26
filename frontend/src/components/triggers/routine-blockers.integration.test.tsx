import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { TriggerRow } from "./trigger-row";
import { useRoutinesReadiness } from "@/hooks/use-routine-readiness";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { RoutineBlocker } from "@/lib/routine-readiness-api";
import { useAuthStore } from "@/stores";
import type { Trigger } from "@/types/triggers";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("./action-consents-dialog", () => ({
  ActionConsentsDialog: () => <div role="dialog" aria-label="Access review" />,
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function trigger(overrides: Partial<Trigger> = {}): Trigger {
  return {
    id: "t1",
    agent_id: "a1",
    agent_name: "Digest bot",
    name: "Morning digest",
    created_by_user_id: "creator",
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

function blocker(overrides: Partial<RoutineBlocker>): RoutineBlocker {
  return { code: "sources_review", severity: "blocked", run_id: null, count: null, ...overrides };
}

/** The readiness check answers `blockers` for t1; the runs drawer finds nothing. */
function serve(blockers: RoutineBlocker[] | Promise<never>) {
  vi.mocked(apiClient.post).mockImplementation(async (path: string) => {
    if (path === "/triggers/readiness") {
      return Array.isArray(blockers) ? { items: [{ trigger_id: "t1", blockers }] } : blockers;
    }
    throw new Error(`unexpected POST ${path}`);
  });
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/runs") return { items: [], total: 0 };
    if (path.includes("/attempts?")) return { items: [], total: 0 };
    throw new Error(`unexpected GET ${path}`);
  });
}

/** How a list renders its rows: one readiness read, its answer handed to each row. */
function Listed({ triggers }: { triggers: Trigger[] }) {
  const readiness = useRoutinesReadiness(triggers);
  return triggers.map((item) => (
    <TriggerRow key={item.id} trigger={item} blockers={readiness(item)} />
  ));
}

const row = () => screen.getByRole("article");
const RUN_NOW = { name: "Run now" };

beforeEach(() => {
  vi.clearAllMocks();
  useAuthStore.setState({ user: { id: "creator" } as never });
});
afterEach(() => useAuthStore.setState({ user: null }));

it("marks an active routine that will not run red, says why and lets its creator fix it", async () => {
  serve([blocker({ code: "sources_review" })]);
  const user = userEvent.setup();
  render(<Listed triggers={[trigger()]} />, { wrapper });
  expect(
    await screen.findByText(
      "The agent or its sources changed since the last review. Review them again.",
    ),
  ).toBeVisible();
  expect(row()).toHaveAttribute("data-state", "blocked");
  expect(row().className).toContain("border-destructive/40");
  expect(screen.getByRole("button", RUN_NOW)).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Review access" }));
  expect(screen.getByRole("dialog", { name: "Access review" })).toBeInTheDocument();
});

it("offers the review once when several reasons are fixed in it", async () => {
  serve([
    blocker({ code: "sources_review" }),
    blocker({ code: "actions_need_approval", severity: "attention", count: 2 }),
  ]);
  render(<Listed triggers={[trigger()]} />, { wrapper });
  expect(
    await screen.findByText("2 actions have no standing consent and will need approval if used."),
  ).toBeVisible();
  expect(screen.getAllByRole("button", { name: "Review access" })).toHaveLength(1);
});

it("tells someone else that only the creator can fix it", async () => {
  useAuthStore.setState({ user: { id: "admin" } as never });
  serve([blocker({ code: "platform_identity" })]);
  render(<Listed triggers={[trigger()]} />, { wrapper });
  expect(await screen.findByText("Only its creator can fix this.")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Review access" })).not.toBeInTheDocument();
});

it("greys out a paused routine and says what resuming would meet", async () => {
  serve([blocker({ code: "creator_cannot_run" })]);
  render(<Listed triggers={[trigger({ is_active: false })]} />, { wrapper });
  expect(await screen.findByText("Its creator can no longer run this agent.")).toBeVisible();
  expect(screen.getByText("Resuming will not help until this is fixed:")).toBeVisible();
  expect(row()).toHaveAttribute("data-state", "paused");
  expect(row().className).not.toContain("border-destructive");
  expect(
    screen.getByRole("button", { name: "See what this trigger has done" }).className,
  ).toContain("opacity-60");
});

it("greys out a paused routine with nothing in its way, without a resume warning", async () => {
  serve([]);
  render(<Listed triggers={[trigger({ is_active: false })]} />, { wrapper });
  await waitFor(() =>
    expect(apiClient.post).toHaveBeenCalledWith("/triggers/readiness", { trigger_ids: ["t1"] }),
  );
  expect(row()).toHaveAttribute("data-state", "paused");
  await waitFor(() => expect(screen.queryByRole("list", { name: "Routine readiness" })).toBeNull());
});

it("holds a schedule behind a run waiting for approval and opens it from the row", async () => {
  serve([blocker({ code: "awaiting_approval", run_id: "r1" })]);
  const user = userEvent.setup();
  render(<Listed triggers={[trigger()]} />, { wrapper });
  expect(
    await screen.findByText(
      "A previous run is waiting for approval. No new run starts until it is decided.",
    ),
  ).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Open runs" }));
  await waitFor(() =>
    expect(vi.mocked(apiClient.get).mock.calls.some(([path]) => path === "/runs")).toBe(true),
  );
});

it("marks runs that will stop on approval amber and still lets them be run", async () => {
  serve([blocker({ code: "actions_need_approval", severity: "attention", count: 2 })]);
  render(<Listed triggers={[trigger()]} />, { wrapper });
  await screen.findByText("2 actions have no standing consent and will need approval if used.");
  const reasons = screen.getByRole("list", { name: "Routine readiness" });
  expect(
    within(reasons).getByText("2 actions have no standing consent and will need approval if used."),
  ).toBeVisible();
  expect(row()).toHaveAttribute("data-state", "attention");
  expect(screen.getByRole("button", RUN_NOW)).toBeEnabled();
});

it("does not present an unanswered check as confirmed readiness", () => {
  serve(new Promise<never>(() => {}));
  render(<Listed triggers={[trigger()]} />, { wrapper });
  expect(screen.getByText("Checking whether this routine can run…")).toBeVisible();
  expect(row()).toHaveAttribute("data-state", "unknown");
  expect(row().className).not.toContain("border-warning");
  expect(screen.getByRole("button", RUN_NOW)).toBeEnabled();
});

it("replaces stale diagnostics after a failed refresh and lets the reader retry", async () => {
  serve([blocker({ code: "sources_review" })]);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Listed triggers={[trigger()]} />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(row()).toHaveAttribute("data-state", "blocked"));
  vi.mocked(apiClient.post).mockRejectedValue(new Error("Unavailable"));
  await client.invalidateQueries({ queryKey: qk.triggers.readinessAll() });
  expect(
    await screen.findByText(
      "Could not check whether this routine can run. Run now will still check its permissions.",
    ),
  ).toBeVisible();
  expect(row()).toHaveAttribute("data-state", "unknown");
  expect(screen.getByRole("button", RUN_NOW)).toBeEnabled();
  vi.mocked(apiClient.post).mockResolvedValue({ items: [{ trigger_id: "t1", blockers: [] }] });
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(row()).toHaveAttribute("data-state", "ready"));
});

it("shows what the listing already proves before the readiness check answers", () => {
  serve(new Promise<never>(() => {}));
  render(<Listed triggers={[trigger({ paused_for_budget: true, setup_required: true })]} />, {
    wrapper,
  });
  expect(
    screen.getByText("This month's budget is spent. It runs again on the first of the month."),
  ).toBeVisible();
  expect(screen.getByText("Its sources have not been reviewed yet.")).toBeVisible();
  expect(row()).toHaveAttribute("data-state", "blocked");
});

it("keeps Run now for a schedule held only by a parked run", async () => {
  serve([blocker({ code: "awaiting_answer", run_id: "r1" })]);
  render(<Listed triggers={[trigger()]} />, { wrapper });
  expect(
    await screen.findByText(
      "A previous run is waiting for an answer. No new run starts until it gets one.",
    ),
  ).toBeVisible();
  expect(row()).toHaveAttribute("data-state", "blocked");
  expect(screen.getByRole("button", RUN_NOW)).toBeEnabled();
});

it("reads a whole screen at once, a hundred routines per request", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({ items: [] });
  vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0 });
  const many = Array.from({ length: 101 }, (_, index) =>
    trigger({ id: `t${String(index).padStart(3, "0")}` }),
  );
  render(<Listed triggers={many} />, { wrapper });
  await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(2));
  const sizes = vi
    .mocked(apiClient.post)
    .mock.calls.map(([, body]) => (body as { trigger_ids: string[] }).trigger_ids.length);
  expect(sizes.sort((a, b) => a - b)).toEqual([1, 100]);
});

it("shows only what the listing proves when a row is rendered without a readiness read", () => {
  render(<TriggerRow trigger={trigger({ setup_required: true })} />, { wrapper });
  expect(screen.getByText("Its sources have not been reviewed yet.")).toBeVisible();
  expect(apiClient.post).not.toHaveBeenCalled();
});
