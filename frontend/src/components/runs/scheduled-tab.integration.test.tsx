import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ScheduledTab } from "./scheduled-tab";
import { apiClient } from "@/lib/api-client";
import type { Trigger } from "@/types/triggers";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return {
    ...actual,
    apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

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
    agent_name: "Nightly",
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
    conversation_id: null,
    webhook_url: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

function serveOrg(triggers: Trigger[]) {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.startsWith("/triggers")) return { items: triggers, total: triggers.length };
    // A row's own useTriggers query, keyed on its agent.
    if (path.startsWith("/agents/")) return { items: triggers, total: triggers.length };
    throw new Error(`unexpected GET ${path}`);
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});
afterEach(() => vi.clearAllMocks());

describe("ScheduledTab", () => {
  it("lists every organization trigger, named by its agent", async () => {
    serveOrg([trigger()]);
    render(<ScheduledTab />, { wrapper });

    expect(await screen.findByText("Nightly")).toBeVisible();
    expect(screen.getByText("Every 15 minutes")).toBeVisible();
    // The row draws the agent's face beside the name - initials here, since the
    // fixture has no uploaded avatar - not a bare string in a list of strings.
    expect(screen.getByText("N")).toBeVisible();
  });

  it("says nothing is scheduled rather than drawing an empty box", async () => {
    serveOrg([]);
    render(<ScheduledTab />, { wrapper });

    expect(await screen.findByText("Nothing runs on its own yet")).toBeVisible();
  });

  it("says a failed request out loud instead of as an empty list", async () => {
    // An empty page and a 502 are the same pixels; the error is its own state.
    vi.mocked(apiClient.get).mockRejectedValue(new Error("boom"));
    render(<ScheduledTab />, { wrapper });

    await waitFor(() => expect(screen.getByText("boom")).toBeVisible());
  });

  it("pauses a trigger from its row", async () => {
    const user = userEvent.setup();
    serveOrg([trigger()]);
    vi.mocked(apiClient.patch).mockResolvedValue(trigger({ is_active: false }));
    render(<ScheduledTab />, { wrapper });

    await user.click(await screen.findByRole("button", { name: "Pause" }));

    expect(apiClient.patch).toHaveBeenCalledWith("/agents/a1/triggers/t1", { is_active: false });
  });

  it("pages an organization's routines rather than rendering all of them", async () => {
    // `useOrgTriggers` walks every page of the endpoint into one array, so past
    // the page size this card was rendering sixty rows into one scroll with no
    // control to reach the sixty-first.
    serveOrg(
      Array.from({ length: 58 }, (_, index) =>
        trigger({ id: `t${index}`, name: `Routine ${index}` }),
      ),
    );
    render(<ScheduledTab />, { wrapper });

    expect(await screen.findByText("Routine 0")).toBeVisible();
    expect(screen.queryByText("Routine 57")).toBeNull();
    expect(screen.getByText(/58 routines/)).toBeVisible();

    await userEvent.setup().click(screen.getByRole("button", { name: "Next page" }));

    expect(screen.getByText("Routine 57")).toBeVisible();
  });

  it("finds one routine among many by name, agent or message", async () => {
    const user = userEvent.setup();
    serveOrg([
      trigger({ id: "t1", name: "Invoice sweep", prompt: "Chase the unpaid ones" }),
      trigger({ id: "t2", name: "Standup digest", prompt: "Summarise yesterday" }),
    ]);
    render(<ScheduledTab />, { wrapper });

    await user.type(await screen.findByPlaceholderText("Search routines"), "unpaid");

    expect(screen.getByText("Invoice sweep")).toBeVisible();
    expect(screen.queryByText("Standup digest")).toBeNull();
  });

  it("says no routine matches rather than that nothing runs on its own", async () => {
    // Two different answers that used to render the same empty state: a filter
    // matching none reads as an organization that has never scheduled anything.
    const user = userEvent.setup();
    serveOrg([trigger({ name: "Invoice sweep" })]);
    render(<ScheduledTab />, { wrapper });

    await user.type(await screen.findByPlaceholderText("Search routines"), "zzz");

    expect(screen.getByText("No routine matches that.")).toBeVisible();
    expect(screen.queryByText("Nothing runs on its own yet")).toBeNull();
  });

  it("shows no row actions on a trigger the caller may not manage", async () => {
    // The server resolves manage rights per row: a caller with no run grant on
    // this agent gets a read-only row, and the controls do not render.
    serveOrg([trigger({ can_manage: false })]);
    render(<ScheduledTab />, { wrapper });

    await screen.findByText("Nightly");
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });
});
