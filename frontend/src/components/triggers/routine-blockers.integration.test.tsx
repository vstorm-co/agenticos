import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { TriggerRow } from "./trigger-row";
import { apiClient } from "@/lib/api-client";
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

/** The readiness check answers `blockers`; the runs drawer finds nothing. */
function serve(blockers: RoutineBlocker[] | Promise<never>) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path === "/agents/a1/triggers/t1/readiness") {
      return Array.isArray(blockers) ? { trigger_id: "t1", blockers } : blockers;
    }
    if (path === "/runs") return { items: [], total: 0 };
    if (path.includes("/attempts?")) return { items: [], total: 0 };
    throw new Error(`unexpected GET ${path}`);
  });
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
  render(<TriggerRow trigger={trigger()} />, { wrapper });
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

it("tells someone else that only the creator can fix it", async () => {
  useAuthStore.setState({ user: { id: "admin" } as never });
  serve([blocker({ code: "platform_identity" })]);
  render(<TriggerRow trigger={trigger()} />, { wrapper });
  expect(await screen.findByText("Only its creator can fix this.")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Review access" })).not.toBeInTheDocument();
});

it("greys out a paused routine and says what resuming would meet", async () => {
  serve([blocker({ code: "creator_cannot_run" })]);
  render(<TriggerRow trigger={trigger({ is_active: false })} />, { wrapper });
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
  render(<TriggerRow trigger={trigger({ is_active: false })} />, { wrapper });
  await waitFor(() =>
    expect(apiClient.get).toHaveBeenCalledWith("/agents/a1/triggers/t1/readiness"),
  );
  expect(row()).toHaveAttribute("data-state", "paused");
  expect(screen.queryByRole("list", { name: "Why this routine will not run" })).toBeNull();
});

it("holds a schedule behind a run waiting for approval and opens it from the row", async () => {
  serve([blocker({ code: "awaiting_approval", run_id: "r1" })]);
  const user = userEvent.setup();
  render(<TriggerRow trigger={trigger()} />, { wrapper });
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
  render(<TriggerRow trigger={trigger()} />, { wrapper });
  const reasons = await screen.findByRole("list", { name: "Why this routine will not run" });
  expect(
    within(reasons).getByText(
      "2 actions have no standing consent, so each run stops for approval.",
    ),
  ).toBeVisible();
  expect(row()).toHaveAttribute("data-state", "attention");
  expect(screen.getByRole("button", RUN_NOW)).toBeEnabled();
});

it("shows what the listing already proves before the readiness check answers", () => {
  serve(new Promise<never>(() => {}));
  render(<TriggerRow trigger={trigger({ paused_for_budget: true, setup_required: true })} />, {
    wrapper,
  });
  expect(
    screen.getByText("This month's budget is spent. It runs again on the first of the month."),
  ).toBeVisible();
  expect(screen.getByText("Its sources have not been reviewed yet.")).toBeVisible();
  expect(row()).toHaveAttribute("data-state", "blocked");
});
